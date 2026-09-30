import queue
import unittest
from unittest.mock import patch

from roundscreen.bridge import DeviceBridge


class BridgeTests(unittest.TestCase):
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
        with patch("roundscreen.bridge.list_ports.comports", return_value=ports):
            self.assertEqual(DeviceBridge(queue.Queue())._port(), "COM9")
            self.assertIsNone(DeviceBridge(queue.Queue(), "COM7")._port())


if __name__ == "__main__":
    unittest.main()
