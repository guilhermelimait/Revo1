import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from revo1 import config


class ConfigTests(unittest.TestCase):
    def test_missing_file_uses_defaults(self):
        with TemporaryDirectory() as folder:
            self.assertEqual(config.load(Path(folder) / "settings.json"),
                             {"mode": "Volume", "orientation": 0, "port": "",
                              "name": "Revo1", "accent": "standard",
                              "number_size": 32, "minimize_to_tray": False})

    def test_selection_and_orientation_survive_restart(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            settings = {"mode": "Brightness", "orientation": 270, "port": "COM6",
                        "name": "Desk knob", "accent": "#FF3B30", "number_size": 48,
                        "minimize_to_tray": True}
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
                        '{"minimize_to_tray":"yes"}'):
                path.write_text(bad, encoding="utf-8")
                with self.assertRaises(ValueError):
                    config.load(path)


if __name__ == "__main__":
    unittest.main()
