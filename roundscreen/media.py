"""Read and control whatever is playing through the Windows media transport."""

import asyncio
import threading
import unicodedata

try:
    from winsdk.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as SessionManager,
        GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
    )
except ImportError:  # pragma: no cover - winsdk is Windows only
    SessionManager = None
    PlaybackStatus = None

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


class MediaSession:
    """Serialises winsdk calls onto one private event loop.

    The Windows Runtime projection wants an asyncio loop, and the app polls
    from a worker thread, so the loop lives on a thread of its own.
    """

    def __init__(self):
        self.available = SessionManager is not None
        self._loop = None
        self._thread = None
        self._lock = threading.Lock()

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
        manager = await SessionManager.request_async()
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
        return self._run(self._snapshot())

    async def _command(self, name):
        session = await self._session()
        if session is None:
            return False
        return bool(await getattr(session, name)())

    def play_pause(self):
        return bool(self._run(self._command("try_toggle_play_pause_async")))

    def next_track(self):
        return bool(self._run(self._command("try_skip_next_async")))

    def previous_track(self):
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
        return bool(self._run(self._seek(delta_seconds)))
