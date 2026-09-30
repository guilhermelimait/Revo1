# Changelog

## 1.0.0 - 2026-09-30

First public release.

- Custom firmware for the Waveshare ESP32-S3-Knob-Touch-LCD-1.8 with a
  Nest-style sculpted dial and a full-ring gauge.
- Windows companion app with the same dial, kept in sync with the knob.
- Controls: volume, scrolling, brightness, microphone, zoom and media
  (title, artist, progress, play/pause, previous, next, seek).
- Radial icon menu opened from the centre or the mode name; knob to choose,
  tap to confirm.
- Settings: device name, automatic device detection, screen orientation,
  bar colour (standard, preset or custom), number size, and separate
  **Invert scroll** / **Invert zoom** switches for the knob direction.
- Optional minimise to the notification area (tray), also used when started
  at sign-in.
- About page: app and firmware versions, the latest GitHub release, and a
  one-click firmware update over USB. The firmware reports its version with
  `VERSION,<x.y.z>`; it's taken from `revo1/__init__.py` at build time.
  **Install from file...** flashes a downloaded or locally built image, after
  checking that it really is Revo1 firmware.
- The knob keeps its last control, orientation, colour and number size in
  flash, so a restart doesn't undo them; after a restart it asks the app
  (`SYNC`) for the current state.
- Accented letters in song titles are shown without accents instead of "?".
- `Revo1-Setup.exe`: a per-user Windows installer with Python bundled,
  its own icon, a Start Menu entry, an optional start at sign-in, and an
  uninstaller in Apps & features. Built by GitHub Actions for every release.
- `scripts/flash-firmware.ps1` for flashing, with an automatic backup of the
  stock firmware.
- Media control uses the maintained PyWinRT packages (`winrt-*`) instead of
  `winsdk`, so running from source works on Python 3.10 and newer.
