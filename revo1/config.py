import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


MODES = ("Volume", "Scroll", "Brightness", "Mic", "Zoom", "Media", "Pomodoro")
ORIENTATIONS = (0, 90, 180, 270)
DEFAULT_NAME = "Revo1"
# "standard" gives each control its own colour; otherwise one "#RRGGBB" for all.
STANDARD_ACCENT = "standard"
NUMBER_SIZES = (24, 32, 40, 48)
DEFAULTS = {"mode": "Volume", "orientation": 0, "port": "", "name": DEFAULT_NAME,
            "accent": STANDARD_ACCENT, "number_size": 32, "minimize_to_tray": False,
            "invert_scroll": False, "invert_zoom": False, "swipe_screens": True,
            "screens": list(MODES), "backlight": 100,
            "focus_minutes": 25, "break_minutes": 5,
            "saver_enabled": False, "saver_idle": 5, "saver_interval": 30,
            "saver_show": "pictures", "dim_idle": True}
FLAGS = ("minimize_to_tray", "invert_scroll", "invert_zoom", "swipe_screens",
         "saver_enabled", "dim_idle")
# Screensaver: minutes without touching the knob, and seconds per picture.
SAVER_IDLE_CHOICES = (1, 2, 5, 10, 30)
SAVER_INTERVAL_CHOICES = (10, 30, 60, 300)
# What the screensaver shows: the stored pictures, or the date and time.
SAVER_SHOW_CHOICES = ("pictures", "clock")
POMODORO_MINUTES = range(1, 181)
BACKLIGHT_RANGE = range(5, 101)


def screen_mask(screens):
    """The bit mask the firmware uses for a list of enabled mode names."""
    return sum(1 << MODES.index(mode) for mode in screens if mode in MODES)


def valid_screens(value):
    return (isinstance(value, list) and value and len(set(value)) == len(value)
            and all(mode in MODES for mode in value))


def valid_accent(value):
    if value == STANDARD_ACCENT:
        return True
    if not isinstance(value, str) or len(value) != 7 or value[0] != "#":
        return False
    try:
        int(value[1:], 16)
    except ValueError:
        return False
    return True


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
    saver_show = data.get("saver_show", DEFAULTS["saver_show"])
    numbers = {key: data.get(key, DEFAULTS[key])
               for key in ("backlight", "focus_minutes", "break_minutes",
                           "saver_idle", "saver_interval")}
    if (mode not in MODES or orientation not in ORIENTATIONS or not isinstance(port, str)
            or not isinstance(name, str) or not valid_accent(accent)
            or number_size not in NUMBER_SIZES
            or not all(isinstance(flag, bool) for flag in flags.values())
            or not valid_screens(screens)
            or saver_show not in SAVER_SHOW_CHOICES
            or not all(type(value) is int for value in numbers.values())
            or numbers["backlight"] not in BACKLIGHT_RANGE
            or numbers["focus_minutes"] not in POMODORO_MINUTES
            or numbers["break_minutes"] not in POMODORO_MINUTES
            or numbers["saver_idle"] not in SAVER_IDLE_CHOICES
            or numbers["saver_interval"] not in SAVER_INTERVAL_CHOICES):
        raise ValueError(f"Invalid settings in {path}")
    # Keep the menu order fixed whatever order the file lists them in.
    screens = [candidate for candidate in MODES if candidate in screens]
    if mode not in screens:
        mode = screens[0]
    return {"mode": mode, "orientation": orientation, "port": port,
            "name": name.strip() or DEFAULT_NAME,
            "accent": accent if accent == STANDARD_ACCENT else accent.upper(),
            "number_size": number_size, "screens": screens, "saver_show": saver_show,
            **numbers, **flags}


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
