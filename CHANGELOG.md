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
  bar colour (standard, preset or custom) and number size.
- Accented letters in song titles are shown without accents instead of "?".
- `install.ps1` for the app and `scripts/flash-firmware.ps1` for flashing,
  with an automatic backup of the stock firmware.
