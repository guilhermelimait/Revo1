import queue
import unittest
from unittest.mock import patch

from revo1.bridge import DeviceBridge


class BridgeTests(unittest.TestCase):
    def test_greetings_match_the_firmware(self):
        from pathlib import Path
        from revo1.bridge import HELLO_LINES
        source = (Path(__file__).resolve().parents[1] / "firmware" / "main" / "main.c").read_text()
        self.assertIn(f'printf("{HELLO_LINES[0]}\\n");', source)
        # Firmware from before the rename must still be found, so it can be updated.
        self.assertIn("HELLO,ROUNDSCREEN,1", HELLO_LINES)
        # A restarted knob asks for its state, and keeps what it last showed.
        self.assertIn('printf("SYNC\\n");', source)
        self.assertIn("save_settings();", source)

    def test_state_packet(self):
        bridge = DeviceBridge(queue.Queue())
        bridge.send_state("Brightness", 55, 270)
        self.assertEqual(bridge.outbound.get_nowait(), b"STATE,BRIGHTNESS,55,270\n")
        bridge.send_menu()
        self.assertEqual(bridge.outbound.get_nowait(), b"SHOWMENU\n")

    def test_port_selection(self):
        from types import SimpleNamespace
        ports = [
            SimpleNamespace(device="COM6", vid=0x1A86, pid=0x7523),
            SimpleNamespace(device="COM9", vid=0x303A, pid=0x1001),
        ]
        with patch("revo1.bridge.list_ports.comports", return_value=ports):
            self.assertEqual(DeviceBridge(queue.Queue())._port(), "COM9")
            self.assertIsNone(DeviceBridge(queue.Queue(), "COM7")._port())


    def test_new_commands(self):
        bridge = DeviceBridge(queue.Queue())
        bridge.send_screens(65)
        bridge.send_pomodoro(1, 299, 300, True)
        bridge.send_backlight(40)
        bridge.send_saver(True, 300, 30)
        bridge.request_library()
        bridge.send_swipes(False)
        sent = [bridge.outbound.get_nowait() for _ in range(6)]
        self.assertEqual(sent, [b"SCREENS,65\n", b"POMO,1,299,300,1\n", b"BACKLIGHT,40\n",
                                b"SAVER,1,300,30\n", b"LIBRARY\n", b"SWIPES,0\n"])

    def test_device_lines_become_events(self):
        events = queue.Queue()
        bridge = DeviceBridge(events)
        for line in ("TAP,6", "CURSOR,7", "POMO,TOGGLE", "SAVER,ON",
                     "LIBRARY,13561856,2,1024,A88B6A4C", "LIBRARY,x"):
            bridge._handle_line(line, "COM9")
        got = []
        while not events.empty():
            got.append(events.get_nowait())
        self.assertEqual(got, [("tap", 6), ("pomodoro_toggle", None), ("saver", True),
                               ("library", {"capacity": 13561856, "count": 2,
                                            "bytes": 1024, "crc": 0xA88B6A4C})])

    def test_upload_sends_data_then_header_and_waits_for_acks(self):
        from revo1.bridge import HEADER_BYTES, UPLOAD_CHUNK
        import base64

        class Knob:
            def __init__(self):
                self.replies = []
                self.written = {}
                self.order = []

            def write(self, data):
                line = data.decode().strip()
                if line.startswith("MEDIA_BEGIN"):
                    self.replies.append(b"MEDIA_READY\n")
                elif line.startswith("MD,"):
                    _, offset, payload = line.split(",", 2)
                    self.written[int(offset)] = base64.b64decode(payload)
                    self.order.append(int(offset))
                    self.replies.append(f"MD_OK,{offset}\n".encode())
                elif line == "MEDIA_END":
                    self.replies.append(b"MEDIA_OK,1\n")

            def read_until(self, terminator, size):
                return self.replies.pop(0) if self.replies else b""

        events = queue.Queue()
        bridge = DeviceBridge(events)
        blob = bytes(range(256)) * 60
        knob = Knob()
        bridge._upload(knob, "COM9", blob)
        rebuilt = b"".join(knob.written[offset] for offset in sorted(knob.written))
        self.assertEqual(rebuilt, blob)
        self.assertEqual(knob.order[-2:], [0, UPLOAD_CHUNK])
        self.assertTrue(all(offset >= HEADER_BYTES for offset in knob.order[:-2]))
        kinds = []
        while not events.empty():
            kinds.append(events.get_nowait())
        self.assertEqual(kinds[-1], ("upload_done", 1))


if __name__ == "__main__":
    unittest.main()
