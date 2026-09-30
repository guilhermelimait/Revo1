"""A focus/break timer that runs on the PC; the knob shows it and a chime
marks each change of phase."""

import math
import struct
import time
from pathlib import Path

FOCUS = 0
BREAK = 1
PHASE_NAMES = ("Focus", "Break")
SAMPLE_RATE = 22050


class PomodoroTimer:
    """Pure timing logic; `clock` is injectable for tests."""

    def __init__(self, focus_minutes=25, break_minutes=5, clock=time.monotonic):
        self.clock = clock
        self.minutes = [focus_minutes, break_minutes]
        self.phase = FOCUS
        self.running = False
        self._remaining = self.total
        self._stamp = 0.0

    @property
    def total(self):
        return self.minutes[self.phase] * 60

    def remaining(self):
        if not self.running:
            return self._remaining
        return max(0, self._remaining - int(self.clock() - self._stamp))

    def fraction(self):
        return min(1.0, self.remaining() / self.total) if self.total else 0.0

    def start(self):
        if not self.running:
            self._stamp = self.clock()
            self.running = True

    def pause(self):
        if self.running:
            self._remaining = self.remaining()
            self.running = False

    def toggle(self):
        self.pause() if self.running else self.start()

    def reset(self):
        """Back to the start of a focus session, stopped."""
        self.running = False
        self.phase = FOCUS
        self._remaining = self.total

    def set_minutes(self, phase, minutes):
        """Changes a phase's length; a stopped timer at the start of that
        phase follows the new length."""
        minutes = max(1, min(180, int(minutes)))
        untouched = not self.running and self._remaining == self.total
        self.minutes[phase] = minutes
        if phase != self.phase:
            return
        if untouched:
            self._remaining = self.total
        elif self.remaining() > self.total:
            # A shorter phase never leaves more time than its new length.
            self._remaining = self.total
            self._stamp = self.clock()

    def tick(self):
        """Moves on to the next phase when the current one has run out.
        Returns True when it did, so the caller can chime."""
        if not self.running or self.remaining() > 0:
            return False
        self.phase = BREAK if self.phase == FOCUS else FOCUS
        self._remaining = self.total
        self._stamp = self.clock()
        return True


def _tone(notes, volume=0.35):
    """16-bit mono PCM for a sequence of (frequency, seconds) bell-like notes."""
    samples = []
    for frequency, seconds in notes:
        count = int(SAMPLE_RATE * seconds)
        for index in range(count):
            t = index / SAMPLE_RATE
            envelope = math.exp(-4.0 * t / seconds) * min(1.0, index / 200)
            value = (math.sin(2 * math.pi * frequency * t)
                     + 0.35 * math.sin(2 * math.pi * frequency * 2.01 * t)) / 1.35
            samples.append(int(32767 * volume * envelope * value))
    return struct.pack(f"<{len(samples)}h", *samples)


def _wave(pcm):
    header = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF", 36 + len(pcm), b"WAVE", b"fmt ",
                         16, 1, 1, SAMPLE_RATE, SAMPLE_RATE * 2, 2, 16, b"data", len(pcm))
    return header + pcm


# Rising at the end of focus (time for a break), falling back into focus.
CHIMES = {
    BREAK: [(659.25, 0.28), (783.99, 0.28), (1046.5, 0.7)],
    FOCUS: [(1046.5, 0.28), (783.99, 0.28), (523.25, 0.7)],
}


def chime_path(phase, folder):
    """The WAV file for the chime announcing `phase`, written on first use."""
    folder = Path(folder)
    path = folder / f"chime-{PHASE_NAMES[phase].lower()}.wav"
    if not path.exists():
        folder.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_wave(_tone(CHIMES[phase])))
    return path


def play_chime(phase, folder):
    try:
        import winsound
    except ImportError:
        return
    try:
        winsound.PlaySound(str(chime_path(phase, folder)),
                           winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except (OSError, RuntimeError):
        pass
