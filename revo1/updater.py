"""Finds the newest release on GitHub and writes its firmware to the knob."""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path

from revo1 import __version__

REPOSITORY = "guilhermelimait/Revo1"
PROJECT_URL = f"https://github.com/{REPOSITORY}"
RELEASES_URL = f"{PROJECT_URL}/releases"
KOFI_URL = "https://ko-fi.com/guilhermelimait"
LATEST_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
FIRMWARE_ASSET = re.compile(r"^revo1-firmware-.*\.bin$", re.IGNORECASE)
# Espressif's standalone build: esptool is GPL-2.0, so it runs as a separate
# program downloaded on demand rather than being bundled into Revo1.
ESPTOOL_VERSION = "v5.4.0"
ESPTOOL_URL = ("https://github.com/espressif/esptool/releases/download/"
               f"{ESPTOOL_VERSION}/esptool-{ESPTOOL_VERSION}-windows-amd64.zip")
TIMEOUT = 15
USER_AGENT = f"Revo1/{__version__}"
PROGRESS = re.compile(rb"(\d{1,3}(?:\.\d+)?)\s*%")


class UpdateError(Exception):
    pass


def parse_version(text):
    """"v1.2.3" -> (1, 2, 3); None when it isn't a version number."""
    match = re.fullmatch(r"v?(\d+)\.(\d+)(?:\.(\d+))?", (text or "").strip(), re.IGNORECASE)
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())


def is_newer(candidate, current):
    """True when `candidate` is a later version than `current`. An unknown
    `current` (e.g. firmware too old to report one) counts as older."""
    candidate = parse_version(candidate)
    if candidate is None:
        return False
    current = parse_version(current)
    return current is None or candidate > current


def data_dir():
    return Path(os.environ["LOCALAPPDATA"]) / "Revo1"


def _open(url):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(request, timeout=TIMEOUT)


def latest_release():
    """The newest published release, or None when there isn't one yet."""
    try:
        with _open(LATEST_API) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise UpdateError(f"GitHub answered {exc.code}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        raise UpdateError(f"no connection ({reason})") from exc
    tag = str(data.get("tag_name") or "")
    published = None
    if data.get("published_at"):
        try:
            published = datetime.strptime(data["published_at"], "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass
    firmware = next((asset for asset in data.get("assets") or []
                     if FIRMWARE_ASSET.match(str(asset.get("name") or ""))), None)
    return {"tag": tag,
            "version": tag.lstrip("vV"),
            "published": published,
            "url": data.get("html_url") or RELEASES_URL,
            "firmware_name": firmware["name"] if firmware else None,
            "firmware_url": firmware.get("browser_download_url") if firmware else None,
            "firmware_size": firmware.get("size") if firmware else None}


def download(url, destination, progress=None):
    """Downloads `url` to `destination` atomically; progress(fraction)."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    try:
        with _open(url) as response, open(partial, "wb") as file:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                file.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(done / total)
        os.replace(partial, destination)
    except (urllib.error.URLError, OSError) as exc:
        raise UpdateError(f"download failed ({getattr(exc, 'reason', exc)})") from exc
    finally:
        if partial.exists():
            partial.unlink()
    return destination


def esptool_command(progress=None):
    """A command line that runs esptool: the Python module when this is a
    source install that has it, otherwise Espressif's standalone esptool.exe,
    downloaded once into %LOCALAPPDATA%\\Revo1\\tools."""
    if not getattr(sys, "frozen", False):
        if importlib.util.find_spec("esptool"):
            return [sys.executable, "-m", "esptool"]
    tools = data_dir() / "tools" / f"esptool-{ESPTOOL_VERSION}"
    found = next(tools.rglob("esptool.exe"), None) if tools.exists() else None
    if found:
        return [str(found)]
    archive = download(ESPTOOL_URL, data_dir() / "tools" / f"esptool-{ESPTOOL_VERSION}.zip",
                       progress)
    try:
        with zipfile.ZipFile(archive) as zipped:
            zipped.extractall(tools)
    except (zipfile.BadZipFile, OSError) as exc:
        shutil.rmtree(tools, ignore_errors=True)
        raise UpdateError(f"could not unpack esptool ({exc})") from exc
    finally:
        archive.unlink(missing_ok=True)
    found = next(tools.rglob("esptool.exe"), None)
    if not found:
        raise UpdateError("esptool.exe is missing from the download")
    return [str(found)]


IMAGE_MAGIC = 0xE9
APP_OFFSET = 0x10000
FLASH_SIZE = 16 * 1024 * 1024
FIRMWARE_MARKERS = (b"HELLO,REVO1,1", b"HELLO,ROUNDSCREEN,1")


def check_image(path):
    """Refuses anything but a merged Revo1 image (bootloader at 0x0, app at
    0x10000), so a wrong file can't be written over the knob's flash."""
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise UpdateError(f"can't read the file ({exc.strerror or exc})") from exc
    if not APP_OFFSET < len(data) <= FLASH_SIZE:
        raise UpdateError("that file is not a Revo1 firmware image (wrong size)")
    if data[0] != IMAGE_MAGIC or data[APP_OFFSET] != IMAGE_MAGIC:
        raise UpdateError("that file is not a merged ESP32-S3 image; "
                          "use the revo1-firmware-x.y.z.bin from a release")
    if not any(marker in data for marker in FIRMWARE_MARKERS):
        raise UpdateError("that image is not Revo1 firmware")
    match = re.search(r"(\d+\.\d+\.\d+)", Path(path).name)
    return match.group(1) if match else None


def flash(command, port, image, progress=None):
    """Writes a merged firmware image at 0x0 and resets the knob."""
    arguments = command + ["--chip", "esp32s3", "--port", port, "--baud", "921600",
                           "write-flash", "0x0", str(image)]
    try:
        process = subprocess.Popen(arguments, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT,
                                   env=dict(os.environ, PYTHONUNBUFFERED="1"),
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as exc:
        raise UpdateError(f"could not start esptool ({exc})") from exc
    output = bytearray()
    with process.stdout:
        while True:
            chunk = process.stdout.read1(256)
            if not chunk:
                break
            output += chunk
            matches = PROGRESS.findall(chunk)
            if progress and matches:
                progress(min(float(matches[-1]), 100.0) / 100)
    if process.wait() != 0:
        lines = [line for line in output.decode("utf-8", "replace").splitlines()
                 if line.strip()]
        detail = lines[-1].strip() if lines else f"exit code {process.returncode}"
        raise UpdateError(f"esptool failed: {detail[:160]}")
