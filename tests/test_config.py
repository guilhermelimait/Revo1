import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from revo1 import config


class ConfigTests(unittest.TestCase):
    def test_missing_file_uses_defaults(self):
        with TemporaryDirectory() as folder:
            self.assertEqual(config.load(Path(folder) / "settings.json"), config.DEFAULTS)
            self.assertEqual(config.DEFAULTS["screens"], list(config.MODES))

    def test_missing_flags_keep_their_defaults(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text(json.dumps({"mode": "Volume"}))
            settings = config.load(path)
            self.assertTrue(settings["swipe_screens"])
            self.assertFalse(settings["invert_scroll"])

    def test_selection_and_orientation_survive_restart(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            settings = {"mode": "Brightness", "orientation": 270, "port": "COM6",
                        "name": "Desk knob", "accent": "#FF3B30", "number_size": 48,
                        "minimize_to_tray": True, "invert_scroll": True, "invert_zoom": False,
                        "swipe_screens": False,
                        "screens": ["Volume", "Brightness", "Pomodoro"], "backlight": 40,
                        "focus_minutes": 50, "break_minutes": 10, "saver_enabled": True,
                        "saver_idle": 10, "saver_interval": 60, "saver_show": "clock",
                        "dim_idle": False}
            config.save(settings, path)
            self.assertEqual(config.load(path), settings)
            self.assertEqual(json.loads(path.read_text()), settings)

    def test_invalid_settings_raise(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text('{"mode":"Invalid","orientation":45}', encoding="utf-8")
            with self.assertRaises(ValueError):
                config.load(path)

    def test_invalid_interface_settings_raise(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            for bad in ('{"accent":"red"}', '{"accent":"#GG0000"}', '{"number_size":30}',
                        '{"minimize_to_tray":"yes"}', '{"invert_zoom":1}',
                        '{"screens":[]}', '{"screens":["Volume","Volume"]}',
                        '{"screens":["Radio"]}', '{"backlight":4}', '{"backlight":50.5}',
                        '{"focus_minutes":0}', '{"break_minutes":true}',
                        '{"saver_idle":3}', '{"saver_show":"video"}', '{"saver_interval":15}', '{"saver_enabled":1}'):
                path.write_text(bad, encoding="utf-8")
                with self.assertRaises(ValueError):
                    config.load(path)


    def test_screens_keep_menu_order_and_mode_follows(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text('{"mode":"Zoom","screens":["Media","Volume"]}', encoding="utf-8")
            settings = config.load(path)
            self.assertEqual(settings["screens"], ["Volume", "Media"])
            self.assertEqual(settings["mode"], "Volume")

    def test_screen_mask(self):
        self.assertEqual(config.screen_mask(config.MODES), 127)
        self.assertEqual(config.screen_mask(["Volume", "Pomodoro"]), 1 | 64)


if __name__ == "__main__":
    unittest.main()
