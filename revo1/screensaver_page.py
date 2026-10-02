"""The Screensaver page, in three tabs: General (on/off and dimming), Timing
(when it starts and how long each picture stays) and Display (pictures, the
time, or both, plus the pictures and clips kept on the knob)."""

import calendar
import io
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import numpy as np
from PIL import Image, ImageDraw, ImageTk

from revo1 import config, dial, screensaver, ui
from revo1.layout import CARD_WIDTH, PANEL_BG
from revo1.screensaver import DEFAULT_CAPACITY, FILE_TYPES, MediaError

SAVER_TABS = (("general", "General"), ("timing", "Timing"), ("display", "Display"),
              ("pictures", "Pictures"))
IDLE_LABELS = {1: "1 min", 2: "2 min", 5: "5 min", 10: "10 min", 30: "30 min"}
INTERVAL_LABELS = {10: "10 s", 30: "30 s", 60: "1 min", 180: "3 min", 300: "5 min"}
CLOCK_LABELS = {"24h": "24-hour", "12h": "AM/PM"}
RING_LABELS = {"dots": "Bullets", "bar": "Bar", "wave": "Wiggly", "ticks": "Ticks",
               "comet": "Comet", "none": "None"}
RING_GAP = 8
RING_SWATCH_H = 88
# The knob's faint track for the seconds still to come.
RING_TRACK = (0x34, 0x34, 0x3E)
# Every button on the page is one size; five of them fill a row exactly.
CHOICE_W = 140
CHOICE_H = 36
CHOICE_GAP = (CARD_WIDTH - 5 * CHOICE_W) // 4
SHOW_TITLES = {"pictures": "Pictures", "clock": "Date and time", "both": "Pictures and time"}
SHOW_DETAILS = {"pictures": "Your photos and videos", "clock": "Big clock and the date",
                "both": "The time over your photos"}
SHOW_GAP = 12
SHOW_HEIGHT = 76
# Summary cards on the General tab, each opening the tab that changes it.
GLANCE = (("idle", "timing"), ("interval", "timing"), ("show", "display"))
GLANCE_GAP = 12
GLANCE_HEIGHT = 88
HEADING_HEIGHT = 40
# Display tab: the knob preview on the left, its settings to the right.
PREVIEW = 196
PREVIEW_GAP = 28
COLUMN_W = CARD_WIDTH - PREVIEW - PREVIEW_GAP
BLOCK_GAP = 24
THUMB = 48
THUMB_COLUMNS = 13
# The library always shows this many rows (it scrolls past them), so the
# Pictures tab keeps one height and fits the window.
THUMB_ROWS_SHOWN = 3
THUMB_ROW = THUMB + 10
# The thumbnails sit in a rounded panel, inset by this much.
LIBRARY_PAD = 16
THUMB_STEP = (CARD_WIDTH - 2 * LIBRARY_PAD - THUMB) / (THUMB_COLUMNS - 1)
LIBRARY_HEIGHT = THUMB_ROW * THUMB_ROWS_SHOWN - 10 + 2 * LIBRARY_PAD
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


def ring_cover(size, radius, unit, marks, filled, style):
    """Coverage (0..1) of the seconds ring on a size x size square centred on
    the ring, as the knob draws it: `lit` for the accent part and `dim` for
    the track. Lengths are in output pixels; `unit` is one knob pixel and
    `marks` the number of seconds round the ring, `filled` how many are lit."""
    centre = (size - 1) / 2
    y, x = np.mgrid[:size, :size].astype(np.float32)
    dx, dy = x - centre, y - centre
    off = np.hypot(dx, dy) - radius
    at = (np.arctan2(dx, -dy) % (2 * np.pi)) / (2 * np.pi) * marks
    step = 2 * np.pi * radius / marks
    nearest = np.rint(at) % marks
    along = (at - np.rint(at)) * step
    passed = nearest <= filled - 1
    major = nearest % max(1, marks // 12) == 0
    zero = np.zeros_like(off)
    lit, dim = zero, zero

    def clip(value):
        return np.clip(value, 0, 1)

    if style == "dots":
        cover = clip(np.where(major, 3.2, 2.0) * unit + 0.5 - np.hypot(off, along))
        lit, dim = np.where(passed, cover, 0), np.where(passed, 0, cover)
    elif style == "ticks":
        cover = (clip(np.where(major, 1.4, 0.9) * unit + 0.5 - np.abs(along)) *
                 clip(np.minimum(off - np.where(major, -10, -4) * unit, 8 * unit - off) + 0.5))
        lit, dim = np.where(passed, cover, 0), np.where(passed, 0, cover)
    elif style in ("bar", "wave"):
        head = clip((filled - at) * step + 0.5)
        if style == "bar":
            cover = clip(3 * unit + 0.5 - np.abs(off))
            lit, dim = cover * head, cover * (1 - head)
        else:
            phase = at * np.pi
            slope = 4 * unit * np.pi / step * np.cos(phase)
            wave = clip(2 * unit + 0.5 - np.abs(off - 4 * unit * np.sin(phase)) /
                        np.sqrt(1 + slope * slope))
            lit = wave * head
            dim = clip(1.25 * unit + 0.5 - np.abs(off)) * (1 - head)
    elif style == "comet":
        second = filled - 1
        length = marks / 3
        behind = (second - at) % marks
        tail = np.where(behind < length, 1 - behind / length, 0)
        head_along = ((at - second + 1.5 * marks) % marks - marks / 2) * step
        head = clip(4 * unit + 0.5 - np.hypot(off, head_along))
        lit = np.maximum(head, clip(0.5 + 3 * unit * tail - np.abs(off)) * tail)
        dim = clip(unit + 0.5 - np.abs(off)) * (1 - lit)
    return lit, dim


def paint_ring(image, centre, radius, unit, marks, filled, style, accent, over_picture):
    """Draws the seconds ring onto an RGB image around `centre` (pixels)."""
    if style == "none":
        return
    size = int(2 * (radius + 12 * unit)) | 1
    left, top = round(centre[0] - size / 2 + 0.5), round(centre[1] - size / 2 + 0.5)
    box = (left, top, left + size, top + size)
    lit, dim = ring_cover(size, radius, unit, marks, filled, style)
    pixels = np.asarray(image.crop(box), dtype=np.float32)
    if over_picture:
        pixels *= (1 - 0.55 * dim)[..., None]
    else:
        pixels += (np.array(RING_TRACK, np.float32) - pixels) * dim[..., None]
    pixels += (np.array(ui.rgb(accent), np.float32) - pixels) * lit[..., None]
    image.paste(Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8), "RGB"), box)


def shade_for_clock(picture):
    """Darkens the middle of a picture as the knob does behind the time:
    about half brightness in the centre, easing back to full at the rim."""
    size = picture.width
    centre = (size - 1) / 2
    y, x = np.ogrid[:size, :size]
    r = np.hypot(x - centre, y - centre) * 360 / size
    t = np.clip((r - 110) / 70, 0, 1)
    factor = 0.45 + 0.55 * t * t * (3 - 2 * t)
    pixels = np.asarray(picture, dtype=np.float32) * factor[..., None]
    return Image.fromarray(pixels.astype(np.uint8), "RGB")


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

        tabs = tk.Frame(page, bg=ui.MAIN_BG)
        tabs.pack(padx=k.px(28), pady=(0, k.px(18)), anchor="w")
        self.saver_tab_buttons = []
        for key, label in SAVER_TABS:
            button = ui.Button(
                tabs, ui.MAIN_BG,
                lambda hover, key=key, label=label: self.paint_tab(
                    key, label, hover, SAVER_TABS, self.saver_tab),
                lambda key=key: self.show_saver_tab(key))
            button.pack(side="left")
            self.saver_tab_buttons.append(button)

        self.saver_tabs = {key: tk.Frame(page, bg=ui.MAIN_BG) for key, _ in SAVER_TABS}
        self.saver_choices = []
        self.saver_boxes_shown = None
        self.saver_preview_cache = (None, None)
        self.build_saver_general(self.saver_tabs["general"])
        self.build_saver_timing(self.saver_tabs["timing"])
        self.build_saver_display(self.saver_tabs["display"])
        self.build_saver_pictures(self.saver_tabs["pictures"])
        self.library_crc = self.library.checksum()
        self.screensaver_page = page
        self.show_saver_tab(self.saver_tab)

    def build_saver_general(self, tab):
        k = self.kit
        body = self.section(tab)
        self.saver_heading(body, "When the knob is idle",
                           "What happens after nobody touches or turns it for a while.")
        self.saver_toggle = ui.Button(
            body, PANEL_BG,
            lambda hover: self.paint_toggle(
                self.settings["saver_enabled"], "Screensaver",
                "A touch or a turn brings the dial back", hover),
            lambda: self.toggle_setting("saver_enabled"))
        self.saver_toggle.pack(anchor="w", pady=(k.px(14), 0))
        self.dim_toggle = ui.Button(
            body, PANEL_BG,
            lambda hover: self.paint_toggle(
                self.settings["dim_idle"], "Dim the screen",
                "After 10 min, 10% dimmer every 5 min until off", hover),
            lambda: self.toggle_setting("dim_idle"))
        self.dim_toggle.pack(anchor="w", pady=(k.px(8), 0))

        body = self.section(tab)
        self.saver_heading(body, "At a glance", "Click a card to change it.")
        row = tk.Frame(body, bg=PANEL_BG)
        row.pack(anchor="w", pady=(k.px(14), 0))
        widths = self.fill_widths([0] * len(GLANCE), GLANCE_GAP)
        self.saver_glance = [
            ui.Button(row, PANEL_BG,
                      lambda hover, key=key, width=width: self.paint_glance(key, hover, width),
                      lambda target=target: self.show_saver_tab(target))
            for (key, target), width in zip(GLANCE, widths)]
        self.pack_row(self.saver_glance, GLANCE_GAP)

    def build_saver_timing(self, tab):
        k = self.kit
        body = self.section(tab)
        self.saver_heading(body, "Start after",
                           "How long the knob waits, untouched, before the screensaver starts.")
        self.saver_choice_row(body, "saver_idle", IDLE_LABELS).pack(
            anchor="w", pady=(k.px(14), 0))
        body = self.section(tab)
        self.saver_heading(body, "Each picture",
                           "How long every picture stays on screen before the next one.")
        self.saver_choice_row(body, "saver_interval", INTERVAL_LABELS).pack(
            anchor="w", pady=(k.px(14), 0))

    def build_saver_display(self, tab):
        k = self.kit
        body = self.section(tab)
        self.saver_heading(body, "What the knob shows",
                           "Your pictures, a big clock, or the time over your pictures.")
        row = tk.Frame(body, bg=PANEL_BG)
        row.pack(anchor="w", pady=(k.px(14), 0))
        widths = self.fill_widths([0] * len(SHOW_TITLES), SHOW_GAP)
        self.saver_show_cards = [
            ui.Button(row, PANEL_BG,
                      lambda hover, value=value, width=width:
                          self.paint_show_card(value, hover, width),
                      lambda value=value: self.set_saver_choice("saver_show", value))
            for value, width in zip(SHOW_TITLES, widths)]
        self.pack_row(self.saver_show_cards, SHOW_GAP)

        body = self.section(tab)
        self.saver_preview = ui.Picture(body, PANEL_BG)
        self.saver_preview.pack(side="left", anchor="n")
        column = tk.Frame(body, bg=PANEL_BG)
        column.pack(side="left", anchor="n", padx=(k.px(PREVIEW_GAP), 0))

        self.saver_clock_box = box = tk.Frame(column, bg=PANEL_BG)
        self.saver_heading(box, "Clock", "How the time is written on the knob.", COLUMN_W)
        row = tk.Frame(box, bg=PANEL_BG)
        row.pack(anchor="w", pady=(k.px(14), 0))
        buttons = [ui.Button(
            row, PANEL_BG,
            lambda hover, value=value: self.paint_choice(
                self.settings["clock_format"] == value, CLOCK_LABELS[value], hover),
            lambda value=value: self.set_saver_choice("clock_format", value))
            for value in CLOCK_LABELS]
        self.pack_row(buttons, CHOICE_GAP)
        self.saver_choices += buttons
        self.saver_heading(box, "Seconds ring", "How the seconds go round the edge.",
                           COLUMN_W).pack_configure(pady=(k.px(BLOCK_GAP), 0))
        row = tk.Frame(box, bg=PANEL_BG)
        row.pack(anchor="w", pady=(k.px(14), 0))
        widths = self.fill_widths([0] * len(RING_LABELS), RING_GAP, COLUMN_W)
        buttons = [ui.Button(
            row, PANEL_BG,
            lambda hover, value=value, width=width: self.paint_ring_swatch(value, hover, width),
            lambda value=value: self.set_saver_choice("saver_ring", value))
            for value, width in zip(RING_LABELS, widths)]
        self.pack_row(buttons, RING_GAP)
        self.saver_choices += buttons

        # With pictures only, the column points to the Pictures tab instead.
        self.saver_library_box = box = tk.Frame(column, bg=PANEL_BG)
        self.saver_library_note = ui.Picture(box, PANEL_BG)
        self.saver_library_note.pack(anchor="w")
        self.saver_library_link = ui.Button(
            box, PANEL_BG,
            lambda hover: self.paint_choice(False, "Manage pictures \u203a", hover,
                                            CHOICE_W * 2 + CHOICE_GAP),
            lambda: self.show_saver_tab("pictures"))
        self.saver_library_link.pack(anchor="w", pady=(k.px(14), 0))

    def build_saver_pictures(self, tab):
        k = self.kit
        body = self.section(tab)
        self.saver_summary = ui.Picture(body, PANEL_BG)
        self.saver_summary.pack(anchor="w")
        self.thumb_canvas = tk.Canvas(body, bg=PANEL_BG, highlightthickness=0, bd=0,
                                      width=k.px(CARD_WIDTH),
                                      height=k.px(LIBRARY_HEIGHT))
        self.thumb_canvas.pack(anchor="w", pady=(k.px(14), 0))
        self.thumb_item = self.thumb_canvas.create_image(0, 0, anchor="nw")
        self.thumb_photo = None
        self.thumb_hover = None
        self.thumb_canvas.bind("<Motion>", self.hover_thumb)
        self.thumb_canvas.bind("<Leave>", lambda event: self.set_thumb_hover(None))
        self.thumb_canvas.bind("<Button-1>", self.click_thumb)
        self.thumb_canvas.bind("<MouseWheel>", self.scroll_thumbs)
        row = tk.Frame(body, bg=PANEL_BG)
        row.pack(anchor="w", pady=(k.px(14), 0))
        widths = self.fill_widths([0, 0], CHOICE_GAP)
        self.saver_buttons = [
            ui.Button(row, PANEL_BG,
                      lambda hover, width=widths[0]: self.paint_pill(
                          "Add pictures or videos\u2026", hover, width=width,
                          enabled=not self.saver_busy(), height=CHOICE_H),
                      self.add_saver_media),
            ui.Button(row, PANEL_BG,
                      lambda hover, width=widths[1]: self.paint_pill(
                          "Send to knob", hover, primary=True, width=width,
                          enabled=self.can_upload(), height=CHOICE_H),
                      self.upload_saver_media),
        ]
        self.pack_row(self.saver_buttons, CHOICE_GAP)
        self.saver_status = ui.Picture(body, PANEL_BG)
        self.saver_status.pack(anchor="w", pady=(k.px(8), 0))

    def saver_heading(self, parent, title, detail, width=CARD_WIDTH):
        """A block title with one line saying what it is for."""
        k = self.kit
        picture = ui.Picture(parent, PANEL_BG)
        image = k.canvas(width, HEADING_HEIGHT, PANEL_BG)
        k.text(image, 0, 10, title, "semibold", 11, ui.INK)
        k.text(image, 0, 31, detail, "regular", 9, ui.MUTED_INK, width=width)
        picture.show(image)
        picture.pack(anchor="w")
        return picture

    def saver_choice_row(self, parent, key, labels):
        row = tk.Frame(parent, bg=PANEL_BG)
        buttons = [ui.Button(
            row, PANEL_BG,
            lambda hover, value=value, text=text:
                self.paint_choice(self.settings[key] == value, text, hover),
            lambda value=value: self.set_saver_choice(key, value))
            for value, text in labels.items()]
        self.pack_row(buttons, CHOICE_GAP)
        self.saver_choices += buttons
        return row

    # ----- painters -----------------------------------------------------

    def paint_choice(self, chosen, label, hover, width=CHOICE_W):
        k = self.kit
        height = CHOICE_H
        image = k.canvas(width, height, PANEL_BG)
        if chosen:
            k.rounded(image, (0, 0, width, height), 10, ui.INK)
            ink = "#FFFFFF"
        else:
            k.rounded(image, (0, 0, width, height), 10, "#FFFFFF" if hover else ui.CARD_BG,
                      ui.CARD_EDGE)
            ink = ui.SUBTLE_INK
        k.text(image, width / 2, height / 2, label, "semibold", 10, ink, anchor="mm")
        return image

    def glance_text(self, key):
        """Label, value and a short note for one At a glance card."""
        settings = self.settings
        show = settings["saver_show"]
        if key == "idle":
            if not settings["saver_enabled"]:
                return "Starts after", "Off", "The screensaver is turned off"
            return "Starts after", IDLE_LABELS[settings["saver_idle"]], "Without a touch or turn"
        if key == "interval":
            note = ("Only used for pictures" if show == "clock"
                    else "Before the next picture")
            return "Each picture", INTERVAL_LABELS[settings["saver_interval"]], note
        if show == "clock":
            note = f"{CLOCK_LABELS[settings['clock_format']]} clock"
        else:
            count = len(self.library.items)
            note = (f"{count} item{'s' if count != 1 else ''} in the library" if count
                    else "No pictures added yet")
        return "Shows", SHOW_TITLES[show], note

    def paint_glance(self, key, hover, width):
        k = self.kit
        height = GLANCE_HEIGHT
        image = k.canvas(width, height, PANEL_BG)
        k.rounded(image, (0, 0, width, height), 12, "#FFFFFF" if hover else ui.CARD_BG,
                  ui.CARD_EDGE)
        label, value, note = self.glance_text(key)
        k.text(image, 18, 22, label, "regular", 9, ui.MUTED_INK)
        k.text(image, 18, 46, value, "semibold", 15, ui.INK, width=width - 46)
        k.text(image, 18, 68, note, "regular", 8.5, ui.SUBTLE_INK, width=width - 36)
        k.text(image, width - 18, 22, "\u203a", "semibold", 13,
               dial.label_ink(self.accent(self.mode)) if hover else ui.MUTED_INK,
               anchor="mm")
        return image

    def paint_show_card(self, value, hover, width):
        """A big pick for what the screensaver shows; the chosen one is ringed
        in the accent and ticked."""
        k = self.kit
        height = SHOW_HEIGHT
        image = k.canvas(width, height, PANEL_BG)
        accent = self.accent(self.mode)
        chosen = self.settings["saver_show"] == value
        if chosen:
            k.rounded(image, (0, 0, width, height), 12, accent)
            k.rounded(image, (2, 2, width - 2, height - 2), 10, "#FFFFFF")
        else:
            k.rounded(image, (0, 0, width, height), 12, "#FFFFFF" if hover else ui.CARD_BG,
                      ui.CARD_EDGE)
        cx, cy = 34, height / 2
        ink = "#FFFFFF" if chosen else ui.SUBTLE_INK
        k.dot(image, cx, cy, 18, accent if chosen else ui.CARD_EDGE)
        if value == "both":
            k.icon(image, "Screensaver", cx - 3, cy - 3, ink, 0.5)
            k.dot(image, cx + 9, cy + 9, 8.5, "#FFFFFF" if chosen else ui.CARD_BG)
            k.icon(image, "Clock", cx + 9, cy + 9,
                   dial.label_ink(accent) if chosen else ui.SUBTLE_INK, 0.34)
        else:
            k.icon(image, "Screensaver" if value == "pictures" else "Clock", cx, cy, ink, 0.6)
        left = 64
        k.text(image, left, cy - 9, SHOW_TITLES[value], "semibold", 10.5, ui.INK,
               width=width - left - 26)
        k.text(image, left, cy + 10, SHOW_DETAILS[value], "regular", 8.5, ui.MUTED_INK,
               width=width - left - 10)
        if chosen:
            k.dot(image, width - 14, 14, 7, accent)
            k.icon(image, "Check", width - 14, 14, "#FFFFFF", 0.55)
        return image

    def paint_ring_swatch(self, value, hover, width):
        """A small knob face showing one ring style, about two thirds round."""
        k = self.kit
        height = RING_SWATCH_H
        image = k.canvas(width, height, PANEL_BG)
        accent = self.accent(self.mode)
        chosen = self.settings["saver_ring"] == value
        if chosen:
            k.rounded(image, (0, 0, width, height), 12, accent)
            k.rounded(image, (2, 2, width - 2, height - 2), 10, "#FFFFFF")
        else:
            k.rounded(image, (0, 0, width, height), 12, "#FFFFFF" if hover else ui.CARD_BG,
                      ui.CARD_EDGE)
        cx, cy = width / 2, 36
        k.dot(image, cx, cy, 26, "#101014")
        if value == "none":
            k.rounded(image, (cx - 6, cy - 1, cx + 6, cy + 1), 1, "#6E6E78")
        paint_ring(image, (k.px(cx), k.px(cy)), k.scale * 20, k.scale * 0.75, 20, 13,
                   value, accent, False)
        k.text(image, cx, height - 15, RING_LABELS[value], "semibold" if chosen else "regular",
               9, ui.INK if chosen else ui.SUBTLE_INK, anchor="mm")
        return image

    def preview_picture(self):
        """The first picture in the library at full size, kept between repaints."""
        items = self.library.items
        if not items:
            return None
        item_id = items[0]["id"]
        if self.saver_preview_cache[0] != item_id:
            try:
                with Image.open(io.BytesIO(self.library.first_frame(item_id))) as frame:
                    picture = frame.convert("RGB")
            except (OSError, ValueError, Image.DecompressionBombError):
                picture = None
            self.saver_preview_cache = (item_id, picture)
        return self.saver_preview_cache[1]

    def paint_saver_preview(self):
        """The knob as the screensaver will look: the first picture, the clock,
        or the time over the darkened picture."""
        k = self.kit
        show = self.settings["saver_show"]
        size = PREVIEW
        image = k.canvas(size, size + 30, PANEL_BG)
        accent = self.accent(self.mode)
        c = size / 2
        r = c - 1
        k.dot(image, c, c, r, "#101014")
        k.dot(image, c, c, r - 3, accent)
        k.dot(image, c, c, r - 6, "#101014")
        inner = r - 6
        if show != "clock":
            picture = self.preview_picture()
            if picture is not None:
                pixels = k.px(inner * 2)
                picture = picture.resize((pixels, pixels), Image.LANCZOS)
                if show == "both":
                    picture = shade_for_clock(picture)
                mask = Image.new("L", (pixels * 4, pixels * 4), 0)
                ImageDraw.Draw(mask).ellipse((0, 0, pixels * 4 - 1, pixels * 4 - 1), fill=255)
                mask = mask.resize((pixels, pixels), Image.LANCZOS)
                image.paste(picture, (k.px(c - inner), k.px(c - inner)), mask)
            elif show == "pictures":
                k.icon(image, "Screensaver", c, c - 10, "#6E6E78", 1.0)
                k.text(image, c, c + 22, "Add pictures to see them here", "regular", 8,
                       "#8C8C96", anchor="mm")
        if show != "pictures":
            # The knob's layout scaled down: 96 px time, 24 px AM/PM and date.
            f = inner / 180
            now = time.localtime()
            g = k.scale * f
            paint_ring(image, (k.px(c), k.px(c)), 164 * g, g, 60, now.tm_sec + 1,
                       self.settings["saver_ring"], accent,
                       show == "both" and self.preview_picture() is not None)
            h24 = self.uses_24_hour_clock()
            hour = now.tm_hour if h24 else (now.tm_hour % 12 or 12)
            k.text(image, c, c - 8 * f, f"{hour}:{now.tm_min:02d}", "device",
                   96 * f * 0.75, "#F2F2F5", anchor="mm")
            if not h24:
                k.text(image, c, c - 76 * f, "AM" if now.tm_hour < 12 else "PM", "device",
                       24 * f * 0.75, "#C8C8D2", anchor="mm")
            k.text(image, c, c + 64 * f, f"{time.strftime('%a', now)} {now.tm_mday} "
                   f"{time.strftime('%b', now)}", "device", 24 * f * 0.75, "#C8C8D2",
                   anchor="mm")
        k.text(image, c, size + 18, "Preview", "regular", 8.5, ui.MUTED_INK, anchor="mm")
        return image

    def paint_library_note(self):
        """The Display tab's pointer to the library when only pictures show."""
        k = self.kit
        width, height = COLUMN_W, 62
        image = k.canvas(width, height, PANEL_BG)
        count = len(self.library.items)
        k.text(image, 0, 10, "Your pictures", "semibold", 11, ui.INK)
        if count:
            text = (f"{count} item{'s' if count != 1 else ''} \u00b7 "
                    f"{_size_text(self.library.total_bytes())}, shown one after another.")
        else:
            text = "No pictures yet. Add some in the Pictures tab."
        k.text(image, 0, 31, text, "regular", 9, ui.MUTED_INK, width=width)
        k.text(image, 0, 52, "Add, remove and send them to the knob in the Pictures tab.",
               "regular", 9, ui.MUTED_INK, width=width)
        return image

    def capacity(self):
        if self.device_library:
            return self.device_library["capacity"]
        return DEFAULT_CAPACITY

    def paint_saver_summary(self):
        k = self.kit
        width, height = CARD_WIDTH, HEADING_HEIGHT
        image = k.canvas(width, height, PANEL_BG)
        used, capacity = self.library.total_bytes(), self.capacity()
        count = len(self.library.items)
        k.text(image, 0, 10, "Your pictures and clips", "semibold", 11, ui.INK)
        text = (f"{count} item{'s' if count != 1 else ''} \u00b7 "
                f"{_size_text(used)} of {_size_text(capacity)}")
        k.text(image, width, 10, text, "regular", 9, ui.MUTED_INK, anchor="rm")
        k.rounded(image, (0, 30, width, 34), 2, ui.CARD_EDGE)
        if used:
            k.rounded(image, (0, 30, max(4, width * min(1.0, used / capacity)), 34), 2,
                      dial.label_ink(self.accent(self.mode)))
        return image

    def paint_thumbs(self):
        """All thumbnails on one canvas (it scrolls past two rows), with a play
        mark on clips and a remove button on the one under the pointer."""
        k = self.kit
        items = self.library.items
        rows = max(THUMB_ROWS_SHOWN, (len(items) + THUMB_COLUMNS - 1) // THUMB_COLUMNS)
        height = rows * THUMB_ROW - 10 + 2 * LIBRARY_PAD
        image = k.canvas(CARD_WIDTH, height, PANEL_BG)
        k.rounded(image, (0, 0, CARD_WIDTH, height), 12, ui.CARD_BG, ui.CARD_EDGE)
        size = k.px(THUMB)
        if not items:
            k.icon(image, "Screensaver", CARD_WIDTH / 2, height / 2 - 14, ui.MUTED_INK, 0.9)
            k.text(image, CARD_WIDTH / 2, height / 2 + 16,
                   "No pictures yet. Add some to use them on the knob.",
                   "regular", 9, ui.MUTED_INK, anchor="mm")
            return image
        mask = Image.new("L", (size * 4, size * 4), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
        mask = mask.resize((size, size), Image.LANCZOS)
        for index, item in enumerate(items):
            x = LIBRARY_PAD + (index % THUMB_COLUMNS) * THUMB_STEP
            y = LIBRARY_PAD + (index // THUMB_COLUMNS) * THUMB_ROW
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

    def show_saver_tab(self, key):
        self.saver_tab = key
        for frame in self.saver_tabs.values():
            frame.pack_forget()
        self.saver_tabs[key].pack(fill="x", anchor="w")
        self.refresh_screensaver()

    def refresh_screensaver(self):
        if not hasattr(self, "screensaver_page"):
            return
        for button in ([self.saver_toggle, self.dim_toggle] + self.saver_tab_buttons +
                       self.saver_glance + self.saver_choices + self.saver_buttons +
                       self.saver_show_cards + [self.saver_library_link]):
            button.refresh()
        show = self.settings["saver_show"]
        box = self.saver_library_box if show == "pictures" else self.saver_clock_box
        if box is not self.saver_boxes_shown:
            self.saver_clock_box.pack_forget()
            self.saver_library_box.pack_forget()
            box.pack(anchor="w")
            self.saver_boxes_shown = box
        self.saver_preview.show(self.paint_saver_preview())
        if show == "pictures":
            self.saver_library_note.show(self.paint_library_note())
        self.saver_summary.show(self.paint_saver_summary())
        self.show_thumbs()
        self.saver_status.show(self.paint_saver_status())
        self.refresh_dashboard_tile("Screensaver")

    def show_thumbs(self):
        image = self.paint_thumbs()
        self.thumb_photo = ImageTk.PhotoImage(image, master=self.thumb_canvas)
        self.thumb_canvas.itemconfigure(self.thumb_item, image=self.thumb_photo)
        self.thumb_canvas.configure(scrollregion=(0, 0, image.width, image.height))

    def thumb_at(self, event):
        k = self.kit
        x = event.x / k.scale - LIBRARY_PAD
        y = self.thumb_canvas.canvasy(event.y) / k.scale - LIBRARY_PAD
        step = THUMB_STEP
        if x < 0 or y < 0:
            return None, 0, 0
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
                                   config.SAVER_SHOW_CHOICES.index(self.settings["saver_show"]),
                                   config.RING_STYLES.index(self.settings["saver_ring"]))
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
