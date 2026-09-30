import unittest
from unittest.mock import MagicMock, patch

from revo1 import windows_controls as controls


class ControlsTests(unittest.TestCase):
    def test_volume_rotation_clamps_to_range(self):
        audio = MagicMock()
        audio.GetMasterVolumeLevelScalar.return_value = 0.98
        with patch("revo1.windows_controls._volume", return_value=audio):
            self.assertEqual(controls.change_volume(4), 100)
            audio.SetMasterVolumeLevelScalar.assert_called_once_with(1.0, None)

    def test_brightness_rotation_clamps_to_range(self):
        with patch("revo1.windows_controls.brightness_level", return_value=98), \
             patch("revo1.windows_controls._set_brightness") as setter:
            self.assertEqual(controls.change_brightness(2), 100)
            setter.assert_called_once_with(100)

    def test_scroll_sends_one_wheel_event(self):
        with patch("revo1.windows_controls._send_input") as send:
            controls.scroll(-2)
            sent = send.call_args.args[0]
            self.assertEqual(sent.type, 0)
            self.assertEqual(sent.data.mi.mouseData, (-240) & 0xFFFFFFFF)
            self.assertEqual(sent.data.mi.dwFlags, 0x0800)


if __name__ == "__main__":
    unittest.main()
