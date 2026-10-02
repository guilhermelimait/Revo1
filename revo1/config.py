import json
import os
import string
from pathlib import Path
from tempfile import NamedTemporaryFile


MODES = ("Volume", "Scroll", "Brightness", "Mic", "Zoom", "Media", "Pomodoro", "Games")
# The screens before Games existed. A file written then lists only these as
# known, so screens added since start switched on rather than missing.
LEGACY_SCREENS = MODES[:7]
ORIENTATIONS = (0, 90, 180, 270)
DEFAULT_NAME = "Revo1"
# "standard" gives each control its own colour; otherwise one "#RRGGBB" for all.
STANDARD_ACCENT = "standard"
NUMBER_SIZES = (24, 32, 40, 48)
DEFAULTS = {"mode": "Volume", "orientation": 0, "port": "", "name": DEFAULT_NAME,
            "accent": STANDARD_ACCENT, "number_size": 32, "minimize_to_tray": False,
            "invert_scroll": False, "invert_zoom": False, "swipe_screens": True,
            "screens": list(MODES), "known_screens": list(MODES), "backlight": 100,
            "focus_minutes": 25, "break_minutes": 5,
            "saver_enabled": False, "saver_idle": 5, "saver_interval": 30,
            "saver_show": "pictures", "clock_format": "24h", "saver_ring": "dots",
            "clock_ink": "#F2F2F5", "clock_face": "#000000", "clock_shade": True,
            "dim_idle": True, "wireless": True, "link_key": "", "wifi_ssid": "",
            "knob_ip": "", "knob_ble": ""}
FLAGS = ("minimize_to_tray", "invert_scroll", "invert_zoom", "swipe_screens",
         "saver_enabled", "dim_idle", "wireless", "clock_shade")
# The wireless pairing: the key (protected with Windows DPAPI, see
# secure.protect_key), the network the knob joins, and where it was last seen.
# The Wi-Fi password is only ever sent to the knob, never stored here.
WIRELESS_TEXT = ("link_key", "wifi_ssid", "knob_ip", "knob_ble")
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
RING_STYLES = ("dots", "bar", "wave", "ticks", "comet", "none")
# The screensaver clock's colours ("#RRGGBB"): the time, and the face behind
# it when only the date and time show.
CLOCK_COLOURS = ("clock_ink", "clock_face")
POMODORO_MINUTES = range(1, 181)
BACKLIGHT_RANGE = range(5, 101)


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
    mode = data.get("mode", "Volume")
    orientation = data.get("orientation", 0)
    port = data.get("port", "")
    name = data.get("name", DEFAULT_NAME)
    accent = data.get("accent", STANDARD_ACCENT)
    number_size = data.get("number_size", 32)
    flags = {key: data.get(key, DEFAULTS[key]) for key in FLAGS}
    screens = data.get("screens", list(MODES))
    known = data.get("known_screens", list(LEGACY_SCREENS))
    saver_show = data.get("saver_show", DEFAULTS["saver_show"])
    clock_format = data.get("clock_format", DEFAULTS["clock_format"])
    saver_ring = data.get("saver_ring", DEFAULTS["saver_ring"])
    wireless = {key: data.get(key, DEFAULTS[key]) for key in WIRELESS_TEXT}
    colours = {key: data.get(key, DEFAULTS[key]) for key in CLOCK_COLOURS}
    numbers = {key: data.get(key, DEFAULTS[key])
               for key in ("backlight", "focus_minutes", "break_minutes",
                           "saver_idle", "saver_interval")}
    if (mode not in MODES or orientation not in ORIENTATIONS or not isinstance(port, str)
            or not isinstance(name, str) or not valid_accent(accent)
            or number_size not in NUMBER_SIZES
            or not all(isinstance(flag, bool) for flag in flags.values())
            or not valid_screens(screens)
            or not all(isinstance(value, str) for value in wireless.values())
            or not isinstance(known, list)
            or not all(isinstance(item, str) for item in known)
            or saver_show not in SAVER_SHOW_CHOICES
            or clock_format not in CLOCK_FORMATS
            or saver_ring not in RING_STYLES
            or not all(valid_colour(value) for value in colours.values())
            or not all(type(value) is int for value in numbers.values())
            or numbers["backlight"] not in BACKLIGHT_RANGE
            or numbers["focus_minutes"] not in POMODORO_MINUTES
            or numbers["break_minutes"] not in POMODORO_MINUTES
            or numbers["saver_idle"] not in SAVER_IDLE_CHOICES
            or numbers["saver_interval"] not in SAVER_INTERVAL_CHOICES):
        raise ValueError(f"Invalid settings in {path}")
    # Keep the menu order fixed whatever order the file lists them in.
    screens = [candidate for candidate in MODES
               if candidate in screens or candidate not in known]
    if mode not in screens:
        mode = screens[0]
    return {"mode": mode, "orientation": orientation, "port": port,
            "name": name.strip() or DEFAULT_NAME,
            "accent": accent if accent == STANDARD_ACCENT else accent.upper(),
            "number_size": number_size, "screens": screens,
            "known_screens": list(MODES), "saver_show": saver_show,
            "clock_format": clock_format, "saver_ring": saver_ring,
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
