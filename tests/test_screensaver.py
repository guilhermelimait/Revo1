import io
import struct
import unittest
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from PIL import Image

from revo1 import screensaver


class ScreensaverTests(unittest.TestCase):
    def test_pictures_become_round_baseline_frames(self):
        with TemporaryDirectory() as folder:
            source = Path(folder) / "wide.png"
            Image.new("RGB", (800, 400), (255, 0, 0)).save(source)
            frames, frame_ms = screensaver.convert(source)
            self.assertEqual((len(frames), frame_ms), (1, 0))
            with Image.open(io.BytesIO(frames[0])) as frame:
                self.assertEqual(frame.size, (360, 360))
                self.assertFalse(frame.info.get("progressive"))
                self.assertLess(sum(frame.getpixel((2, 2))), 30)
                self.assertGreater(frame.getpixel((180, 180))[0], 200)

    def test_animations_keep_their_frames(self):
        with TemporaryDirectory() as folder:
            source = Path(folder) / "blink.gif"
            frames = [Image.new("RGB", (100, 100), colour) for colour in ("red", "blue", "lime")]
            frames[0].save(source, save_all=True, append_images=frames[1:], duration=200, loop=0)
            converted, frame_ms = screensaver.convert(source)
            self.assertEqual(len(converted), 3)
            self.assertEqual(frame_ms, 200)

    def test_library_packs_the_firmware_layout(self):
        with TemporaryDirectory() as folder:
            source = Path(folder) / "a.jpg"
            Image.new("RGB", (400, 400), (0, 128, 255)).save(source)
            library = screensaver.Library(Path(folder) / "lib")
            first = library.add(source)
            library.add(source)
            blob = library.pack()
            magic, version, count, size, crc = struct.unpack_from("<5I", blob)
            self.assertEqual((magic, version, count), (screensaver.MAGIC, 1, 2))
            data = blob[screensaver.HEADER_BYTES:]
            self.assertEqual((size, crc), (len(data), zlib.crc32(data)))
            self.assertEqual(crc, library.checksum())
            offset, length, frames, frame_ms, _ = struct.unpack_from("<IIHHI", blob, 48)
            self.assertEqual((offset, length, frames), (first["bytes"], first["bytes"], 1))
            jpeg_length = struct.unpack_from("<I", data)[0]
            self.assertEqual(data[4:6], b"\xff\xd8")
            self.assertEqual(first["bytes"], 4 + jpeg_length + (-jpeg_length % 4))
            # Kept between runs; removing deletes the converted file too.
            reopened = screensaver.Library(Path(folder) / "lib")
            self.assertEqual(len(reopened.items), 2)
            reopened.remove(first["id"])
            self.assertEqual(len(screensaver.Library(Path(folder) / "lib").items), 1)
            with self.assertRaises(screensaver.MediaError):
                reopened.add(source, capacity=10)

    def test_header_and_frame_limits_match_the_firmware(self):
        source = (Path(__file__).resolve().parents[1] / "firmware" / "main" / "main.c").read_text()
        self.assertIn("#define MEDIA_MAGIC 0x%08Xu" % screensaver.MAGIC, source)
        self.assertIn(f"#define MEDIA_HEADER_BYTES {screensaver.HEADER_BYTES}", source)
        self.assertIn(f"#define MEDIA_MAX_ITEMS {screensaver.MAX_ITEMS}", source)
        self.assertLessEqual(32 + 16 * screensaver.MAX_ITEMS, screensaver.HEADER_BYTES)
        partitions = (Path(__file__).resolve().parents[1] / "firmware" / "partitions.csv").read_text()
        self.assertIn("media,    data, 0x40,    0x310000, 0xCF0000,", partitions)


    def test_videos_are_decoded_by_ffmpeg(self):
        size = screensaver.SIZE
        raw = bytes([0, 200, 0]) * size * size * 3 + b"partial"

        class Process:
            def __init__(self, command, **kwargs):
                self.command = command
                self.stdout = io.BytesIO(raw)
                self.stderr = io.BytesIO(b"")

            def wait(self):
                return 0

            def poll(self):
                return 0

        with mock.patch.object(screensaver.subprocess, "Popen", Process):
            frames, frame_ms = screensaver._video_frames(
                Path("clip.mp4"), ffmpeg="ffmpeg.exe")
        self.assertEqual((len(frames), frame_ms), (3, 100))
        with Image.open(io.BytesIO(frames[0])) as frame:
            self.assertGreater(frame.getpixel((180, 180))[1], 150)
        command = screensaver.ffmpeg_command("ffmpeg.exe", "clip.mp4")
        self.assertIn("rawvideo", command)
        self.assertIn(str(screensaver.MAX_CLIP_SECONDS), command)
        self.assertTrue(any("crop=360:360" in part for part in command))

    def test_video_without_ffmpeg_is_a_clear_error(self):
        with mock.patch.object(screensaver, "find_ffmpeg", return_value=None):
            with self.assertRaisesRegex(screensaver.MediaError, "FFmpeg"):
                screensaver.convert("clip.mp4")

    def test_ffmpeg_on_path_is_used_without_download(self):
        with mock.patch.object(screensaver.shutil, "which", return_value="C:/ff/ffmpeg.exe"):
            with mock.patch("revo1.updater.download") as download:
                self.assertEqual(screensaver.ensure_ffmpeg(), "C:/ff/ffmpeg.exe")
        download.assert_not_called()

if __name__ == "__main__":
    unittest.main()
