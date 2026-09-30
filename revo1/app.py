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

from revo1 import __version__, config, dial, icons, tray, ui, updater
from revo1 import windows_controls as controls
from revo1.bridge import DeviceBridge, find_devices
from revo1.dial import DialRenderer
from revo1.media import MediaSession

LEVEL_MODES = ("Volume", "Mic", "Brightness")
# Window layout, in 96-dpi pixels.
SIDEBAR_WIDTH = 212
MAIN_WIDTH = 440
WINDOW_HEIGHT = 560
NAV_WIDTH = 188
NAV_HEIGHT = 44
CARD_WIDTH = MAIN_WIDTH - 56
DEVICE_ROW_HEIGHT = 36
DEVICE_SCAN_MS = 2000
NUMBER_LABELS = {24: "Small", 32: "Medium", 40: "Large", 48: "X-Large"}
SETTINGS_TABS = (("device", "Device"), ("controls", "Controls"), ("interface", "Interface"),
                 ("about", "About"))
# How long a release check stays fresh before the About tab asks GitHub again.
RELEASE_CHECK_S = 30 * 60


class App:
    def __init__(self, root, tray=None, start_minimized=False):
        self.root = root
        self.tray = tray
        self.settings = config.load()
        for key, value in config.DEFAULTS.items():
            self.settings.setdefault(key, value)
        self.mode = self.settings["mode"]
        self.value = 50
        self.events = queue.Queue()
        self.bridge = DeviceBridge(self.events, self.settings["port"])
        self.actions = queue.Queue()
        self.worker = threading.Thread(target=self.run_actions, daemon=True)
        self._connected = False
        self.state_pushed = 0.0
        self.connected_port = None
        self.menu = False
        # The option the knob points at while the menu is open.
        self.menu_cursor = config.MODES.index(self.mode)
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
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.bind("<Unmap>", self.on_unmap)

        self.dial = DialRenderer(background=ui.rgb(ui.MAIN_BG), scale=self.scale)
        self.dial_image = None
        self.dial_item = None
        self.comet_animating = False
        self.reset_comet()
        self.page = "control"
        self.settings_tab = "device"
        self.devices = None
        self.device_rows = []
        self.scan_pending = False

        self.status = tk.StringVar(value="Looking for the device...")
        self.build_sidebar()
        self.build_control_page()
        self.build_settings_page()
        self.status.trace_add("write", lambda *args: self.refresh_status())
        self.show_page("control")

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
        for key in config.MODES + ("Settings",):
            button = ui.Button(bar, ui.SIDEBAR_BG,
                               lambda hover, key=key: self.paint_nav(key, hover),
                               lambda key=key: self.navigate(key))
            if key == "Settings":
                button.pack(side="bottom", padx=k.px(12), pady=(0, k.px(18)), anchor="w")
            else:
                button.pack(padx=k.px(12), pady=k.px(2), anchor="w")
            self.nav[key] = button
        self.refresh_identity()

    def build_control_page(self):
        k = self.kit
        page = tk.Frame(self.root, bg=ui.MAIN_BG)
        self.canvas = tk.Canvas(page, width=self.dial.size, height=self.dial.size,
                                bg=ui.MAIN_BG, highlightthickness=0)
        self.canvas.bind("<Button-1>", self.canvas_click)
        self.canvas.pack(pady=(k.px(36), k.px(16)))
        self.label = ui.Picture(page, ui.MAIN_BG)
        self.label.pack()
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
        self.build_about_tab(self.tabs["about"])
        self.settings_page = page
        self.show_tab(self.settings_tab)
        self.refresh_status()

    def build_device_tab(self, tab):
        k = self.kit
        card = ui.Card(tab, k, CARD_WIDTH, ui.MAIN_BG)
        card.pack(padx=k.px(28), anchor="w")
        body = card.body
        self.caption(body, "DEVICE NAME").pack(anchor="w")
        self.name_entry = tk.Entry(body, font=(ui.TK_FAMILY, 11), bg="#FFFFFF", fg=ui.INK,
                                   relief="flat", highlightthickness=1,
                                   highlightbackground=ui.CARD_EDGE,
                                   highlightcolor=ui.SUBTLE_INK, insertbackground=ui.INK)
        self.name_entry.insert(0, self.settings["name"])
        self.name_entry.bind("<Return>", self.save_name)
        self.name_entry.bind("<FocusOut>", self.save_name)
        self.name_entry.pack(fill="x", pady=(k.px(6), k.px(12)), ipady=k.px(4), ipadx=k.px(6))
        self.caption(body, "DEVICES").pack(anchor="w")
        self.connection_text = ui.Picture(body, ui.CARD_BG)
        self.connection_text.pack(anchor="w", pady=(k.px(2), 0))
        self.device_list = tk.Frame(body, bg=ui.CARD_BG)
        self.device_list.pack(fill="x")

    def build_controls_tab(self, tab):
        k = self.kit
        card = ui.Card(tab, k, CARD_WIDTH, ui.MAIN_BG)
        card.pack(padx=k.px(28), anchor="w")
        body = card.body
        self.caption(body, "SCREEN ORIENTATION").pack(anchor="w")
        row = tk.Frame(body, bg=ui.CARD_BG)
        row.pack(anchor="w", pady=(k.px(6), 0))
        self.orientation_buttons = []
        for value in config.ORIENTATIONS:
            button = ui.Button(row, ui.CARD_BG,
                               lambda hover, value=value: self.paint_orientation(value, hover),
                               lambda value=value: self.set_orientation(value))
            button.pack(side="left", padx=(0, k.px(8)))
            self.orientation_buttons.append(button)

        card = ui.Card(tab, k, CARD_WIDTH, ui.MAIN_BG)
        card.pack(padx=k.px(28), pady=(k.px(12), k.px(20)), anchor="w")
        body = card.body
        self.caption(body, "KNOB DIRECTION").pack(anchor="w")
        self.invert_toggles = []
        for key, title, detail in (
                ("invert_scroll", "Invert scroll",
                 "Turning clockwise scrolls up instead of down"),
                ("invert_zoom", "Invert zoom",
                 "Turning clockwise zooms out instead of in")):
            toggle = ui.Button(body, ui.CARD_BG,
                               lambda hover, key=key, title=title, detail=detail:
                                   self.paint_toggle(self.settings[key], title, detail, hover),
                               lambda key=key: self.toggle_setting(key))
            toggle.pack(anchor="w", pady=(k.px(6), 0))
            self.invert_toggles.append(toggle)

    def build_interface_tab(self, tab):
        k = self.kit
        card = ui.Card(tab, k, CARD_WIDTH, ui.MAIN_BG)
        card.pack(padx=k.px(28), anchor="w")
        body = card.body
        self.caption(body, "BAR COLOUR").pack(anchor="w")
        self.accent_buttons = []
        row = tk.Frame(body, bg=ui.CARD_BG)
        row.pack(anchor="w", pady=(k.px(6), 0))
        for key in ("standard", "custom"):
            button = ui.Button(row, ui.CARD_BG,
                               lambda hover, key=key: self.paint_accent_choice(key, hover),
                               lambda key=key: self.pick_accent_choice(key))
            button.pack(side="left", padx=(0, k.px(8)))
            self.accent_buttons.append(button)
        row = tk.Frame(body, bg=ui.CARD_BG)
        row.pack(anchor="w", pady=(k.px(10), 0))
        for colour in dial.PRESET_ACCENTS:
            button = ui.Button(row, ui.CARD_BG,
                               lambda hover, colour=colour: self.paint_swatch(colour, hover),
                               lambda colour=colour: self.set_accent(colour))
            button.pack(side="left", padx=(0, k.px(6)))
            self.accent_buttons.append(button)

        card = ui.Card(tab, k, CARD_WIDTH, ui.MAIN_BG)
        card.pack(padx=k.px(28), pady=(k.px(12), k.px(20)), anchor="w")
        body = card.body
        self.caption(body, "NUMBER SIZE").pack(anchor="w")
        row = tk.Frame(body, bg=ui.CARD_BG)
        row.pack(anchor="w", pady=(k.px(6), 0))
        self.size_buttons = []
        for size in config.NUMBER_SIZES:
            button = ui.Button(row, ui.CARD_BG,
                               lambda hover, size=size: self.paint_number_size(size, hover),
                               lambda size=size: self.set_number_size(size))
            button.pack(side="left", padx=(0, k.px(8)))
            self.size_buttons.append(button)

        card = ui.Card(tab, k, CARD_WIDTH, ui.MAIN_BG)
        card.pack(padx=k.px(28), pady=(0, k.px(20)), anchor="w")
        body = card.body
        self.caption(body, "WINDOW").pack(anchor="w")
        self.tray_toggle = ui.Button(body, ui.CARD_BG, self.paint_tray_toggle,
                                     self.toggle_tray)
        self.tray_toggle.pack(anchor="w", pady=(k.px(6), 0))

    def build_about_tab(self, tab):
        k = self.kit
        card = ui.Card(tab, k, CARD_WIDTH, ui.MAIN_BG)
        card.pack(padx=k.px(28), anchor="w")
        body = card.body
        header = ui.Picture(body, ui.CARD_BG)
        header.show(self.paint_about_header())
        header.pack(anchor="w")
        row = tk.Frame(body, bg=ui.CARD_BG)
        row.pack(anchor="w", pady=(k.px(12), 0))
        for label, url in (("GitHub", updater.PROJECT_URL),
                           ("Releases", updater.RELEASES_URL),
                           ("Licence", updater.PROJECT_URL + "/blob/main/LICENSE")):
            ui.Button(row, ui.CARD_BG,
                      lambda hover, label=label: self.paint_pill(label, hover),
                      lambda url=url: webbrowser.open(url)).pack(side="left",
                                                                 padx=(0, k.px(8)))

        card = ui.Card(tab, k, CARD_WIDTH, ui.MAIN_BG)
        card.pack(padx=k.px(28), pady=(k.px(12), k.px(20)), anchor="w")
        body = card.body
        self.caption(body, "UPDATES").pack(anchor="w")
        self.about_info = ui.Picture(body, ui.CARD_BG)
        self.about_info.pack(anchor="w", pady=(k.px(4), 0))
        self.about_actions = tk.Frame(body, bg=ui.CARD_BG)
        self.about_actions.pack(anchor="w", pady=(k.px(10), 0))
        self.refresh_about()

    def caption(self, parent, text):
        picture = ui.Picture(parent, ui.CARD_BG)
        image = self.kit.canvas(CARD_WIDTH - 36, 16, ui.CARD_BG)
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
        else:
            selected = self.page == "control" and key == self.mode
        accent = self.accent(key) if key in config.MODES else None
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
        k.text(image, 56, NAV_HEIGHT / 2, key, "semibold" if selected else "regular", 10.5,
               ui.INK if selected else ui.SUBTLE_INK)
        return image

    def paint_device(self, port, description, hover):
        k = self.kit
        width, height = CARD_WIDTH - 36, DEVICE_ROW_HEIGHT
        image = k.canvas(width, height, ui.CARD_BG)
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

    def paint_orientation(self, value, hover):
        k = self.kit
        width, height = 64, 32
        image = k.canvas(width, height, ui.CARD_BG)
        if value == self.settings["orientation"]:
            k.rounded(image, (0, 0, width, height), 9, ui.INK)
            ink = "#FFFFFF"
        else:
            k.rounded(image, (0, 0, width, height), 9, "#FFFFFF" if hover else ui.CARD_BG,
                      ui.CARD_EDGE)
            ink = ui.SUBTLE_INK
        k.text(image, width / 2, height / 2, f"{value}°", "semibold", 10, ink, anchor="mm")
        return image

    def paint_tab(self, key, label, hover):
        """Underline tabs: plain labels on one hairline, the open one marked by
        a bar in the current accent."""
        k = self.kit
        # The row spans the card width, however many tabs there are.
        width, height = CARD_WIDTH // len(SETTINGS_TABS), 34
        image = k.canvas(width, height, ui.MAIN_BG)
        active = key == self.settings_tab
        k.rounded(image, (0, height - 1, width, height), 0.1, ui.CARD_EDGE)
        if active:
            k.rounded(image, (8, height - 3, width - 8, height), 1.5, self.accent(self.mode))
        elif hover:
            k.rounded(image, (8, height - 2, width - 8, height), 1, ui.MUTED_INK)
        ink = ui.INK if active else (ui.SUBTLE_INK if hover else ui.MUTED_INK)
        k.text(image, width / 2, (height - 3) / 2, label, "semibold" if active else "device",
               10, ink, anchor="mm")
        return image

    def paint_accent_choice(self, key, hover):
        """"Standard" keeps a colour per control; "Custom" opens a colour picker."""
        k = self.kit
        width, height = 140, 36
        image = k.canvas(width, height, ui.CARD_BG)
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
                angle = math.radians(90 - index * 60)
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
        image = k.canvas(size, size, ui.CARD_BG)
        c = size / 2
        if self.settings["accent"] == colour:
            k.dot(image, c, c, 16, ui.INK)
            k.dot(image, c, c, 14, ui.CARD_BG)
        elif hover:
            k.dot(image, c, c, 16, ui.CARD_EDGE)
            k.dot(image, c, c, 14.5, ui.CARD_BG)
        k.dot(image, c, c, 11.5, colour)
        return image

    def paint_number_size(self, size, hover):
        k = self.kit
        width, height = 76, 56
        image = k.canvas(width, height, ui.CARD_BG)
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
        width, height = CARD_WIDTH - 36, 40
        image = k.canvas(width, height, ui.CARD_BG)
        k.text(image, 0, 12, title, "semibold", 10, ui.INK)
        k.text(image, 0, 30, detail, "regular", 8.5, ui.MUTED_INK, width=width - 60)
        x0, y0 = width - 44, height / 2 - 12
        track = ui.INK if on else (ui.SUBTLE_INK if hover else ui.IDLE_GREY)
        k.rounded(image, (x0, y0, x0 + 44, y0 + 24), 12, track)
        k.dot(image, x0 + (32 if on else 12), height / 2, 9, "#FFFFFF")
        return image

    def paint_pill(self, label, hover, primary=False, enabled=True):
        k = self.kit
        font = k.font("semibold", 9.5)
        width, height = round(font.getlength(label) / k.scale) + 28, 30
        image = k.canvas(width, height, ui.CARD_BG)
        if primary and enabled:
            fill = dial.label_ink(self.accent(self.mode)) if hover else ui.INK
            k.rounded(image, (0, 0, width, height), 15, fill)
            ink = "#FFFFFF"
        else:
            k.rounded(image, (0, 0, width, height), 15,
                      "#FFFFFF" if hover and enabled else ui.CARD_BG, ui.CARD_EDGE)
            ink = ui.INK if enabled else ui.MUTED_INK
        k.text(image, width / 2, height / 2, label, "semibold", 9.5, ink, anchor="mm")
        return image

    def paint_about_header(self):
        k = self.kit
        width, height = CARD_WIDTH - 36, 64
        image = k.canvas(width, height, ui.CARD_BG)
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
        width = CARD_WIDTH - 36
        rows = self.about_rows()
        extra = 28 if self.update_text else 0
        image = k.canvas(width, len(rows) * 24 + extra, ui.CARD_BG)
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
        k.text(image, 12, 15, self.settings["name"], "semibold", 14, ui.INK, width=NAV_WIDTH - 20)
        k.dot(image, 16, 38, 3.5, ui.OK_GREEN if self.connected else ui.IDLE_GREY)
        k.text(image, 26, 38, "Connected" if self.connected else "Not connected",
               "regular", 9, ui.SUBTLE_INK)
        self.identity.show(image)

    def refresh_status(self):
        image = self.kit.canvas(CARD_WIDTH - 36, 20, ui.CARD_BG)
        self.kit.text(image, 0, 10, self.status.get(), "regular", 10, ui.SUBTLE_INK,
                      width=CARD_WIDTH - 36)
        self.connection_text.show(image)
        for button in self.device_rows:
            button.refresh()

    def refresh_nav(self):
        for button in self.nav.values():
            button.refresh()

    # ----- settings actions ---------------------------------------------

    def show_page(self, page):
        self.page = page
        self.control_page.pack_forget()
        self.settings_page.pack_forget()
        (self.settings_page if page == "settings" else self.control_page).pack(
            side="left", fill="both", expand=True)
        self.refresh_nav()

    def navigate(self, key):
        if key == "Settings":
            self.show_page("settings")
            self.scan_devices()
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

    def set_number_size(self, size):
        self.settings["number_size"] = size
        config.save(self.settings)
        self.apply_style()

    def apply_style(self):
        for button in (self.accent_buttons + self.size_buttons + self.device_rows
                       + self.tab_buttons):
            button.refresh()
        self.refresh_nav()
        self.render()
        if self.connected:
            self.bridge.send_style(self.settings["accent"], self.settings["number_size"])

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
            button = ui.Button(self.device_list, ui.CARD_BG,
                               lambda hover, p=port, d=description: self.paint_device(p, d, hover),
                               lambda p=port: self.use_port(p))
            button.pack(anchor="w", pady=(k.px(6), 0))
            self.device_rows.append(button)
        if not self.devices:
            note = ui.Picture(self.device_list, ui.CARD_BG)
            image = k.canvas(CARD_WIDTH - 36, 22, ui.CARD_BG)
            k.text(image, 0, 11, "No Revo1 found. Check the USB cable.", "regular", 9,
                   ui.MUTED_INK)
            note.show(image)
            note.pack(anchor="w", pady=(k.px(6), 0))
        self.fit_window()

    def fit_window(self):
        """Grows the window when the settings no longer fit, so every device
        and orientation button stays visible."""
        self.root.update_idletasks()
        needed = min(self.settings_page.winfo_reqheight(),
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

    def on_unmap(self, event):
        if (event.widget is self.root and self.tray and self.settings["minimize_to_tray"]
                and self.root.state() == "iconic"):
            self.root.withdraw()
            self.tray.show()

    def minimize(self):
        """Starts out of the way, as when launched at sign-in."""
        if self.tray and self.settings["minimize_to_tray"]:
            self.root.withdraw()
            self.tray.show()
        else:
            self.root.iconify()

    def show_window(self):
        if self.tray:
            self.tray.hide()
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
        room = self.kit.px(CARD_WIDTH - 36)
        line, used = None, room
        for label, command, primary, enabled in actions:
            width = self.paint_pill(label, False).width + self.kit.px(8)
            if used + width > room + self.kit.px(8):
                line = tk.Frame(self.about_actions, bg=ui.CARD_BG)
                line.pack(anchor="w", pady=(0 if used == room else self.kit.px(8), 0))
                used = 0
            used += width
            button = ui.Button(
                line, ui.CARD_BG,
                lambda hover, label=label, primary=primary, enabled=enabled:
                    self.paint_pill(label, hover, primary, enabled),
                (command if enabled else (lambda: None)))
            if not enabled:
                button.config(cursor="arrow")
            button.pack(side="left", padx=(0, self.kit.px(8)))
        if self.page == "settings" and self.settings_tab == "about":
            self.fit_window()

    def update_firmware(self):
        if self.update_busy or not self.firmware_update_available():
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
        if self.update_busy or not self.connected:
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
        if self.mode == "Media" and not self.media_pending:
            self.media_pending = True
            self.actions.put(("__mediapoll__", 0))
        self.root.after(1000, self.refresh_media)

    def refresh_external_volume(self):
        if self.mode == "Volume":
            try:
                actual = controls.volume_level()
                if actual != self.value:
                    self.value = actual
                    self.render()
                    if not self.menu:
                        self.sync()
            except (COMError, OSError, RuntimeError, ValueError) as exc:
                self.status.set(f"Volume update failed: {exc}")
        self.root.after(1000, self.refresh_external_volume)

    def refresh_value(self):
        if self.mode == "Volume":
            self.value = controls.volume_level()
        elif self.mode == "Mic":
            self.value = controls.microphone_level()
        elif self.mode == "Brightness":
            self.value = controls.brightness_level()
        else:
            self.value = 50
        self.render()
        self.sync()

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

    def set_heading(self, text, colour):
        """The heading under the dial, rendered like the dial text."""
        image = self.kit.canvas(MAIN_WIDTH - 40, 30, ui.MAIN_BG)
        self.kit.text(image, (MAIN_WIDTH - 40) / 2, 15, text, "semibold", 15, colour,
                      anchor="mm")
        self.label.show(image)

    def render(self):
        """Mirrors the device: same chrome, arc, type and layout."""
        accent = self.accent(self.mode)
        c = dial.CENTER

        if self.menu:
            selected = self.menu_cursor
            accent = self.accent(config.MODES[selected])
            pixels = np.array(self.dial.menu(accent, selected).convert("RGB"))
            for index, mode in enumerate(config.MODES):
                radians = math.radians(90 - index * 60)
                ink = dial.label_ink(accent) if index == selected else dial.MENU_INK
                self.draw_icon(pixels, mode, c + dial.MENU_LABEL_R * math.cos(radians),
                               c - dial.MENU_LABEL_R * math.sin(radians), ink)
            self.set_heading("Turn to choose, tap to confirm", ui.MUTED_INK)
            image = Image.fromarray(pixels)
            self.put_text(ImageDraw.Draw(image), c, c, config.MODES[selected].upper(),
                          16, dial.label_ink(accent))
            self.show_dial(image)
            return

        self.set_heading(self.mode, dial.label_ink(accent))
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
            if duration:
                clock = (f"{position // 60}:{position % 60:02d} / "
                         f"{duration // 60}:{duration % 60:02d}")
                self.put_text(draw, c, c + dial.MEDIA_TIME_Y, clock, 12, dial.TIME_INK)
        elif self.mode in LEVEL_MODES:
            pixels = np.array(self.dial.level(accent, self.value / 100))
            for side, name in ((-1, "ChevronLeft"), (1, "ChevronRight")):
                self.draw_icon(pixels, name, c + side * dial.CHEVRON_X, c,
                               dial.CHEVRON_INK, size=1.0)
            image = Image.fromarray(pixels)
            draw = ImageDraw.Draw(image)
            self.put_text(draw, c, c, str(self.value), self.settings["number_size"],
                          dial.VALUE_INK)
        else:
            image = self.dial.comet(accent, (self.comet_q8 >> 8) & dial.MASK,
                                    self.comet_direction)
            draw = ImageDraw.Draw(image)
            self.put_text(draw, c, c, self.mode.upper(), 16, dial.VALUE_INK)
        self.put_text(draw, c, c + dial.FOOTER_Y, self.mode.upper(), 12, dial.FOOTER_INK,
                      tracking=3)
        self.show_dial(image)

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
        if self.menu:
            # An icon picks itself; anywhere else confirms the knob's choice.
            if 50 <= distance <= 170:
                angle = (90 - math.degrees(math.atan2(dy, dx)) + 30) % 360
                self.choose(config.MODES[int(angle // 60)])
            else:
                self.choose(config.MODES[self.menu_cursor])
        elif distance < dial.CAP_R or (abs(x - c) <= dial.FOOTER_HIT_W and
                                       abs(y - c - dial.FOOTER_Y) <= dial.FOOTER_HIT_H):
            self.open_menu()
            if self.connected:
                self.bridge.send_menu()

    def open_menu(self):
        self.menu = True
        self.menu_cursor = config.MODES.index(self.mode)
        self.render()

    def choose(self, mode):
        self.menu = False
        self.select_mode(mode)

    def sync(self):
        if self.connected:
            self.bridge.send_state(self.mode, self.value, self.settings["orientation"])
            if self.mode == "Media":
                self.push_media(force=True)

    def apply_media(self, snapshot):
        self.media_state = snapshot
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
        self.reset_comet()
        try:
            self.refresh_value()
        except (COMError, OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            self.status.set(f"{self.mode}: {exc}")

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
                        self.media.seek(steps * 5)
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
        self.bridge.send_style(self.settings["accent"], self.settings["number_size"])
        try:
            self.refresh_value()
        except (COMError, OSError, RuntimeError, ValueError,
                subprocess.SubprocessError) as exc:
            self.status.set(f"{self.mode}: {exc}")
            self.sync()

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
                    self.device_version = None
                    self.refresh_about()
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
                    self.close()
                    return
                elif kind == "hello":
                    if not self.connected:
                        self.connected_port = payload
                        self.connected = True
                        self.status.set(f"Connected on {payload}")
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
                    index = (config.MODES.index(self.mode) + direction) % len(config.MODES)
                    self.select_mode(config.MODES[index])
                elif kind == "menu":
                    self.open_menu()
                elif kind == "cursor" and self.menu and 0 <= payload < len(config.MODES):
                    self.menu_cursor = payload
                    self.render()
                elif kind == "media":
                    self.media_pending = False
                    self.apply_media(payload)
                elif kind == "mediacmd":
                    self.actions.put(("__mediacmd__", payload))
                elif kind == "tap" and 0 <= payload < len(config.MODES):
                    self.choose(config.MODES[payload])
                elif kind == "value" and payload[0] == self.mode:
                    self.value = payload[1]
                    self.render()
                    self.sync()
        except queue.Empty:
            pass
        self.root.after(80, self.poll)

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
