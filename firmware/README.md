# Revo1 ESP32-S3 firmware

PlatformIO / ESP-IDF 5.5 project for the Waveshare ESP32-S3-Knob-Touch-LCD-1.8.
Most people do not need to build it: download
`revo1-firmware-<version>.bin` from the GitHub releases and flash it
with `scripts\flash-firmware.ps1` as described in the [main README](../README.md).

## Build

With [PlatformIO](https://platformio.org/install/cli) installed, from this
directory:

```powershell
pio run
```

The first build downloads ESP-IDF, LVGL 8.4 and the SH8601 panel driver
(declared in `main\idf_component.yml`). The outputs are in
`.pio\build\waveshare-knob\`: `bootloader.bin` (address `0x0`),
`partitions.bin` (`0x8000`) and `firmware.bin` (`0x10000`). The board
definition is `esp32-s3-devkitc1-n16r8` (16 MB flash, 8 MB octal PSRAM).

To flash from PlatformIO, connect the ESP32-S3 side of the USB-C plug (USB ID
`303A:1001`, listed as *USB Serial Device*, not the CH340 port) and run:

```powershell
pio run -t upload --upload-port COMx
```

Back up the stock firmware first if you may want it back:
`python -m esptool --chip esp32s3 --port COMx read-flash 0x0 0x1000000 backup.bin`.

To produce the single image used by the release, which is flashed at `0x0`:

```powershell
python -m esptool --chip esp32s3 merge-bin -o revo1-firmware.bin `
  0x0 .pio\build\waveshare-knob\bootloader.bin `
  0x8000 .pio\build\waveshare-knob\partitions.bin `
  0x10000 .pio\build\waveshare-knob\firmware.bin
```

If `pio run` fails inside PlatformIO's SCons launcher (for example
`ModuleNotFoundError: SCons.Tool.FortranCommon`) after a first configure,
running `ninja` in `.pio\build\waveshare-knob` with PlatformIO's toolchain
on `PATH` builds the same project; its application image is
`revo1_firmware.bin` and the partition table is
`partition_table\partition-table.bin`.

## Hardware and sources

The board mapping and SH8601 panel initialization table are based on Waveshare's
[ESP32-S3-Knob-Touch-LCD-1.8 demo archive](https://files.waveshare.com/wiki/ESP32-S3-Knob-Touch-LCD-1.8/ESP32-S3-Knob-Touch-LCD-1.8-Demo.zip)
and [wiki](https://www.waveshare.com/wiki/ESP32-S3-Knob-Touch-LCD-1.8).
The SH8601 driver is pulled from Waveshare's
[ESP32 component registry](https://components.espressif.com/components/waveshare/esp_lcd_sh8601).
LVGL 8.4 and the panel driver are declared in `main\idf_component.yml`.

| Function | Pins / address |
| --- | --- |
| SH8601 QSPI | CS 14, SCLK 13, D0..D3 15..18, reset 21 |
| Display backlight | GPIO 47, PWM |
| CST816 touch | I2C address 0x15, SDA 11, SCL 12, reset 10 |
| Encoder | A 8, B 7; no knob-press input |
| Touch interrupt | GPIO 9 (polled touch data is used) |

The native USB Serial/JTAG console runs at 115200 baud and implements the
`HELLO,REVO1,1`, `VERSION`, `SYNC`, `ROT`, `MENU`, `CURSOR`, `TAP`, `SWIPE`, `MEDIA`, `STATE`,
`SHOWMENU`, `COMETRESET`, `STYLE`, `TRACK`, `ARTIST`, `PLAY`, `SCREENS`,
`BACKLIGHT`, `POMO`, `SAVER`, `LIBRARY` and media upload lines used by
`revo1\bridge.py`. The menu has one sector per enabled screen (`SCREENS`
mask), in the host mode order; `CURSOR` and `TAP` report the mode index, not
the sector.

The USB Serial/JTAG driver is installed with an 8 KB receive buffer, and
`serial_reader_task` reads lines of up to 4200 bytes. Media upload lines are
handled right there in the reader task (they write flash); every other line
goes through a queue to the UI loop, which applies `SERIAL_LINE_MAX` (96).

## Pomodoro

The host owns the timer. `POMO,<phase>,<remaining s>,<total s>,<running>`
arrives on every change and once a minute; the firmware counts the seconds
down locally in between so the ring and the `M:SS` number move smoothly, and
a tap on the dial sends `POMO,TOGGLE` back. The chime plays on the PC.

## Backlight

`BACKLIGHT,<1..100>` sets the LEDC duty on GPIO 47 with a squared curve
(`255 * p^2 / 10000`, at least 3) so the low end of the slider stays usable.

## Screensaver storage and upload

`partitions.csv` has a `media` data partition of 0xCF0000 bytes (about
12.9 MB) at 0x310000. Its layout:

- A 4096-byte header: magic `RVM1` (`0x314D5652`), version 1, item count,
  data bytes, CRC-32 of the data (zlib polynomial; `esp_rom_crc32_le`), then
  one 16-byte entry per item (up to 250): data offset, byte length, frame
  count, milliseconds per frame.
- The data: each frame is `<u32 length>` + a baseline 360 x 360 JPEG, padded
  to 4 bytes.

Upload: `MEDIA_BEGIN,<total bytes>` erases what is needed and answers
`MEDIA_READY` (or `MEDIA_ERR,SIZE|ERASE|NOSTORAGE`). The host then sends
`MD,<offset>,<base64>` lines of up to 3072 bytes, each answered by `MD_OK` or
`MD_ERR` with the offset; the app keeps four in flight and writes the header
last, so an interrupted upload never looks valid. `MEDIA_END` checks the
header and CRC and answers `MEDIA_OK,<items>` or `MEDIA_ERR,CHECK`.
`MEDIA_CLEAR` erases the header. After each change, and on `LIBRARY`, the
knob reports `LIBRARY,<capacity>,<items>,<bytes>,<CRC hex>`, which the app
compares with its own collection.

Playback uses the ROM TJpgDec decoder straight from flash into the
framebuffer. The screensaver starts after `SAVER,<enabled>,<idle s>,<s per
item>` idle seconds without a touch or a turn, prints `SAVER,ON`, and hides
the dial labels; the waking touch or turn is swallowed and prints
`SAVER,OFF`. A frame that fails to decode prints `SAVER,BAD,<item>` and the
item is skipped.

## Media transport screen

`draw_media_icons` draws a large play-pause at the centre of the cap for
`MEDIA_MODE`, with previous and next out on the face either side of it, and the gauge shows song
progress with a bright head at the play position. The buttons use the same
signed-distance vector shapes as the menu icons (`draw_menu_icon`), so they
are anti-aliased and no icon font or bitmap has to be stored in flash. The
title and artist sit in the band below the cap (`MEDIA_TITLE_Y`,
`MEDIA_ARTIST_Y`), and the time sits in the cap under the buttons.

`PLAY,<status>,<position>,<duration>` stamps `media_stamp` with
`esp_timer_get_time()`. `media_elapsed` then interpolates locally while the
status is playing, so the ring advances smoothly between the once-a-second host
updates instead of stepping.

The transport touch zones are checked **before** the centre-tap menu circle,
which covers the whole cap (`DIAL_CAP_R`) outside the menu, so tapping the cap
anywhere except a button still opens the menu.
Track text is sanitised to printable ASCII on arrival because the bundled
Montserrat fonts have no wider coverage, and `SERIAL_LINE_MAX` caps a line at
96 bytes.

## Dial renderer

Every screen is a sculpted dial that uses the whole disc. There is no dark
bezel: the full screen is a light face lit from the upper left, with a brighter
centre cap (radius 76). A recessed channel at radius 164 hugs the edge and
carries the arc, and the outer rim rolls off over the last 4 px. On the light
face the arc's halo is a tint blend rather than additive light, and the unlit
track is a darker etched line. Text is dark on the face. The mode name sits on
the upper face, between the cap and the ring.

- **Level modes** fill the gauge clockwise from 6 o'clock all the way round, so
  at 100% the colour meets itself as a full ring.
  The colour runs from a deep tail to the full accent at the head, and a bright
  tick marks the live end.
- **Scroll and zoom** show the mode name in the cap and a comet that follows
  the knob. Each detent moves `arc_target` by `COMET_STEP_Q8` (32 segments),
  and the head eases a quarter of the remaining distance per 40 ms frame,
  snapping within two segments. The PC app runs the same integer maths
  (`dial.COMET_*`) on the same `ROT` stream, so it stays in step. Both reset
  the comet to `GAUGE_START` on every view change, and the app sends
  `COMETRESET` on connect in case the device kept running while it was closed.
- **Media** uses the gauge as song progress.
- **The menu** keeps the same chrome, but the ring is split into six segments,
  one per control, aligned with the touch sectors. The segment for the
  last-used mode is lit in that mode's accent colour. Each control is shown
  as an icon (speaker, mouse, sun, microphone, magnifier, play/pause) rather
  than a word. The icons are small vector shapes drawn with signed distances
  (`draw_menu_icons`), so their edges are anti-aliased; they are drawn with
  the chrome and cost nothing per frame. The last-used icon uses a deepened
  accent. There is no HOME strip: a centre tap opens the menu from any mode.
  In the menu the highlight follows `menu_cursor`, not the active mode. Each
  knob detent moves it one option clockwise (or back), sends `CURSOR,<n>`,
  and recomposes the chrome. The centre cap names the highlighted option. Any
  tap confirms it with `TAP,<n>`; a tap on an icon confirms that icon instead.
  The centre cap is radius 76, so the menu icons (radius 120) sit wholly on
  the grey face.

`STYLE,<STANDARD|RRGGBB>,<24|32|40|48>` sets the interface style. With a
colour, `accent_of` returns it for every mode instead of `mode_accents`, so
the bars, the menu highlight and the media button all use it. The size picks
the Montserrat font for the big number (`number_font`). Montserrat 24, 40 and
48 are enabled in `sdkconfig.waveshare-knob` and `sdkconfig.defaults` for
this.

## Saved settings

The last mode, orientation, bar colour and number size are kept in NVS
(namespace `revo1`: `mode`, `orient`, `numsize`, `accent`, with
`0xFFFFFFFF` meaning standard colours), together with the enabled screens
(`screens`), backlight (`light`) and screensaver settings (`saver`, `idle`,
`every`). `load_settings` reads them before the
display starts, so a restarted knob comes back in the same view and the same
orientation even when the PC app isn't running. `save_settings` runs after
`STATE`, `STYLE`, a menu tap or a swipe, and only writes flash when a value
actually changed. The level itself isn't stored; it comes from Windows.

Until the first `STATE` after boot, the firmware sends `SYNC` with every
`HELLO`, and a connected app answers with its style and state. The merged
release image covers the NVS partition, so a firmware update clears the saved
settings; the app sends them again straight after the update. The media
partition lies outside the merged image, so the screensaver collection
survives firmware updates.

Performance is the main design constraint:

- `render_dial_chrome` (per-pixel `sqrtf`) only runs when the view changes.
  `capture_arc_backdrop` then saves the finished chrome under the arc.
- `build_arc_band` precomputes every pixel of the annulus once: its screen
  offset, segment, and distance from the channel centre in quarter pixels. `draw_arc`
  walks that table each frame, so the arc has no gaps from polar sampling and
  touches only about 32 k pixels.
- `mark_arc_dirty` invalidates the annulus as 32-row horizontal strips that
  follow the ring's curve. That comes to 20 areas (re-check if the radii change).
  Four straight bands along the sides are **not** enough: at the diagonals the
  ring curves inside the square they enclose, and those pixels were never
  flushed. The strip count must stay under LVGL's 32-entry invalidation buffer.
- `dial_advance` reports whether anything moved, and an idle dial costs no
  redraw. Label text is only touched on state changes, because label work used
  to cost more per frame than drawing.
- `firmware\main\main.c` and `revo1\dial.py` share the same maths, and
  the menu icon table is mirrored in `revo1\icons.py`; keep them in step
  so the PC window matches the screen.

Other constraints:

- PSRAM writes are capped near 33 MB/s. Row half-widths and edge
  anti-aliasing coverage are precomputed by `build_screen_tables`.
- The animation ticks at roughly 25 fps.
- `LV_COLOR_16_SWAP` is enabled, so `lv_color_t.full` holds byte-swapped
  RGB565. `pack_pixel` mixes channels in native order and swaps once at the
  end. The earlier monochrome build only ever wrote `0x0000` and `0xFFFF`,
  which are unaffected by swapping, so this never came up before. The option
  must also be set in `sdkconfig.waveshare-knob`. When it was missing there,
  LVGL mixed label text with a misread canvas colour, which left a dark
  fringe around every number and caption.
- LVGL 8.4 gradient dithering (`CONFIG_LV_DITHER_GRADIENT`) is enabled. This
  option was removed in LVGL 9, so upgrading would lose it.
- `main\CMakeLists.txt` applies `-O3 -funroll-loops` to this component.
  `build_flags` in `platformio.ini` do not reach the sources when Ninja is
  invoked directly, so the `target_compile_options` call is what takes effect.
- The SH8601 QSPI clock runs at 70 MHz, tested stable.

Note that PlatformIO's generated `sdkconfig.waveshare-knob` overrides
`sdkconfig.defaults` once it exists, so configuration changes must be made in
the generated file or it must be deleted first.

## Encoder

The knob is **not** a quadrature encoder. It rests with both lines high and
pulses one contact at a time, never passing through the both-low state, so
hardware PCNT decoding nets consecutive pulses to zero and loses the click.

As measured on this unit, one detent produces two same-direction pulses about
70 ms apart, and a counter-clockwise detent can emit a trailing opposite pulse.
`encoder_interrupt` therefore uses per-line falling-edge GPIO interrupts with a
2 ms bounce reject and a directional lockout that rejects an opposite-direction
pulse within 120 ms of the last accepted step. `app_main` then divides the
pulse count by `ENCODER_PULSES_PER_DETENT`, carrying the remainder so slow
turns are not discarded poll by poll, and clearing that carry on a direction
change so a leftover half-detent cannot swallow the first pulse of the new
direction. Verified on hardware: five detents clockwise report exactly `+5`,
and five back report exactly `-5`.

The trade-off is that reversing direction within 120 ms can lose at most one
step. Shorten `ENCODER_DIRECTION_LOCKOUT_US` if fast reversals drop steps.

Orientation changes rotate the rendered display and touch coordinates in
software. USB upload, touch input, and 90-degree orientation have been tested
on hardware.
