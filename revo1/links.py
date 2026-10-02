"""Wireless links to the knob: Wi-Fi (TCP) and Bluetooth LE.

Both carry the encrypted session from `secure.py` and offer the same
`read_until` / `write` / `close` calls as a pyserial port, so the bridge drives
USB and wireless links with the same code.
"""

import asyncio
import queue
import socket
import threading
import time

from revo1 import secure

TCP_PORT = 47010
DISCOVERY_PORT = 47011
SERVICE_UUID = "7b8f0001-6c1e-4e8a-9c3d-2a1f5e0b9a10"
RX_UUID = "7b8f0002-6c1e-4e8a-9c3d-2a1f5e0b9a10"
TX_UUID = "7b8f0003-6c1e-4e8a-9c3d-2a1f5e0b9a10"


class LinkError(OSError):
    pass


class SecureLink:
    """Line-oriented reads and writes over an encrypted channel."""

    kind = "wireless"

    def __init__(self, key, label):
        self.label = label
        self.channel = secure.Channel(key, self._send_raw, self._receive_raw)
        self.lines = b""
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def read_until(self, separator=b"\n", size=None):
        """The next whole line, or b"" if none arrives within 0.2 s."""
        deadline = time.monotonic() + 0.2
        while separator not in self.lines:
            left = deadline - time.monotonic()
            if left <= 0:
                return b""
            try:
                plaintext = self.channel.receive(left)
            except secure.SecureError as exc:
                raise LinkError(str(exc)) from exc
            if plaintext is None:
                return b""
            self.lines += plaintext
        line, _, self.lines = self.lines.partition(separator)
        return line + separator

    def write(self, data):
        try:
            self.channel.send(bytes(data))
        except secure.SecureError as exc:
            raise LinkError(str(exc)) from exc

    def handshake(self):
        try:
            self.channel.handshake()
        except secure.SecureError as exc:
            self.close()
            raise LinkError(str(exc)) from exc


# ----- Wi-Fi --------------------------------------------------------------------

class TcpLink(SecureLink):
    kind = "wifi"

    def __init__(self, host, key, timeout=2.5):
        super().__init__(key, f"Wi-Fi ({host})")
        self.host = host
        self.sock = socket.create_connection((host, TCP_PORT), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.handshake()

    def _send_raw(self, data):
        if self.closed:
            raise LinkError("The Wi-Fi link is closed")
        self.sock.settimeout(5)
        try:
            self.sock.sendall(data)
        except OSError as exc:
            raise LinkError(f"Wi-Fi send failed: {exc}") from exc

    def _receive_raw(self, count, timeout):
        if self.closed:
            raise LinkError("The Wi-Fi link is closed")
        self.sock.settimeout(max(0.01, timeout))
        try:
            data = self.sock.recv(max(count, 4096))
        except socket.timeout:
            return b""
        except OSError as exc:
            raise LinkError(f"Wi-Fi link lost: {exc}") from exc
        if not data:
            raise LinkError("The knob closed the Wi-Fi link")
        return data

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                self.sock.close()
            except OSError:
                pass


def discover_wifi(key_id, timeout=1.2):
    """Asks the local network for knobs; returns the address of the one
    paired with `key_id`, or None."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.2)
        targets = {"255.255.255.255"}
        try:
            for address in socket.gethostbyname_ex(socket.gethostname())[2]:
                if not address.startswith("127."):
                    targets.add(address.rsplit(".", 1)[0] + ".255")
        except OSError:
            pass
        for target in targets:
            try:
                sock.sendto(b"REVO1?", (target, DISCOVERY_PORT))
            except OSError:
                pass
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, (address, _) = sock.recvfrom(64)
            except socket.timeout:
                continue
            except OSError:
                return None
            parts = data.decode("ascii", errors="replace").split(",")
            if len(parts) == 3 and parts[0] == "REVO1" and parts[1] == key_id:
                return address
    return None


# ----- Bluetooth LE -------------------------------------------------------------

_loop = None
_loop_lock = threading.Lock()


def _ble_loop():
    """One asyncio loop in a background thread runs every bleak call."""
    global _loop
    with _loop_lock:
        if _loop is None:
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, daemon=True,
                             name="revo1-ble").start()
        return _loop


def _await(coroutine, timeout):
    future = asyncio.run_coroutine_threadsafe(coroutine, _ble_loop())
    try:
        return future.result(timeout)
    except Exception:
        future.cancel()
        raise


def ble_available():
    import importlib.util
    return importlib.util.find_spec("bleak") is not None


def discover_ble(timeout=6.0):
    """The address of the first knob advertising the Revo1 service, or None."""
    from bleak import BleakScanner

    # Matched here rather than by an OS scan filter, which Windows applies
    # unreliably; stops as soon as the knob shows up.
    async def scan():
        device = await BleakScanner.find_device_by_filter(
            lambda device, advert: SERVICE_UUID in (advert.service_uuids or ()),
            timeout=timeout)
        return device.address if device else None

    try:
        return _await(scan(), timeout + 5)
    except Exception:
        return None


class BleLink(SecureLink):
    kind = "ble"

    def __init__(self, address, key):
        super().__init__(key, "Bluetooth")
        from bleak import BleakClient
        self.address = address
        self.incoming = queue.Queue()
        self.client = BleakClient(address, disconnected_callback=self._lost)
        try:
            _await(self._open(), 20)
        except Exception as exc:
            self.close()
            raise LinkError(f"Bluetooth connection failed: {exc}") from exc
        self.handshake()

    async def _open(self):
        await self.client.connect()
        characteristic = self.client.services.get_characteristic(RX_UUID)
        if characteristic is None:
            raise LinkError("This device has no Revo1 service")
        self.piece = max(20, min(512, characteristic.max_write_without_response_size))
        await self.client.start_notify(TX_UUID, lambda _, data: self.incoming.put(bytes(data)))

    def _lost(self, _client):
        self.closed = True
        self.incoming.put(None)

    def _send_raw(self, data):
        if self.closed:
            raise LinkError("The Bluetooth link is closed")

        async def write():
            for start in range(0, len(data), self.piece):
                await self.client.write_gatt_char(RX_UUID, data[start:start + self.piece],
                                                  response=False)

        try:
            _await(write(), 15)
        except Exception as exc:
            raise LinkError(f"Bluetooth send failed: {exc}") from exc

    def _receive_raw(self, count, timeout):
        try:
            data = self.incoming.get(timeout=max(0.01, timeout))
        except queue.Empty:
            return b""
        if data is None:
            raise LinkError("The Bluetooth link was lost")
        return data

    def close(self):
        if self.client is None:
            return
        client, self.client = self.client, None
        self.closed = True
        try:
            _await(client.disconnect(), 5)
        except Exception:
            pass
