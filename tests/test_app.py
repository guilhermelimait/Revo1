import queue
import time
import tkinter as tk
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pathlib import Path

from revo1 import dial, ui
from revo1.app import App
from revo1.screensaver import MediaError


class AppTests(unittest.TestCase):
    def test_about_offers_firmware_only_when_the_release_is_newer(self):
        root = tk.Tk()
        root.withdraw()
        saved = {"mode": "Volume", "orientation": 0, "port": ""}
        release = {"tag": "v1.1.0", "version": "1.1.0", "published": None, "url": "u",
                   "firmware_name": "revo1-firmware-1.1.0.bin",
                   "firmware_url": "https://example.test/fw.bin", "firmware_size": 1}
        with patch("revo1.app.config.load", return_value=saved), \
             patch("revo1.app.config.save"), \
             patch("revo1.app.DeviceBridge"), \
             patch("revo1.app.controls.volume_level", return_value=60):
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

    def test_restarted_knob_gets_its_state_again(self):
        root = tk.Tk()
        root.withdraw()
        saved = {"mode": "Volume", "orientation": 270, "port": ""}
        with patch("revo1.app.config.load", return_value=saved), \
             patch("revo1.app.config.save"), \
             patch("revo1.app.DeviceBridge"), \
             patch("revo1.app.controls.volume_level", return_value=60):
            app = App(root)
            app.events.put(("hello", "COM9"))
            app.events.put(("sync", "COM9"))
            app.poll()
            # The SYNC that arrives with the first HELLO is already answered.
            self.assertEqual(app.bridge.send_state.call_count, 1)
            app.state_pushed -= 3
            app.events.put(("sync", "COM9"))
            app.poll()
            self.assertEqual(app.bridge.send_state.call_count, 2)
            app.bridge.send_state.assert_called_with("Volume", 60, 270)
            self.assertEqual(app.bridge.send_style.call_count, 2)
            app.close()

    def test_minimise_goes_to_the_tray_only_when_enabled(self):
        root = tk.Tk()
        saved = {"mode": "Volume", "orientation": 0, "port": "", "minimize_to_tray": False}
        tray = SimpleNamespace(show=lambda: shown.append(True), hide=lambda: None,
                               stop=lambda: None)
        shown = []
        with patch("revo1.app.config.load", return_value=saved), \
             patch("revo1.app.config.save"), \
             patch("revo1.app.DeviceBridge"), \
             patch("revo1.app.controls.volume_level", return_value=60):
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
        with patch("revo1.app.config.load", return_value=saved), \
             patch("revo1.app.config.save") as save, \
             patch("revo1.app.DeviceBridge") as bridge, \
             patch("revo1.app.controls.volume_level", return_value=60):
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
        with patch("revo1.app.config.load", return_value=saved), \
             patch("revo1.app.config.save"), \
             patch("revo1.app.DeviceBridge"), \
             patch("revo1.app.controls.volume_level", return_value=60), \
             patch("revo1.app.controls.brightness_level", return_value=75):
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
        with patch("revo1.app.config.load", return_value=saved), \
             patch("revo1.app.config.save"), \
             patch("revo1.app.DeviceBridge"), \
             patch("revo1.app.controls.volume_level", return_value=60), \
             patch("revo1.app.controls.brightness_level", return_value=75):
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
        with patch("revo1.app.config.load", return_value=saved), \
             patch("revo1.app.config.save"), \
             patch("revo1.app.DeviceBridge"), \
             patch("revo1.app.controls.volume_level", return_value=60), \
             patch("revo1.app.find_devices", return_value=devices[:1]) as find:
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
        with patch("revo1.app.config.load", return_value=saved), \
             patch("revo1.app.config.save") as save, \
             patch("revo1.app.DeviceBridge") as bridge:
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
        with patch("revo1.app.config.load", return_value=saved), \
             patch("revo1.app.config.save"), \
             patch("revo1.app.DeviceBridge"):
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

    def test_invert_flips_the_action_but_not_the_comet(self):
        root = tk.Tk()
        root.withdraw()
        saved = {"mode": "Scroll", "orientation": 0, "port": ""}
        with patch("revo1.app.config.load", return_value=saved), \
             patch("revo1.app.config.save") as save, \
             patch("revo1.app.DeviceBridge"):
            app = App(root)
            app.actions = queue.Queue()
            app.rotate(2)
            self.assertEqual(app.actions.get_nowait(), ("Scroll", 2))
            app.toggle_setting("invert_scroll")
            self.assertTrue(save.call_args[0][0]["invert_scroll"])
            target = app.comet_target_q8
            app.rotate(2)
            self.assertEqual(app.actions.get_nowait(), ("Scroll", -2))
            self.assertEqual(app.comet_target_q8, target - 2 * dial.COMET_STEP_Q8)
            app.select_mode("Zoom")
            app.rotate(1)
            self.assertEqual(app.actions.get_nowait(), ("Zoom", 1))
            app.toggle_setting("invert_zoom")
            app.rotate(1)
            self.assertEqual(app.actions.get_nowait(), ("Zoom", -1))
            app.select_mode("Volume")
            app.rotate(1)
            self.assertEqual(app.actions.get_nowait(), ("Volume", 1))
            app.close()

    def test_external_volume_change_updates_device_once(self):
        root = tk.Tk()
        root.withdraw()
        saved = {"mode": "Volume", "orientation": 90, "port": ""}
        with patch("revo1.app.config.load", return_value=saved), \
             patch("revo1.app.DeviceBridge") as bridge, \
             patch("revo1.app.controls.volume_level", side_effect=[40, 65, 65]):
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
        with patch("revo1.app.config.load", return_value=saved), \
             patch("revo1.app.config.save"), \
             patch("revo1.app.DeviceBridge") as bridge, \
             patch("revo1.app.controls.volume_level", return_value=40):
            app = App(root)
            app.connected = True
            app.menu = False
            y = (dial.CENTER + dial.FOOTER_Y) * app.scale
            app.canvas_click(SimpleNamespace(x=dial.CENTER * app.scale, y=y))
            self.assertTrue(app.menu)
            bridge.return_value.send_menu.assert_called_once()
            app.close()

    def test_dashboard_switches_screens_off_the_knob(self):
        root = tk.Tk()
        root.withdraw()
        saved = {"mode": "Volume", "orientation": 0, "port": ""}
        with patch("revo1.app.config.load", return_value=saved), \
             patch("revo1.app.config.save"), \
             patch("revo1.app.DeviceBridge"), \
             patch("revo1.app.controls.volume_level", return_value=60):
            app = App(root)
            self.assertEqual(app.page, "dashboard")
            app.events.put(("hello", "COM9"))
            app.poll()
            app.bridge.send_screens.assert_called_with(127)
            app.toggle_tile("Volume")
            app.bridge.send_screens.assert_called_with(126)
            # The knob leaves a screen that was switched off, and so does the app.
            self.assertEqual(app.mode, "Scroll")
            self.assertNotIn("Volume", app.nav)
            for mode in ("Scroll", "Brightness", "Mic", "Zoom", "Media"):
                app.toggle_tile(mode)
            self.assertEqual(saved["screens"], ["Pomodoro"])
            app.toggle_tile("Pomodoro")
            self.assertEqual(saved["screens"], ["Pomodoro"])
            app.close()

    def test_videos_ask_before_downloading_ffmpeg(self):
        root = tk.Tk()
        root.withdraw()
        saved = {"mode": "Volume", "orientation": 0, "port": ""}
        with patch("revo1.app.config.load", return_value=saved), \
             patch("revo1.app.config.save"), \
             patch("revo1.app.DeviceBridge"), \
             patch("revo1.app.controls.volume_level", return_value=60), \
             patch("revo1.screensaver_page.filedialog.askopenfilenames",
                   return_value=("C:/clip.mp4",)), \
             patch("revo1.screensaver.find_ffmpeg", return_value=None), \
             patch("revo1.screensaver.ensure_ffmpeg",
                   side_effect=MediaError("offline")) as ensure, \
             patch("revo1.screensaver_page.messagebox") as box:
            app = App(root)
            box.askyesno.return_value = False
            app.add_saver_media()
            self.assertIsNone(app.upload_state)
            ensure.assert_not_called()
            box.askyesno.return_value = True
            app.add_saver_media()
            for _ in range(50):
                app.poll()
                if app.upload_state and app.upload_state[0] == "failed":
                    break
                time.sleep(0.05)
            ensure.assert_called_once()
            self.assertIn("offline", app.upload_state[1])
            app.close()

    def test_swipes_can_be_switched_off_on_the_knob(self):
        root = tk.Tk()
        root.withdraw()
        saved = {"mode": "Volume", "orientation": 0, "port": ""}
        with patch("revo1.app.config.load", return_value=saved), \
             patch("revo1.app.config.save"), \
             patch("revo1.app.DeviceBridge"), \
             patch("revo1.app.controls.volume_level", return_value=60):
            app = App(root)
            app.events.put(("hello", "COM9"))
            app.poll()
            app.bridge.send_swipes.assert_called_with(True)
            app.toggle_setting("swipe_screens")
            self.assertFalse(saved["swipe_screens"])
            app.bridge.send_swipes.assert_called_with(False)
            app.close()

    def test_menu_has_one_slot_per_screen(self):
        root = tk.Tk()
        root.withdraw()
        saved = {"mode": "Volume", "orientation": 0, "port": "",
                 "screens": ["Volume", "Media", "Pomodoro", "Zoom"]}
        with patch("revo1.app.config.load", return_value=saved), \
             patch("revo1.app.config.save"), \
             patch("revo1.app.DeviceBridge"), \
             patch("revo1.app.controls.volume_level", return_value=60):
            app = App(root)
            s = app.scale
            app.open_menu()
            # Four slots: top, right, bottom, left.
            app.canvas_click(SimpleNamespace(x=300 * s, y=180 * s))
            self.assertEqual(app.mode, "Media")
            app.open_menu()
            app.canvas_click(SimpleNamespace(x=180 * s, y=300 * s))
            self.assertEqual(app.mode, "Pomodoro")
            app.open_menu()
            app.canvas_click(SimpleNamespace(x=60 * s, y=180 * s))
            self.assertEqual(app.mode, "Zoom")
            app.events.put(("swipe", "LEFT"))
            app.poll()
            self.assertEqual(app.mode, "Volume")
            app.close()

    def test_pomodoro_knob_sets_length_and_tap_starts(self):
        root = tk.Tk()
        root.withdraw()
        saved = {"mode": "Pomodoro", "orientation": 0, "port": ""}
        with patch("revo1.app.config.load", return_value=saved), \
             patch("revo1.app.config.save"), \
             patch("revo1.app.DeviceBridge"), \
             patch("revo1.app.controls.volume_level", return_value=60):
            app = App(root)
            app.events.put(("hello", "COM9"))
            app.poll()
            app.events.put(("rotate", 5))
            app.poll()
            self.assertEqual(saved["focus_minutes"], 30)
            app.bridge.send_pomodoro.assert_called_with(0, 1800, 1800, False)
            app.events.put(("pomodoro_toggle", None))
            app.poll()
            self.assertTrue(app.pomodoro.running)
            # While it runs the knob leaves the length alone.
            app.events.put(("rotate", 5))
            app.poll()
            self.assertEqual(saved["focus_minutes"], 30)
            app.canvas_click(SimpleNamespace(x=180 * app.scale, y=180 * app.scale))
            self.assertFalse(app.pomodoro.running)
            self.assertFalse(app.menu)
            app.close()

    def test_backlight_is_sent_and_saved(self):
        root = tk.Tk()
        root.withdraw()
        saved = {"mode": "Volume", "orientation": 0, "port": ""}
        with patch("revo1.app.config.load", return_value=saved), \
             patch("revo1.app.config.save") as save, \
             patch("revo1.app.DeviceBridge"), \
             patch("revo1.app.controls.volume_level", return_value=60):
            app = App(root)
            app.events.put(("hello", "COM9"))
            app.poll()
            app.bridge.send_backlight.assert_called_with(100)
            app.drag_backlight(SimpleNamespace(x=app.kit.px(30)))
            app.release_backlight(None)
            self.assertEqual(saved["backlight"], 5)
            app.bridge.send_backlight.assert_called_with(5)
            self.assertTrue(save.called)
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
