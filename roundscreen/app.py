import ctypes
import math
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import colorchooser, messagebox

from comtypes import COMError, CoInitialize, CoUninitialize
import numpy as np
from PIL import Image, ImageDraw, ImageTk

from roundscreen import config, dial, icons, ui, windows_controls as controls
from roundscreen.bridge import DeviceBridge, find_devices
from roundscreen.dial import DialRenderer
from roundscreen.media import MediaSession

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


class App:
    def __init__(self, root):
        self.root = root
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
        self.connected_port = None
        self.menu = False
        # The option the knob points at while the menu is open.
        self.menu_cursor = config.MODES.index(self.mode)
        self.media = MediaSession()
        self.media_state = None
        self.media_track = None
        self.media_pending = False

        root.title("RoundScreen")
        self.scale = root.winfo_fpixels("1i") / 96.0
        self.kit = ui.Kit(self.scale)
        size = f"{self.kit.px(SIDEBAR_WIDTH + MAIN_WIDTH)}x{self.kit.px(WINDOW_HEIGHT)}"
        root.geometry(size)
        root.minsize(self.kit.px(SIDEBAR_WIDTH + MAIN_WIDTH), self.kit.px(WINDOW_HEIGHT))
        root.configure(bg=ui.MAIN_BG)
        root.protocol("WM_DELETE_WINDOW", self.close)

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
        for key, label in (("device", "Device"), ("interface", "Interface")):
            button = ui.Button(tabs, ui.MAIN_BG,
                               lambda hover, key=key, label=label: self.paint_tab(key, label, hover),
                               lambda key=key: self.show_tab(key))
            button.pack(side="left", padx=(0, k.px(6)))
            self.tab_buttons.append(button)

        self.tabs = {"device": tk.Frame(page, bg=ui.MAIN_BG),
                     "interface": tk.Frame(page, bg=ui.MAIN_BG)}
        self.build_device_tab(self.tabs["device"])
        self.build_interface_tab(self.tabs["interface"])
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

        card = ui.Card(tab, k, CARD_WIDTH, ui.MAIN_BG)
        card.pack(padx=k.px(28), pady=(k.px(12), k.px(20)), anchor="w")
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
        k = self.kit
        width, height = 100, 32
        image = k.canvas(width, height, ui.MAIN_BG)
        if key == self.settings_tab:
            k.rounded(image, (0, 0, width, height), 9, ui.INK)
            ink = "#FFFFFF"
        else:
            k.rounded(image, (0, 0, width, height), 9, ui.CARD_BG if hover else ui.MAIN_BG,
                      ui.CARD_EDGE)
            ink = ui.SUBTLE_INK
        k.text(image, width / 2, height / 2, label, "semibold", 10, ink, anchor="mm")
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
        for button in self.accent_buttons + self.size_buttons + self.device_rows:
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
        for port, description in [("", "first RoundScreen found")] + list(self.devices):
            button = ui.Button(self.device_list, ui.CARD_BG,
                               lambda hover, p=port, d=description: self.paint_device(p, d, hover),
                               lambda p=port: self.use_port(p))
            button.pack(anchor="w", pady=(k.px(6), 0))
            self.device_rows.append(button)
        if not self.devices:
            note = ui.Picture(self.device_list, ui.CARD_BG)
            image = k.canvas(CARD_WIDTH - 36, 22, ui.CARD_BG)
            k.text(image, 0, 11, "No RoundScreen found. Check the USB cable.", "regular", 9,
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
                elif kind == "hello":
                    if not self.connected:
                        self.connected_port = payload
                        self.connected = True
                        # Start both comets from the same place, even if the
                        # device kept running while the app was closed.
                        self.reset_comet()
                        self.bridge.send_comet_reset()
                        self.status.set(f"Connected on {payload}")
                        self.bridge.send_style(self.settings["accent"],
                                               self.settings["number_size"])
                        try:
                            self.refresh_value()
                        except (COMError, OSError, RuntimeError, ValueError,
                                subprocess.SubprocessError) as exc:
                            self.status.set(f"{self.mode}: {exc}")
                            self.sync()
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
        self.bridge.stop()
        self.root.destroy()


def main():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.CreateMutexW(None, False, "Local\\RoundScreenCompanion")
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        user = ctypes.WinDLL("user32", use_last_error=True)
        user.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        user.FindWindowW.restype = ctypes.c_void_p
        window = user.FindWindowW(None, "RoundScreen")
        if window:
            user.ShowWindow(ctypes.c_void_p(window), 9)
            user.SetForegroundWindow(ctypes.c_void_p(window))
        kernel.CloseHandle(handle)
        return
    try:
        # Without this Windows bitmap-stretches the window on scaled displays
        # and the dial turns soft.
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    ui.register_fonts()
    root = tk.Tk()
    try:
        try:
            App(root)
        except (OSError, ValueError, RuntimeError) as exc:
            messagebox.showerror("RoundScreen startup failed", str(exc))
            root.destroy()
            return
        root.mainloop()
    finally:
        kernel.CloseHandle(handle)


if __name__ == "__main__":
    main()
