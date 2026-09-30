import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pathlib import Path

from roundscreen import dial, ui
from roundscreen.app import App


class AppTests(unittest.TestCase):
    def test_about_offers_firmware_only_when_the_release_is_newer(self):
        root = tk.Tk()
        root.withdraw()
        saved = {"mode": "Volume", "orientation": 0, "port": ""}
        release = {"tag": "v1.1.0", "version": "1.1.0", "published": None, "url": "u",
                   "firmware_name": "roundscreen-firmware-1.1.0.bin",
                   "firmware_url": "https://example.test/fw.bin", "firmware_size": 1}
        with patch("roundscreen.app.config.load", return_value=saved), \
             patch("roundscreen.app.config.save"), \
             patch("roundscreen.app.DeviceBridge"), \
             patch("roundscreen.app.controls.volume_level", return_value=60):
            app = App(root)
            app.events.put(("release", ("ok", release)))
            app.events.put(("hello", "COM9"))
            app.poll()
            # Firmware that doesn't report a version is older than any release.
            self.assertTrue(app.firmware_update_available())
            app.events.put(("version", "1.1.0"))
            app.poll()
            self.assertFalse(app.firmware_update_available())
            app.events.put(("disconnected", "COM9"))
            app.poll()
            self.assertIsNone(app.device_version)
            self.assertFalse(app.firmware_update_available())
            app.close()

    def test_minimise_goes_to_the_tray_only_when_enabled(self):
        root = tk.Tk()
        saved = {"mode": "Volume", "orientation": 0, "port": "", "minimize_to_tray": False}
        tray = SimpleNamespace(show=lambda: shown.append(True), hide=lambda: None,
                               stop=lambda: None)
        shown = []
        with patch("roundscreen.app.config.load", return_value=saved), \
             patch("roundscreen.app.config.save"), \
             patch("roundscreen.app.DeviceBridge"), \
             patch("roundscreen.app.controls.volume_level", return_value=60):
            app = App(root, tray=tray)
            with patch.object(root, "state", return_value="iconic"):
                app.on_unmap(SimpleNamespace(widget=root))
                self.assertEqual(shown, [])
                app.toggle_tray()
                app.on_unmap(SimpleNamespace(widget=root))
            self.assertEqual(shown, [True])
            self.assertEqual(root.wm_state(), "withdrawn")
            app.close()

    def test_swipe_and_orientation_persist(self):
        root = tk.Tk()
        root.withdraw()
        saved = {"mode": "Volume", "orientation": 0, "port": ""}
        with patch("roundscreen.app.config.load", return_value=saved), \
             patch("roundscreen.app.config.save") as save, \
             patch("roundscreen.app.DeviceBridge") as bridge, \
             patch("roundscreen.app.controls.volume_level", return_value=60):
            app = App(root)
            app.events.put(("swipe", "LEFT"))
            app.poll()
            self.assertEqual(app.mode, "Scroll")
            app.set_orientation(270)
            self.assertEqual(saved["orientation"], 270)
            self.assertEqual(saved["mode"], "Scroll")
            self.assertEqual(save.call_count, 2)
            bridge.return_value.stop.assert_not_called()
            app.close()

    def test_radial_menu_selects_and_remembers_control(self):
        root = tk.Tk()
        root.withdraw()
        saved = {"mode": "Volume", "orientation": 0, "port": ""}
        with patch("roundscreen.app.config.load", return_value=saved), \
             patch("roundscreen.app.config.save"), \
             patch("roundscreen.app.DeviceBridge"), \
             patch("roundscreen.app.controls.volume_level", return_value=60), \
             patch("roundscreen.app.controls.brightness_level", return_value=75):
            app = App(root)
            app.canvas_click(SimpleNamespace(x=180, y=180))
            self.assertTrue(app.menu)
            app.canvas_click(SimpleNamespace(x=180, y=100))
            self.assertFalse(app.menu)
            self.assertEqual(saved["mode"], "Volume")
            app.canvas_click(SimpleNamespace(x=180, y=180))
            app.events.put(("tap", 2))
            app.poll()
            self.assertEqual(saved["mode"], "Brightness")
            app.close()

    def test_knob_moves_menu_cursor_and_tap_confirms(self):
        root = tk.Tk()
        root.withdraw()
        saved = {"mode": "Volume", "orientation": 0, "port": ""}
        with patch("roundscreen.app.config.load", return_value=saved), \
             patch("roundscreen.app.config.save"), \
             patch("roundscreen.app.DeviceBridge"), \
             patch("roundscreen.app.controls.volume_level", return_value=60), \
             patch("roundscreen.app.controls.brightness_level", return_value=75):
            app = App(root)
            app.events.put(("menu", None))
            app.events.put(("cursor", 2))
            app.poll()
            self.assertTrue(app.menu)
            self.assertEqual(app.menu_cursor, 2)
            app.canvas_click(SimpleNamespace(x=180 * app.scale, y=180 * app.scale))
            self.assertFalse(app.menu)
            self.assertEqual(saved["mode"], "Brightness")
            app.close()

    def test_settings_scans_automatically_and_fits_every_device(self):
        root = tk.Tk()
        root.withdraw()
        saved = {"mode": "Volume", "orientation": 0, "port": "", "name": "Knob"}
        devices = [(f"COM{n}", "USB Serial Device") for n in range(3, 8)]
        with patch("roundscreen.app.config.load", return_value=saved), \
             patch("roundscreen.app.config.save"), \
             patch("roundscreen.app.DeviceBridge"), \
             patch("roundscreen.app.controls.volume_level", return_value=60), \
             patch("roundscreen.app.find_devices", return_value=devices[:1]) as find:
            app = App(root)
            find.assert_not_called()
            app.navigate("Settings")
            self.assertEqual(len(app.device_rows), 2)
            find.return_value = devices
            app.rescan_devices()
            self.assertEqual(len(app.device_rows), 6)
            root.update_idletasks()
            self.assertGreaterEqual(root.winfo_height(), app.settings_page.winfo_reqheight())
            app.close()

    def test_interface_style_is_saved_sent_and_media_buttons_sit_in_cap(self):
        root = tk.Tk()
        root.withdraw()
        saved = {"mode": "Media", "orientation": 0, "port": "", "name": "Knob",
                 "accent": "standard", "number_size": 32}
        with patch("roundscreen.app.config.load", return_value=saved), \
             patch("roundscreen.app.config.save") as save, \
             patch("roundscreen.app.DeviceBridge") as bridge:
            app = App(root)
            app.connected = True
            self.assertEqual(app.accent("Volume"), (0, 176, 255))
            app.set_accent("#FF3B30")
            app.set_number_size(48)
            self.assertEqual(saved["accent"], "#FF3B30")
            self.assertEqual(saved["number_size"], 48)
            self.assertEqual(app.accent("Volume"), (255, 59, 48))
            bridge.return_value.send_style.assert_called_with("#FF3B30", 48)
            self.assertEqual(save.call_count, 2)
            app.show_tab("interface")
            self.assertEqual(app.settings_tab, "interface")
            scale = app.scale
            with patch.object(app.actions, "put") as put:
                app.canvas_click(SimpleNamespace(x=180 * scale, y=180 * scale))
                put.assert_called_with(("__mediacmd__", "PLAYPAUSE"))
                app.canvas_click(SimpleNamespace(x=66 * scale, y=180 * scale))
                put.assert_called_with(("__mediacmd__", "PREV"))
            app.canvas_click(SimpleNamespace(x=180 * scale, y=130 * scale))
            self.assertTrue(app.menu)
            app.close()

    def test_comet_follows_detents_exactly_like_the_device(self):
        root = tk.Tk()
        root.withdraw()
        saved = {"mode": "Scroll", "orientation": 0, "port": ""}
        with patch("roundscreen.app.config.load", return_value=saved), \
             patch("roundscreen.app.config.save"), \
             patch("roundscreen.app.DeviceBridge"):
            app = App(root)
            start = dial.GAUGE_START << 8
            for steps in (3, -1, 5, 40):
                app.rotate(steps)
            while app.advance_comet():
                pass
            self.assertEqual(app.comet_q8, start - 47 * dial.COMET_STEP_Q8)
            self.assertEqual(app.comet_direction, -1)
            app.select_mode("Zoom")
            self.assertEqual(app.comet_q8, start)
            app.close()

    def test_external_volume_change_updates_device_once(self):
        root = tk.Tk()
        root.withdraw()
        saved = {"mode": "Volume", "orientation": 90, "port": ""}
        with patch("roundscreen.app.config.load", return_value=saved), \
             patch("roundscreen.app.DeviceBridge") as bridge, \
             patch("roundscreen.app.controls.volume_level", side_effect=[40, 65, 65]):
            app = App(root)
            app.connected = True
            app.refresh_external_volume()
            self.assertEqual(app.value, 65)
            bridge.return_value.send_state.assert_called_once_with("Volume", 65, 90)
            app.refresh_external_volume()
            bridge.return_value.send_state.assert_called_once()
            app.close()

    def test_tapping_the_mode_name_returns_to_the_menu(self):
        root = tk.Tk()
        root.withdraw()
        saved = {"mode": "Media", "orientation": 0, "port": ""}
        with patch("roundscreen.app.config.load", return_value=saved), \
             patch("roundscreen.app.config.save"), \
             patch("roundscreen.app.DeviceBridge") as bridge, \
             patch("roundscreen.app.controls.volume_level", return_value=40):
            app = App(root)
            app.connected = True
            app.menu = False
            y = (dial.CENTER + dial.FOOTER_Y) * app.scale
            app.canvas_click(SimpleNamespace(x=dial.CENTER * app.scale, y=y))
            self.assertTrue(app.menu)
            bridge.return_value.send_menu.assert_called_once()
            app.close()

    def test_dial_text_uses_the_devices_own_font_file(self):
        lvgl = (Path(__file__).parents[1] / "firmware" / "managed_components" / "lvgl__lvgl"
                / "scripts" / "built_in_font" / "Montserrat-Medium.ttf")
        for path in list(ui.FONT_FILES.values()) + [ui.ICON_FILE]:
            self.assertTrue(path.is_file(), path)
        if lvgl.is_file():
            self.assertEqual(ui.FONT_FILES["device"].read_bytes(), lvgl.read_bytes())


if __name__ == "__main__":
    unittest.main()
