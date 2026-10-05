"""A small drawing kit for the companion window. Every label, button and icon
is rendered with Pillow, so the window shares the dial's greyscale
anti-aliasing instead of mixing in ClearType's coloured fringes."""

import tkinter as tk
from tkinter import ttk
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk

from revo1 import icons, theme

# Montserrat everywhere, the family the device's LVGL fonts are built from, so
# the window and the screen read as one product. "device" is the exact file
# LVGL converted (lvgl/scripts/built_in_font/Montserrat-Medium.ttf), used for
# everything drawn on the dial. SIL Open Font License 1.1, see fonts/OFL.txt.
FONT_DIR = Path(__file__).with_name("fonts")
ICON_FILE = Path(__file__).with_name("assets") / "revo1.ico"
# Groups the window with its Start Menu shortcut on the taskbar (the installer
# gives the shortcut the same ID).
APP_ID = "guilhermelimait.Revo1"
FONT_FILES = {
    "regular": FONT_DIR / "Montserrat-Regular.ttf",
    "device": FONT_DIR / "Montserrat-Medium.ttf",
    "semibold": FONT_DIR / "Montserrat-SemiBold.ttf",
}
TK_FAMILY = "Montserrat"
CONTROL_RADIUS = 10
CONTROL_HEIGHT = 40
TAB_HEIGHT = 44
TEXT_TITLE = 18
TEXT_HEADING = 11
TEXT_BUTTON = 10
TEXT_BODY = 9.5
TEXT_DETAIL = 9
TEXT_LINE = 22
GAP = 8
GROUP_GAP = 28
PAGE_INSET = 28
PAGE_TOP = 18
HEADER_GAP = 12
MODAL_INSET = 20


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
(MAIN_BG, SIDEBAR_BG, CARD_BG, CARD_EDGE, HOVER_BG, CARD_HOVER, FIELD_BG,
 INK, SUBTLE_INK, MUTED_INK, OK_GREEN, IDLE_GREY, SELECT_BG, SELECT_INK,
 SELECT_SUBTLE, SWITCH_KNOB, ERROR_INK, WARNING_INK) = theme.LIGHT.values()
ACTIVE_THEME = "light"


def set_theme(name):
    global ACTIVE_THEME
    if name not in ("light", "dark"):
        raise ValueError(f"Unknown palette: {name}")
    globals().update(theme.DARK if name == "dark" else theme.LIGHT)
    ACTIVE_THEME = name


def accent_ink(accent):
    if ACTIVE_THEME == "light":
        return "#%02X%02X%02X" % tuple(v * 3 // 4 for v in accent)
    def luminance(channels):
        channels = [v / 255 for v in channels]
        return sum((v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4) * weight
                   for v, weight in zip(channels, (0.2126, 0.7152, 0.0722)))
    background = luminance(rgb(CARD_HOVER))
    for step in range(21):
        channels = tuple(round(v + (255 - v) * step / 20) for v in accent)
        if (luminance(channels) + 0.05) / (background + 0.05) >= 4.5:
            return "#%02X%02X%02X" % channels
    raise ValueError("The theme's accent cannot meet text contrast")


def style_native(root):
    from tkinter import ttk
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=CARD_BG, foreground=INK,
                    troughcolor=MAIN_BG, bordercolor=CARD_EDGE,
                    lightcolor=CARD_EDGE, darkcolor=CARD_EDGE,
                    arrowcolor=SUBTLE_INK)
    style.configure("Launcher.Treeview", background=CARD_BG,
                    fieldbackground=CARD_BG, foreground=INK)
    style.map("Launcher.Treeview", background=[("selected", SELECT_BG)],
              foreground=[("selected", SELECT_INK)])
    root.option_add("*Entry.Background", FIELD_BG)
    root.option_add("*Entry.Foreground", INK)
    root.option_add("*Entry.InsertBackground", INK)
    root.option_add("*Entry.SelectBackground", SELECT_BG)
    root.option_add("*Entry.SelectForeground", SELECT_INK)
    root.option_add("*Scrollbar.Background", CARD_BG)
    root.option_add("*Scrollbar.ActiveBackground", HOVER_BG)
    root.option_add("*Scrollbar.TroughColor", MAIN_BG)


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

    def button_surface(self, image, width, height, hover=False, selected=False, enabled=True):
        fill = SELECT_BG if selected and enabled else (
            CARD_HOVER if hover and enabled else CARD_BG)
        self.rounded(image, (0, 0, width, height), CONTROL_RADIUS, fill,
                     None if selected and enabled else CARD_EDGE)
        if not enabled:
            return MUTED_INK, MUTED_INK
        return (SELECT_INK, SELECT_SUBTLE) if selected else (INK, SUBTLE_INK)

    def page_header(self, title, subtitle, width):
        image = self.canvas(width, 62, MAIN_BG)
        self.text(image, 0, 22, title, "semibold", TEXT_TITLE, INK)
        self.text(image, 0, 50, subtitle, "regular", TEXT_BODY, SUBTLE_INK, width=width)
        return image

    def colour_swatch(self, image, x, y, colour, hover=False, selected=False, radius=20):
        self.dot(image, x, y, radius, INK if selected else (SUBTLE_INK if hover else CARD_EDGE))
        self.dot(image, x, y, radius - 1.5, MAIN_BG)
        self.dot(image, x, y, radius * 0.725, CARD_EDGE)
        self.dot(image, x, y, radius * 0.675, colour or (CARD_HOVER if hover else CARD_BG))
        if colour is None:
            self.text(image, x, y, "+", "semibold", 12, INK, anchor="mm")

    def wrap(self, text, face, points, width):
        font = self.font(face, points)
        lines = []
        for paragraph in text.split("\n"):
            line = ""
            for word in paragraph.split():
                candidate = f"{line} {word}".strip()
                if line and font.getlength(candidate) > self.px(width):
                    lines.append(line)
                    line = word
                else:
                    line = candidate
                while font.getlength(line) > self.px(width):
                    cut = len(line) - 1
                    while cut > 1 and font.getlength(line[:cut]) > self.px(width):
                        cut -= 1
                    lines.append(line[:cut])
                    line = line[cut:]
            lines.append(line)
        return lines

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

    def keyboard_access(self):
        self.configure(takefocus=True, highlightthickness=1,
                       highlightbackground=self.cget("bg"), highlightcolor=INK)
        self.bind("<Return>", lambda event: self.command())
        self.bind("<space>", lambda event: self.command())

    def _set_hover(self, hover):
        self.hover = hover
        self.refresh()

    def refresh(self):
        self.photo = ImageTk.PhotoImage(self.paint(self.hover), master=self)
        self.config(image=self.photo)


class TextField(tk.Canvas):
    """Native editable text inside the shared rounded, focus-aware surface."""

    def __init__(self, parent, kit, width, background=None, **options):
        background = MAIN_BG if background is None else background
        super().__init__(parent, bg=background, bd=0, highlightthickness=0,
                         width=kit.px(width), height=kit.px(TAB_HEIGHT))
        self.kit = kit
        self.photo = None
        self.image_item = self.create_image(0, 0, anchor="nw")
        self.entry = tk.Entry(self, font=(TK_FAMILY, TEXT_BUTTON), bg=FIELD_BG, fg=INK,
                              insertbackground=INK, selectbackground=SELECT_BG,
                              selectforeground=SELECT_INK, relief="flat", bd=0,
                              highlightthickness=0, **options)
        self.entry_item = self.create_window(kit.px(12), kit.px(TAB_HEIGHT / 2),
                                             window=self.entry, anchor="w")
        self.entry.bind("<FocusIn>", lambda event: self._draw(True), add="+")
        self.entry.bind("<FocusOut>", lambda event: self._draw(False), add="+")
        self.bind("<Configure>", lambda event: self._draw(self.entry == self.focus_get()))
        self._draw(False)

    def _draw(self, focused):
        width = (self.winfo_width() if self.winfo_width() > 1 else int(self.cget("width"))) / self.kit.scale
        image = self.kit.canvas(width, TAB_HEIGHT, self.cget("bg"))
        self.kit.rounded(image, (0, 0, width, TAB_HEIGHT), CONTROL_RADIUS, FIELD_BG,
                         INK if focused else CARD_EDGE)
        self.photo = ImageTk.PhotoImage(image, master=self)
        self.itemconfigure(self.image_item, image=self.photo)
        self.itemconfigure(self.entry_item, width=self.kit.px(width - 24))


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
        self.kit.rounded(image, (0, 0, self.width, height), CONTROL_RADIUS, CARD_BG, CARD_EDGE)
        self.photo = ImageTk.PhotoImage(image, master=self)
        self.itemconfigure(self.image_item, image=self.photo)
        self.config(height=image.height)


class ScrollArea(tk.Frame):
    """Fixed-width content with local scrolling and keyboard focus reveal."""

    def __init__(self, parent, kit, width, inset=28):
        super().__init__(parent, bg=MAIN_BG)
        self.kit = kit
        self.canvas = tk.Canvas(self, bg=MAIN_BG, bd=0, highlightthickness=0,
                                height=kit.px(300), yscrollincrement=kit.px(24),
                                takefocus=True)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollbar.pack(side="right", fill="y", padx=(0, kit.px(8)))
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.body = tk.Frame(self.canvas, bg=MAIN_BG)
        self.item = self.canvas.create_window(kit.px(inset), kit.px(16), window=self.body,
                                             anchor="nw", width=kit.px(width))
        self.body.bind("<Configure>", self._fit)
        self.canvas.bind("<Configure>", self._fit)
        for key, amount in (("<Prior>", -1), ("<Next>", 1)):
            self.canvas.bind(key, lambda event, amount=amount: self._page(amount))
        self.canvas.bind("<Home>", lambda event: self._edge(0))
        self.canvas.bind("<End>", lambda event: self._edge(1))
        self.root = self.winfo_toplevel()
        self.bindings = [(sequence, self.root.bind(sequence, handler, add="+"))
                         for sequence, handler in
                         (("<MouseWheel>", self._wheel), ("<FocusIn>", self._focus))]
        self.bind("<Destroy>", self._cleanup, add="+")

    def _fit(self, event=None):
        height = self.body.winfo_reqheight() + self.kit.px(40)
        self.canvas.configure(scrollregion=(0, 0, 0, max(height, self.canvas.winfo_height())))
        if height > self.canvas.winfo_height():
            if not self.scrollbar.winfo_manager():
                self.scrollbar.pack(side="right", fill="y", padx=(0, self.kit.px(8)),
                                    before=self.canvas)
        else:
            self.scrollbar.pack_forget()

    def _wheel(self, event):
        if not self.winfo_ismapped() or not event.delta or self.root.grab_current() is not None:
            return
        x, y = event.x_root, event.y_root
        if (self.winfo_rootx() <= x < self.winfo_rootx() + self.winfo_width() and
                self.winfo_rooty() <= y < self.winfo_rooty() + self.winfo_height()):
            self.canvas.yview_scroll(-int(event.delta / 120) or (-1 if event.delta > 0 else 1),
                                     "units")
            return "break"

    def _focus(self, event):
        widget = event.widget
        ancestor = widget
        while ancestor is not None and ancestor is not self.body:
            ancestor = getattr(ancestor, "master", None)
        if ancestor is None or not widget.winfo_ismapped():
            return
        self.ensure_visible(widget)

    def ensure_visible(self, widget):
        top = widget.winfo_rooty() - self.canvas.winfo_rooty() + self.canvas.canvasy(0)
        bottom = top + widget.winfo_height()
        visible = self.canvas.canvasy(0)
        height = self.canvas.winfo_height()
        region = tuple(float(v) for v in self.canvas.cget("scrollregion").split())
        total = region[3]
        if top < visible:
            self.canvas.yview_moveto(max(0, top - self.kit.px(12)) / total)
        elif bottom > visible + height:
            self.canvas.yview_moveto((bottom + self.kit.px(12) - height) / total)

    def _page(self, amount):
        self.canvas.yview_scroll(amount, "pages")
        return "break"

    def _edge(self, fraction):
        self.canvas.yview_moveto(fraction)
        return "break"

    def _cleanup(self, event):
        if event.widget is self:
            for sequence, binding in self.bindings:
                self.root.unbind(sequence, binding)
