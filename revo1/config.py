import json
import os
import string
from pathlib import Path
from tempfile import NamedTemporaryFile
from revo1.launcher import valid_slots
from revo1.theme import CHOICES as THEME_CHOICES


MODES = ("Volume", "Scroll", "Brightness", "Mic", "Zoom", "Media", "Pomodoro", "Games", "Launcher")
# Names shown to the user where they differ from the saved and protocol name.
TITLES = {"Mic": "Microphone", "Launcher": "App launcher"}


def title(mode):
    return TITLES.get(mode, mode)
# The screens before Games existed. A file written then lists only these as
# known, so screens added since start switched on rather than missing.
LEGACY_SCREENS = MODES[:7]
ORIENTATIONS = (0, 90, 180, 270)
DEFAULT_NAME = "Revo1"
# "standard" gives each control its own colour; otherwise one "#RRGGBB" for all.
STANDARD_ACCENT = "standard"
NUMBER_SIZES = (24, 32, 40, 48)
# How a level ring is coloured along its length; the order is the number sent
# to the knob.
BAR_STYLES = ("glow", "fade", "soft", "solid")
OVERLAY_STYLES = ("pill", "notch")
OVERLAY_DETAILS = ("standard", "minimal")
OVERLAY_MODES = MODES
DEFAULTS = {"mode": "Volume", "orientation": 0, "port": "", "name": DEFAULT_NAME, "theme": "light",
            "accent": STANDARD_ACCENT, "bar_style": "glow", "number_size": 32, "minimize_to_tray": False,
            "invert_scroll": False, "invert_zoom": False, "swipe_screens": True, "control_overlay": True,
            "overlay_style": "pill", "overlay_detail": "standard", "overlay_modes": list(OVERLAY_MODES),
            "screens": list(MODES), "known_screens": list(MODES), "backlight": 100,
            "focus_minutes": 25, "break_minutes": 5,
            "saver_enabled": False, "saver_idle": 5, "saver_interval": 30,
            "saver_show": "pictures", "clock_format": "24h", "saver_ring": "dots",
            "clock_ink": "#F2F2F5", "clock_face": "#000000", "clock_shade": True,
            "dim_idle": True, "battery_saver": False, "bluetooth_enabled": True, "link_key": "", "knob_ble": "",
            "whack_best": 0, "whack_last": -1, "launcher": [None] * 7}
FLAGS = ("minimize_to_tray", "invert_scroll", "invert_zoom", "swipe_screens",
         "saver_enabled", "dim_idle", "clock_shade", "battery_saver", "control_overlay",
         "bluetooth_enabled")
# The wireless pairing: the key (protected with Windows DPAPI, see
# secure.protect_key) and the knob's last known Bluetooth address.
WIRELESS_TEXT = ("link_key", "knob_ble")
# Screensaver: minutes without touching the knob, and seconds per picture.
SAVER_IDLE_CHOICES = (1, 2, 5, 10, 30)
SAVER_INTERVAL_CHOICES = (10, 30, 60, 180, 300)
# What the screensaver shows: the stored pictures, the date and time, or the
# time over the pictures. The order is the number sent to the knob.
SAVER_SHOW_CHOICES = ("pictures", "clock", "both")
# The screensaver clock: 24-hour first (and the default), then AM/PM.
CLOCK_FORMATS = ("24h", "12h")
# The seconds ring around the screensaver clock; the order is the number sent
# to the knob.
# New styles go on the end: the knob stores and receives the position.
RING_STYLES = ("dots", "bar", "wave", "ticks", "comet", "none",
               "walker", "snake", "sparkle", "orbit", "pulse")
# The screensaver clock's colours ("#RRGGBB"): the time, and the face behind
# it when only the date and time show.
CLOCK_COLOURS = ("clock_ink", "clock_face")
POMODORO_MINUTES = range(1, 181)
BACKLIGHT_RANGE = range(5, 101)
# Whack-a-Mole scores, as the knob reports them; -1 is "no round played yet".
SCORE_RANGE = range(0, 0x10000)


def screen_mask(screens):
    """The bit mask the firmware uses for a list of enabled mode names."""
    return sum(1 << MODES.index(mode) for mode in screens if mode in MODES)


def valid_screens(value):
    return (isinstance(value, list) and value and len(set(value)) == len(value)
            and all(mode in MODES for mode in value))


def valid_accent(value):
    return value == STANDARD_ACCENT or valid_colour(value)


def valid_colour(value):
    return (isinstance(value, str) and len(value) == 7 and value[0] == "#"
            and all(digit in string.hexdigits for digit in value[1:]))


def config_path():
    return Path(os.environ["LOCALAPPDATA"]) / "Revo1" / "settings.json"


def load(path=None):
    path = Path(path) if path else config_path()
    if not path.exists():
        return dict(DEFAULTS)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Settings must be a JSON object")
    # A value this version doesn't accept (written by a newer or older Revo1,
    # or edited by hand) falls back to its default rather than stopping the
    # app, so the rest of the settings, the pairing included, are kept.
    def pick(key, valid):
        value = data.get(key, DEFAULTS[key])
        return value if valid(value) else DEFAULTS[key]

    def number_in(choices):
        return lambda value: type(value) is int and value in choices

    mode = pick("mode", lambda value: value in MODES)
    orientation = pick("orientation", number_in(ORIENTATIONS))
    port = pick("port", lambda value: isinstance(value, str))
    name = pick("name", lambda value: isinstance(value, str))
    accent = pick("accent", valid_accent)
    number_size = pick("number_size", number_in(NUMBER_SIZES))
    bar_style = pick("bar_style", lambda value: value in BAR_STYLES)
    theme = pick("theme", lambda value: value in THEME_CHOICES)
    overlay_style = pick("overlay_style", lambda value: value in OVERLAY_STYLES)
    overlay_detail = pick("overlay_detail", lambda value: value in OVERLAY_DETAILS)
    overlay_modes = pick("overlay_modes", lambda value: (
        isinstance(value, list) and all(isinstance(item, str) and item in OVERLAY_MODES
                                       for item in value)))
    overlay_modes = [candidate for candidate in OVERLAY_MODES if candidate in overlay_modes]
    flags = {key: pick(key, lambda value: isinstance(value, bool)) for key in FLAGS}
    screens = data.get("screens", list(MODES))
    if isinstance(screens, list):
        # Screens this version doesn't have are dropped; the rest are kept.
        screens = [item for item in dict.fromkeys(screens) if item in MODES]
    if not valid_screens(screens):
        screens = list(MODES)
    known = data.get("known_screens", list(LEGACY_SCREENS))
    if not isinstance(known, list) or not all(isinstance(item, str) for item in known):
        known = list(LEGACY_SCREENS)
    saver_show = pick("saver_show", lambda value: value in SAVER_SHOW_CHOICES)
    clock_format = pick("clock_format", lambda value: value in CLOCK_FORMATS)
    saver_ring = pick("saver_ring", lambda value: value in RING_STYLES)
    wireless = {key: pick(key, lambda value: isinstance(value, str)) for key in WIRELESS_TEXT}
    launcher_slots = pick("launcher", valid_slots)
    colours = {key: pick(key, valid_colour) for key in CLOCK_COLOURS}
    numbers = {"backlight": pick("backlight", number_in(BACKLIGHT_RANGE)),
               "focus_minutes": pick("focus_minutes", number_in(POMODORO_MINUTES)),
               "break_minutes": pick("break_minutes", number_in(POMODORO_MINUTES)),
               "saver_idle": pick("saver_idle", number_in(SAVER_IDLE_CHOICES)),
               "saver_interval": pick("saver_interval", number_in(SAVER_INTERVAL_CHOICES)),
               "whack_best": pick("whack_best", number_in(SCORE_RANGE)),
               "whack_last": pick("whack_last", number_in(range(-1, 0x10000)))}
    # Keep the menu order fixed whatever order the file lists them in.
    screens = [candidate for candidate in MODES
               if candidate in screens or candidate not in known]
    if mode not in screens:
        mode = screens[0]
    return {"mode": mode, "orientation": orientation, "port": port,
            "name": name.strip() or DEFAULT_NAME,
            "accent": accent if accent == STANDARD_ACCENT else accent.upper(),
            "bar_style": bar_style, "number_size": number_size, "screens": screens, "theme": theme,
            "overlay_style": overlay_style, "overlay_detail": overlay_detail, "overlay_modes": overlay_modes,
            "known_screens": list(MODES), "saver_show": saver_show,
            "clock_format": clock_format, "saver_ring": saver_ring,
            "launcher": launcher_slots,
            **{key: value.upper() for key, value in colours.items()},
            **numbers, **flags, **wireless}


def save(settings, path=None):
    path = Path(path) if path else config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                prefix=".settings-", suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            json.dump(settings, file, indent=2)
            file.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
