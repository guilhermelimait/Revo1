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


if __name__ == "__main__":
    unittest.main()
