import base64
import queue
import threading
import time

import serial
from serial.tools import list_ports

# USB IDs of the ESP32-S3 native USB Serial/JTAG port the knob enumerates as.
DEVICE_IDS = (0x303A, 0x1001)
# The firmware's greeting. Early builds, made while the project was called
# RoundScreen, still say so; they're accepted so the app can update them.
HELLO_LINES = ("HELLO,REVO1,1", "HELLO,ROUNDSCREEN,1")
MODE_COUNT = 7
# Raw bytes per upload line; the firmware accepts up to 3072.
UPLOAD_CHUNK = 3072
# Chunks in flight before waiting for an acknowledgement.
UPLOAD_WINDOW = 4


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

    def send_swipes(self, enabled):
        self.outbound.put(f"SWIPES,{int(bool(enabled))}\n".encode("ascii"))

    def send_backlight(self, percent):
        self.outbound.put(f"BACKLIGHT,{int(percent)}\n".encode("ascii"))

    def send_saver(self, enabled, idle_seconds, interval_seconds):
        self.outbound.put(f"SAVER,{int(bool(enabled))},{int(idle_seconds)},"
                          f"{int(interval_seconds)}\n".encode("ascii"))

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
            if not port:
                status = "Device not found (connect the ESP32-S3 USB side)"
                if status != last_error:
                    self.events.put(("status", status))
                    last_error = status
                self.reconnect_event.wait(2)
                continue
            try:
                with serial.Serial(port, 115200, timeout=0.2, write_timeout=1) as connection:
                    self.events.put(("status", f"Waiting for companion firmware on {port}"))
                    while not self.stop_event.is_set():
                        if self.reconnect_event.is_set():
                            self.events.put(("disconnected", port))
                            break
                        line = connection.read_until(b"\n", 256).decode(
                            "ascii", errors="replace").strip()
                        if line in HELLO_LINES:
                            last_error = None
                        self._handle_line(line, port)
                        self._flush(connection)
                        try:
                            kind, payload = self.jobs.get_nowait()
                        except queue.Empty:
                            continue
                        if kind == "upload":
                            self._upload(connection, port, payload)
                        elif kind == "clear":
                            self._clear(connection, port)
            except (serial.SerialException, OSError) as exc:
                self.events.put(("disconnected", port))
                status = f"Serial connection error on {port}: {exc}"
                if status != last_error:
                    self.events.put(("status", status))
                    last_error = status
                self.reconnect_event.wait(2)

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
        elif line == "POMO,TOGGLE":
            self.events.put(("pomodoro_toggle", None))
        elif line in ("SAVER,ON", "SAVER,OFF"):
            self.events.put(("saver", line == "SAVER,ON"))
        elif line.startswith("MEDIA,"):
            command = line[6:]
            if command in ("PREV", "PLAYPAUSE", "NEXT"):
                self.events.put(("mediacmd", command))
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
