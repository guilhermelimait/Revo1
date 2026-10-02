"""Read and control whatever is playing through the Windows media transport."""

import asyncio
import ctypes
from ctypes import wintypes
import os
import threading
import time
import unicodedata

try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as SessionManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
    )
except ImportError:  # pragma: no cover - the WinRT projection is Windows only
    SessionManager = None
    PlaybackStatus = None

try:
    from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
except ImportError:  # pragma: no cover - Windows only
    AudioUtilities = None

TEXT_MAX = 58
# Letters that do not decompose into a base letter plus accents.
FOLD = str.maketrans({"\u00df": "ss", "\u00e6": "ae", "\u00c6": "AE", "\u00f8": "o",
                      "\u00d8": "O", "\u0153": "oe", "\u0152": "OE", "\u0142": "l",
                      "\u0141": "L", "\u0111": "d", "\u0110": "D", "\u00f0": "d",
                      "\u00fe": "th", "\u2018": "'", "\u2019": "'", "\u201c": '"',
                      "\u201d": '"', "\u2013": "-", "\u2014": "-", "\u2026": "..."})

STOPPED = 0
PLAYING = 1
PAUSED = 2

# An app counts as playing while its output peaks above this level.
SOUND_PEAK = 0.0005
# A player that went quiet is shown as paused for this long, so the knob can
# resume it, unless a registered player has played since.
PAUSED_HOLD_S = 30 * 60
WM_APPCOMMAND = 0x0319
APPCOMMANDS = {"PLAYPAUSE": 14, "NEXT": 11, "PREV": 12}
VK_LEFT, VK_RIGHT, VK_MENU = 0x25, 0x27, 0x12
KEYEVENTF_KEYUP = 0x0002
# Players without media controls (Stremio, mpv, VLC...) seek this far per
# arrow key press, so one knob click moves the estimated clock by as much.
ARROW_SEEK_S = 10


def clean(text):
    """Reduce to the printable ASCII the device fonts can render. Accented
    letters keep their base letter ("Musica" rather than "M?sica"); only
    characters with no Latin equivalent become "?"."""
    folded = unicodedata.normalize("NFKD", (text or "").translate(FOLD))
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    ascii_text = "".join(character if 0x20 <= ord(character) < 0x7F else "?"
                         for character in folded)
    ascii_text = ascii_text.strip()
    if len(ascii_text) > TEXT_MAX:
        ascii_text = ascii_text[:TEXT_MAX - 1].rstrip() + "~"
    return ascii_text


def _sounding_apps():
    """(pid, peak) for every app with an active audio session, loudest first.
    Needs COM initialised on the calling thread."""
    if AudioUtilities is None:
        return []
    found = []
    for session in AudioUtilities.GetAllSessions():
        process = session.Process
        if process is None or process.pid == os.getpid():
            continue
        try:
            peak = session._ctl.QueryInterface(IAudioMeterInformation).GetPeakValue()
        except (OSError, ValueError):
            continue
        found.append((process.pid, peak))
    return sorted(found, key=lambda item: -item[1])


def _main_window(pid):
    """The app's visible top-level window and its title, or (None, "")."""
    if os.name != "nt":
        return None, ""
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(window, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(owner))
        if (owner.value == pid and user32.IsWindowVisible(window)
                and not user32.GetWindow(window, 4)):
            text = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(window, text, 256)
            if text.value:
                found.append((window, text.value))
                return False
        return True

    user32.EnumWindows(visit, 0)
    return found[0] if found else (None, "")


class MediaSession:
    """Serialises WinRT calls onto one private event loop.

    The Windows Runtime projection wants an asyncio loop, and the app polls
    from a worker thread, so the loop lives on a thread of its own.
    """

    def __init__(self):
        self.available = SessionManager is not None
        self._loop = None
        self._thread = None
        self._lock = threading.Lock()
        # The last app found playing without a media session: (pid, seen at).
        self._sound_app = None
        self._registered_at = 0.0
        self._source = None
        # Estimated play time of that app, which reports none of its own:
        # [pid, seconds counted, when last counted, playing then].
        self._sound_clock = None

    def _run(self, coroutine):
        if not self.available:
            return None
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(target=self._loop.run_forever,
                                                daemon=True)
                self._thread.start()
            future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        try:
            return future.result(timeout=3)
        except Exception:
            return None

    async def _session(self):
        """The playing session if there is one, otherwise Windows' current
        one. Windows can keep a paused player as current while another plays."""
        manager = await SessionManager.request_async()
        for session in manager.get_sessions():
            playback = session.get_playback_info()
            if playback is not None and playback.playback_status == PlaybackStatus.PLAYING:
                return session
        return manager.get_current_session()

    async def _snapshot(self):
        session = await self._session()
        if session is None:
            return None
        properties = await session.try_get_media_properties_async()
        timeline = session.get_timeline_properties()
        playback = session.get_playback_info()

        status = STOPPED
        if playback is not None:
            if playback.playback_status == PlaybackStatus.PLAYING:
                status = PLAYING
            elif playback.playback_status == PlaybackStatus.PAUSED:
                status = PAUSED

        position = duration = 0
        if timeline is not None:
            span = timeline.end_time - timeline.start_time
            duration = max(0, int(span.total_seconds()))
            position = max(0, int((timeline.position - timeline.start_time)
                                  .total_seconds()))
            position = min(position, duration)

        return {
            "title": clean(properties.title if properties else ""),
            "artist": clean(properties.artist if properties else ""),
            "status": status,
            "position": position,
            "duration": duration,
        }

    def snapshot(self):
        """What is playing. Players that register with Windows' media controls
        come first; otherwise any app making sound (Stremio, for example)
        is shown by its window title."""
        registered = self._run(self._snapshot())
        now = time.monotonic()
        if registered and registered["status"] == PLAYING:
            self._registered_at = now
            self._source = "registered"
            return registered
        sound = self._sound_snapshot(now)
        if sound is not None:
            self._source = "sound"
            return sound
        self._source = "registered" if registered else None
        return registered

    def _sound_snapshot(self, now):
        try:
            apps = _sounding_apps()
        except (OSError, ValueError, RuntimeError):
            return None
        playing = [pid for pid, peak in apps if peak > SOUND_PEAK]
        status = PLAYING
        if playing:
            pid = playing[0]
            self._sound_app = (pid, now)
        elif (self._sound_app and now - self._sound_app[1] < PAUSED_HOLD_S
              and self._sound_app[1] > self._registered_at
              and any(pid == self._sound_app[0] for pid, _ in apps)):
            pid = self._sound_app[0]
            status = PAUSED
        else:
            return None
        window, title = _main_window(pid)
        if window is None:
            return None
        return {"title": clean(title), "artist": "", "status": status,
                "position": self._count(pid, status == PLAYING, now),
                "duration": 0}

    def _count(self, pid, playing, now):
        """Seconds the app has been heard playing since Revo1 noticed it,
        frozen while it is paused."""
        clock = self._sound_clock
        if clock is None or clock[0] != pid:
            clock = self._sound_clock = [pid, 0.0, now, False]
        if clock[3]:
            clock[1] += now - clock[2]
        clock[2], clock[3] = now, playing
        return int(clock[1])

    def _sound_command(self, name):
        """Sends a media command straight to the sounding app's window, so a
        paused registered player such as Spotify isn't woken instead."""
        if self._source != "sound" or not self._sound_app:
            return None
        window, _ = _main_window(self._sound_app[0])
        if window is None:
            return False
        ctypes.windll.user32.SendMessageW(window, WM_APPCOMMAND, window,
                                          APPCOMMANDS[name] << 16)
        self._sound_app = (self._sound_app[0], time.monotonic())
        return True

    async def _command(self, name):
        session = await self._session()
        if session is None:
            return False
        return bool(await getattr(session, name)())

    def play_pause(self):
        sent = self._sound_command("PLAYPAUSE")
        if sent is not None:
            return sent
        return bool(self._run(self._command("try_toggle_play_pause_async")))

    def next_track(self):
        sent = self._sound_command("NEXT")
        if sent is not None:
            return sent
        return bool(self._run(self._command("try_skip_next_async")))

    def previous_track(self):
        sent = self._sound_command("PREV")
        if sent is not None:
            return sent
        return bool(self._run(self._command("try_skip_previous_async")))

    async def _seek(self, delta_seconds):
        session = await self._session()
        if session is None:
            return False
        timeline = session.get_timeline_properties()
        if timeline is None:
            return False
        target = timeline.position.total_seconds() + delta_seconds
        lower = timeline.start_time.total_seconds()
        upper = timeline.end_time.total_seconds()
        target = max(lower, min(upper, target))
        # The playback position is expressed in 100 ns ticks.
        return bool(await session.try_change_playback_position_async(
            int(target * 10_000_000)))

    def seek(self, delta_seconds):
        if self._source == "sound":
            return self._sound_seek(delta_seconds)
        return bool(self._run(self._seek(delta_seconds)))

    def seek_clicks(self, clicks, seconds=5):
        """Knob seek: `seconds` per click with media controls, otherwise one
        arrow key press (the player's own step) per click."""
        if self._source == "sound":
            return self._sound_seek(clicks * ARROW_SEEK_S)
        return bool(self._run(self._seek(clicks * seconds)))

    def _sound_seek(self, delta_seconds):
        """Players without media controls only seek from the keyboard, so the
        arrow keys are pressed in the player's window, briefly brought to the
        front if needed, and the previous window gets the focus back."""
        if not self._sound_app or os.name != "nt":
            return False
        window, _ = _main_window(self._sound_app[0])
        if window is None:
            return False
        presses = max(1, round(abs(delta_seconds) / ARROW_SEEK_S))
        key = VK_RIGHT if delta_seconds > 0 else VK_LEFT
        user32 = ctypes.windll.user32
        previous = user32.GetForegroundWindow()
        if previous != window:
            # Windows only lets the foreground app hand over the focus; a
            # tapped Alt key counts as the user's input and lifts that lock.
            user32.keybd_event(VK_MENU, 0, 0, 0)
            user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
            user32.SetForegroundWindow(window)
            time.sleep(0.05)
            if user32.GetForegroundWindow() != window:
                return False
        for _ in range(presses):
            user32.keybd_event(key, 0, 0, 0)
            user32.keybd_event(key, 0, KEYEVENTF_KEYUP, 0)
        if previous and previous != window:
            time.sleep(0.05)
            user32.SetForegroundWindow(previous)
        clock = self._sound_clock
        if clock and clock[0] == self._sound_app[0]:
            clock[1] = max(0.0, clock[1] + presses * ARROW_SEEK_S *
                           (1 if delta_seconds > 0 else -1))
        return True
