import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from revo1 import pomodoro


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class PomodoroTests(unittest.TestCase):
    def test_runs_pauses_and_changes_phase(self):
        clock = Clock()
        timer = pomodoro.PomodoroTimer(25, 5, clock=clock)
        self.assertEqual(timer.remaining(), 1500)
        timer.start()
        clock.now += 600
        self.assertEqual(timer.remaining(), 900)
        timer.pause()
        clock.now += 600
        self.assertEqual(timer.remaining(), 900)
        self.assertFalse(timer.tick())
        timer.start()
        clock.now += 900
        self.assertTrue(timer.tick())
        self.assertEqual(timer.phase, pomodoro.BREAK)
        self.assertEqual(timer.remaining(), 300)
        self.assertTrue(timer.running)
        clock.now += 300
        self.assertTrue(timer.tick())
        self.assertEqual(timer.phase, pomodoro.FOCUS)

    def test_a_shorter_phase_caps_the_time_left(self):
        clock = Clock()
        timer = pomodoro.PomodoroTimer(25, 5, clock=clock)
        timer.start()
        clock.now += 60
        timer.set_minutes(pomodoro.FOCUS, 7)
        self.assertEqual(timer.remaining(), 7 * 60)
        self.assertEqual(timer.fraction(), 1.0)
        clock.now += 60
        self.assertEqual(timer.remaining(), 6 * 60)
        timer.pause()
        timer.set_minutes(pomodoro.FOCUS, 3)
        self.assertEqual(timer.remaining(), 3 * 60)

    def test_lengths_follow_only_an_untouched_phase(self):
        clock = Clock()
        timer = pomodoro.PomodoroTimer(25, 5, clock=clock)
        timer.set_minutes(pomodoro.FOCUS, 50)
        self.assertEqual(timer.remaining(), 3000)
        timer.start()
        clock.now += 60
        timer.pause()
        timer.set_minutes(pomodoro.FOCUS, 60)
        self.assertEqual(timer.remaining(), 2940)
        timer.set_minutes(pomodoro.FOCUS, 10)
        self.assertEqual(timer.remaining(), 600)
        timer.reset()
        self.assertEqual(timer.remaining(), 600)
        timer.set_minutes(pomodoro.BREAK, 0)
        self.assertEqual(timer.minutes[pomodoro.BREAK], 1)

    def test_chimes_are_valid_wave_files(self):
        with TemporaryDirectory() as folder:
            for phase in (pomodoro.FOCUS, pomodoro.BREAK):
                data = Path(pomodoro.chime_path(phase, folder)).read_bytes()
                self.assertEqual(data[:4], b"RIFF")
                self.assertEqual(data[8:12], b"WAVE")
                self.assertGreater(len(data), 20000)


if __name__ == "__main__":
    unittest.main()
