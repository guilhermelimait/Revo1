import base64
import queue
import threading
import time

import serial
from serial.tools import list_ports

from revo1 import links, secure

# USB IDs of the ESP32-S3 native USB Serial/JTAG port the knob enumerates as.
DEVICE_IDS = (0x303A, 0x1001)
# The firmware's greeting. Early builds, made while the project was called
# RoundScreen, still say so; they're accepted so the app can update them.
HELLO_LINES = ("HELLO,REVO1,1", "HELLO,ROUNDSCREEN,1")
MODE_COUNT = 8
# Raw bytes per upload line; the firmware accepts up to 3072.
UPLOAD_CHUNK = 3072
# Chunks in flight before waiting for an acknowledgement.
UPLOAD_WINDOW = 4
# How often a wireless session checks whether a USB cable has appeared.
USB_CHECK_S = 1.5
# Pause between rounds of looking for the knob over Wi-Fi and Bluetooth.
WIRELESS_RETRY_S = 4


def find_devices():
    """Every connected knob, as (port, description) pairs."""
    return [(port.device, port.description or port.device)
            for port in sorted(list_ports.comports(), key=lambda p: p.device)
            if (port.vid, port.pid) == DEVICE_IDS]


class DeviceBridge:
    def __init__(self, events, preferred_port=""):
        self.events = events
        self.preferred_port = preferred_port
        self.outbound = queue.Queue()
        self.stop_event = threading.Event()
        self.reconnect_event = threading.Event()
        self.pause_event = threading.Event()
        self.idle_event = threading.Event()
        self.jobs = queue.Queue()
        self.thread = threading.Thread(target=self._run, daemon=True)
        # Wireless: the pairing key and where the knob was last seen.
        self.link_key = None
        self.key_id = ""
        self.knob_ip = ""
        self.knob_ble = ""
        self.wireless_enabled = True
        self.link_kind = None

    def set_wireless(self, key, enabled=True, knob_ip="", knob_ble=""):
        """The pairing key (None when not paired) and the last known Wi-Fi
        address and Bluetooth address of the knob."""
        changed = (key != self.link_key or enabled != self.wireless_enabled)
        self.link_key = key
        self.key_id = secure.key_id(key) if key else ""
        self.wireless_enabled = enabled
        self.knob_ip = knob_ip or self.knob_ip
        self.knob_ble = knob_ble or self.knob_ble
        if changed and self.link_kind in ("wifi", "ble"):
            self.reconnect_event.set()

    def pair(self, key, ssid, password):
        """Gives the knob the key and the Wi-Fi network (USB only). Answers
        with ("pair_done", None) or ("pair_error", reason)."""
        self.jobs.put(("pair", (bytes(key), ssid, password)))

    def unpair(self):
        self.jobs.put(("unpair", None))

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.reconnect_event.set()
        self.thread.join(timeout=3)

    def use_port(self, port):
        """Switches to `port` ("" for automatic), dropping the current link."""
        self.preferred_port = port
        self.reconnect_event.set()

    def pause(self, timeout=5):
        """Closes the serial port and keeps it closed until `resume`, so a
        firmware flasher can use it. Returns True once the port is free."""
        self.idle_event.clear()
        self.pause_event.set()
        self.reconnect_event.set()
        return self.idle_event.wait(timeout)

    def resume(self):
        self.pause_event.clear()
        self.reconnect_event.set()

    def send_state(self, mode, value, orientation):
        self.outbound.put(f"STATE,{mode.upper()},{value},{orientation}\n".encode("ascii"))

    def send_style(self, accent, number_size):
        """accent is "standard" or "#RRGGBB"; number_size is the font in pixels."""
        colour = "STANDARD" if accent == "standard" else accent.lstrip("#").upper()
        self.outbound.put(f"STYLE,{colour},{number_size}\n".encode("ascii"))

    def send_comet_reset(self):
        """Puts the device's scroll/zoom comet back at its start position."""
        self.outbound.put(b"COMETRESET\n")

    def send_menu(self):
        self.outbound.put(b"SHOWMENU\n")

    def send_track(self, title, artist):
        self.outbound.put(f"TRACK,{title}\n".encode("ascii", errors="replace"))
        self.outbound.put(f"ARTIST,{artist}\n".encode("ascii", errors="replace"))

    def send_playback(self, status, position, duration):
        self.outbound.put(f"PLAY,{status},{position},{duration}\n".encode("ascii"))

    def send_screens(self, mask):
        """mask has bit n set for each mode index shown on the knob."""
        self.outbound.put(f"SCREENS,{int(mask)}\n".encode("ascii"))

    def send_pomodoro(self, phase, remaining, total, running):
        self.outbound.put(f"POMO,{int(phase)},{int(remaining)},{int(total)},"
                          f"{int(bool(running))}\n".encode("ascii"))

    def send_mute(self, volume, mic):
        self.outbound.put(f"MUTE,{int(bool(volume))},{int(bool(mic))}\n".encode("ascii"))

    def send_swipes(self, enabled):
        self.outbound.put(f"SWIPES,{int(bool(enabled))}\n".encode("ascii"))

    def send_backlight(self, percent):
        self.outbound.put(f"BACKLIGHT,{int(percent)}\n".encode("ascii"))

    def send_saver(self, enabled, idle_seconds, interval_seconds, show=0, ring=None):
        """show: 0 pictures, 1 the date and time, 2 the time over the pictures.
        ring: the seconds ring style (config.RING_STYLES index), if given."""
        line = (f"SAVER,{int(bool(enabled))},{int(idle_seconds)},"
                f"{int(interval_seconds)},{int(show)}")
        if ring is not None:
            line += f",{int(ring)}"
        self.outbound.put(f"{line}\n".encode("ascii"))

    def send_saver_look(self, shade, ink, face):
        """The screensaver clock's look: whether pictures are darkened behind
        the time, the time's colour and the face behind it ("#RRGGBB")."""
        self.outbound.put(f"SAVERLOOK,{int(bool(shade))},{ink[1:7]},{face[1:7]}\n"
                          .encode("ascii"))

    def send_dim(self, enabled):
        self.outbound.put(f"DIM,{int(bool(enabled))}\n".encode("ascii"))

    def send_time(self, local_seconds, h24=True):
        """local_seconds is the local wall-clock time counted as if it were UTC."""
        self.outbound.put(f"TIME,{int(local_seconds)},{int(bool(h24))}\n".encode("ascii"))

    def request_library(self):
        self.outbound.put(b"LIBRARY\n")

    def upload_library(self, blob):
        """Writes a packed screensaver library (header + data) to the knob.
        Progress arrives as ("upload", fraction) events, then ("upload_done",
        count) or ("upload_error", reason)."""
        self.jobs.put(("upload", bytes(blob)))

    def clear_library(self):
        self.jobs.put(("clear", None))

    def _port(self):
        ports = [port for port in list_ports.comports()
                 if (port.vid, port.pid) == DEVICE_IDS]
        if self.preferred_port:
            return next((port.device for port in ports
                         if port.device.upper() == self.preferred_port.upper()), None)
        return ports[0].device if len(ports) == 1 else None

    def _run(self):
        last_error = None
        while not self.stop_event.is_set():
            if self.pause_event.is_set():
                self.idle_event.set()
                self.stop_event.wait(0.1)
                continue
            self.reconnect_event.clear()
            port = self._port()
            if port:
                # USB always wins while a cable is plugged in.
                try:
                    with serial.Serial(port, 115200, timeout=0.2, write_timeout=1) as connection:
                        self.link_kind = "usb"
                        self.events.put(("status", f"Waiting for companion firmware on {port}"))
                        if self._serve(connection, port):
                            last_error = None
                except (serial.SerialException, OSError) as exc:
                    self.events.put(("disconnected", port))
                    status = f"Serial connection error on {port}: {exc}"
                    if status != last_error:
                        self.events.put(("status", status))
                        last_error = status
                    self.reconnect_event.wait(2)
                finally:
                    self.link_kind = None
                continue
            link = self._open_wireless()
            if link:
                last_error = None
                try:
                    with link:
                        self.link_kind = link.kind
                        self._serve(link, link.label)
                except OSError as exc:
                    self.events.put(("disconnected", link.label))
                    self.events.put(("status", f"{link.label} link lost: {exc}"))
                finally:
                    self.link_kind = None
                continue
            status = ("Device not found (connect the USB cable, or check the knob is on "
                      "and in range)" if self._wireless_ready() else
                      "Device not found (connect the ESP32-S3 USB side)")
            if status != last_error:
                self.events.put(("status", status))
                last_error = status
            self._fail_jobs("Connect the knob to do that")
            self.reconnect_event.wait(WIRELESS_RETRY_S if self._wireless_ready() else 2)

    def _wireless_ready(self):
        return bool(self.link_key) and self.wireless_enabled

    def _open_wireless(self):
        """Wi-Fi first (faster), then Bluetooth; None if neither answers."""
        if not self._wireless_ready():
            return None
        key = self.link_key
        candidates = [self.knob_ip] if self.knob_ip else []
        found = links.discover_wifi(self.key_id)
        if found and found not in candidates:
            candidates.insert(0, found)
        for host in candidates:
            if self._usb_or_stop():
                return None
            try:
                link = links.TcpLink(host, key)
            except OSError:
                continue
            self.knob_ip = host
            self.events.put(("knob_seen", ("wifi", host)))
            return link
        if not links.ble_available() or self._usb_or_stop():
            return None
        self.events.put(("status", "Looking for the knob over Bluetooth..."))
        addresses = [self.knob_ble] if self.knob_ble else []
        found = links.discover_ble()
        if found and found not in addresses:
            addresses.insert(0, found)
        for address in addresses:
            if self._usb_or_stop():
                return None
            try:
                link = links.BleLink(address, key)
            except OSError:
                continue
            self.knob_ble = address
            self.events.put(("knob_seen", ("ble", address)))
            return link
        return None

    def _usb_or_stop(self):
        return (self.stop_event.is_set() or self.pause_event.is_set()
                or self.reconnect_event.is_set() or bool(self._port()))

    def _serve(self, connection, label):
        """Runs one connection until it drops or the bridge switches link.
        Returns True once the knob said hello."""
        greeted = False
        wireless = not isinstance(connection, serial.Serial)
        next_usb_check = time.monotonic() + USB_CHECK_S
        while not self.stop_event.is_set():
            if self.reconnect_event.is_set() or self.pause_event.is_set():
                break
            if wireless and time.monotonic() >= next_usb_check:
                next_usb_check = time.monotonic() + USB_CHECK_S
                if self._port():
                    break
            line = connection.read_until(b"\n", 256).decode("ascii", errors="replace").strip()
            if line in HELLO_LINES:
                greeted = True
            self._handle_line(line, label)
            self._flush(connection)
            try:
                kind, payload = self.jobs.get_nowait()
            except queue.Empty:
                continue
            if kind == "upload":
                self._upload(connection, label, payload)
            elif kind == "clear":
                self._clear(connection, label)
            elif kind in ("pair", "unpair"):
                if wireless:
                    self.events.put(("pair_error", "Connect the knob with the USB cable to "
                                                   "pair it"))
                else:
                    self._pair(connection, label, kind, payload)
        self.events.put(("disconnected", label))
        return greeted

    def _fail_jobs(self, reason):
        """With no knob, pending pairing requests fail instead of waiting."""
        kept = []
        try:
            while True:
                kind, payload = self.jobs.get_nowait()
                if kind in ("pair", "unpair"):
                    self.events.put(("pair_error", reason))
                else:
                    kept.append((kind, payload))
        except queue.Empty:
            pass
        for job in kept:
            self.jobs.put(job)

    def _pair(self, connection, port, kind, payload):
        if kind == "unpair":
            connection.write(b"UNPAIR\n")
            reply = self._await(connection, port, ("UNPAIR_OK", "PAIR_ERR"), 10)
            if reply == "UNPAIR_OK":
                self.events.put(("pair_done", None))
            else:
                self.events.put(("pair_error", reply or "The knob did not answer"))
            return
        key, ssid, password = payload
        line = ("PAIR," + key.hex() + "," + ssid.encode("utf-8").hex() + ","
                + password.encode("utf-8").hex() + "\n")
        connection.write(line.encode("ascii"))
        reply = self._await(connection, port, ("PAIR_OK", "PAIR_ERR"), 10)
        if reply == "PAIR_OK":
            self.events.put(("pair_done", key))
        else:
            reason = {"PAIR_ERR,FORMAT": "The knob rejected the network name or password",
                      "PAIR_ERR,STORE": "The knob could not save the pairing"}.get(
                          reply, reply or "The knob did not answer (update its firmware)")
            self.events.put(("pair_error", reason))

    def _flush(self, connection):
        try:
            while True:
                connection.write(self.outbound.get_nowait())
        except queue.Empty:
            pass

    def _handle_line(self, line, port):
        """Turns one line from the knob into an event. Returns the line so a
        running upload can look for its acknowledgements."""
        if not line:
            return line
        if line in HELLO_LINES:
            # The knob shows "not connected" when nothing answers its hello.
            self.outbound.put(b"APP\n")
            self.events.put(("hello", port))
        elif line.startswith("VERSION,"):
            version = line[8:]
            if version and len(version) <= 32:
                self.events.put(("version", version))
        elif line.startswith("ROT,"):
            try:
                steps = int(line[4:])
                if 0 < abs(steps) <= 100:
                    self.events.put(("rotate", steps))
            except ValueError:
                self.events.put(("status", f"Invalid knob event: {line[:80]}"))
        elif line in ("SWIPE,LEFT", "SWIPE,RIGHT"):
            self.events.put(("swipe", line[6:]))
        elif line == "MENU":
            self.events.put(("menu", None))
        elif line == "SYNC":
            self.events.put(("sync", port))
        elif line.startswith("GAME,WHACK,"):
            try:
                score, best = (int(part) for part in line[11:].split(","))
            except ValueError:
                return line
            if 0 <= score <= 65535 and 0 <= best <= 65535:
                self.events.put(("game", (score, best)))
        elif line == "POMO,TOGGLE":
            self.events.put(("pomodoro_toggle", None))
        elif line == "MUTE,TOGGLE":
            self.events.put(("mute_toggle", None))
        elif line in ("SAVER,ON", "SAVER,OFF"):
            self.events.put(("saver", line == "SAVER,ON"))
        elif line.startswith("MEDIA,"):
            command = line[6:]
            if command in ("PREV", "PLAYPAUSE", "NEXT"):
                self.events.put(("mediacmd", command))
        elif line.startswith("NET,"):
            network = parse_network(line)
            if network:
                self.events.put(("net", network))
        elif line.startswith("LIBRARY,"):
            library = parse_library(line)
            if library:
                self.events.put(("library", library))
        elif line.startswith(("CURSOR,", "TAP,")):
            name, _, text = line.partition(",")
            try:
                index = int(text)
            except ValueError:
                self.events.put(("status", f"Invalid menu event: {line[:80]}"))
                return line
            if 0 <= index < MODE_COUNT:
                self.events.put((name.lower(), index))
        return line

    def _await(self, connection, port, prefixes, timeout):
        """Reads lines, still handling ordinary events, until one starts with
        one of `prefixes`; returns it, or None on timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.stop_event.is_set():
            line = self._handle_line(connection.read_until(b"\n", 256).decode(
                "ascii", errors="replace").strip(), port)
            self._flush(connection)
            if line.startswith(prefixes):
                return line
        return None

    def _upload(self, connection, port, blob):
        try:
            self._send_library(connection, port, blob)
        except UploadError as exc:
            self.events.put(("upload_error", str(exc)))

    def _send_library(self, connection, port, blob):
        connection.write(f"MEDIA_BEGIN,{len(blob)}\n".encode("ascii"))
        # Erasing ~13 MB of flash takes the firmware a while.
        reply = self._await(connection, port, ("MEDIA_READY", "MEDIA_ERR"), 180)
        if reply != "MEDIA_READY":
            raise UploadError(reply or "The knob did not answer")
        # The header goes last, so an interrupted upload leaves no library.
        offsets = list(range(HEADER_BYTES, len(blob), UPLOAD_CHUNK))
        offsets += list(range(0, HEADER_BYTES, UPLOAD_CHUNK))
        in_flight = 0
        for number, offset in enumerate(offsets):
            limit = HEADER_BYTES if offset < HEADER_BYTES else len(blob)
            chunk = blob[offset:min(offset + UPLOAD_CHUNK, limit)]
            connection.write(f"MD,{offset},".encode("ascii")
                             + base64.b64encode(chunk) + b"\n")
            in_flight += 1
            while in_flight >= UPLOAD_WINDOW or (number == len(offsets) - 1 and in_flight):
                reply = self._await(connection, port, ("MD_OK", "MD_ERR"), 15)
                if not reply or reply.startswith("MD_ERR"):
                    raise UploadError(reply or "The knob stopped answering")
                in_flight -= 1
            if number % 16 == 0:
                self.events.put(("upload", number / len(offsets)))
        connection.write(b"MEDIA_END\n")
        reply = self._await(connection, port, ("MEDIA_OK", "MEDIA_ERR"), 60)
        if not reply or not reply.startswith("MEDIA_OK"):
            raise UploadError(reply or "The knob did not confirm the pictures")
        self.events.put(("upload_done", int(reply.partition(",")[2] or 0)))

    def _clear(self, connection, port):
        connection.write(b"MEDIA_CLEAR\n")
        reply = self._await(connection, port, ("MEDIA_OK", "MEDIA_ERR"), 30)
        if reply and reply.startswith("MEDIA_OK"):
            self.events.put(("upload_done", 0))
        else:
            self.events.put(("upload_error", reply or "The knob did not answer"))


HEADER_BYTES = 4096


class UploadError(Exception):
    pass


def parse_library(line):
    """"LIBRARY,<capacity>,<count>,<bytes>,<crc hex>" as a dict, or None."""
    parts = line.split(",")
    if len(parts) != 5 or parts[0] != "LIBRARY":
        return None
    try:
        capacity, count, used = (int(part) for part in parts[1:4])
        crc = int(parts[4], 16)
    except ValueError:
        return None
    if min(capacity, count, used) < 0:
        return None
    return {"capacity": capacity, "count": count, "bytes": used, "crc": crc}


WIFI_STATES = ("off", "connecting", "connected", "bad_password", "not_found")


def parse_network(line):
    """"NET,<key id>,<wifi>,<ip>,<name>,<links>" as a dict, or None."""
    parts = line.split(",")
    if len(parts) != 6 or parts[0] != "NET":
        return None
    try:
        wifi = int(parts[2])
        active = int(parts[5])
    except ValueError:
        return None
    if not 0 <= wifi < len(WIFI_STATES) or not 0 <= active <= 3:
        return None
    key_id = "" if parts[1] == "-" else parts[1]
    return {"key_id": key_id, "wifi": WIFI_STATES[wifi],
            "ip": "" if parts[3] == "-" else parts[3], "name": parts[4][:24],
            "wifi_link": bool(active & 1), "ble_link": bool(active & 2)}
