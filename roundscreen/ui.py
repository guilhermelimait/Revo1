"""A small drawing kit for the companion window. Every label, button and icon
is rendered with Pillow, so the window shares the dial's greyscale
anti-aliasing instead of mixing in ClearType's coloured fringes."""

import tkinter as tk
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk

from roundscreen import icons

# Montserrat everywhere, the family the device's LVGL fonts are built from, so
# the window and the screen read as one product. "device" is the exact file
# LVGL converted (lvgl/scripts/built_in_font/Montserrat-Medium.ttf), used for
# everything drawn on the dial. SIL Open Font License 1.1, see fonts/OFL.txt.
FONT_DIR = Path(__file__).with_name("fonts")
FONT_FILES = {
    "regular": FONT_DIR / "Montserrat-Regular.ttf",
    "device": FONT_DIR / "Montserrat-Medium.ttf",
    "semibold": FONT_DIR / "Montserrat-SemiBold.ttf",
}
TK_FAMILY = "Montserrat"


def register_fonts():
    """Makes the bundled Montserrat usable by native Tk widgets too, for this
    process only (FR_PRIVATE), without installing anything on the system."""
    try:
        import ctypes
        for path in FONT_FILES.values():
            ctypes.windll.gdi32.AddFontResourceExW(str(path), 0x10, 0)
    except (AttributeError, OSError):
        pass

# The device palette: a pale warm-grey face, a brighter cap, dark ink.
MAIN_BG = "#EAE9EC"
SIDEBAR_BG = "#DEDDE2"
CARD_BG = "#F6F5F8"
CARD_EDGE = "#D3D2D8"
HOVER_BG = "#E6E5EA"
INK = "#2A2A34"
SUBTLE_INK = "#55556A"
MUTED_INK = "#8A8A98"
OK_GREEN = "#2FA66A"
IDLE_GREY = "#A9A8B2"


def rgb(colour):
    if isinstance(colour, tuple):
        return colour
    return tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))


class Kit:
    """Converts layout units (96-dpi pixels) to screen pixels and caches fonts."""

    def __init__(self, scale):
        self.scale = scale
        self.fonts = {}

    def px(self, value):
        return round(value * self.scale)

    def font(self, face, points):
        return self.pixel_font(face, points * 4 / 3)

    def pixel_font(self, face, pixels):
        """`pixels` is the em size in layout pixels, as LVGL fonts are sized."""
        size = round(pixels * self.scale)
        key = (face, size)
        if key not in self.fonts:
            self.fonts[key] = ImageFont.truetype(str(FONT_FILES[face]), size)
        return self.fonts[key]

    def fit(self, text, font, width):
        if font.getlength(text) <= width:
            return text
        while text and font.getlength(text + "\u2026") > width:
            text = text[:-1]
        return text.rstrip() + "\u2026"

    def canvas(self, width, height, background):
        return Image.new("RGB", (self.px(width), self.px(height)), rgb(background))

    def rounded(self, image, box, radius, fill, outline=None):
        """Draws a rounded rectangle (layout units) supersampled 4x."""
        x0, y0, x1, y1 = (self.px(v) for v in box)
        width, height = x1 - x0, y1 - y0
        if width <= 0 or height <= 0:
            return
        factor = 4
        mask = Image.new("L", (width * factor, height * factor), 0)
        shape = ImageDraw.Draw(mask)
        r = self.px(radius) * factor
        if outline:
            shape.rounded_rectangle((0, 0, width * factor - 1, height * factor - 1), r, fill=255)
            edge = Image.new("RGB", (width, height), rgb(outline))
            image.paste(edge, (x0, y0), mask.resize((width, height), Image.LANCZOS))
            mask = Image.new("L", (width * factor, height * factor), 0)
            inset = round(self.scale * factor)
            ImageDraw.Draw(mask).rounded_rectangle(
                (inset, inset, width * factor - 1 - inset, height * factor - 1 - inset),
                max(r - inset, 0), fill=255)
        else:
            shape.rounded_rectangle((0, 0, width * factor - 1, height * factor - 1), r, fill=255)
        body = Image.new("RGB", (width, height), rgb(fill))
        image.paste(body, (x0, y0), mask.resize((width, height), Image.LANCZOS))

    def text(self, image, x, y, text, face, points, fill, anchor="lm", width=None):
        font = self.font(face, points)
        if width:
            text = self.fit(text, font, self.px(width))
        ImageDraw.Draw(image).text((self.px(x), self.px(y)), text, font=font,
                                   fill=rgb(fill), anchor=anchor)

    def icon(self, image, name, x, y, colour, size=1.0):
        pixels = np.array(image)
        icons.draw(pixels, name, x, y, rgb(colour), self.scale, size)
        image.paste(Image.fromarray(pixels))

    def dot(self, image, x, y, radius, colour):
        factor = 4
        d = self.px(radius * 2) * factor
        mask = Image.new("L", (d, d), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, d - 1, d - 1), fill=255)
        size = self.px(radius * 2)
        image.paste(Image.new("RGB", (size, size), rgb(colour)),
                    (self.px(x - radius), self.px(y - radius)),
                    mask.resize((size, size), Image.LANCZOS))


class Picture(tk.Label):
    """A static, Pillow-rendered image; `show` swaps it in place."""

    def __init__(self, parent, background):
        super().__init__(parent, bg=background, bd=0, highlightthickness=0)
        self.photo = None

    def show(self, image):
        self.photo = ImageTk.PhotoImage(image, master=self)
        self.config(image=self.photo)


class Button(tk.Label):
    """A clickable Pillow-rendered image. `paint(hover)` returns the image."""

    def __init__(self, parent, background, paint, command):
        super().__init__(parent, bg=background, bd=0, highlightthickness=0,
                         cursor="hand2")
        self.paint = paint
        self.command = command
        self.hover = False
        self.photo = None
        self.bind("<Enter>", lambda event: self._set_hover(True))
        self.bind("<Leave>", lambda event: self._set_hover(False))
        self.bind("<Button-1>", lambda event: self.command())
        self.refresh()

    def _set_hover(self, hover):
        self.hover = hover
        self.refresh()

    def refresh(self):
        self.photo = ImageTk.PhotoImage(self.paint(self.hover), master=self)
        self.config(image=self.photo)


class Card(tk.Canvas):
    """A rounded panel that grows to fit the frame placed in it (`body`)."""

    def __init__(self, parent, kit, width, background, padding=18):
        super().__init__(parent, bg=background, bd=0, highlightthickness=0,
                         width=kit.px(width), height=kit.px(40))
        self.kit = kit
        self.width = width
        self.padding = padding
        self.background = background
        self.photo = None
        self.image_item = self.create_image(0, 0, anchor="nw")
        self.body = tk.Frame(self, bg=CARD_BG)
        self.create_window(kit.px(padding), kit.px(padding), window=self.body,
                           anchor="nw", width=kit.px(width - 2 * padding))
        self.body.bind("<Configure>", self._fit)

    def _fit(self, event):
        height = event.height / self.kit.scale + 2 * self.padding
        image = self.kit.canvas(self.width, height, self.background)
        self.kit.rounded(image, (0, 0, self.width, height), 14, CARD_BG, CARD_EDGE)
        self.photo = ImageTk.PhotoImage(image, master=self)
        self.itemconfigure(self.image_item, image=self.photo)
        self.config(height=image.height)
