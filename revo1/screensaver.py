"""The screensaver library: pictures and short clips converted into round
360x360 JPEG frames on the PC, and packed into the layout the firmware reads
from its "media" flash partition.

Packed layout (little endian):
    header, 4096 bytes: magic "RVM1", version 1, item count, data bytes,
        CRC-32 of the data, 3 reserved words, then one 16-byte entry per item:
        offset (from the start of the data), bytes, frames (u16),
        frame_ms (u16), reserved.
    data: each item's frames as [u32 length][JPEG][padding to 4 bytes].
"""

import io
import json
import os
import shutil
import struct
import subprocess
import uuid
import zipfile
import zlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps, ImageSequence

SIZE = 360
MAGIC = 0x314D5652
HEADER_BYTES = 4096
MAX_ITEMS = 250
MAX_FRAME_BYTES = 256 * 1024
# The firmware's media partition minus its header; the knob reports its own.
DEFAULT_CAPACITY = 0xCF0000 - HEADER_BYTES
IMAGE_QUALITY = 85
VIDEO_QUALITY = 70
VIDEO_FPS = 10
MAX_CLIP_SECONDS = 20
THUMB_SIZE = 96

# Pictures that come with Revo1, already centred on the round screen. Each is
# offered once: a new library starts with them, and one that is removed stays
# removed.
STARTER_PICTURES = (("Moon", Path(__file__).with_name("assets") / "moon.jpg"),)

IMAGE_TYPES = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif", ".tif", ".tiff")
VIDEO_TYPES = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".wmv")
FILE_TYPES = [("Pictures and videos", " ".join(f"*{ext}" for ext in IMAGE_TYPES + VIDEO_TYPES)),
              ("Pictures", " ".join(f"*{ext}" for ext in IMAGE_TYPES)),
              ("Videos", " ".join(f"*{ext}" for ext in VIDEO_TYPES))]


# FFmpeg reads the videos. It runs as a separate program, downloaded on
# demand (like esptool), instead of being linked into Revo1. This is the LGPL
# x64 build from https://github.com/BtbN/FFmpeg-Builds; Windows on ARM runs it
# under emulation (their ARM64 build crashed on start in testing).
FFMPEG_VERSION = "8.1"
FFMPEG_URL = ("https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
              f"ffmpeg-n{FFMPEG_VERSION}-latest-win64-lgpl-shared-{FFMPEG_VERSION}.zip")
FFMPEG_DOWNLOAD_MB = 80


class MediaError(Exception):
    pass


def _ffmpeg_folder():
    return Path(os.environ["LOCALAPPDATA"]) / "Revo1" / "tools" / f"ffmpeg-{FFMPEG_VERSION}"


def find_ffmpeg():
    """ffmpeg.exe from PATH or from an earlier download, or None."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    folder = _ffmpeg_folder()
    found = next(folder.rglob("ffmpeg.exe"), None) if folder.exists() else None
    return str(found) if found else None


def ensure_ffmpeg(progress=None):
    """The path of ffmpeg.exe, downloading it into
    %LOCALAPPDATA%\\Revo1\\tools the first time; progress(fraction)."""
    found = find_ffmpeg()
    if found:
        return found
    from revo1 import updater
    folder = _ffmpeg_folder()
    try:
        archive = updater.download(FFMPEG_URL, folder.parent / f"{folder.name}.zip", progress)
    except updater.UpdateError as exc:
        raise MediaError(f"Could not download the video converter: {exc}") from exc
    try:
        with zipfile.ZipFile(archive) as zipped:
            # Only the programs and their DLLs; the headers and docs aren't needed.
            members = [name for name in zipped.namelist() if "/bin/" in name]
            zipped.extractall(folder, members)
    except (zipfile.BadZipFile, OSError) as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise MediaError(f"Could not unpack the video converter: {exc}") from exc
    finally:
        archive.unlink(missing_ok=True)
    found = find_ffmpeg()
    if not found:
        raise MediaError("ffmpeg.exe is missing from the download")
    return found


def is_video(path):
    return Path(path).suffix.lower() in VIDEO_TYPES


def library_folder():
    return Path(os.environ["LOCALAPPDATA"]) / "Revo1" / "screensaver"


def _round_mask():
    mask = Image.new("L", (SIZE * 4, SIZE * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, SIZE * 4 - 1, SIZE * 4 - 1), fill=255)
    return mask.resize((SIZE, SIZE), Image.LANCZOS)


_MASK = None


def fit_round(image):
    """Cover-crops to the round screen, black outside the circle."""
    global _MASK
    if _MASK is None:
        _MASK = _round_mask()
    frame = ImageOps.fit(image.convert("RGB"), (SIZE, SIZE), Image.LANCZOS)
    black = Image.new("RGB", (SIZE, SIZE), (0, 0, 0))
    return Image.composite(frame, black, _MASK)


def encode_jpeg(frame, quality):
    """Baseline JPEG: the device's decoder cannot read progressive files."""
    buffer = io.BytesIO()
    frame.save(buffer, "JPEG", quality=quality, progressive=False, optimize=True)
    data = buffer.getvalue()
    if len(data) > MAX_FRAME_BYTES:
        raise MediaError("A frame is too large for the knob")
    return data


def pack_frames(frames):
    """[u32 length][JPEG][padding] for each frame."""
    return b"".join(struct.pack("<I", len(frame)) + frame + b"\0" * (-len(frame) % 4)
                    for frame in frames)


def _still_frames(image):
    return [encode_jpeg(fit_round(ImageOps.exif_transpose(image)), IMAGE_QUALITY)], 0


def _animated_frames(image):
    """GIF/WebP animations, resampled to at most VIDEO_FPS."""
    step_ms = 1000 // VIDEO_FPS
    frames = []
    clock = 0
    next_at = 0
    for frame in ImageSequence.Iterator(image):
        duration = max(20, int(frame.info.get("duration", 100) or 100))
        if clock >= next_at:
            frames.append(encode_jpeg(fit_round(frame), VIDEO_QUALITY))
            next_at = clock + step_ms
        clock += duration
        if clock >= MAX_CLIP_SECONDS * 1000:
            break
    frame_ms = max(step_ms, clock // max(len(frames), 1))
    return frames, min(frame_ms, 5000)


def ffmpeg_command(ffmpeg, path):
    """Decodes the first MAX_CLIP_SECONDS at VIDEO_FPS, cover-cropped to a
    SIZE x SIZE square, as raw RGB frames on stdout."""
    return [ffmpeg, "-v", "error", "-nostdin", "-i", str(path), "-t", str(MAX_CLIP_SECONDS),
            "-an", "-sn", "-vf",
            f"fps={VIDEO_FPS},scale={SIZE}:{SIZE}:force_original_aspect_ratio=increase,"
            f"crop={SIZE}:{SIZE}",
            "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]


def _video_frames(path, ffmpeg=None):
    ffmpeg = ffmpeg or find_ffmpeg()
    if not ffmpeg:
        raise MediaError("The video converter (FFmpeg) is not installed")
    frame_bytes = SIZE * SIZE * 3
    frames = []
    try:
        process = subprocess.Popen(ffmpeg_command(ffmpeg, path), stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as exc:
        raise MediaError(f"Could not start the video converter: {exc}") from exc
    try:
        while True:
            raw = process.stdout.read(frame_bytes)
            if len(raw) < frame_bytes:
                break
            frame = Image.frombytes("RGB", (SIZE, SIZE), raw)
            frames.append(encode_jpeg(fit_round(frame), VIDEO_QUALITY))
        error = process.stderr.read().decode(errors="replace").strip()
        process.wait()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    if not frames:
        detail = error.splitlines()[-1] if error else "no frames"
        raise MediaError(f"Could not read the video: {detail}")
    return frames, 1000 // VIDEO_FPS


def convert(path):
    """Converts a picture or clip into (frames, frame_ms); stills have one
    frame and frame_ms 0."""
    path = Path(path)
    if is_video(path):
        return _video_frames(path)
    try:
        with Image.open(path) as image:
            if getattr(image, "n_frames", 1) > 1:
                frames, frame_ms = _animated_frames(image)
            else:
                frames, frame_ms = _still_frames(image)
    except MediaError:
        raise
    except Exception as exc:
        raise MediaError(f"Could not read the picture: {exc}") from exc
    if len(frames) == 1:
        frame_ms = 0
    return frames, frame_ms


def pack_library(items):
    """items: [(frames_blob, frame_count, frame_ms)] -> the bytes to upload."""
    if not items:
        raise MediaError("The screensaver has no pictures")
    if len(items) > MAX_ITEMS:
        raise MediaError(f"The knob holds at most {MAX_ITEMS} items")
    data = bytearray()
    entries = []
    for blob, frame_count, frame_ms in items:
        entries.append(struct.pack("<IIHHI", len(data), len(blob), frame_count,
                                   frame_ms, 0))
        data += blob
    header = struct.pack("<8I", MAGIC, 1, len(items), len(data),
                         zlib.crc32(data), 0, 0, 0) + b"".join(entries)
    return header + b"\0" * (HEADER_BYTES - len(header)) + bytes(data)


class Library:
    """The pictures chosen on the PC, kept converted and ready to upload."""

    def __init__(self, folder=None, starters=()):
        self.folder = Path(folder) if folder else library_folder()
        self.items = []
        self._load()
        self._add_starters(starters)

    @property
    def _index(self):
        return self.folder / "library.json"

    def _add_starters(self, starters):
        """Adds each built-in picture the first time this library sees it."""
        record = self.folder / "starters.json"
        try:
            offered = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            offered = []
        if not isinstance(offered, list):
            offered = []
        added = False
        for name, path in starters:
            if name in offered:
                continue
            try:
                self.add(path, name=name)
            except (MediaError, OSError):
                continue
            offered.append(name)
            added = True
        if added:
            record.write_text(json.dumps(offered), encoding="utf-8")

    def _load(self):
        try:
            data = json.loads(self._index.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, list):
            return
        for item in data:
            if (isinstance(item, dict) and isinstance(item.get("id"), str)
                    and (self.folder / f"{item['id']}.bin").exists()):
                self.items.append(item)

    def _save(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        temporary = self._index.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.items, indent=2), encoding="utf-8")
        os.replace(temporary, self._index)

    def total_bytes(self):
        return sum(item["bytes"] for item in self.items)

    def packed_size(self):
        return HEADER_BYTES + self.total_bytes()

    def add(self, path, capacity=DEFAULT_CAPACITY, name=None):
        """Converts `path` and keeps it; raises MediaError if it cannot be
        read or would not fit in `capacity` bytes on the knob."""
        if len(self.items) >= MAX_ITEMS:
            raise MediaError(f"The knob holds at most {MAX_ITEMS} items")
        path = Path(path)
        frames, frame_ms = convert(path)
        blob = pack_frames(frames)
        if self.total_bytes() + len(blob) > capacity:
            raise MediaError("Not enough room left on the knob")
        item_id = uuid.uuid4().hex[:12]
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / f"{item_id}.bin").write_bytes(blob)
        with Image.open(io.BytesIO(frames[0])) as first:
            thumb = first.resize((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
            thumb.save(self.folder / f"{item_id}.png")
        item = {"id": item_id, "name": name or path.name, "frames": len(frames),
                "frame_ms": frame_ms, "bytes": len(blob)}
        self.items.append(item)
        self._save()
        return item

    def remove(self, item_id):
        self.items = [item for item in self.items if item["id"] != item_id]
        for suffix in (".bin", ".png"):
            try:
                (self.folder / f"{item_id}{suffix}").unlink()
            except OSError:
                pass
        self._save()

    def thumbnail(self, item_id):
        return self.folder / f"{item_id}.png"

    def first_frame(self, item_id):
        """The first 360x360 JPEG of an item, as it is shown on the knob."""
        with open(self.folder / f"{item_id}.bin", "rb") as blob:
            length = struct.unpack("<I", blob.read(4))[0]
            return blob.read(length)

    def pack(self):
        return pack_library([((self.folder / f"{item['id']}.bin").read_bytes(),
                              item["frames"], item["frame_ms"]) for item in self.items])

    def checksum(self):
        """CRC-32 of the data, as the knob reports it after an upload."""
        crc = 0
        for item in self.items:
            crc = zlib.crc32((self.folder / f"{item['id']}.bin").read_bytes(), crc)
        return crc
