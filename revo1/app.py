import ctypes
import math
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox

from comtypes import COMError, CoInitialize, CoUninitialize
import numpy as np
from PIL import Image, ImageDraw, ImageTk

from revo1 import __version__, config, dial, icons, pomodoro, tray, ui, updater
from revo1 import windows_controls as controls
from revo1.bridge import DeviceBridge, find_devices
from revo1.dashboard_page import DashboardPage
from revo1.games_page import GamesPage
from revo1.dial import DialRenderer
from revo1.layout import (BUTTON_MIN, CARD_WIDTH, FORM_WIDTH, DIAL_GAP, MAIN_WIDTH, NAV_HEIGHT, NAV_WIDTH,
                          PANEL_BG, SIDE_WIDTH, SIDEBAR_WIDTH, WINDOW_HEIGHT)
from revo1.media import MediaSession
from revo1.screensaver import STARTER_PICTURES, Library
from revo1.screensaver_page import TIME_RESEND_S, ScreensaverPage
from revo1.wireless_page import WirelessTab, link_kind

LEVEL_MODES = ("Volume", "Mic", "Brightness")
MUTE_MODES = ("Volume", "Mic")
MUTED_RED = "#E5484D"
# How the knob is reached, as the sidebar names it: (icon, words).
LINK_NAMES = {"usb": ("Usb", "USB cable"), "ble": ("Bluetooth", "Bluetooth")}
# Beside the dial: what the knob does on each screen.
SCREEN_HELP = {
    "Volume": ("Turn the knob to set the PC volume.",
               "Tap the speaker in the centre to mute."),
    "Scroll": ("Turn the knob to scroll the window",
               "under the mouse pointer."),
    "Brightness": ("Turn the knob to set the brightness",
                   "of your screen."),
    "Mic": ("Turn the knob to set the microphone level.",
            "Tap the microphone in the centre to mute."),
    "Zoom": ("Turn the knob to zoom in or out",
             "(the same as Ctrl and + or -)."),
    "Media": ("Shows what is playing on the PC.",
              "Tap play/pause, previous or next."),
    "Pomodoro": ("A focus and break timer.",
                 "Tap the dial to start or pause it."),
}
MENU_HELP = ("Turn to choose a screen,", "then tap to open it.")
SIDE_BAR_GAP = 20
KOFI_RED = "#FF5E5B"
DEVICE_ROW_HEIGHT = 36
DEVICE_SCAN_MS = 2000
NUMBER_LABELS = {24: "Small", 32: "Medium", 40: "Large", 48: "X-Large"}
BAR_STYLE_LABELS = {"glow": "Glowing tip", "fade": "Fade to solid",
                    "soft": "Soft gradient", "solid": "Solid"}
SETTINGS_TABS = (("device", "Device"), ("controls", "Controls"), ("interface", "Interface"),
                 ("wireless", "Wireless"), ("about", "About"))
# How long a release check stays fresh before the About tab asks GitHub again.
RELEASE_CHECK_S = 30 * 60


class App(DashboardPage, ScreensaverPage, GamesPage, WirelessTab):
    def __init__(self, root, tray=None, start_minimized=False):
        self.root = root
        self.tray = tray
        self.settings = config.load()
        for key, value in config.DEFAULTS.items():
            self.settings.setdefault(key, value)
        self.settings["screens"] = list(self.settings["screens"])
        self.mode = self.settings["mode"]
        self.value = 50
        self.events = queue.Queue()
        self.bridge = DeviceBridge(self.events, self.settings["port"])
        self.init_wireless()
        self.actions = queue.Queue()
        self.worker = threading.Thread(target=self.run_actions, daemon=True)
        self._connected = False
        self.state_pushed = 0.0
        self.time_pushed = 0.0
        self.connected_port = None
        self.menu = False
        # The option the knob points at while the menu is open.
        self.menu_cursor = config.MODES.index(self.mode)
        self.pomodoro = pomodoro.PomodoroTimer(self.settings["focus_minutes"],
                                               self.settings["break_minutes"])
        self.pomodoro_sent = 0.0
        self.pomodoro_shown = None
        self.chime_folder = config.config_path().parent
        self.library = Library(starters=STARTER_PICTURES)
        # What the knob reports holding: None until it answers LIBRARY, which
        # firmware without screensaver support never does.
        self.device_library = None
        self.upload_state = None
        self.levels = {}
        self.muted = self.read_mute()
        self.backlight_sent = 0.0
        self.media = MediaSession()
        self.media_state = None
        self.media_track = None
        self.media_pending = False
        # Reported by the firmware after HELLO; None until then, and for
        # firmware older than 1.0.0 that doesn't report one.
        self.device_version = None
        self.release = None
        self.release_state = "idle"
        self.release_error = ""
        self.release_checked = 0.0
        self.update_busy = False
        self.update_text = ""
        self.update_progress = None

        root.title("Revo1")
        try:
            root.iconbitmap(default=str(ui.ICON_FILE))
        except tk.TclError:
            pass
        self.scale = root.winfo_fpixels("1i") / 96.0
        self.kit = ui.Kit(self.scale)
        size = f"{self.kit.px(SIDEBAR_WIDTH + MAIN_WIDTH)}x{self.kit.px(WINDOW_HEIGHT)}"
        root.geometry(size)
        root.minsize(self.kit.px(SIDEBAR_WIDTH + MAIN_WIDTH), self.kit.px(WINDOW_HEIGHT))
        root.configure(bg=ui.MAIN_BG)
        root.protocol("WM_DELETE_WINDOW", self.request_close)
        self.in_tray = False
        root.bind("<Unmap>", self.on_unmap)

        self.dial = DialRenderer(background=ui.rgb(ui.MAIN_BG), scale=self.scale)
        self.dial.bar_style = self.settings["bar_style"]
        self.dial_image = None
        self.dial_item = None
        self.comet_animating = False
        self.reset_comet()
        self.page = "dashboard"
        self.settings_tab = "device"
        self.saver_tab = "general"
        self.devices = None
        self.device_rows = []
        self.scan_pending = False

        self.status = tk.StringVar(value="Looking for the device...")
        self.build_sidebar()
        self.build_dashboard_page()
        self.build_control_page()
        self.build_screensaver_page()
        self.build_settings_page()
        self.status.trace_add("write", lambda *args: self.refresh_status())
        self.show_page("dashboard")

        self.bridge.start()
        self.worker.start()
        try:
            self.refresh_value()
        except (COMError, OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            self.status.set(f"{self.mode}: {exc}")
            self.render()
        root.after(80, self.poll)
        root.after(1000, self.refresh_external_volume)
        root.after(300, self.refresh_media)
        root.after(250, self.tick_pomodoro)
        root.after(500, self.refresh_levels)
        self.center_window()
        if start_minimized:
            root.after(0, self.minimize)

    @property
    def connected(self):
        return self._connected

    @connected.setter
    def connected(self, value):
        self._connected = value
        if hasattr(self, "identity"):
            self.refresh_identity()

    # ----- layout -------------------------------------------------------

    def build_sidebar(self):
        k = self.kit
        bar = tk.Frame(self.root, bg=ui.SIDEBAR_BG, width=k.px(SIDEBAR_WIDTH))
        bar.pack(side="left", fill="y")
        bar.pack_propagate(False)
        self.identity = ui.Picture(bar, ui.SIDEBAR_BG)
        self.identity.pack(padx=k.px(12), pady=(k.px(22), k.px(18)), anchor="w")
        self.nav = {}
        self.nav_list = tk.Frame(bar, bg=ui.SIDEBAR_BG)
        self.nav_list.pack(fill="x")
        self.build_nav()
        self.refresh_identity()

    def build_nav(self):
        """The sidebar lists the screens that are on the knob, between the
        dashboard and the screensaver, with settings last, all evenly spaced."""
        k = self.kit
        for child in self.nav_list.winfo_children():
            child.destroy()
        self.nav = {}
        for key in (("Dashboard",) + tuple(self.settings["screens"])
                    + ("Screensaver", "Settings")):
            button = ui.Button(self.nav_list, ui.SIDEBAR_BG,
                               lambda hover, key=key: self.paint_nav(key, hover),
                               lambda key=key: self.navigate(key))
            button.pack(padx=k.px(12), pady=k.px(1), anchor="w")
            self.nav[key] = button

    def build_control_page(self):
        k = self.kit
        page = tk.Frame(self.root, bg=ui.MAIN_BG)
        # Games swap the dial for their cards; the knob's menu still shows the dial.
        # The dial on the left; its name, help and buttons on the right.
        self.dial_box = tk.Frame(page, bg=ui.MAIN_BG)
        self.dial_box.pack(expand=True)
        self.canvas = tk.Canvas(self.dial_box, width=self.dial.size, height=self.dial.size,
                                bg=ui.MAIN_BG, highlightthickness=0)
        self.canvas.bind("<Button-1>", self.canvas_click)
        self.canvas.pack(side="left")
        side = tk.Frame(self.dial_box, bg=ui.MAIN_BG)
        side.pack(side="left", padx=(k.px(DIAL_GAP), 0))
        self.label = ui.Picture(side, ui.MAIN_BG)
        self.label.pack(anchor="w")
        # Timer lengths and buttons, shown only on the Pomodoro screen.
        self.pomodoro_bar = tk.Frame(side, bg=ui.MAIN_BG)
        self.pomodoro_buttons = []
        widths = self.fill_widths([0, 0], total=SIDE_WIDTH)
        for keys in (("focus", "break"), ("start", "reset")):
            row = tk.Frame(self.pomodoro_bar, bg=ui.MAIN_BG)
            row.pack(pady=(0, k.px(8)))
            buttons = []
            for key, width in zip(keys, widths):
                if key in ("focus", "break"):
                    button = ui.Button(row, ui.MAIN_BG,
                                       lambda hover, key=key, width=width:
                                           self.paint_stepper(key, hover, width),
                                       lambda: None)
                    button.bind("<Button-1>",
                                lambda event, key=key: self.step_pomodoro(key, event))
                else:
                    button = ui.Button(row, ui.MAIN_BG,
                                       lambda hover, key=key, width=width:
                                           self.paint_pill(self.pomodoro_label(key), hover,
                                                           primary=key == "start",
                                                           width=width),
                                       lambda key=key: self.pomodoro_action(key))
                buttons.append(button)
            self.pack_row(buttons)
            self.pomodoro_buttons += buttons
        if self.mode == "Pomodoro":
            self.pomodoro_bar.pack(anchor="w", pady=(k.px(SIDE_BAR_GAP), 0))
        # Mute for the speakers or the microphone, beside the Volume and Mic dials.
        self.mute_bar = tk.Frame(side, bg=ui.MAIN_BG)
        self.mute_button = ui.Button(self.mute_bar, ui.MAIN_BG, self.paint_mute_button,
                                     self.toggle_mute)
        self.mute_button.pack()
        if self.mode in MUTE_MODES:
            self.mute_bar.pack(anchor="w", pady=(k.px(SIDE_BAR_GAP), 0))
        self.build_games_panel(page)
        self.control_page = page

    def build_settings_page(self):
        k = self.kit
        page = tk.Frame(self.root, bg=ui.MAIN_BG)
        title = ui.Picture(page, ui.MAIN_BG)
        image = k.canvas(CARD_WIDTH, 44, ui.MAIN_BG)
        k.text(image, 0, 22, "Settings", "semibold", 18, ui.INK)
        title.show(image)
        title.pack(padx=k.px(28), pady=(k.px(18), k.px(4)), anchor="w")

        tabs = tk.Frame(page, bg=ui.MAIN_BG)
        tabs.pack(padx=k.px(28), pady=(0, k.px(12)), anchor="w")
        self.tab_buttons = []
        for key, label in SETTINGS_TABS:
            button = ui.Button(tabs, ui.MAIN_BG,
                               lambda hover, key=key, label=label: self.paint_tab(key, label, hover),
                               lambda key=key: self.show_tab(key))
            button.pack(side="left")
            self.tab_buttons.append(button)

        self.tabs = {key: tk.Frame(page, bg=ui.MAIN_BG) for key, _ in SETTINGS_TABS}
        self.build_device_tab(self.tabs["device"])
        self.build_controls_tab(self.tabs["controls"])
        self.build_interface_tab(self.tabs["interface"])
        self.build_wireless_tab(self.tabs["wireless"])
        self.build_about_tab(self.tabs["about"])
        self.settings_page = page
        self.show_tab(self.settings_tab)
        self.refresh_status()

    def build_device_tab(self, tab):
        k = self.kit
        body = self.section(tab)
        self.caption(body, "SCREEN BACKLIGHT").pack(anchor="w")
        self.backlight_slider = ui.Button(body, PANEL_BG, self.paint_backlight, lambda: None)
        for sequence in ("<Button-1>", "<B1-Motion>"):
            self.backlight_slider.bind(sequence, self.drag_backlight)
        self.backlight_slider.bind("<ButtonRelease-1>", self.release_backlight)
        self.backlight_slider.pack(anchor="w", pady=(k.px(6), 0))

        body = self.section(tab)
        self.caption(body, "DEVICE NAME").pack(anchor="w")
        self.name_entry = tk.Entry(body, font=(ui.TK_FAMILY, 11), bg="#FFFFFF", fg=ui.INK,
                                   relief="flat", highlightthickness=1,
                                   highlightbackground=ui.CARD_EDGE,
                                   highlightcolor=ui.SUBTLE_INK, insertbackground=ui.INK)
        self.name_entry.insert(0, self.settings["name"])
        self.name_entry.bind("<Return>", self.save_name)
        self.name_entry.bind("<FocusOut>", self.save_name)
        self.name_entry.config(width=24)
        self.name_entry.pack(anchor="w", pady=(k.px(6), k.px(12)), ipady=k.px(4), ipadx=k.px(6))
        self.caption(body, "DEVICES").pack(anchor="w")
        self.connection_text = ui.Picture(body, PANEL_BG)
        self.connection_text.pack(anchor="w", pady=(k.px(2), 0))
        self.device_list = tk.Frame(body, bg=PANEL_BG)
        self.device_list.pack(anchor="w")

    def build_controls_tab(self, tab):
        k = self.kit
        body = self.section(tab)
        self.caption(body, "SCREEN ORIENTATION").pack(anchor="w")
        row = tk.Frame(body, bg=PANEL_BG)
        row.pack(anchor="w", pady=(k.px(6), 0))
        self.orientation_buttons = []
        widths = [72] * len(config.ORIENTATIONS)
        for value, width in zip(config.ORIENTATIONS, widths):
            button = ui.Button(row, PANEL_BG,
                               lambda hover, value=value, width=width:
                                   self.paint_orientation(value, hover, width),
                               lambda value=value: self.set_orientation(value))
            self.orientation_buttons.append(button)
        self.pack_row(self.orientation_buttons)

        body = self.section(tab)
        self.caption(body, "KNOB DIRECTION").pack(anchor="w")
        self.invert_toggles = []
        for key, title, detail in (
                ("invert_scroll", "Invert scroll",
                 "Turning clockwise scrolls up instead of down"),
                ("invert_zoom", "Invert zoom",
                 "Turning clockwise zooms out instead of in")):
            toggle = ui.Button(body, PANEL_BG,
                               lambda hover, key=key, title=title, detail=detail:
                                   self.paint_toggle(self.settings[key], title, detail, hover),
                               lambda key=key: self.toggle_setting(key))
            toggle.pack(anchor="w", pady=(k.px(6), 0))
            self.invert_toggles.append(toggle)

        body = self.section(tab)
        self.caption(body, "TOUCH").pack(anchor="w")
        toggle = ui.Button(body, PANEL_BG,
                           lambda hover: self.paint_toggle(
                               self.settings["swipe_screens"], "Swipe between screens",
                               "Swipe left or right on the knob to change screen", hover),
                           lambda: self.toggle_setting("swipe_screens"))
        toggle.pack(anchor="w", pady=(k.px(6), 0))
        self.invert_toggles.append(toggle)

    def build_interface_tab(self, tab):
        k = self.kit
        body = self.section(tab)
        self.caption(body, "BAR COLOUR").pack(anchor="w")
        self.accent_buttons = []
        row = tk.Frame(body, bg=PANEL_BG)
        row.pack(anchor="w", pady=(k.px(6), 0))
        for key, width in zip(("standard", "custom"), (150, 150)):
            button = ui.Button(row, PANEL_BG,
                               lambda hover, key=key, width=width:
                                   self.paint_accent_choice(key, hover, width),
                               lambda key=key: self.pick_accent_choice(key))
            self.accent_buttons.append(button)
        self.pack_row(self.accent_buttons)
        row = tk.Frame(body, bg=PANEL_BG)
        row.pack(anchor="w", pady=(k.px(10), 0))
        swatches = []
        for colour in dial.PRESET_ACCENTS:
            swatches.append(ui.Button(row, PANEL_BG,
                                      lambda hover, colour=colour: self.paint_swatch(colour, hover),
                                      lambda colour=colour: self.set_accent(colour)))
        self.pack_row(swatches, 6)
        self.accent_buttons += swatches
        self.caption(body, "BAR STYLE").pack(anchor="w", pady=(k.px(16), 0))
        row = tk.Frame(body, bg=PANEL_BG)
        row.pack(anchor="w", pady=(k.px(2), 0))
        styles = [ui.Button(row, PANEL_BG,
                            lambda hover, style=style: self.paint_radio(
                                self.settings["bar_style"] == style, BAR_STYLE_LABELS[style], hover),
                            lambda style=style: self.set_bar_style(style))
                  for style in config.BAR_STYLES]
        self.pack_row(styles, 20)
        self.accent_buttons += styles

        body = self.section(tab)
        self.caption(body, "NUMBER SIZE").pack(anchor="w")
        row = tk.Frame(body, bg=PANEL_BG)
        row.pack(anchor="w", pady=(k.px(6), 0))
        self.size_buttons = []
        widths = [80] * len(config.NUMBER_SIZES)
        for size, width in zip(config.NUMBER_SIZES, widths):
            button = ui.Button(row, PANEL_BG,
                               lambda hover, size=size, width=width:
                                   self.paint_number_size(size, hover, width),
                               lambda size=size: self.set_number_size(size))
            self.size_buttons.append(button)
        self.pack_row(self.size_buttons)

        body = self.section(tab)
        self.caption(body, "WINDOW").pack(anchor="w")
        self.tray_toggle = ui.Button(body, PANEL_BG, self.paint_tray_toggle,
                                     self.toggle_tray)
        self.tray_toggle.pack(anchor="w", pady=(k.px(6), 0))

    def build_about_tab(self, tab):
        k = self.kit
        body = self.section(tab)
        header = ui.Picture(body, PANEL_BG)
        header.show(self.paint_about_header())
        header.pack(anchor="w")
        row = tk.Frame(body, bg=PANEL_BG)
        row.pack(anchor="w", pady=(k.px(12), 0))
        links = (("GitHub", updater.PROJECT_URL, False),
                 ("Releases", updater.RELEASES_URL, False),
                 ("Licence", updater.PROJECT_URL + "/blob/main/LICENSE", False),
                 ("Ko-fi", updater.KOFI_URL, True))
        widths = self.button_widths([self.pill_width(label, kofi) for label, _, kofi in links])
        buttons = []
        for (label, url, kofi), width in zip(links, widths):
            buttons.append(ui.Button(
                row, PANEL_BG,
                lambda hover, label=label, width=width, kofi=kofi:
                    self.paint_pill(label, hover, width=width, heart=kofi),
                lambda url=url: webbrowser.open(url)))
        self.pack_row(buttons)

        body = self.section(tab)
        self.caption(body, "UPDATES").pack(anchor="w")
        self.about_info = ui.Picture(body, PANEL_BG)
        self.about_info.pack(anchor="w", pady=(k.px(4), 0))
        self.about_actions = tk.Frame(body, bg=PANEL_BG)
        self.about_actions.pack(anchor="w", pady=(k.px(10), 0))
        self.refresh_about()

    def section(self, tab):
        """One group of settings. Groups after the first are set off by a
        hairline rather than each sitting in its own rounded box."""
        k = self.kit
        if tab.winfo_children():
            rule = ui.Picture(tab, PANEL_BG)
            image = k.canvas(CARD_WIDTH, 1, PANEL_BG)
            k.rounded(image, (0, 0, CARD_WIDTH, 1), 0.1, ui.CARD_EDGE)
            rule.show(image)
            rule.pack(padx=k.px(28), pady=(0, k.px(18)), anchor="w")
        body = tk.Frame(tab, bg=PANEL_BG)
        body.pack(padx=k.px(28), pady=(0, k.px(18)), anchor="w")
        return body

    @staticmethod
    def fill_widths(naturals, gap=8, total=CARD_WIDTH):
        """Widths (layout units) that stretch buttons to span the full row:
        the spare room is shared out and the last one takes the remainder."""
        extra = max(total - sum(naturals) - gap * (len(naturals) - 1), 0)
        share = extra // len(naturals)
        widths = [int(width) + share for width in naturals]
        widths[-1] = total - gap * (len(naturals) - 1) - sum(widths[:-1])
        return widths

    @staticmethod
    def button_widths(naturals):
        """Content-sized buttons, with a floor so short labels still make a
        comfortable target."""
        return [max(BUTTON_MIN, round(width)) for width in naturals]

    def pack_row(self, buttons, gap=8):
        """Packs buttons side by side, gap between them and none at the end."""
        for index, button in enumerate(buttons):
            button.pack(side="left",
                        padx=(0, 0 if index == len(buttons) - 1 else self.kit.px(gap)))

    def caption(self, parent, text):
        picture = ui.Picture(parent, PANEL_BG)
        image = self.kit.canvas(CARD_WIDTH, 16, PANEL_BG)
        x = 0.0
        for ch in text:
            self.kit.text(image, x, 8, ch, "semibold", 8, ui.MUTED_INK)
            x += self.kit.font("semibold", 8).getlength(ch) / self.scale + 1.2
        picture.show(image)
        return picture

    # ----- painters -----------------------------------------------------

    def paint_nav(self, key, hover):
        k = self.kit
        image = k.canvas(NAV_WIDTH, NAV_HEIGHT, ui.SIDEBAR_BG)
        if key == "Settings":
            selected = self.page == "settings"
        elif key == "Dashboard":
            selected = self.page == "dashboard"
        elif key == "Screensaver":
            selected = self.page == "screensaver"
        else:
            selected = self.page == "control" and key == self.mode
        accent = self.accent(key) if key in dial.ACCENTS else None
        if selected:
            k.rounded(image, (0, 0, NAV_WIDTH, NAV_HEIGHT), 12, ui.CARD_BG, ui.CARD_EDGE)
            if accent:
                k.rounded(image, (7, 13, 10, NAV_HEIGHT - 13), 1.5, accent)
        elif hover:
            k.rounded(image, (0, 0, NAV_WIDTH, NAV_HEIGHT), 12, ui.HOVER_BG)
        if selected:
            ink = dial.label_ink(accent) if accent else ui.INK
        else:
            ink = ui.SUBTLE_INK
        k.icon(image, key, 31, NAV_HEIGHT / 2, ink, 0.8)
        k.text(image, 56, NAV_HEIGHT / 2, config.title(key), "semibold" if selected else "regular", 10.5,
               ui.INK if selected else ui.SUBTLE_INK)
        return image

    def paint_device(self, port, description, hover):
        k = self.kit
        width, height = FORM_WIDTH, DEVICE_ROW_HEIGHT
        image = k.canvas(width, height, PANEL_BG)
        chosen = self.settings["port"].upper() == port.upper()
        k.rounded(image, (0, 0, width, height), 9,
                  "#FFFFFF" if hover or chosen else ui.CARD_BG, ui.CARD_EDGE)
        live = self.connected and (not port or port.upper() == (self.connected_port or "").upper())
        k.dot(image, 16, height / 2, 3.5, ui.OK_GREEN if live else ui.IDLE_GREY)
        title = port or "Automatic"
        k.text(image, 28, height / 2, title, "semibold", 10, ui.INK)
        offset = 28 + k.font("semibold", 10).getlength(title) / k.scale + 10
        k.text(image, offset, height / 2, description, "regular", 8.5, ui.MUTED_INK,
               width=width - offset - 36)
        if chosen:
            k.icon(image, "Check", width - 20, height / 2,
                   dial.label_ink(self.accent(self.mode)), 0.8)
        return image

    def paint_orientation(self, value, hover, width=64):
        k = self.kit
        height = 32
        image = k.canvas(width, height, PANEL_BG)
        if value == self.settings["orientation"]:
            k.rounded(image, (0, 0, width, height), 9, ui.INK)
            ink = "#FFFFFF"
        else:
            k.rounded(image, (0, 0, width, height), 9, "#FFFFFF" if hover else ui.CARD_BG,
                      ui.CARD_EDGE)
            ink = ui.SUBTLE_INK
        k.text(image, width / 2, height / 2, f"{value}°", "semibold", 10, ink, anchor="mm")
        return image

    def tab_width(self, key, tabs=SETTINGS_TABS):
        """Tabs are as wide as their label plus a gap; the last one runs on to
        the edge so the hairline under them spans the whole page."""
        font = self.kit.font("semibold", 10)
        widths = [font.getlength(label) / self.kit.scale + 28 for _, label in tabs]
        index = [key for key, _ in tabs].index(key)
        if index == len(tabs) - 1:
            return CARD_WIDTH - sum(round(width) for width in widths[:-1])
        return round(widths[index])

    def paint_tab(self, key, label, hover, tabs=SETTINGS_TABS, current=None):
        """Underline tabs: labels on one hairline, the open one in bold with a
        bar in the current accent. The first label lines up with the settings."""
        k = self.kit
        width, height = self.tab_width(key, tabs), 34
        image = k.canvas(width, height, PANEL_BG)
        active = key == (current or self.settings_tab)
        k.rounded(image, (0, height - 1, width, height), 0.1, ui.CARD_EDGE)
        text = k.font("semibold", 10).getlength(label) / k.scale
        if active:
            k.rounded(image, (0, height - 3, text, height), 1.5, self.accent(self.mode))
        elif hover:
            k.rounded(image, (0, height - 2, text, height), 1, ui.MUTED_INK)
        ink = ui.INK if active else (ui.SUBTLE_INK if hover else ui.MUTED_INK)
        k.text(image, 0, (height - 3) / 2, label, "semibold" if active else "device", 10, ink)
        return image

    def paint_accent_choice(self, key, hover, width=140):
        """"Standard" keeps a colour per control; "Custom" opens a colour picker."""
        k = self.kit
        height = 36
        image = k.canvas(width, height, PANEL_BG)
        accent = self.settings["accent"]
        if key == "standard":
            chosen = accent == config.STANDARD_ACCENT
        else:
            chosen = accent != config.STANDARD_ACCENT and accent not in dial.PRESET_ACCENTS
        if chosen:
            k.rounded(image, (0, 0, width, height), 10, ui.INK)
            ink = "#FFFFFF"
        else:
            k.rounded(image, (0, 0, width, height), 10, "#FFFFFF" if hover else ui.CARD_BG,
                      ui.CARD_EDGE)
            ink = ui.SUBTLE_INK
        if key == "standard":
            for index, mode in enumerate(config.MODES):
                angle = math.radians(90 - index * 360 / len(config.MODES))
                k.dot(image, 20 + 6 * math.cos(angle), height / 2 - 6 * math.sin(angle), 2.6,
                      dial.ACCENTS[mode])
            label = "Standard"
        else:
            colour = accent if chosen else "#FFFFFF"
            k.dot(image, 20, height / 2, 8, ui.CARD_EDGE)
            k.dot(image, 20, height / 2, 7, colour)
            label = "Custom\u2026"
        k.text(image, 38, height / 2, label, "semibold", 10, ink)
        return image

    def paint_swatch(self, colour, hover):
        k = self.kit
        size = 34
        image = k.canvas(size, size, PANEL_BG)
        c = size / 2
        if self.settings["accent"] == colour:
            k.dot(image, c, c, 16, ui.INK)
            k.dot(image, c, c, 14, PANEL_BG)
        elif hover:
            k.dot(image, c, c, 16, ui.CARD_EDGE)
            k.dot(image, c, c, 14.5, PANEL_BG)
        k.dot(image, c, c, 11.5, colour)
        return image

    def paint_number_size(self, size, hover, width=76):
        k = self.kit
        height = 56
        image = k.canvas(width, height, PANEL_BG)
        if size == self.settings["number_size"]:
            k.rounded(image, (0, 0, width, height), 10, ui.INK)
            ink, label_ink = "#FFFFFF", "#C8C8D2"
        else:
            k.rounded(image, (0, 0, width, height), 10, "#FFFFFF" if hover else ui.CARD_BG,
                      ui.CARD_EDGE)
            ink, label_ink = ui.INK, ui.MUTED_INK
        k.text(image, width / 2, 23, "42", "device", size * 0.42, ink, anchor="mm")
        k.text(image, width / 2, 45, NUMBER_LABELS[size], "regular", 7.5, label_ink,
               anchor="mm")
        return image

    def paint_tray_toggle(self, hover):
        return self.paint_toggle(self.settings["minimize_to_tray"],
                                 "Minimise to the notification area",
                                 "Keeps Revo1 running next to the clock", hover)

    def paint_toggle(self, on, title, detail, hover):
        k = self.kit
        width, height = FORM_WIDTH, 40
        image = k.canvas(width, height, PANEL_BG)
        k.text(image, 0, 12, title, "semibold", 10, ui.INK)
        k.text(image, 0, 30, detail, "regular", 8.5, ui.MUTED_INK, width=width - 60)
        x0, y0 = width - 44, height / 2 - 12
        track = ui.INK if on else (ui.SUBTLE_INK if hover else ui.IDLE_GREY)
        k.rounded(image, (x0, y0, x0 + 44, y0 + 24), 12, track)
        k.dot(image, x0 + (32 if on else 12), height / 2, 9, "#FFFFFF")
        return image

    def pill_width(self, label, heart=False):
        width = self.kit.font("semibold", 9.5).getlength(label) / self.kit.scale + 28
        return round(width + (16 if heart else 0))

    def paint_pill(self, label, hover, primary=False, enabled=True, width=None, heart=False,
                   height=30):
        k = self.kit
        width = width or self.pill_width(label, heart)
        image = k.canvas(width, height, PANEL_BG)
        if primary and enabled:
            fill = dial.label_ink(self.accent(self.mode)) if hover else ui.INK
            k.rounded(image, (0, 0, width, height), height / 2, fill)
            ink = "#FFFFFF"
        else:
            k.rounded(image, (0, 0, width, height), height / 2,
                      "#FFFFFF" if hover and enabled else ui.CARD_BG, ui.CARD_EDGE)
            ink = ui.INK if enabled else ui.MUTED_INK
        if heart:
            text = k.font("semibold", 9.5).getlength(label) / k.scale
            left = (width - text - 16) / 2
            self.paint_heart(image, left + 5, height / 2, KOFI_RED)
            k.text(image, left + 16, height / 2, label, "semibold", 9.5, ink)
        else:
            k.text(image, width / 2, height / 2, label, "semibold", 9.5, ink, anchor="mm")
        return image

    def paint_mute_button(self, hover):
        """Mute or Unmute, with the speaker or microphone icon; red while muted."""
        k = self.kit
        mode = self.mode if self.mode in MUTE_MODES else "Volume"
        muted = self.muted.get(mode, False)
        width, height = SIDE_WIDTH, 34
        image = k.canvas(width, height, ui.MAIN_BG)
        if muted:
            k.rounded(image, (0, 0, width, height), 17, "#D93F45" if hover else MUTED_RED)
            ink = "#FFFFFF"
        else:
            k.rounded(image, (0, 0, width, height), 17, "#FFFFFF" if hover else ui.CARD_BG,
                      ui.CARD_EDGE)
            ink = ui.INK
        label = "Unmute" if muted else "Mute"
        label += " microphone" if mode == "Mic" else " sound"
        text = k.font("semibold", 9.5).getlength(label) / k.scale
        left = (width - text - 24) / 2
        k.icon(image, mode + "Muted" if not muted else mode, left + 8, height / 2, ink, 0.55)
        k.text(image, left + 24, height / 2, label, "semibold", 9.5, ink)
        return image

    def paint_heart(self, image, x, y, colour):
        """A small heart from two dots and a triangle (layout units)."""
        k = self.kit
        k.dot(image, x - 2.6, y - 1.6, 3, colour)
        k.dot(image, x + 2.6, y - 1.6, 3, colour)
        scale = 4
        size = k.px(12) * scale
        mask = Image.new("L", (size, size), 0)
        c = size / 2
        r = k.px(3) * scale
        ImageDraw.Draw(mask).polygon(
            [(c - 2 * r * 0.93, c - k.px(1.6) * scale + r * 0.37),
             (c + 2 * r * 0.93, c - k.px(1.6) * scale + r * 0.37),
             (c, c + k.px(4.6) * scale)], fill=255)
        mask = mask.resize((size // scale, size // scale), Image.LANCZOS)
        image.paste(Image.new("RGB", mask.size, ui.rgb(colour)),
                    (round(k.px(x) - mask.width / 2), round(k.px(y) - mask.height / 2)), mask)

    def paint_about_header(self):
        k = self.kit
        width, height = CARD_WIDTH, 64
        image = k.canvas(width, height, PANEL_BG)
        try:
            with Image.open(ui.ICON_FILE.with_suffix(".png")) as logo:
                logo = logo.convert("RGBA").resize((k.px(56), k.px(56)), Image.LANCZOS)
                image.paste(logo, (0, k.px(4)), logo)
        except OSError:
            pass
        k.text(image, 70, 16, "Revo1", "semibold", 14, ui.INK)
        k.text(image, 70, 36, f"Version {__version__}", "regular", 9.5, ui.SUBTLE_INK)
        k.text(image, 70, 53, "Companion for the Waveshare ESP32-S3 knob",
               "regular", 8.5, ui.MUTED_INK, width=width - 70)
        return image

    def about_rows(self):
        """(label, value) lines for the Updates card."""
        if not self.connected:
            firmware = "Device not connected"
        elif self.device_version:
            firmware = self.device_version
        else:
            firmware = "Older than 1.0.0"
        release = self.release
        if self.release_state == "checking":
            latest = "Checking\u2026"
        elif self.release_state == "error":
            latest = f"Couldn't check: {self.release_error}"
        elif self.release_state == "ok" and release is None:
            latest = "No release published yet"
        elif release:
            latest = release["tag"] or release["version"]
            if release["published"]:
                latest += f" \u00b7 {release['published']:%d %b %Y}"
        else:
            latest = "\u2014"
        return [("App", __version__), ("Device firmware", firmware), ("Latest release", latest)]

    def firmware_update_available(self):
        release = self.release
        return bool(self.connected and release and release["firmware_url"]
                    and updater.is_newer(release["version"], self.device_version))

    def app_update_available(self):
        return bool(self.release and updater.is_newer(self.release["version"], __version__))

    def paint_about_info(self):
        k = self.kit
        width = CARD_WIDTH
        rows = self.about_rows()
        extra = 28 if self.update_text else 0
        image = k.canvas(width, len(rows) * 24 + extra, PANEL_BG)
        for index, (label, value) in enumerate(rows):
            y = index * 24 + 12
            k.text(image, 0, y, label, "regular", 9.5, ui.SUBTLE_INK)
            k.text(image, 120, y, value, "semibold", 9.5, ui.INK, width=width - 120)
        if self.update_text:
            y = len(rows) * 24 + 8
            k.text(image, 0, y, self.update_text, "regular", 9, ui.SUBTLE_INK, width=width)
            if self.update_progress is not None:
                k.rounded(image, (0, y + 11, width, y + 17), 3, ui.CARD_EDGE)
                filled = max(6, width * self.update_progress)
                k.rounded(image, (0, y + 11, filled, y + 17), 3,
                          dial.label_ink(self.accent(self.mode)))
        return image

    def refresh_identity(self):
        k = self.kit
        image = k.canvas(NAV_WIDTH, 50, ui.SIDEBAR_BG)
        self.paint_knob_badge(image, 24, 25, 17)
        k.text(image, 50, 15, self.settings["name"], "semibold", 14, ui.INK, width=NAV_WIDTH - 54)
        link = LINK_NAMES.get(self.link_kind) if self.connected else None
        if link:
            icon, name = link
            k.icon(image, icon, 55, 38, ui.OK_GREEN, 0.42)
            k.text(image, 64, 38, f"On {name}", "regular", 9, ui.SUBTLE_INK,
                   width=NAV_WIDTH - 66)
        else:
            k.dot(image, 54, 38, 3.5, ui.OK_GREEN if self.connected else ui.IDLE_GREY)
            k.text(image, 63, 38, "Connected" if self.connected else "Not connected",
                   "regular", 9, ui.SUBTLE_INK)
        self.identity.show(image)

    def paint_knob_badge(self, image, cx, cy, radius):
        """A miniature of the knob: a light bezel round a dark screen, whose
        ring always shows the bar colour of the current screen."""
        k = self.kit
        factor = 4
        size = k.px(radius * 2) * factor
        badge = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(badge)
        unit = size / (radius * 2)

        def circle(r, fill=None, outline=None, width=0):
            pad = size / 2 - r * unit
            draw.ellipse((pad, pad, size - pad, size - pad), fill=fill, outline=outline,
                         width=round(width * unit))

        circle(radius, fill=(0xC4, 0xC4, 0xCC))
        circle(radius - 1, fill=(0xEC, 0xEC, 0xF0))
        circle(radius - 4, fill=(0x1C, 0x1C, 0x24))
        ring = radius - 7
        pad = size / 2 - ring * unit
        box = (pad, pad, size - pad, size - pad)
        draw.arc(box, 135, 405, fill=(0x3A, 0x3A, 0x46), width=round(2.2 * unit))
        draw.arc(box, 135, 315, fill=tuple(self.accent(self.mode)), width=round(2.2 * unit))
        badge = badge.resize((size // factor, size // factor), Image.LANCZOS)
        image.paste(badge, (k.px(cx - radius), k.px(cy - radius)), badge)

    def refresh_status(self):
        image = self.kit.canvas(CARD_WIDTH, 20, PANEL_BG)
        self.kit.text(image, 0, 10, self.status.get(), "regular", 10, ui.SUBTLE_INK,
                      width=CARD_WIDTH)
        self.connection_text.show(image)
        for button in self.device_rows:
            button.refresh()

    def refresh_nav(self):
        for button in self.nav.values():
            button.refresh()
        if hasattr(self, "identity"):
            self.refresh_identity()

    # ----- settings actions ---------------------------------------------

    def show_page(self, page):
        self.page = page
        pages = {"dashboard": self.dashboard_page, "control": self.control_page,
                 "screensaver": self.screensaver_page, "settings": self.settings_page}
        for frame in pages.values():
            frame.pack_forget()
        pages[page].pack(side="left", fill="both", expand=True)
        self.refresh_nav()
        if page == "dashboard":
            self.refresh_dashboard()
        elif page == "screensaver":
            self.refresh_screensaver()

    def navigate(self, key):
        if key == "Settings":
            self.show_page("settings")
            self.scan_devices()
            return
        if key == "Dashboard":
            self.show_page("dashboard")
            return
        if key == "Screensaver":
            self.show_page("screensaver")
            return
        self.show_page("control")
        if key != self.mode or self.menu:
            self.choose(key)

    def show_tab(self, key):
        self.settings_tab = key
        if key == "about" and (self.release_state in ("idle", "error") or
                               time.monotonic() - self.release_checked > RELEASE_CHECK_S):
            self.check_release()
        for frame in self.tabs.values():
            frame.pack_forget()
        self.tabs[key].pack(fill="x", anchor="w")
        for button in self.tab_buttons:
            button.refresh()
        if self.page == "settings":
            self.fit_window()

    def accent(self, mode):
        """The bar colour for `mode`: its own in the standard style, otherwise
        the single colour the user picked."""
        chosen = self.settings["accent"]
        if chosen == config.STANDARD_ACCENT:
            return dial.ACCENTS[mode]
        return ui.rgb(chosen)

    def pick_accent_choice(self, key):
        if key == "standard":
            self.set_accent(config.STANDARD_ACCENT)
            return
        current = self.settings["accent"]
        initial = current if current != config.STANDARD_ACCENT else "#00B0FF"
        chosen = colorchooser.askcolor(color=initial, parent=self.root,
                                       title="Bar colour")[1]
        if chosen:
            self.set_accent(chosen.upper())

    def set_accent(self, value):
        self.settings["accent"] = value
        config.save(self.settings)
        self.apply_style()

    def set_bar_style(self, style):
        self.settings["bar_style"] = style
        self.dial.bar_style = style
        config.save(self.settings)
        self.apply_style()

    def set_number_size(self, size):
        self.settings["number_size"] = size
        config.save(self.settings)
        self.apply_style()

    def apply_style(self):
        for button in (self.accent_buttons + self.size_buttons + self.device_rows
                       + self.tab_buttons + self.pomodoro_buttons + [self.backlight_slider]):
            button.refresh()
        self.refresh_nav()
        self.refresh_dashboard()
        self.refresh_screensaver()
        self.render()
        if self.connected:
            self.bridge.send_style(self.settings["accent"], self.settings["number_size"],
                                   self.settings["bar_style"])

    def save_name(self, event=None):
        name = self.name_entry.get().strip() or config.DEFAULT_NAME
        if name != self.settings["name"]:
            self.settings["name"] = name
            config.save(self.settings)
            self.refresh_identity()

    def scan_devices(self):
        """Keeps the device list current while Settings is open, so plugging
        a knob in or out shows up without pressing anything."""
        if self.page != "settings":
            return
        try:
            devices = find_devices()
        except OSError as exc:
            devices = []
            self.status.set(f"Device search failed: {exc}")
        if devices != self.devices:
            self.devices = devices
            self.show_devices()
        if not self.scan_pending:
            self.scan_pending = True
            self.root.after(DEVICE_SCAN_MS, self.rescan_devices)

    def rescan_devices(self):
        self.scan_pending = False
        self.scan_devices()

    def show_devices(self):
        for child in self.device_list.winfo_children():
            child.destroy()
        k = self.kit
        self.device_rows = []
        for port, description in [("", "first Revo1 found")] + list(self.devices):
            button = ui.Button(self.device_list, PANEL_BG,
                               lambda hover, p=port, d=description: self.paint_device(p, d, hover),
                               lambda p=port: self.use_port(p))
            button.pack(anchor="w", pady=(k.px(6), 0))
            self.device_rows.append(button)
        if not self.devices:
            note = ui.Picture(self.device_list, PANEL_BG)
            image = k.canvas(CARD_WIDTH, 22, PANEL_BG)
            k.text(image, 0, 11, "No knob on USB. Once paired, Revo1 reaches it over "
                   "Bluetooth instead.", "regular", 9,
                   ui.MUTED_INK)
            note.show(image)
            note.pack(anchor="w", pady=(k.px(6), 0))
        self.fit_window()

    def center_window(self):
        """Places the window in the middle of the work area (the screen
        minus the taskbar) of the monitor under the mouse pointer."""
        root = self.root
        root.update_idletasks()
        width = max(root.winfo_width(), root.winfo_reqwidth())
        height = max(root.winfo_height(), root.winfo_reqheight())
        left, top = 0, 0
        right, bottom = root.winfo_screenwidth(), root.winfo_screenheight()
        frame_w = frame_h = 0
        try:
            from ctypes import wintypes

            class MonitorInfo(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                            ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

            user32 = ctypes.windll.user32
            user32.MonitorFromPoint.restype = wintypes.HANDLE
            user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
            point = wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(point))
            monitor = user32.MonitorFromPoint(point, 2)  # MONITOR_DEFAULTTONEAREST
            info = MonitorInfo(cbSize=ctypes.sizeof(MonitorInfo))
            if user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                work = info.rcWork
                left, top, right, bottom = work.left, work.top, work.right, work.bottom
            # geometry() sizes the client area; the borders and title bar
            # (SM_CYCAPTION, SM_CXSIZEFRAME, SM_CYSIZEFRAME, SM_CXPADDEDBORDER)
            # come on top of it.
            padded = user32.GetSystemMetrics(92)
            frame_w = 2 * (user32.GetSystemMetrics(32) + padded)
            frame_h = user32.GetSystemMetrics(4) + 2 * (user32.GetSystemMetrics(33) + padded)
        except (AttributeError, OSError):
            pass
        x = left + max(0, (right - left - width - frame_w) // 2)
        y = top + max(0, (bottom - top - height - frame_h) // 2)
        root.geometry(f"+{x}+{y}")

    def fit_window(self, page=None):
        """Grows the window when a page no longer fits, so every device
        and orientation button stays visible."""
        self.root.update_idletasks()
        page = page or self.settings_page
        needed = min(page.winfo_reqheight(),
                     self.root.winfo_screenheight() - self.kit.px(80))
        if needed > self.root.winfo_height():
            self.root.geometry(f"{self.root.winfo_width()}x{needed}")

    def use_port(self, port):
        if port == self.settings["port"]:
            return
        self.settings["port"] = port
        config.save(self.settings)
        self.connected = False
        self.bridge.use_port(port)
        self.status.set(f"Connecting to {port}..." if port else "Looking for the device...")

    # ----- tray -----------------------------------------------------------

    def toggle_tray(self):
        self.toggle_setting("minimize_to_tray")

    def toggle_setting(self, key):
        self.settings[key] = not self.settings[key]
        config.save(self.settings)
        for toggle in [self.tray_toggle] + self.invert_toggles:
            toggle.refresh()
        if key == "saver_enabled":
            self.push_saver()
        elif key == "swipe_screens" and self.connected:
            self.bridge.send_swipes(self.settings["swipe_screens"])
        elif key == "dim_idle":
            if self.connected:
                self.bridge.send_dim(self.settings["dim_idle"])
            self.refresh_screensaver()

    def on_unmap(self, event):
        if (event.widget is self.root and self.tray and self.settings["minimize_to_tray"]
                and not self.in_tray and self.root.state() == "iconic"):
            self.in_tray = True
            self.root.withdraw()
            self.tray.show()

    def minimize(self):
        """Starts out of the way, as when launched at sign-in."""
        if self.tray and self.settings["minimize_to_tray"]:
            self.in_tray = True
            self.root.withdraw()
            self.tray.show()
        else:
            self.root.iconify()

    def show_window(self):
        if self.tray:
            self.tray.hide()
        self.in_tray = False
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    # ----- about and updates ---------------------------------------------

    def check_release(self):
        if self.release_state == "checking":
            return
        self.release_state = "checking"
        self.refresh_about()

        def run():
            try:
                self.events.put(("release", ("ok", updater.latest_release())))
            except updater.UpdateError as exc:
                self.events.put(("release", ("error", str(exc))))

        threading.Thread(target=run, name="release-check", daemon=True).start()

    def refresh_about(self):
        if not hasattr(self, "about_info"):
            return
        self.about_info.show(self.paint_about_info())
        for child in self.about_actions.winfo_children():
            child.destroy()
        actions = [("Check again", self.check_release, False,
                    self.release_state != "checking" and not self.update_busy)]
        if self.connected or self.update_busy:
            actions.insert(0, ("Install from file\u2026", self.install_firmware_file, False,
                               not self.update_busy))
        if self.firmware_update_available() or self.update_busy:
            actions.insert(0, ("Update firmware", self.update_firmware, True,
                               not self.update_busy))
        if self.app_update_available():
            actions.insert(0, ("Update app", lambda: webbrowser.open(self.release["url"]),
                               True, True))
        # Wraps onto a second line when the buttons don't fit side by side.
        lines, used = [], CARD_WIDTH + 1
        for action in actions:
            width = self.pill_width(action[0])
            if used + 8 + width > CARD_WIDTH:
                lines.append([])
                used = -8
            lines[-1].append(action)
            used += 8 + width
        for number, line_actions in enumerate(lines):
            line = tk.Frame(self.about_actions, bg=PANEL_BG)
            line.pack(anchor="w", pady=(self.kit.px(8) if number else 0, 0))
            widths = self.button_widths([self.pill_width(action[0]) for action in line_actions])
            buttons = []
            for (label, command, primary, enabled), width in zip(line_actions, widths):
                button = ui.Button(
                    line, PANEL_BG,
                    lambda hover, label=label, primary=primary, enabled=enabled, width=width:
                        self.paint_pill(label, hover, primary, enabled, width),
                    (command if enabled else (lambda: None)))
                if not enabled:
                    button.config(cursor="arrow")
                buttons.append(button)
            self.pack_row(buttons)
        if self.page == "settings" and self.settings_tab == "about":
            self.fit_window()

    def update_firmware(self):
        if self.update_busy or not self.firmware_update_available() or self.uploading():
            return
        port = self.connected_port
        release = self.release
        current = self.device_version or "an older version"
        if not messagebox.askyesno(
                "Update firmware",
                f"Install firmware {release['version']} on the knob at {port} "
                f"(it has {current})?\n\nKeep the USB cable plugged in until it finishes. "
                "The screen restarts at the end.", parent=self.root):
            return
        self.start_firmware_update(port, release=release)

    def install_firmware_file(self):
        """Flashes a revo1-firmware-x.y.z.bin the user picked, e.g. a release
        downloaded by hand or a local build."""
        if self.update_busy or not self.connected or self.uploading():
            return
        port = self.connected_port
        path = filedialog.askopenfilename(
            parent=self.root, title="Choose the Revo1 firmware",
            filetypes=[("Revo1 firmware", "revo1-firmware-*.bin"),
                       ("Firmware images", "*.bin")])
        if not path:
            return
        try:
            version = updater.check_image(path)
        except updater.UpdateError as exc:
            messagebox.showerror("Install firmware", f"Can't install it: {exc}.",
                                 parent=self.root)
            return
        current = self.device_version or "an older version"
        name = f"firmware {version}" if version else "this firmware"
        if not messagebox.askyesno(
                "Install firmware",
                f"Install {name} on the knob at {port} (it has {current})?\n\n"
                "Keep the USB cable plugged in until it finishes. "
                "The screen restarts at the end.", parent=self.root):
            return
        self.start_firmware_update(port, image=Path(path), version=version)

    def uploading(self):
        """The serial link can't be handed to the flasher mid-upload."""
        if self.upload_state and self.upload_state[0] == "busy":
            messagebox.showinfo("Update firmware",
                                "Wait until the screensaver pictures have been sent to the knob.",
                                parent=self.root)
            return True
        return False

    def start_firmware_update(self, port, release=None, image=None, version=None):
        self.update_busy = True
        self.update_text = "Starting\u2026"
        self.update_progress = None
        self.refresh_about()
        threading.Thread(target=self.run_firmware_update, args=(port, release, image, version),
                         name="firmware-update", daemon=True).start()

    def run_firmware_update(self, port, release=None, image=None, version=None):
        def report(text, fraction=None):
            self.events.put(("update", (text, fraction)))

        paused = False
        try:
            if release:
                version = release["version"]
                image = updater.data_dir() / "firmware" / release["firmware_name"]
                if not image.exists():
                    report("Downloading the firmware\u2026", 0.0)
                    updater.download(release["firmware_url"], image,
                                     lambda f: report("Downloading the firmware\u2026", f))
                updater.check_image(image)
            report("Getting the flashing tool\u2026", None)
            command = updater.esptool_command(
                lambda f: report("Downloading the flashing tool (once)\u2026", f))
            report("Releasing the USB port\u2026", None)
            paused = True
            if not self.bridge.pause():
                raise updater.UpdateError("the USB port is still busy")
            report(f"Connecting to the knob on {port}\u2026", None)
            updater.flash(command, port, image,
                          lambda f: report(f"Writing the firmware\u2026 {round(f * 100)}%", f))
            installed = f"Firmware {version}" if version else "The firmware"
            self.events.put(("update_done", (True, f"{installed} installed. "
                                                   "The knob is restarting.")))
        except updater.UpdateError as exc:
            self.events.put(("update_done", (False, f"Update failed: {exc}")))
        finally:
            if paused:
                self.bridge.resume()

    def refresh_media(self):
        if (self.mode == "Media" or self.page == "dashboard") and not self.media_pending:
            self.media_pending = True
            self.actions.put(("__mediapoll__", 0))
        self.root.after(1000, self.refresh_media)

    def read_mute(self):
        """Mute state of both devices; False for one Windows can't reach."""
        state = {}
        for mode, read in (("Volume", controls.volume_muted),
                           ("Mic", controls.microphone_muted)):
            try:
                state[mode] = read()
            except (COMError, OSError, RuntimeError, ValueError):
                state[mode] = False
        return state

    def refresh_mute(self):
        """Picks up mute changes, from the button or from Windows itself."""
        state = self.read_mute()
        if state != self.muted:
            self.muted = state
            if self.connected:
                self.bridge.send_mute(state["Volume"], state["Mic"])
            self.refresh_dashboard_tile("Volume")
            self.refresh_dashboard_tile("Mic")
            if self.page == "control" and not self.menu and self.mode in MUTE_MODES:
                self.render()

    def toggle_mute(self):
        mode = self.mode if self.mode in MUTE_MODES else "Volume"
        try:
            if mode == "Mic":
                controls.set_microphone_muted(not self.muted["Mic"])
            else:
                controls.set_volume_muted(not self.muted["Volume"])
        except (COMError, OSError, RuntimeError, ValueError) as exc:
            self.status.set(f"{mode} mute failed: {exc}")
        self.refresh_mute()

    def refresh_external_volume(self):
        self.refresh_mute()
        if self.mode == "Volume":
            try:
                actual = controls.volume_level()
                if actual != self.value:
                    self.value = actual
                    self.render()
                    self.sync()
            except (COMError, OSError, RuntimeError, ValueError) as exc:
                self.status.set(f"Volume update failed: {exc}")
        self.root.after(1000, self.refresh_external_volume)

    def refresh_value(self, show=False):
        """Reads the current level and sends it to the knob; `show` also
        opens that screen there, otherwise an open menu stays open."""
        if self.mode == "Volume":
            self.value = controls.volume_level()
        elif self.mode == "Mic":
            self.value = controls.microphone_level()
        elif self.mode == "Brightness":
            self.value = controls.brightness_level()
        else:
            self.value = 50
        self.render()
        self.sync(show)

    def put_text(self, draw, x, y, text, pixels, fill, max_width=None, tracking=0):
        """Centres `text` on (x, y) exactly as an LVGL label would: the same
        Montserrat Medium file at the same pixel size (lv_font_montserrat_<n>),
        the same letter spacing, and "..." when it is too long. Pillow's
        greyscale anti-aliasing blends it into the dial without ClearType's
        coloured fringe."""
        font = self.kit.pixel_font("device", pixels)
        s = self.scale
        if tracking:
            gap = tracking * s
            widths = [font.getlength(ch) for ch in text]
            left = x * s - (sum(widths) + gap * (len(text) - 1)) / 2
            for ch, width in zip(text, widths):
                draw.text((left, y * s), ch, font=font, fill=fill, anchor="lm")
                left += width + gap
            return
        if max_width and font.getlength(text) > max_width * s:
            while text and font.getlength(text + "...") > max_width * s:
                text = text[:-1]
            text = text + "..."
        draw.text((x * s, y * s), text, font=font, fill=fill, anchor="mm")

    def draw_icon(self, pixels, name, x, y, colour, size=icons.ICON_SIZE):
        icons.draw(pixels, name, x, y, ui.rgb(colour),
                   self.scale, size)

    def place_side_bars(self):
        """The Pomodoro or Mute buttons beside the dial; none while the menu is open."""
        for bar, shown in ((self.pomodoro_bar, self.mode == "Pomodoro"),
                           (self.mute_bar, self.mode in MUTE_MODES)):
            if shown and not self.menu:
                if not bar.winfo_manager():
                    bar.pack(anchor="w", pady=(self.kit.px(SIDE_BAR_GAP), 0))
            elif bar.winfo_manager():
                bar.pack_forget()

    def set_heading(self, text, colour, lines=()):
        """The screen's name beside the dial, with a few lines on using it."""
        k = self.kit
        image = k.canvas(SIDE_WIDTH, 40 + 20 * len(lines), ui.MAIN_BG)
        k.text(image, 0, 18, text, "semibold", 18, colour, width=SIDE_WIDTH)
        for index, line in enumerate(lines):
            k.text(image, 0, 52 + 20 * index, line, "regular", 10, ui.SUBTLE_INK,
                   width=SIDE_WIDTH)
        self.label.show(image)

    def render(self):
        """Mirrors the device: same chrome, arc, type and layout."""
        accent = self.accent(self.mode)
        c = dial.CENTER
        games = self.mode == "Games" and not self.menu
        if games:
            self.dial_box.pack_forget()
            self.games_panel.pack(fill="x")
            self.refresh_games()
            return
        if self.games_panel.winfo_manager():
            self.games_panel.pack_forget()
        if not self.dial_box.winfo_manager():
            self.dial_box.pack(expand=True)
        self.place_side_bars()

        if self.menu:
            screens = self.settings["screens"]
            chosen = config.MODES[self.menu_cursor]
            slot = screens.index(chosen) if chosen in screens else 0
            accent = self.accent(chosen)
            pixels = np.array(self.dial.menu(accent, slot, len(screens)).convert("RGB"))
            for index, mode in enumerate(screens):
                radians = math.radians(90 - index * 360 / len(screens))
                ink = dial.label_ink(accent) if index == slot else dial.MENU_INK
                self.draw_icon(pixels, mode, c + dial.MENU_LABEL_R * math.cos(radians),
                               c - dial.MENU_LABEL_R * math.sin(radians), ink)
            self.set_heading("Menu", ui.INK, MENU_HELP)
            image = Image.fromarray(pixels)
            self.put_text(ImageDraw.Draw(image), c, c, config.title(chosen).upper(),
                          16, dial.label_ink(accent))
            self.show_dial(image)
            return

        self.set_heading(config.title(self.mode), dial.label_ink(accent), SCREEN_HELP.get(self.mode, ()))
        if self.mode == "Media":
            state = self.media_state or {}
            duration = state.get("duration", 0)
            position = state.get("position", 0)
            pixels = np.array(self.dial.level(accent, position / duration if duration else 0))
            self.draw_media_icons(pixels, accent, state.get("status") == 1)
            image = Image.fromarray(pixels)
            draw = ImageDraw.Draw(image)
            self.put_text(draw, c, c + dial.MEDIA_TITLE_Y,
                          state.get("title") or "NOTHING PLAYING",
                          16, dial.VALUE_INK, max_width=200)
            self.put_text(draw, c, c + dial.MEDIA_ARTIST_Y, state.get("artist", ""),
                          12, dial.ARTIST_INK, max_width=160)
            # Players without media controls report no length, only the time
            # Revo1 has counted, so that is shown on its own.
            clock = f"{position // 60}:{position % 60:02d}"
            if duration:
                clock += f" / {duration // 60}:{duration % 60:02d}"
            if duration or state.get("status"):
                self.put_text(draw, c, c + dial.MEDIA_TIME_Y, clock, 12, dial.TIME_INK)
        elif self.mode == "Pomodoro":
            timer = self.pomodoro
            remaining = timer.remaining()
            self.pomodoro_shown = remaining
            pixels = np.array(self.dial.level(accent, timer.fraction()))
            self.draw_icon(pixels, "Pomodoro", c, c + dial.MUTE_ICON_Y,
                           dial.FOOTER_INK, size=dial.MUTE_ICON_SIZE)
            image = Image.fromarray(pixels)
            draw = ImageDraw.Draw(image)
            self.put_text(draw, c, c, f"{remaining // 60}:{remaining % 60:02d}",
                          self.settings["number_size"], dial.VALUE_INK)
            self.put_text(draw, c, c + dial.MUTE_LABEL_Y,
                          pomodoro.PHASE_NAMES[timer.phase].upper(), 12, dial.TIME_INK)
            self.put_text(draw, c, c + dial.MEDIA_TITLE_Y,
                          "Tap to pause" if timer.running else "Tap to start",
                          16, dial.VALUE_INK)
        elif self.mode in LEVEL_MODES:
            pixels = np.array(self.dial.level(accent, self.value / 100))
            muted = self.muted.get(self.mode, False)
            if self.mode in MUTE_MODES:
                self.draw_icon(pixels, self.mode + "Muted" if muted else self.mode,
                               c, c + dial.MUTE_ICON_Y,
                               dial.MUTED_INK if muted else dial.FOOTER_INK,
                               size=dial.MUTE_ICON_SIZE)
            else:
                self.draw_icon(pixels, self.mode, c, c + dial.MUTE_ICON_Y,
                               dial.FOOTER_INK, size=dial.MUTE_ICON_SIZE)
            image = Image.fromarray(pixels)
            draw = ImageDraw.Draw(image)
            self.put_text(draw, c, c, str(self.value), self.settings["number_size"],
                          dial.MUTED_VALUE_INK if muted else dial.VALUE_INK)
            if muted:
                self.put_text(draw, c, c + dial.MUTE_LABEL_Y, "MUTED", 12, dial.MUTED_INK)
        else:
            image = self.dial.comet(accent, (self.comet_q8 >> 8) & dial.MASK,
                                    self.comet_direction)
            pixels = np.array(image.convert("RGB"))
            self.draw_icon(pixels, self.mode, c, c + dial.MODE_ICON_Y, dial.label_ink(accent),
                           size=dial.MODE_ICON_SIZE)
            image = Image.fromarray(pixels)
            self.put_text(ImageDraw.Draw(image), c, c + dial.MODE_LABEL_Y,
                          config.title(self.mode).upper(), 16, dial.label_ink(accent))
        pixels = np.array(image.convert("RGB"))
        self.draw_icon(pixels, "Back", c, c + dial.FOOTER_Y, dial.FOOTER_INK,
                       size=dial.BACK_ICON_SIZE)
        self.show_dial(Image.fromarray(pixels))
        if self.mode == "Pomodoro":
            for button in self.pomodoro_buttons:
                button.refresh()
        if self.mode in MUTE_MODES:
            self.mute_button.refresh()

    def show_dial(self, image):
        # Tk only keeps a weak reference, so the PhotoImage must be held here.
        self.dial_image = ImageTk.PhotoImage(image, master=self.canvas)
        if self.dial_item is None:
            self.dial_item = self.canvas.create_image(0, 0, image=self.dial_image, anchor="nw")
        else:
            self.canvas.itemconfigure(self.dial_item, image=self.dial_image)

    def draw_media_icons(self, pixels, accent, playing):
        c, gap = dial.CENTER, dial.MEDIA_BUTTON_SPACING
        bright = tuple(v * 170 // 256 for v in accent)
        # The middle icon is a button, so it shows the action a tap performs.
        self.draw_icon(pixels, "Prev", c - gap, c, dial.ICON_INK, size=dial.MEDIA_SKIP_SIZE)
        self.draw_icon(pixels, "Pause" if playing else "Play", c, c, bright,
                       size=dial.MEDIA_PLAY_SIZE)
        self.draw_icon(pixels, "Next", c + gap, c, dial.ICON_INK, size=dial.MEDIA_SKIP_SIZE)

    def canvas_click(self, event):
        c = dial.CENTER
        x, y = event.x / self.scale, event.y / self.scale
        dx, dy = x - c, c - y
        distance = math.hypot(dx, dy)
        # The transport buttons share the cap with the menu gesture, so they
        # are checked first and the rest of the cap still opens the menu.
        if not self.menu and self.mode == "Media" and abs(y - c) <= dial.MEDIA_HIT:
            offset = x - c
            if abs(offset) <= dial.MEDIA_HIT:
                self.actions.put(("__mediacmd__", "PLAYPAUSE"))
                return
            if abs(offset + dial.MEDIA_BUTTON_SPACING) <= dial.MEDIA_HIT:
                self.actions.put(("__mediacmd__", "PREV"))
                return
            if abs(offset - dial.MEDIA_BUTTON_SPACING) <= dial.MEDIA_HIT:
                self.actions.put(("__mediacmd__", "NEXT"))
                return
        on_footer = (abs(x - c) <= dial.FOOTER_HIT_W
                     and abs(y - c - dial.FOOTER_Y) <= dial.FOOTER_HIT_H)
        if self.menu:
            # An icon picks itself; anywhere else confirms the knob's choice.
            screens = self.settings["screens"]
            if 50 <= distance <= 170:
                step = 360 / len(screens)
                angle = (90 - math.degrees(math.atan2(dy, dx)) + step / 2) % 360
                self.choose(screens[min(int(angle // step), len(screens) - 1)])
            else:
                self.choose(config.MODES[self.menu_cursor])
        elif self.mode == "Pomodoro" and distance < dial.CAP_R and not on_footer:
            self.pomodoro_action("start")
        elif self.mode in MUTE_MODES and distance < dial.CAP_R and not on_footer:
            self.toggle_mute()
        elif distance < dial.CAP_R or on_footer:
            self.open_menu()
            if self.connected:
                self.bridge.send_menu()

    def open_menu(self):
        self.menu = True
        screens = self.settings["screens"]
        self.menu_cursor = config.MODES.index(self.mode if self.mode in screens else screens[0])
        self.render()

    def choose(self, mode):
        self.menu = False
        self.select_mode(mode)

    def sync(self, show=False):
        if self.connected:
            self.bridge.send_state(self.mode, self.value, self.settings["orientation"],
                                   keep=not show)
            if self.mode == "Media":
                self.push_media(force=True)

    def apply_media(self, snapshot):
        self.media_state = snapshot
        if self.page == "dashboard":
            self.refresh_dashboard_tile("Media")
        self.push_media()
        if self.mode == "Media" and not self.menu:
            self.render()

    def push_media(self, force=False):
        if not self.connected:
            return
        state = self.media_state or {"title": "", "artist": "", "status": 0,
                                     "position": 0, "duration": 0}
        track = (state["title"], state["artist"])
        if force or track != self.media_track:
            self.media_track = track
            self.bridge.send_track(track[0], track[1])
        self.bridge.send_playback(state["status"], state["position"],
                                  state["duration"])

    def select_mode(self, mode):
        self.mode = mode
        self.settings["mode"] = self.mode
        config.save(self.settings)
        self.refresh_nav()
        self.place_side_bars()
        self.reset_comet()
        try:
            self.refresh_value(show=True)
        except (COMError, OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            self.status.set(f"{self.mode}: {exc}")
            self.sync(show=True)

    def set_orientation(self, value):
        self.reset_comet()
        self.settings["orientation"] = int(value)
        config.save(self.settings)
        for button in self.orientation_buttons:
            button.refresh()
        self.sync()

    def reset_comet(self):
        """The device restarts its comet whenever the view changes; this is
        called at the same moments so the two stay on the same segment."""
        self.comet_q8 = dial.GAUGE_START << 8
        self.comet_target_q8 = self.comet_q8
        self.comet_direction = 1

    def rotate(self, steps):
        if self.mode == "Games":
            return
        if self.mode == "Pomodoro":
            # Before a phase starts the knob sets its length; once it has
            # started, a minute per click is added to or taken from what is left.
            timer = self.pomodoro
            if timer.untouched:
                self.set_pomodoro_minutes(timer.phase, timer.minutes[timer.phase] + steps)
            else:
                timer.adjust(steps * 60)
                self.after_pomodoro_change()
            return
        if self.mode in ("Scroll", "Zoom") and steps:
            # Segment indices run anticlockwise, so a clockwise turn decreases them.
            self.comet_target_q8 -= steps * dial.COMET_STEP_Q8
            self.comet_direction = -1 if steps > 0 else 1
            if not self.comet_animating:
                self.comet_animating = True
                self.animate_comet()
        # The comet always follows the hand; only what the turn does flips.
        if ((self.mode == "Scroll" and self.settings["invert_scroll"])
                or (self.mode == "Zoom" and self.settings["invert_zoom"])):
            steps = -steps
        self.actions.put((self.mode, steps))

    def advance_comet(self):
        """One 40 ms frame of the firmware's easing, in the same integer maths."""
        delta = self.comet_target_q8 - self.comet_q8
        if -dial.COMET_SNAP_Q8 < delta < dial.COMET_SNAP_Q8:
            self.comet_q8 += delta
        else:
            self.comet_q8 += int(delta / 4)
        return self.comet_q8 != self.comet_target_q8

    def animate_comet(self):
        moving = self.advance_comet()
        if not self.menu and self.mode in ("Scroll", "Zoom"):
            self.render()
        if moving:
            self.root.after(dial.FRAME_MS, self.animate_comet)
        else:
            self.comet_animating = False

    def run_actions(self):
        CoInitialize()
        try:
            while True:
                mode, steps = self.actions.get()
                if mode is None:
                    return
                if mode == "__mediapoll__":
                    self.events.put(("media", self.media.snapshot()))
                    continue
                if mode == "__levels__":
                    levels = {}
                    for name, read in (("Volume", controls.volume_level),
                                       ("Mic", controls.microphone_level),
                                       ("Brightness", controls.brightness_level)):
                        try:
                            levels[name] = read()
                        except (COMError, OSError, RuntimeError, ValueError,
                                subprocess.SubprocessError):
                            levels[name] = None
                    self.events.put(("levels", levels))
                    continue
                if mode == "__mediacmd__":
                    if steps == "PLAYPAUSE":
                        self.media.play_pause()
                    elif steps == "NEXT":
                        self.media.next_track()
                    elif steps == "PREV":
                        self.media.previous_track()
                    self.events.put(("media", self.media.snapshot()))
                    continue
                try:
                    if mode == "Volume":
                        value = controls.change_volume(steps)
                    elif mode == "Brightness":
                        value = controls.change_brightness(steps)
                    elif mode == "Mic":
                        value = controls.change_microphone(steps)
                    elif mode == "Scroll":
                        controls.scroll(-steps)
                        value = 50
                    elif mode == "Zoom":
                        controls.zoom(steps)
                        value = 50
                    else:
                        self.media.seek_clicks(steps)
                        self.events.put(("media", self.media.snapshot()))
                        value = 50
                    self.events.put(("value", (mode, value)))
                except (COMError, OSError, RuntimeError, ValueError,
                        subprocess.SubprocessError) as exc:
                    self.events.put(("status", f"{mode} action failed: {exc}"))
        finally:
            CoUninitialize()

    def push_device_state(self):
        """Sends the app's style and view to the knob, as on a fresh connection."""
        self.state_pushed = time.monotonic()
        # Start both comets from the same place, even if the device kept
        # running while the app was closed.
        self.reset_comet()
        self.bridge.send_comet_reset()
        self.bridge.send_style(self.settings["accent"], self.settings["number_size"],
                               self.settings["bar_style"])
        self.bridge.send_screens(config.screen_mask(self.settings["screens"]))
        self.bridge.send_backlight(self.settings["backlight"])
        self.bridge.send_swipes(self.settings["swipe_screens"])
        self.bridge.send_dim(self.settings["dim_idle"])
        self.push_time()
        self.push_saver()
        self.push_pomodoro()
        self.bridge.send_mute(self.muted["Volume"], self.muted["Mic"])
        self.bridge.send_game_best(self.settings["whack_best"])
        self.bridge.request_library()
        try:
            self.refresh_value()
        except (COMError, OSError, RuntimeError, ValueError,
                subprocess.SubprocessError) as exc:
            self.status.set(f"{self.mode}: {exc}")
            self.sync()
        # A fresh connection starts from the knob's main menu.
        self.open_menu()
        self.bridge.send_menu()

    def poll(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "status":
                    self.status.set(payload)
                    if payload.startswith("Serial connection error") or payload.startswith("Device not found"):
                        self.connected = False
                elif kind == "disconnected":
                    self.connected = False
                    self.link_kind = None
                    self.refresh_wireless()
                    self.device_version = None
                    self.device_library = None
                    if self.upload_state and self.upload_state[0] == "busy":
                        self.upload_state = ("error", "The knob was disconnected")
                    self.refresh_about()
                    self.refresh_screensaver()
                elif kind == "version":
                    if payload != self.device_version:
                        self.device_version = payload
                        self.refresh_about()
                elif kind == "release":
                    state, result = payload
                    self.release_state = state
                    self.release_checked = time.monotonic()
                    if state == "ok":
                        self.release = result
                    else:
                        self.release_error = result
                    self.refresh_about()
                elif kind == "update":
                    self.update_text, self.update_progress = payload
                    self.about_info.show(self.paint_about_info())
                elif kind == "update_done":
                    self.update_busy = False
                    self.update_text = payload[1]
                    self.update_progress = None
                    self.refresh_about()
                elif kind == "show":
                    self.show_window()
                elif kind == "quit":
                    if self.request_close():
                        return
                elif kind == "hello":
                    if not self.connected:
                        self.connected_port = payload
                        self.link_kind = link_kind(payload)
                        self.connected = True
                        self.status.set(f"Connected over {payload}" if self.link_kind != "usb"
                                        else f"Connected on {payload}")
                        self.refresh_wireless()
                        self.refresh_about()
                        self.push_device_state()
                elif (kind == "sync" and self.connected
                      and time.monotonic() - self.state_pushed > 2):
                    # The knob restarted and asks for its state again; the
                    # first reply may still be in flight, hence the grace time.
                    self.push_device_state()
                elif kind == "rotate":
                    if not self.menu:
                        self.rotate(payload)
                elif kind == "swipe":
                    direction = -1 if payload == "RIGHT" else 1
                    screens = self.settings["screens"]
                    index = screens.index(self.mode) if self.mode in screens else -direction
                    self.select_mode(screens[(index + direction) % len(screens)])
                elif kind == "menu":
                    self.open_menu()
                elif kind == "cursor" and self.menu and 0 <= payload < len(config.MODES):
                    self.menu_cursor = payload
                    self.render()
                elif kind == "pomodoro_toggle":
                    self.pomodoro_action("start")
                elif kind == "mute_toggle":
                    if self.mode in MUTE_MODES:
                        self.toggle_mute()
                elif kind == "game":
                    self.record_score(payload[0], payload[1])
                elif kind == "game_best":
                    self.record_score(None, payload)
                elif kind == "levels":
                    self.levels_pending = False
                    self.levels = payload
                    self.refresh_dashboard()
                elif kind == "library":
                    self.device_library = payload
                    self.refresh_screensaver()
                elif kind in ("net", "pair_done", "pair_error", "knob_seen"):
                    self.on_wireless_event(kind, payload)
                elif kind in ("upload", "upload_done", "upload_error", "saver_added",
                              "saver_progress", "saver_failed"):
                    self.on_screensaver_event(kind, payload)
                elif kind == "media":
                    self.media_pending = False
                    self.apply_media(payload)
                elif kind == "mediacmd":
                    self.actions.put(("__mediacmd__", payload))
                elif kind == "tap" and 0 <= payload < len(config.MODES):
                    self.choose(config.MODES[payload])
                elif kind == "value" and payload[0] == self.mode:
                    self.value = payload[1]
                    self.levels[self.mode] = payload[1]
                    self.render()
                    self.sync()
        except queue.Empty:
            pass
        # The knob's clock drifts and knows nothing of daylight saving.
        if self.connected and time.monotonic() - self.time_pushed > TIME_RESEND_S:
            self.push_time()
        self.root.after(80, self.poll)

    # ----- pomodoro -------------------------------------------------------

    def pomodoro_label(self, key):
        if key == "start":
            return "Pause" if self.pomodoro.running else "Start"
        return "Reset"

    def paint_stepper(self, key, hover, width):
        """\u2212 25 min +, for the focus or break length."""
        k = self.kit
        height = 30
        image = k.canvas(width, height, ui.MAIN_BG)
        phase = pomodoro.FOCUS if key == "focus" else pomodoro.BREAK
        current = self.pomodoro.phase == phase
        k.rounded(image, (0, 0, width, height), 15, "#FFFFFF" if hover else ui.CARD_BG,
                  dial.label_ink(self.accent("Pomodoro")) if current else ui.CARD_EDGE)
        k.text(image, 18, height / 2, "\u2212", "semibold", 12, ui.SUBTLE_INK, anchor="mm")
        k.text(image, width - 18, height / 2, "+", "semibold", 12, ui.SUBTLE_INK, anchor="mm")
        label = f"{pomodoro.PHASE_NAMES[phase]} \u00b7 {self.pomodoro.minutes[phase]} min"
        k.text(image, width / 2, height / 2, label, "semibold", 9.5, ui.INK, anchor="mm")
        return image

    def step_pomodoro(self, key, event):
        phase = pomodoro.FOCUS if key == "focus" else pomodoro.BREAK
        width = event.widget.winfo_width()
        if event.x < width / 3:
            change = -1
        elif event.x > width * 2 / 3:
            change = 1
        else:
            return
        self.set_pomodoro_minutes(phase, self.pomodoro.minutes[phase] + change)

    def set_pomodoro_minutes(self, phase, minutes):
        minutes = max(1, min(180, minutes))
        self.pomodoro.set_minutes(phase, minutes)
        key = "focus_minutes" if phase == pomodoro.FOCUS else "break_minutes"
        if self.settings[key] != minutes:
            self.settings[key] = minutes
            config.save(self.settings)
        self.after_pomodoro_change()

    def pomodoro_action(self, key):
        if key == "start":
            self.pomodoro.toggle()
        else:
            self.pomodoro.reset()
        self.after_pomodoro_change()

    def after_pomodoro_change(self):
        self.push_pomodoro()
        if self.mode == "Pomodoro" and not self.menu:
            self.render()
        self.refresh_dashboard()

    def push_pomodoro(self):
        if self.connected:
            timer = self.pomodoro
            remaining = timer.remaining()
            # Time added with the knob can outgrow the phase; the ring stays full.
            self.bridge.send_pomodoro(timer.phase, remaining, max(timer.total, remaining),
                                      timer.running)
            self.pomodoro_sent = time.monotonic()

    def tick_pomodoro(self):
        """Runs the timer: chimes at each change of phase and keeps the dial,
        the dashboard and the knob in step."""
        timer = self.pomodoro
        if timer.tick():
            pomodoro.play_chime(timer.phase, self.chime_folder)
            self.after_pomodoro_change()
        elif timer.running:
            if self.mode == "Pomodoro" and not self.menu and \
                    timer.remaining() != self.pomodoro_shown:
                self.render()
            if self.page == "dashboard":
                self.refresh_dashboard_tile("Pomodoro")
            # The knob counts down on its own; a periodic resync stops drift.
            if time.monotonic() - self.pomodoro_sent > 60:
                self.push_pomodoro()
        self.root.after(250, self.tick_pomodoro)

    # ----- backlight ------------------------------------------------------

    def paint_backlight(self, hover):
        k = self.kit
        width, height = FORM_WIDTH, 34
        image = k.canvas(width, height, PANEL_BG)
        value = self.settings["backlight"]
        track = width - 56
        k.icon(image, "Brightness", 10, height / 2, ui.SUBTLE_INK, 0.6)
        left, right = 30, 30 + track - 30
        filled = left + (right - left) * (value - 5) / 95
        k.rounded(image, (left, height / 2 - 3, right, height / 2 + 3), 3, ui.CARD_EDGE)
        k.rounded(image, (left, height / 2 - 3, max(filled, left + 6), height / 2 + 3), 3,
                  dial.label_ink(self.accent(self.mode)))
        k.dot(image, filled, height / 2, 10 if hover else 9, ui.CARD_EDGE)
        k.dot(image, filled, height / 2, 9 if hover else 8, "#FFFFFF")
        k.dot(image, filled, height / 2, 3, dial.label_ink(self.accent(self.mode)))
        k.text(image, width, height / 2, f"{value}%", "semibold", 10, ui.INK, anchor="rm")
        return image

    def drag_backlight(self, event):
        left = self.kit.px(30)
        right = self.kit.px(30 + FORM_WIDTH - 56 - 30)
        fraction = min(1.0, max(0.0, (event.x - left) / max(right - left, 1)))
        value = round(5 + fraction * 95)
        if value != self.settings["backlight"]:
            self.settings["backlight"] = value
            self.backlight_slider.refresh()
            # Live while dragging, but not faster than the knob can take it.
            if self.connected and time.monotonic() - self.backlight_sent > 0.08:
                self.bridge.send_backlight(value)
                self.backlight_sent = time.monotonic()

    def release_backlight(self, event):
        config.save(self.settings)
        if self.connected:
            self.bridge.send_backlight(self.settings["backlight"])

    def request_close(self):
        """Asks before closing, since the knob stops working without the app.
        Returns True once the app is closed."""
        if self.in_tray:
            self.show_window()
        if self.update_busy:
            title = "Firmware update in progress"
            message = ("Closing Revo1 now stops the firmware update, and the knob may "
                       "not start until it is installed again.\n\nClose anyway?")
        else:
            title = "Close Revo1"
            message = ("Closing Revo1 disconnects the knob: it stops controlling the "
                       "volume, media and the other screens until you open Revo1 "
                       "again.\n\nClose Revo1?")
            if self.tray and not self.settings["minimize_to_tray"]:
                message += ("\n\nTip: to keep it running out of the way, turn on "
                            "\u201cMinimise to the notification area\u201d in Settings.")
        if not messagebox.askyesno(title, message, icon="warning", default="no",
                                   parent=self.root):
            return False
        self.close()
        return True

    def close(self):
        self.actions.put((None, 0))
        if self.tray:
            self.tray.stop()
        self.bridge.stop()
        self.root.destroy()


def main():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateMutexW(None, False, "Local\\Revo1Companion")
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        # Already running (maybe hidden in the tray): bring that one forward.
        tray.activate_running_instance()
        kernel.CloseHandle(handle)
        return
    try:
        # Without this Windows bitmap-stretches the window on scaled displays
        # and the dial turns soft.
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ui.APP_ID)
    except (AttributeError, OSError):
        pass
    ui.register_fonts()
    root = tk.Tk()
    events = []
    icon = tray.TrayIcon("Revo1", ui.ICON_FILE,
                         lambda: events and events[0].put(("show", None)),
                         lambda: events and events[0].put(("quit", None)))
    icon.start()
    try:
        try:
            app = App(root, tray=icon, start_minimized="--minimized" in sys.argv[1:])
            events.append(app.events)
        except (OSError, ValueError, RuntimeError) as exc:
            icon.stop()
            messagebox.showerror("Revo1 startup failed", str(exc))
            root.destroy()
            return
        root.mainloop()
    finally:
        kernel.CloseHandle(handle)


if __name__ == "__main__":
    main()
