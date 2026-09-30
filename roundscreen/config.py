import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


MODES = ("Volume", "Scroll", "Brightness", "Mic", "Zoom", "Media")
ORIENTATIONS = (0, 90, 180, 270)
DEFAULT_NAME = "RoundScreen"
# "standard" gives each control its own colour; otherwise one "#RRGGBB" for all.
STANDARD_ACCENT = "standard"
NUMBER_SIZES = (24, 32, 40, 48)
DEFAULTS = {"mode": "Volume", "orientation": 0, "port": "", "name": DEFAULT_NAME,
            "accent": STANDARD_ACCENT, "number_size": 32}


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
    return Path(os.environ["LOCALAPPDATA"]) / "RoundScreen" / "settings.json"


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
    if (mode not in MODES or orientation not in ORIENTATIONS or not isinstance(port, str)
            or not isinstance(name, str) or not valid_accent(accent)
            or number_size not in NUMBER_SIZES):
        raise ValueError(f"Invalid settings in {path}")
    return {"mode": mode, "orientation": orientation, "port": port,
            "name": name.strip() or DEFAULT_NAME,
            "accent": accent if accent == STANDARD_ACCENT else accent.upper(),
            "number_size": number_size}


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
