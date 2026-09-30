# Third-party notices

Revo1's own code is under the [MIT License](LICENSE). It includes or
builds on the following third-party work, which keeps its own licence.

| Component | Where | Licence |
| --- | --- | --- |
| [Montserrat](https://github.com/JulietaUla/Montserrat) typeface | `revo1/fonts/` (bundled) | SIL Open Font License 1.1, see [revo1/fonts/OFL.txt](revo1/fonts/OFL.txt) |
| [LVGL](https://github.com/lvgl/lvgl) 8.4, including its built-in Montserrat fonts | firmware, downloaded at build time | MIT |
| [esp_lcd_sh8601](https://components.espressif.com/components/waveshare/esp_lcd_sh8601) panel driver | firmware, downloaded at build time | Apache-2.0 |
| [cmake_utilities](https://components.espressif.com/components/espressif/cmake_utilities) | firmware, downloaded at build time | Apache-2.0 |
| [ESP-IDF](https://github.com/espressif/esp-idf) | firmware framework | Apache-2.0 |
| SH8601 panel initialisation table and board pin mapping | `firmware/main/panel_init.inc`, `firmware/main/main.c` | Adapted from Waveshare's [ESP32-S3-Knob-Touch-LCD-1.8 demo](https://www.waveshare.com/wiki/ESP32-S3-Knob-Touch-LCD-1.8) |
| [pyserial](https://github.com/pyserial/pyserial) | Python dependency | BSD-3-Clause |
| [pycaw](https://github.com/AndreMiras/pycaw) | Python dependency | MIT |
| [PyWinRT](https://github.com/pywinrt/pywinrt) (`winrt-*`) | Python dependency | MIT |
| [PyInstaller](https://pyinstaller.org) bootloader | `Revo1.exe` | GPL-2.0 with an exception that allows distributing the bundled app under any licence |
| [Python](https://www.python.org) runtime and Tcl/Tk | bundled in `Revo1.exe` | PSF License, Tcl/Tk License |
| [NumPy](https://numpy.org) | Python dependency | BSD-3-Clause |
| [Pillow](https://python-pillow.org) | Python dependency | MIT-CMU |
| [FFmpeg](https://ffmpeg.org) LGPL build from [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds) | downloaded on demand the first time a video is added to the screensaver, run as a separate program; not bundled | LGPL-2.1-or-later |
| TJpgDec (in the ESP32-S3 ROM) | JPEG decoding for the screensaver | ChaN's TJpgDec licence (BSD-style) |
| [esptool](https://github.com/espressif/esptool) standalone build | downloaded on demand by the About page and `scripts/flash-firmware.ps1`, run as a separate program; not bundled | GPL-2.0-or-later |

Waveshare and ESP32 are trademarks of their respective owners. This project
is not affiliated with or endorsed by Waveshare or Espressif.
