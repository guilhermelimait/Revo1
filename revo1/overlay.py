"""A click-through, non-activating Windows HUD for Revo1 control changes."""

import ctypes
from ctypes import wintypes as w
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from revo1 import config, ui

WIDTH, HEIGHT = 260, 76
SIZE_SCALE = 0.9
SURFACE = "#101012"
SURFACE_OPACITY = 0.62
TASKBAR_GAP = 16
HOLD_MS = 1600
FADE_MS = 30
FADE_STEPS = 5
MINIMAL_VALUE_POINTS = 11
MINIMAL_VALUE_GAP = 8
MINIMAL_VALUE_WIDTH = 62


def minimal_layout(k, feedback, width):
    font = k.font("semibold", MINIMAL_VALUE_POINTS)
    value = k.fit(feedback.value, font, k.px(MINIMAL_VALUE_WIDTH))
    left, _, right, _ = font.getbbox(value, anchor="lm")
    text_width = (right - left) / k.scale
    icon_width = 24
    start = (width - icon_width - MINIMAL_VALUE_GAP - text_width) / 2
    return start + icon_width / 2, start + icon_width + MINIMAL_VALUE_GAP - left / k.scale, value


@dataclass(frozen=True)
class Feedback:
    mode: str
    title: str
    value: str
    fraction: float | None = None
    muted: bool = False


def level_feedback(mode, level, muted=False):
    if mode not in ("Volume", "Mic", "Brightness"):
        raise ValueError(f"No percentage level for {mode}")
    if not 0 <= level <= 100:
        raise ValueError(f"Invalid control level: {level}")
    return Feedback(mode, config.title(mode), "Muted" if muted else f"{level}%",
                    0 if muted else level / 100, muted)


def direction_feedback(mode, steps):
    if mode not in ("Scroll", "Zoom") or not steps:
        raise ValueError("Directional feedback needs Scroll/Zoom and nonzero steps")
    value = ("Up" if steps < 0 else "Down") if mode == "Scroll" else (
        "In" if steps > 0 else "Out")
    return Feedback(mode, config.title(mode), value)


def time_feedback(mode, title, seconds, total=0):
    seconds = max(0, int(seconds))
    return Feedback(mode, title, f"{seconds // 60}:{seconds % 60:02d}",
                    min(1, seconds / total) if total > 0 else None)


def paint(feedback, scale, accent, detail="standard"):
    """Transparent corners, an elevated pill, and opaque, crisp content."""
    k = ui.Kit(scale * SIZE_SCALE)
    minimal = detail == "minimal"
    width, height = (136, 64) if minimal else (WIDTH, HEIGHT)
    size = (k.px(width), k.px(height))
    image = Image.new("RGBA", size)
    mask = Image.new("L", size)
    ImageDraw.Draw(mask).rounded_rectangle(
        (k.px(8), k.px(8), k.px(width - 8) - 1, k.px(height - 8) - 1),
        k.px((height - 16) / 2), fill=255)
    shadow = Image.new("L", size)
    ImageDraw.Draw(shadow).rounded_rectangle(
        (k.px(10), k.px(12), k.px(width - 10), k.px(height - 6)),
        k.px((height - 16) / 2), fill=30)
    image.paste((0, 0, 0, 255), (0, 0), shadow.filter(ImageFilter.GaussianBlur(k.px(4))))
    content = k.canvas(width, height, SURFACE)
    tint = accent
    cx, cy = (32, 32) if minimal else (38, 38)
    if minimal:
        cx, text_x, value = minimal_layout(k, feedback, width)
    icon = feedback.mode + "Muted" if feedback.muted else feedback.mode
    k.icon(content, icon, cx, cy, tint, 0.75)
    has_level = feedback.fraction is not None and not minimal
    if not minimal:
        k.text(content, 66, 28 if has_level else 38, feedback.title,
               "device", 9, "#E0E0E5", width=88)
    if minimal:
        k.text(content, text_x, cy, value, "semibold", MINIMAL_VALUE_POINTS, "#FFFFFF")
    else:
        k.text(content, width - 26, 28 if has_level else 38, feedback.value,
               "semibold", 13, "#FFFFFF", anchor="rm", width=76)
    if has_level:
        fraction = min(1, max(0, feedback.fraction))
        k.rounded(content, (66, 46, 234, 50), 2, "#55555B")
        if fraction > 0:
            k.rounded(content, (66, 46, 66 + 168 * fraction, 50), 2, tint)
    layer = content.convert("RGBA")
    layer.putalpha(mask.point(lambda a: round(a * SURFACE_OPACITY)))
    image = Image.alpha_composite(image, layer)
    # Text and icon pixels stay opaque even though their surrounding surface is translucent.
    pixels = np.array(image)
    content_pixels = np.array(content)
    changed = np.any(content_pixels != ui.rgb(SURFACE), axis=2) & (np.array(mask) > 0)
    pixels[:, :, :3][changed] = content_pixels[changed]
    pixels[:, :, 3][changed] = 255
    return Image.fromarray(pixels)


def paint_notch(feedback, scale, accent, detail="standard"):
    """A solid black surface attached to the display's top edge."""
    k = ui.Kit(scale * SIZE_SCALE)
    minimal = detail == "minimal"
    width, height = (120, 48) if minimal else (260, 64)
    size = (k.px(width), k.px(height))
    factor = 4
    mask = Image.new("L", (size[0] * factor, size[1] * factor))
    draw = ImageDraw.Draw(mask)
    radius = k.px(20) * factor
    draw.rounded_rectangle((0, -radius, mask.width - 1, mask.height - 1),
                           radius=radius, fill=255)
    content = k.canvas(width, height, "#000000")
    cx, cy = (24, 24) if minimal else (30, 30)
    if minimal:
        cx, text_x, value = minimal_layout(k, feedback, width)
    icon = feedback.mode + "Muted" if feedback.muted else feedback.mode
    k.icon(content, icon, cx, cy, accent, 0.75)
    has_level = feedback.fraction is not None and not minimal
    if not minimal:
        k.text(content, 58, 24 if has_level else 30, feedback.title,
               "device", 9, "#E0E0E5", width=96)
    if minimal:
        k.text(content, text_x, cy, value, "semibold", MINIMAL_VALUE_POINTS, "#FFFFFF")
    else:
        k.text(content, width - 18, 24 if has_level else 30, feedback.value,
               "semibold", 13, "#FFFFFF", anchor="rm", width=76)
    if has_level:
        fraction = min(1, max(0, feedback.fraction))
        k.rounded(content, (58, 43, 242, 47), 2, "#45454B")
        if fraction > 0:
            k.rounded(content, (58, 43, 58 + 184 * fraction, 47), 2, accent)
    image = content.convert("RGBA")
    image.putalpha(mask.resize(size, Image.Resampling.LANCZOS))
    return image


def position(work, width, height, gap, style="pill"):
    left, top, right, bottom = work
    return (left + max(0, (right - left - width) // 2),
            top if style == "notch" else max(top, bottom - height - gap))


class MONITORINFO(ctypes.Structure):
    _fields_ = [("size", w.DWORD), ("monitor", w.RECT), ("work", w.RECT),
                ("flags", w.DWORD)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("size", w.DWORD), ("width", w.LONG), ("height", w.LONG),
                ("planes", w.WORD), ("bits", w.WORD), ("compression", w.DWORD),
                ("image_size", w.DWORD), ("xppm", w.LONG), ("yppm", w.LONG),
                ("used", w.DWORD), ("important", w.DWORD)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [(name, w.BYTE) for name in ("op", "flags", "alpha", "format")]


class NativeWindow:
    def __init__(self):
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi = ctypes.WinDLL("gdi32", use_last_error=True)
        self.hwnd = None
        api = (
            (self.user, "CreateWindowExW", w.HWND, [w.DWORD, w.LPCWSTR, w.LPCWSTR,
             w.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
             w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID]),
            (self.user, "GetForegroundWindow", w.HWND, []),
            (self.user, "MonitorFromWindow", w.HANDLE, [w.HWND, w.DWORD]),
            (self.user, "GetMonitorInfoW", w.BOOL, [w.HANDLE, ctypes.POINTER(MONITORINFO)]),
            (self.user, "GetDC", w.HDC, [w.HWND]),
            (self.user, "ReleaseDC", ctypes.c_int, [w.HWND, w.HDC]),
            (self.user, "ShowWindow", w.BOOL, [w.HWND, ctypes.c_int]),
            (self.user, "SetWindowPos", w.BOOL, [w.HWND, w.HWND, ctypes.c_int,
             ctypes.c_int, ctypes.c_int, ctypes.c_int, w.UINT]),
            (self.user, "DestroyWindow", w.BOOL, [w.HWND]),
            (self.user, "SystemParametersInfoW", w.BOOL, [w.UINT, w.UINT, w.LPVOID, w.UINT]),
            (self.user, "UpdateLayeredWindow", w.BOOL, [w.HWND, w.HDC,
             ctypes.POINTER(w.POINT), ctypes.POINTER(w.SIZE), w.HDC,
             ctypes.POINTER(w.POINT), w.DWORD, ctypes.POINTER(BLENDFUNCTION), w.DWORD]),
            (self.gdi, "CreateCompatibleDC", w.HDC, [w.HDC]),
            (self.gdi, "CreateDIBSection", w.HBITMAP, [w.HDC,
             ctypes.POINTER(BITMAPINFOHEADER), w.UINT, ctypes.POINTER(w.LPVOID),
             w.HANDLE, w.DWORD]),
            (self.gdi, "SelectObject", w.HANDLE, [w.HDC, w.HANDLE]),
            (self.gdi, "DeleteObject", w.BOOL, [w.HANDLE]),
            (self.gdi, "DeleteDC", w.BOOL, [w.HDC]),
        )
        for library, name, result, args in api:
            function = getattr(library, name)
            function.restype, function.argtypes = result, args

    def work_area(self):
        return self.monitor_bounds(work=True)

    def monitor_area(self):
        return self.monitor_bounds(work=False)

    def monitor_bounds(self, work):
        monitor = self.user.MonitorFromWindow(self.user.GetForegroundWindow(), 2)
        info = MONITORINFO()
        info.size = ctypes.sizeof(info)
        if not self.user.GetMonitorInfoW(monitor, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        rect = info.work if work else info.monitor
        return (rect.left, rect.top, rect.right, rect.bottom)

    def animations_enabled(self):
        enabled = w.BOOL()
        if not self.user.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
            raise ctypes.WinError(ctypes.get_last_error())
        return bool(enabled.value)

    def display(self, image, xy, opacity=255):
        if not self.hwnd:
            # Layered, transparent to input, tool window, no activation; independent of Tk/tray.
            self.hwnd = self.user.CreateWindowExW(
                0x00080000 | 0x20 | 0x80 | 0x08000000, "STATIC", "Revo1 control overlay",
                0x80000000, 0, 0, image.width, image.height, None, None, None, None)
            if not self.hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
        screen = self.user.GetDC(None)
        dc = bitmap = previous = None
        try:
            if not screen:
                raise ctypes.WinError(ctypes.get_last_error())
            dc = self.gdi.CreateCompatibleDC(screen)
            if not dc:
                raise ctypes.WinError(ctypes.get_last_error())
            header = BITMAPINFOHEADER()
            header.size, header.width, header.height = ctypes.sizeof(header), image.width, -image.height
            header.planes, header.bits = 1, 32
            bits = w.LPVOID()
            bitmap = self.gdi.CreateDIBSection(dc, ctypes.byref(header), 0,
                                             ctypes.byref(bits), None, 0)
            if not bitmap:
                raise ctypes.WinError(ctypes.get_last_error())
            previous = self.gdi.SelectObject(dc, bitmap)
            if not previous or previous == ctypes.c_void_p(-1).value:
                previous = None
                raise ctypes.WinError(ctypes.get_last_error())
            rgba = np.array(image, dtype=np.uint16)
            rgba[:, :, :3] = (rgba[:, :, :3] * rgba[:, :, 3:4] + 127) // 255
            bgra = rgba[:, :, [2, 1, 0, 3]].astype(np.uint8).tobytes()
            ctypes.memmove(bits, bgra, len(bgra))
            destination, source = w.POINT(*xy), w.POINT(0, 0)
            size = w.SIZE(image.width, image.height)
            blend = BLENDFUNCTION(0, 0, opacity, 1)
            if not self.user.UpdateLayeredWindow(self.hwnd, screen, ctypes.byref(destination),
                                                ctypes.byref(size), dc, ctypes.byref(source),
                                                0, ctypes.byref(blend), 2):
                raise ctypes.WinError(ctypes.get_last_error())
            if not self.user.SetWindowPos(self.hwnd, w.HWND(-1), 0, 0, 0, 0,
                                          0x1 | 0x2 | 0x10 | 0x40):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            if previous:
                self.gdi.SelectObject(dc, previous)
            if bitmap:
                self.gdi.DeleteObject(bitmap)
            if dc:
                self.gdi.DeleteDC(dc)
            if screen:
                self.user.ReleaseDC(None, screen)

    def hide(self):
        if self.hwnd:
            self.user.ShowWindow(self.hwnd, 0)

    def close(self):
        if self.hwnd:
            if not self.user.DestroyWindow(self.hwnd):
                raise ctypes.WinError(ctypes.get_last_error())
            self.hwnd = None


class ControlOverlay:
    def __init__(self, root, scale, on_error):
        self.root, self.scale, self.on_error = root, scale, on_error
        self.native = None
        self.pending = None
        self.current = None
        self.image = None
        self.xy = None

    def cancel_timer(self):
        if self.pending is not None:
            self.root.after_cancel(self.pending)
            self.pending = None

    def show(self, feedback, accent, style="pill", detail="standard"):
        if style not in config.OVERLAY_STYLES:
            raise ValueError(f"Invalid overlay style: {style}")
        if detail not in config.OVERLAY_DETAILS:
            raise ValueError(f"Invalid overlay detail: {detail}")
        self.cancel_timer()
        self.current = (feedback, accent, style, detail)
        try:
            if self.native is None:
                self.native = NativeWindow()
            self.image = (paint_notch if style == "notch" else paint)(
                feedback, self.scale, accent, detail)
            bounds = self.native.monitor_area() if style == "notch" else self.native.work_area()
            self.xy = position(bounds, self.image.width, self.image.height,
                               round(TASKBAR_GAP * self.scale), style)
            self.native.display(self.image, self.xy)
            self.pending = self.root.after(HOLD_MS, self.fade)
        except OSError as exc:
            self.hide()
            self.on_error(f"Control overlay failed: {exc}")

    def refresh_theme(self):
        if self.current is not None:
            self.show(*self.current)

    def fade(self, step=0):
        self.pending = None
        try:
            if step == 0 and not self.native.animations_enabled():
                self.hide()
            elif step >= FADE_STEPS:
                self.hide()
            else:
                self.native.display(self.image, self.xy,
                                    round(255 * (1 - (step + 1) / (FADE_STEPS + 1))))
                self.pending = self.root.after(FADE_MS, lambda: self.fade(step + 1))
        except OSError as exc:
            self.hide()
            self.on_error(f"Control overlay failed: {exc}")

    def hide(self):
        self.cancel_timer()
        self.current = None
        if self.native:
            self.native.hide()

    def close(self):
        self.hide()
        if self.native:
            self.native.close()
