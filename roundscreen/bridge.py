import queue
import threading

import serial
from serial.tools import list_ports

# USB IDs of the ESP32-S3 native USB Serial/JTAG port the knob enumerates as.
DEVICE_IDS = (0x303A, 0x1001)


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
                        line = connection.read_until(b"\n", 128).decode(
                            "ascii", errors="replace").strip()
                        if line == "HELLO,ROUNDSCREEN,1":
                            self.events.put(("hello", port))
                            last_error = None
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
                        elif line.startswith("MEDIA,"):
                            command = line[6:]
                            if command in ("PREV", "PLAYPAUSE", "NEXT"):
                                self.events.put(("mediacmd", command))
                        elif line.startswith("CURSOR,"):
                            try:
                                index = int(line[7:])
                                if 0 <= index < 6:
                                    self.events.put(("cursor", index))
                            except ValueError:
                                self.events.put(("status", f"Invalid menu event: {line[:80]}"))
                        elif line.startswith("TAP,"):
                            try:
                                index = int(line[4:])
                                if 0 <= index < 6:
                                    self.events.put(("tap", index))
                            except ValueError:
                                self.events.put(("status", f"Invalid touch event: {line[:80]}"))
                        try:
                            while True:
                                connection.write(self.outbound.get_nowait())
                        except queue.Empty:
                            pass
            except (serial.SerialException, OSError) as exc:
                self.events.put(("disconnected", port))
                status = f"Serial connection error on {port}: {exc}"
                if status != last_error:
                    self.events.put(("status", status))
                    last_error = status
                self.reconnect_event.wait(2)
