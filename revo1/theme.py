"""Companion-window palettes; device artwork keeps its own colours."""

import logging
import sys

CHOICES = ("light", "dark", "system")
LABELS = {"light": "Light", "dark": "Dark", "system": "System"}
LIGHT = {
    "MAIN_BG": "#EAE9EC", "SIDEBAR_BG": "#DEDDE2",
    "CARD_BG": "#F6F5F8", "CARD_EDGE": "#D3D2D8",
    "HOVER_BG": "#E6E5EA", "CARD_HOVER": "#FFFFFF", "FIELD_BG": "#FFFFFF",
    "INK": "#2A2A34", "SUBTLE_INK": "#55556A", "MUTED_INK": "#606070",
    "OK_GREEN": "#1C6E46", "IDLE_GREY": "#A9A8B2",
    "SELECT_BG": "#2A2A34", "SELECT_INK": "#FFFFFF", "SELECT_SUBTLE": "#C8C8D2",
    "SWITCH_KNOB": "#FFFFFF", "ERROR_INK": "#B52D35", "WARNING_INK": "#B54708",
}
DARK = {
    "MAIN_BG": "#1B1B22", "SIDEBAR_BG": "#15151B",
    "CARD_BG": "#25252F", "CARD_EDGE": "#454552",
    "HOVER_BG": "#30303D", "CARD_HOVER": "#30303D", "FIELD_BG": "#22222C",
    "INK": "#F1F0F5", "SUBTLE_INK": "#C4C3D0", "MUTED_INK": "#AAA9BA",
    "OK_GREEN": "#69D49A", "IDLE_GREY": "#606070",
    "SELECT_BG": "#DAD8E8", "SELECT_INK": "#20202A", "SELECT_SUBTLE": "#494858",
    "SWITCH_KNOB": "#20202A", "ERROR_INK": "#FF858A", "WARNING_INK": "#FFC58A",
}


def system_theme():
    if sys.platform != "win32":
        return "light"
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            light, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
    except FileNotFoundError:
        # Windows versions without an app-theme preference use light.
        return "light"
    except OSError:
        logging.exception("Could not read the Windows app theme")
        return "light"
    return "light" if light else "dark"


def resolve(choice):
    if choice not in CHOICES:
        raise ValueError(f"Unknown app theme: {choice}")
    return system_theme() if choice == "system" else choice


def title_bar(window, dark):
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes
    window.update_idletasks()
    user32 = ctypes.windll.user32
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    hwnd = user32.GetParent(window.winfo_id())
    dwm = ctypes.windll.dwmapi.DwmSetWindowAttribute
    dwm.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    dwm.restype = ctypes.c_long
    value = ctypes.c_int(bool(dark))
    result = dwm(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
    if result:
        logging.warning("Windows could not theme the title bar (HRESULT %#x)", result & 0xFFFFFFFF)
