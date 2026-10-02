"""The Screensaver page: when to start, how long each picture stays, and the
pictures and clips kept on the knob."""

import calendar
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from PIL import Image, ImageDraw, ImageTk

from revo1 import config, dial, screensaver, ui
from revo1.layout import CARD_WIDTH, PANEL_BG
from revo1.screensaver import DEFAULT_CAPACITY, FILE_TYPES, MediaError

THUMB = 48
THUMB_COLUMNS = 13
THUMB_ROWS_SHOWN = 2
THUMB_ROW = THUMB + 10
IDLE_LABELS = {1: "1 min", 2: "2 min", 5: "5 min", 10: "10 min", 30: "30 min"}
INTERVAL_LABELS = {10: "10 s", 30: "30 s", 60: "1 min", 300: "5 min"}
CLOCK_LABELS = {"24h": "24-hour", "12h": "AM/PM"}
CLOCK_PREVIEW = 132
CLOCK_GAP = 24
CLOCK_BUTTON_W = 150
SHOW_LABELS = {"pictures": "Pictures and videos", "clock": "Date and time"}
SHOW_DETAILS = {"pictures": "Your photos and videos",
                "clock": "Big clock and the date"}
SHOW_TITLES = {"pictures": "Pictures", "clock": "Date and time"}
SHOW_ICONS = {"pictures": "Screensaver", "clock": "Clock"}
SHOW_GAP = 10
ROW_LABEL = 86
ROW_GAP = 6
# How often the knob's clock is set again while connected.
TIME_RESEND_S = 3600


def local_clock():
    """The local wall-clock time as seconds counted as if it were UTC, so the
    knob can show it without knowing the time zone."""
    return calendar.timegm(time.localtime())


def _size_text(size):
    if not size:
        return "0 KB"
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{max(1, round(size / 1024))} KB"


class ScreensaverPage:
    """Mixed into App; uses its kit, settings, bridge and painters."""

    def build_screensaver_page(self):
        k = self.kit
        page = tk.Frame(self.root, bg=ui.MAIN_BG)
        title = ui.Picture(page, ui.MAIN_BG)
        image = k.canvas(CARD_WIDTH, 44, ui.MAIN_BG)
        k.text(image, 0, 22, "Screensaver", "semibold", 18, ui.INK)
        title.show(image)
        title.pack(padx=k.px(28), pady=(k.px(18), k.px(4)), anchor="w")

        body = tk.Frame(page, bg=PANEL_BG)
        body.pack(padx=k.px(28), pady=(k.px(6), k.px(18)), anchor="w")
        self.saver_toggle = ui.Button(
            body, PANEL_BG,
            lambda hover: self.paint_toggle(
                self.settings["saver_enabled"], "Screensaver when the knob is idle",
                "A touch or a turn brings the dial back", hover),
            lambda: self.toggle_setting("saver_enabled"))
        self.saver_toggle.pack(anchor="w")
        self.dim_toggle = ui.Button(
            body, PANEL_BG,
            lambda hover: self.paint_toggle(
                self.settings["dim_idle"], "Dim the screen when idle",
                "After 10 min, 10% dimmer every 5 min until off", hover),
            lambda: self.toggle_setting("dim_idle"))
        self.dim_toggle.pack(anchor="w", pady=(k.px(6), 0))
        self.saver_choices = []
        self.saver_choice_row(body, "Start after", "saver_idle", IDLE_LABELS).pack(
            anchor="w", pady=(k.px(12), 0))

        body = self.section(page)
        self.caption(body, "WHAT THE KNOB SHOWS").pack(anchor="w")
        row = tk.Frame(body, bg=PANEL_BG)
        row.pack(anchor="w", pady=(k.px(6), 0))
        width = (CARD_WIDTH - SHOW_GAP) / 2
        self.saver_show_cards = [
            ui.Button(row, PANEL_BG,
                      lambda hover, value=value: self.paint_show_card(value, hover, width),
                      lambda value=value: self.set_saver_choice("saver_show", value))
            for value in SHOW_LABELS]
        self.pack_row(self.saver_show_cards, SHOW_GAP)

        body = self.section(page)
        self.saver_pictures_box = tk.Frame(body, bg=PANEL_BG)
        self.saver_clock_box = tk.Frame(body, bg=PANEL_BG)
        box = self.saver_pictures_box
        self.saver_choice_row(box, "Each picture", "saver_interval", INTERVAL_LABELS).pack(
            anchor="w")
        self.saver_summary = ui.Picture(box, PANEL_BG)
        self.saver_summary.pack(anchor="w", pady=(k.px(12), k.px(8)))
        self.thumb_canvas = tk.Canvas(box, bg=PANEL_BG, highlightthickness=0, bd=0,
                                      width=k.px(CARD_WIDTH),
                                      height=k.px(THUMB_ROW * THUMB_ROWS_SHOWN - 10))
        self.thumb_canvas.pack(anchor="w")
        self.thumb_item = self.thumb_canvas.create_image(0, 0, anchor="nw")
        self.thumb_photo = None
        self.thumb_hover = None
        self.thumb_canvas.bind("<Motion>", self.hover_thumb)
        self.thumb_canvas.bind("<Leave>", lambda event: self.set_thumb_hover(None))
        self.thumb_canvas.bind("<Button-1>", self.click_thumb)
        self.thumb_canvas.bind("<MouseWheel>", self.scroll_thumbs)
        row = tk.Frame(box, bg=PANEL_BG)
        row.pack(anchor="w", pady=(k.px(10), 0))
        widths = self.fill_widths([150, 0])
        self.saver_buttons = [
            ui.Button(row, PANEL_BG,
                      lambda hover, width=widths[0]: self.paint_pill(
                          "Add pictures or videos\u2026", hover, width=width,
                          enabled=not self.saver_busy()),
                      self.add_saver_media),
            ui.Button(row, PANEL_BG,
                      lambda hover, width=widths[1]: self.paint_pill(
                          "Send to knob", hover, primary=True, width=width,
                          enabled=self.can_upload()),
                      self.upload_saver_media),
        ]
        self.pack_row(self.saver_buttons)
        self.saver_status = ui.Picture(box, PANEL_BG)
        self.saver_status.pack(anchor="w", pady=(k.px(6), 0))
        self.saver_clock_preview = ui.Picture(self.saver_clock_box, PANEL_BG)
        self.saver_clock_preview.pack(side="left")
        column = tk.Frame(self.saver_clock_box, bg=PANEL_BG)
        column.pack(side="left", padx=(k.px(CLOCK_GAP), 0))
        buttons = [ui.Button(
            column, PANEL_BG,
            lambda hover, value=value: self.paint_choice(
                self.settings["clock_format"] == value, CLOCK_LABELS[value], hover,
                CLOCK_BUTTON_W),
            lambda value=value: self.set_saver_choice("clock_format", value))
            for value in CLOCK_LABELS]
        for index, button in enumerate(buttons):
            button.pack(anchor="w", pady=(0 if index == 0 else k.px(ROW_GAP), 0))
        self.saver_choices += buttons
        self.library_crc = self.library.checksum()
        self.screensaver_page = page
        self.refresh_screensaver()

    def saver_choice_row(self, parent, label, key, labels):
        """A short label on the left and the choices filling the rest of the row."""
        k = self.kit
        row = tk.Frame(parent, bg=PANEL_BG)
        name = ui.Picture(row, PANEL_BG)
        image = k.canvas(ROW_LABEL, 32, PANEL_BG)
        k.text(image, 0, 16, label, "semibold", 9.5, ui.SUBTLE_INK)
        name.show(image)
        name.pack(side="left")
        room = CARD_WIDTH - ROW_LABEL - ROW_GAP * (len(labels) - 1)
        widths = [room // len(labels)] * len(labels)
        widths[-1] = room - sum(widths[:-1])
        buttons = [ui.Button(
            row, PANEL_BG,
            lambda hover, value=value, width=width, text=labels[value]:
                self.paint_choice(self.settings[key] == value, text, hover, width),
            lambda value=value: self.set_saver_choice(key, value))
            for value, width in zip(labels, widths)]
        self.pack_row(buttons, ROW_GAP)
        self.saver_choices += buttons
        return row

    # ----- painters -----------------------------------------------------

    def paint_choice(self, chosen, label, hover, width):
        k = self.kit
        height = 32
        image = k.canvas(width, height, PANEL_BG)
        if chosen:
            k.rounded(image, (0, 0, width, height), 9, ui.INK)
            ink = "#FFFFFF"
        else:
            k.rounded(image, (0, 0, width, height), 9, "#FFFFFF" if hover else ui.CARD_BG,
                      ui.CARD_EDGE)
            ink = ui.SUBTLE_INK
        k.text(image, width / 2, height / 2, label, "semibold", 9.5, ink, anchor="mm")
        return image

    def paint_show_card(self, value, hover, width):
        """A big pick for what the screensaver shows; the chosen one is ringed
        in the accent and ticked."""
        k = self.kit
        height = 66
        image = k.canvas(width, height, PANEL_BG)
        accent = self.accent(self.mode)
        chosen = self.settings["saver_show"] == value
        if chosen:
            k.rounded(image, (0, 0, width, height), 12, accent)
            k.rounded(image, (2, 2, width - 2, height - 2), 10, "#FFFFFF")
        else:
            k.rounded(image, (0, 0, width, height), 12, "#FFFFFF" if hover else ui.CARD_BG,
                      ui.CARD_EDGE)
        k.dot(image, 26, height / 2, 15, accent if chosen else ui.CARD_EDGE)
        k.icon(image, SHOW_ICONS[value], 26, height / 2,
               "#FFFFFF" if chosen else ui.SUBTLE_INK, 0.56)
        k.text(image, 50, height / 2 - 8, SHOW_TITLES[value], "semibold", 10, ui.INK,
               width=width - 54)
        detail = SHOW_DETAILS[value]
        if value == "pictures":
            count = len(self.library.items)
            if count:
                detail = f"{count} item{'s' if count != 1 else ''} ready to show"
        k.text(image, 50, height / 2 + 9, detail, "regular", 8.5, ui.MUTED_INK,
               width=width - 54)
        if chosen:
            k.dot(image, width - 12, 12, 7, accent)
            k.icon(image, "Check", width - 12, 12, "#FFFFFF", 0.55)
        return image

    def paint_clock_preview(self):
        """What the knob looks like with the clock."""
        k = self.kit
        width = height = CLOCK_PREVIEW
        image = k.canvas(width, height, PANEL_BG)
        accent = self.accent(self.mode)
        cx, cy, r = 66, height / 2, 62
        k.dot(image, cx, cy, r, "#101014")
        k.dot(image, cx, cy, r - 3, accent)
        k.dot(image, cx, cy, r - 6, "#101014")
        # The knob's layout scaled down: 96 px time, 24 px AM/PM and date.
        f = (r - 6) / 180
        now = time.localtime()
        h24 = self.uses_24_hour_clock()
        hour = now.tm_hour if h24 else (now.tm_hour % 12 or 12)
        k.text(image, cx, cy - 8 * f, f"{hour}:{now.tm_min:02d}", "device",
               96 * f * 0.75, "#F2F2F5", anchor="mm")
        if not h24:
            k.text(image, cx, cy - 76 * f, "AM" if now.tm_hour < 12 else "PM", "device",
                   24 * f * 0.75, "#C8C8D2", anchor="mm")
        k.text(image, cx, cy + 64 * f, f"{time.strftime('%a', now)} {now.tm_mday} "
               f"{time.strftime('%b', now)}", "device", 24 * f * 0.75, "#C8C8D2",
               anchor="mm")
        return image

    def capacity(self):
        if self.device_library:
            return self.device_library["capacity"]
        return DEFAULT_CAPACITY

    def paint_saver_summary(self):
        k = self.kit
        width, height = CARD_WIDTH, 26
        image = k.canvas(width, height, PANEL_BG)
        used, capacity = self.library.total_bytes(), self.capacity()
        count = len(self.library.items)
        k.text(image, 0, 8, "Your pictures and clips", "semibold", 10, ui.INK)
        text = (f"{count} item{'s' if count != 1 else ''} \u00b7 "
                f"{_size_text(used)} of {_size_text(capacity)}")
        k.text(image, width, 8, text, "regular", 8.5, ui.MUTED_INK, anchor="rm")
        k.rounded(image, (0, 20, width, 24), 2, ui.CARD_EDGE)
        if used:
            k.rounded(image, (0, 20, max(4, width * min(1.0, used / capacity)), 24), 2,
                      dial.label_ink(self.accent(self.mode)))
        return image

    def paint_thumbs(self):
        """All thumbnails on one image: round, like the screen, with a badge
        on clips and a remove button on the one under the pointer."""
        k = self.kit
        items = self.library.items
        rows = max(THUMB_ROWS_SHOWN, (len(items) + THUMB_COLUMNS - 1) // THUMB_COLUMNS)
        image = k.canvas(CARD_WIDTH, rows * THUMB_ROW - 10, PANEL_BG)
        step = (CARD_WIDTH - THUMB) / (THUMB_COLUMNS - 1)
        size = k.px(THUMB)
        if not items:
            k.text(image, CARD_WIDTH / 2, THUMB_ROW - 5,
                   "No pictures yet. Add some to use the screensaver.",
                   "regular", 9, ui.MUTED_INK, anchor="mm")
            return image
        mask = Image.new("L", (size * 4, size * 4), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
        mask = mask.resize((size, size), Image.LANCZOS)
        for index, item in enumerate(items):
            x = (index % THUMB_COLUMNS) * step
            y = (index // THUMB_COLUMNS) * THUMB_ROW
            try:
                with Image.open(self.library.thumbnail(item["id"])) as thumb:
                    picture = thumb.convert("RGB").resize((size, size), Image.LANCZOS)
            except OSError:
                picture = Image.new("RGB", (size, size), ui.rgb(ui.CARD_EDGE))
            image.paste(picture, (k.px(x), k.px(y)), mask)
            if item["frames"] > 1:
                k.dot(image, x + THUMB / 2, y + THUMB / 2, 9, "#FFFFFF")
                k.icon(image, "Play", x + THUMB / 2 + 1, y + THUMB / 2, ui.INK, 0.32)
            if index == self.thumb_hover:
                k.dot(image, x + THUMB - 8, y + 8, 9, ui.INK)
                k.icon(image, "Close", x + THUMB - 8, y + 8, "#FFFFFF", 0.7)
        return image

    def paint_saver_status(self):
        k = self.kit
        width = CARD_WIDTH
        image = k.canvas(width, 24, PANEL_BG)
        state = self.upload_state
        progress = None
        if state and state[0] == "busy":
            text, progress = "Sending to the knob\u2026", state[1]
        elif state and state[0] == "adding":
            text = state[1]
            progress = state[2] if len(state) > 2 else None
        elif state and state[0] in ("error", "failed"):
            text = state[1]
        elif not self.connected:
            text = "Connect the knob to send the pictures."
        elif self.device_library is None:
            text = "Update the knob's firmware (Settings \u203a About) to use the screensaver."
        elif self.library_in_sync():
            text = "The knob has these pictures." if self.library.items else \
                "Nothing stored on the knob."
        else:
            text = "Changes not sent yet \u2014 press Send to knob."
        k.text(image, 0, 7, text, "regular", 9, ui.SUBTLE_INK, width=width)
        if progress is not None:
            k.rounded(image, (0, 17, width, 22), 2.5, ui.CARD_EDGE)
            k.rounded(image, (0, 17, max(5, width * progress), 22), 2.5,
                      dial.label_ink(self.accent(self.mode)))
        return image

    # ----- state --------------------------------------------------------

    def library_in_sync(self):
        device = self.device_library
        if not device:
            return False
        if not self.library.items:
            return device["count"] == 0
        return device["count"] == len(self.library.items) and device["crc"] == self.library_crc

    def saver_busy(self):
        return bool(self.upload_state and self.upload_state[0] in ("busy", "adding"))

    def can_upload(self):
        return (self.connected and self.device_library is not None and not self.saver_busy()
                and not self.update_busy and not self.library_in_sync())

    def refresh_screensaver(self):
        if not hasattr(self, "screensaver_page"):
            return
        self.saver_toggle.refresh()
        self.dim_toggle.refresh()
        for button in self.saver_choices + self.saver_buttons + self.saver_show_cards:
            button.refresh()
        pictures = self.settings["saver_show"] == "pictures"
        shown, hidden = ((self.saver_pictures_box, self.saver_clock_box) if pictures
                         else (self.saver_clock_box, self.saver_pictures_box))
        hidden.pack_forget()
        if not shown.winfo_manager():
            shown.pack(anchor="w")
        if pictures:
            self.saver_summary.show(self.paint_saver_summary())
            self.show_thumbs()
            self.saver_status.show(self.paint_saver_status())
        else:
            self.saver_clock_preview.show(self.paint_clock_preview())
        self.refresh_dashboard_tile("Screensaver")

    def show_thumbs(self):
        image = self.paint_thumbs()
        self.thumb_photo = ImageTk.PhotoImage(image, master=self.thumb_canvas)
        self.thumb_canvas.itemconfigure(self.thumb_item, image=self.thumb_photo)
        self.thumb_canvas.configure(scrollregion=(0, 0, image.width, image.height))

    def thumb_at(self, event):
        k = self.kit
        x = event.x / k.scale
        y = self.thumb_canvas.canvasy(event.y) / k.scale
        step = (CARD_WIDTH - THUMB) / (THUMB_COLUMNS - 1)
        column = int(x // step)
        row = int(y // THUMB_ROW)
        if column >= THUMB_COLUMNS or x - column * step > THUMB or y - row * THUMB_ROW > THUMB:
            return None, 0, 0
        index = row * THUMB_COLUMNS + column
        if index >= len(self.library.items):
            return None, 0, 0
        return index, x - column * step, y - row * THUMB_ROW

    def hover_thumb(self, event):
        self.set_thumb_hover(self.thumb_at(event)[0])

    def set_thumb_hover(self, index):
        if index != self.thumb_hover:
            self.thumb_hover = index
            self.thumb_canvas.configure(cursor="hand2" if index is not None else "")
            self.show_thumbs()

    def click_thumb(self, event):
        index, x, y = self.thumb_at(event)
        if index is None or self.saver_busy():
            return
        item = self.library.items[index]
        if x > THUMB - 20 and y < 20 or messagebox.askyesno(
                "Screensaver", f"Remove {item['name']} from the screensaver?",
                parent=self.root):
            self.library.remove(item["id"])
            self.library_changed()

    def scroll_thumbs(self, event):
        self.thumb_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    def library_changed(self):
        self.library_crc = self.library.checksum()
        self.thumb_hover = None
        self.refresh_screensaver()

    # ----- actions --------------------------------------------------------

    def set_saver_choice(self, key, value):
        self.settings[key] = value
        config.save(self.settings)
        if key == "clock_format" and self.connected:
            self.push_time()
        self.push_saver()

    def uses_24_hour_clock(self):
        return self.settings["clock_format"] == "24h"

    def push_time(self):
        self.time_pushed = time.monotonic()
        self.bridge.send_time(local_clock(), self.uses_24_hour_clock())

    def push_saver(self):
        if self.connected:
            self.bridge.send_saver(self.settings["saver_enabled"],
                                   self.settings["saver_idle"] * 60,
                                   self.settings["saver_interval"],
                                   self.settings["saver_show"] == "clock")
        self.refresh_screensaver()

    def add_saver_media(self):
        if self.saver_busy():
            return
        paths = filedialog.askopenfilenames(parent=self.root, title="Add to the screensaver",
                                            filetypes=FILE_TYPES)
        if not paths:
            return
        paths = list(paths)
        videos = [path for path in paths if screensaver.is_video(path)]
        need_ffmpeg = bool(videos) and not screensaver.find_ffmpeg()
        if need_ffmpeg and not messagebox.askyesno(
                "Screensaver",
                "Videos need FFmpeg, a free video converter. Revo1 downloads it "
                f"once (about {screensaver.FFMPEG_DOWNLOAD_MB} MB) from "
                "github.com/BtbN/FFmpeg-Builds.\n\nDownload it now?",
                parent=self.root):
            paths = [path for path in paths if path not in videos]
            if not paths:
                return
            need_ffmpeg = False
        capacity = self.capacity()
        self.upload_state = ("adding", "Preparing\u2026")
        self.refresh_screensaver()

        def run():
            failures = []
            if need_ffmpeg:
                def progress(fraction):
                    self.events.put(("saver_progress", fraction))
                try:
                    screensaver.ensure_ffmpeg(progress)
                except MediaError as exc:
                    failures += [f"{Path(path).name}: {exc}" for path in videos]
                    paths[:] = [path for path in paths if path not in videos]
            for number, path in enumerate(paths, 1):
                self.events.put(("saver_added", f"Preparing {number} of {len(paths)}\u2026"))
                try:
                    self.library.add(path, capacity)
                except (MediaError, OSError) as exc:
                    failures.append(f"{Path(path).name}: {exc}")
            self.events.put(("saver_failed", failures))

        threading.Thread(target=run, daemon=True).start()

    def upload_saver_media(self):
        if not self.can_upload():
            return
        try:
            if self.library.items:
                self.bridge.upload_library(self.library.pack())
            else:
                self.bridge.clear_library()
        except (MediaError, OSError) as exc:
            self.upload_state = ("error", str(exc))
        else:
            self.upload_state = ("busy", 0.0)
        self.refresh_screensaver()

    def on_screensaver_event(self, kind, payload):
        if kind == "upload":
            self.upload_state = ("busy", payload)
            self.saver_status.show(self.paint_saver_status())
            return
        if kind == "upload_done":
            self.upload_state = None
            self.bridge.request_library()
        elif kind == "upload_error":
            self.upload_state = ("error", f"Sending failed: {payload}")
        elif kind == "saver_progress":
            self.upload_state = ("adding", "Downloading the video converter\u2026", payload)
            self.saver_status.show(self.paint_saver_status())
            return
        elif kind == "saver_added":
            self.upload_state = ("adding", payload)
            self.library_changed()
            return
        elif kind == "saver_failed":
            self.upload_state = ("failed", "; ".join(payload)) if payload else None
            self.library_changed()
            if payload:
                messagebox.showwarning("Screensaver", "Some files could not be added:\n\n"
                                       + "\n".join(payload), parent=self.root)
            return
        self.refresh_screensaver()
