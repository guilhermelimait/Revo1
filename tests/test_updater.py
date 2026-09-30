import io
import json
import queue
import sys
import time
import unittest
import urllib.error
from unittest.mock import patch

from roundscreen import updater
from roundscreen.bridge import DeviceBridge


class Response(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class VersionTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(updater.parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(updater.parse_version("1.4"), (1, 4, 0))
        self.assertIsNone(updater.parse_version("nightly"))
        self.assertIsNone(updater.parse_version(None))

    def test_is_newer(self):
        self.assertTrue(updater.is_newer("1.0.1", "1.0.0"))
        self.assertTrue(updater.is_newer("v1.10.0", "1.9.9"))
        self.assertFalse(updater.is_newer("1.0.0", "1.0.0"))
        self.assertFalse(updater.is_newer("0.9.0", "1.0.0"))
        # Firmware too old to report a version is always behind.
        self.assertTrue(updater.is_newer("1.0.0", None))
        self.assertFalse(updater.is_newer("garbage", None))


class ReleaseTests(unittest.TestCase):
    def test_latest_release_finds_the_firmware(self):
        body = json.dumps({
            "tag_name": "v1.2.0", "published_at": "2026-03-04T10:00:00Z",
            "html_url": "https://example.test/r",
            "assets": [{"name": "RoundScreen-Setup-1.2.0.exe", "browser_download_url": "x"},
                       {"name": "roundscreen-firmware-1.2.0.bin", "size": 5,
                        "browser_download_url": "https://example.test/fw.bin"}]}).encode()
        with patch("urllib.request.urlopen", return_value=Response(body)):
            release = updater.latest_release()
        self.assertEqual(release["version"], "1.2.0")
        self.assertEqual(release["published"].year, 2026)
        self.assertEqual(release["firmware_name"], "roundscreen-firmware-1.2.0.bin")
        self.assertEqual(release["firmware_url"], "https://example.test/fw.bin")

    def test_no_release_yet(self):
        error = urllib.error.HTTPError(updater.LATEST_API, 404, "Not Found", {}, None)
        with patch("urllib.request.urlopen", side_effect=error):
            self.assertIsNone(updater.latest_release())

    def test_offline(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")):
            with self.assertRaises(updater.UpdateError):
                updater.latest_release()


class FlashTests(unittest.TestCase):
    def test_progress_and_success(self):
        script = "print('Writing at 0x0 (10 %)'); print('Writing at 0x1 (100 %)')"
        seen = []
        updater.flash([sys.executable, "-c", script, "--"], "COM1", "image.bin", seen.append)
        self.assertEqual(seen[-1], 1.0)

    def test_failure_reports_the_last_line(self):
        script = "import sys; print('A fatal error occurred: no port'); sys.exit(2)"
        with self.assertRaisesRegex(updater.UpdateError, "no port"):
            updater.flash([sys.executable, "-c", script, "--"], "COM1", "image.bin")


class BridgePauseTests(unittest.TestCase):
    def test_pause_frees_the_port_and_resume_reconnects(self):
        with patch("roundscreen.bridge.list_ports.comports", return_value=[]):
            bridge = DeviceBridge(queue.Queue())
            bridge.start()
            try:
                started = time.monotonic()
                self.assertTrue(bridge.pause())
                self.assertLess(time.monotonic() - started, 1.5)
                bridge.resume()
                self.assertFalse(bridge.pause_event.is_set())
            finally:
                bridge.stop()
            self.assertFalse(bridge.thread.is_alive())


if __name__ == "__main__":
    unittest.main()
