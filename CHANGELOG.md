# Changelog

## Unreleased

- Battery indicators now show an icon beside the percentage, without `~`.
  On an app USB connection, a lightning icon and `USB power` appear instead.
  This indicates USB use, not verified battery charging status.
- Estimated battery charge during Bluetooth use: a battery icon and `N%` below the
  connection line in the app, and on device control screens, not the
  menu. Calibrated ADC readings on this unit change from about 4.33 V on USB
  to 3.60 V on battery. A generic LiPo curve supplies an approximate charge
  estimate; invalid and stale readings are hidden. `VOLTAGE` provides an
  on-demand diagnostic without claiming battery charge or charging status.
- Manual Battery Saver in Settings > Device: cap brightness at 40% (20% in
  the screensaver), dim after 30 seconds and turn the display off after five
  minutes. Touch or turn to wake; screensaver animations run at up to 5 fps
  and stop while dark. The mode survives restarts and the app shows the
  device's actual screen brightness.
- Wi-Fi is removed from the app and the firmware: wireless use is Bluetooth
  only. Pairing no longer asks for a network or password (`PAIR,<key hex>`),
  `NET` drops the Wi-Fi fields (`NET,<key id>,<name>,<0 or 1>`), the firmware
  no longer includes the Wi-Fi and TCP/IP stack, and the knob erases the
  network name and password that earlier firmware saved. The app drops its
  saved Wi-Fi network and knob address too.
- The screensaver library now starts with a built-in colourful **Moon**
  picture, centred to fill the round screen. It replaces the earlier moon
  pictures; existing libraries get it once, and removing it keeps it removed.
- The ring on the small knob at the top of the sidebar always shows the bar
  colour: the colour you picked, or the current screen's own colour in the
  standard style.
- The knob no longer jumps to Volume whenever the app connects or reconnects
  (starting Revo1, a reinstall, a cable or Bluetooth link): it opens
  its main menu instead. Value updates no longer close a menu opened on the
  knob either. `STATE` gains an optional keep-view field for this.
- The screensaver's seconds ring now follows the **Time colour**, on the knob
  and in the preview.
- Five animated seconds ring styles, laid out in a second row: **Walker** (a
  little man walking round the edge, lighting the minute behind him),
  **Snake**, **Sparkle** (a comet shedding twinkling sparks), **Orbit** (a
  planet with a moon circling it) and **Heartbeat** (a monitor trace). `SAVER`
  accepts ring values 6 to 10 for them. The knob redraws only the parts that
  move, so each frame stays within about 5 to 13 ms.

- Pomodoro on the knob and in the preview: **FOCUS** or **BREAK** moved above
  the time, and the timer icon sits below it like the other screens.

- New **Bar style** choice under Settings > Interface, beside the bar colour:
  **Glowing tip** (the default, listed first), **Fade to solid**, **Soft
  gradient** or **Solid**. The knob keeps it across restarts; `STYLE` gains an optional third
  field for it.
- The level ring's dark-to-bright gradient now eases into one even colour
  from 85% up, so a full ring closes without a seam where the dark start met
  the bright end. At 100% the white end mark is hidden too.

- Pomodoro: once a timer has started, turning the knob adds or removes a
  minute per click.
- Dashboard tiles are more compact, and the Screensaver tile has its own
  colour like the others. The Brightness screen shows its icon on the knob
  and in the preview.
- Media players without Windows media controls (Stremio, for example) now
  work with the knob: the time counts up from when Revo1 noticed playback,
  and turning the knob seeks 10 seconds per click by sending the arrow keys
  to the player (which is briefly brought to the front). With no known length
  the knob shows the elapsed time alone. Next and previous do what the player
  does with them: Stremio only skips between episodes.
- Whack-a-Mole: the app saves your last and best scores and shows them on the
  Games page. On connecting it sends its best to the knob (`GAMEBEST`), so a
  reflashed knob gets its record back.
- The Settings and Screensaver pages are tighter: forms, switches and sliders
  use a comfortable width instead of the whole page, buttons fit their text,
  choice buttons are smaller and closer together, and the Wireless cards are
  shorter.

- Dashboard tiles are taller and show only what matters: the value, plus
  **Muted**, **Paused** or **Break** when that applies. Gone: the screensaver
  picture count, Pomodoro's "Focus · ready", and Media's "Playing".
- On the knob (and its preview in the app), Scroll and Zoom show the
  screen's icon in the middle with its name below, like the other screens.
- The top of the sidebar shows a small knob next to the name, with a ring
  in the bar colour. Below the name, an icon and label show
  the link in use: USB cable or Bluetooth.
- Wireless is now automatic: once the knob is paired, unplugging the cable
  is enough for Revo1 to find it over Bluetooth. The **Use
  wireless when the cable is unplugged** switch is gone.
- Fixed: Revo1 could refuse to start ("Invalid settings") when its settings
  file held a value it didn't know, for example one written by a newer
  version. Such a value now falls back to its default, and every other
  setting, the wireless pairing included, is kept.
- When the app isn't running, or isn't reachable over USB or
  Bluetooth, the knob now shows **Not connected** and "Open Revo1 on your
  PC" around a large icon in the centre (the heading above it, the hint
  below, in the same type), instead of the dashboard or any other screen, and goes back to its screen
  when the app returns. The app answers each `HELLO` with a new `APP`
  heartbeat, so update the app and the firmware together: an older app would
  leave the knob showing Not connected.
- Closing Revo1 (the window's close button or **Quit** in the notification
  area) now asks first, since the knob disconnects until the app runs again;
  during a firmware update it warns that closing stops the update.
- Fixed: a quick Bluetooth disconnect and reconnect could feed bytes from the
  old connection into the new handshake and drop it.
- The Media screen now also follows players that don't report to Windows'
  media controls, such as Stremio: any app making sound is shown by its
  window title, as playing or paused, and play/pause, previous and next are
  sent straight to it. When several players are open, the one playing wins
  over Windows' "current" one (which could stay on a paused Spotify).
- The Mic screen is now called **Microphone** on the knob and in the app.
  Saved settings and the protocol still use `Mic`/`MIC`.
- Screensaver clock colours: on **Screensaver > Display**, choose the time
  colour (presets or any colour) and, for **Date and time**, the background;
  the date, AM/PM and ring track follow. **Pictures and time** can turn the
  dark shade behind the time off. The clock format is now a pair of radio
  buttons, and the preview warns when the colours are hard to read. New
  protocol line `SAVERLOOK`, saved on the knob.
- The level screens (Volume, Scroll, Brightness, Mic, Zoom) no longer show
  arrows either side of the value, on the knob or in the app.
- Wireless: pair the knob once over USB in the new **Settings > Wireless**
  tab, then use it over Bluetooth LE whenever the cable is unplugged. USB
  always takes over when it's plugged in. The tab shows which link is in use.
  The link is end-to-end encrypted: a mutual HMAC-SHA256 challenge, then
  AES-256-GCM frames with per-session keys. The PC keeps the key protected
  by Windows (DPAPI). New
  protocol lines `PAIR`, `UNPAIR` and `NET`. The app needs `bleak` for
  Bluetooth.
- Firmware updates from the app keep the knob's saved settings and pairing:
  the NVS range of the merged image is no longer written.
- New Games screen: a round card per game on the knob and a grid of game
  cards in the app (with "Soon" placeholders), starting with Whack-a-Mole.
  Turn the knob to aim at one of seven holes and touch to whack; gold moles
  are worth +3 and bombs cost -3. The knob keeps the best score, and the
  app's Games cards show your last and best scores.
- The app window is taller so the sidebar fits all eight screens, and wider:
  the dial sits on the left with the screen's name, help and buttons beside
  it, and the Dashboard and Games show three cards per row (the Dashboard
  is a 3 by 3 grid).
- Whack-a-Mole is aimed with the knob only; touching a hole no longer picks it.
- Mute for the PC's sound and microphone: a button beside the Volume and Mic
  dials in the app, or a tap on the mute icon at the centre of the knob.
  Muted controls show a red crossed-out icon and **MUTED** on both, and
  muting from Windows is picked up.
- The date and time screensaver is much bigger: the time in 96 px Montserrat
  Medium (the app's font), with a larger date and AM/PM.
- Choose **24-hour** (the default) or **AM/PM** for the screensaver clock on
  the Screensaver page, instead of following the Windows time format.
- The Screensaver page has four tabs that fit the window without resizing
  it: General (screensaver and dimming on or off, plus summary cards),
  Timing (when it starts and how long each picture stays), Display (what it
  shows, a preview of the knob, the clock format and seconds ring) and
  Pictures (the library). All choice buttons are the same size.
- New screensaver choice, **Pictures and time**: the time and date over your
  pictures, each picture darkened in the middle so the time is readable
  (`SAVER` kind 2). Until the app has set the knob's clock it shows the
  pictures alone.
- Pictures can stay on for **3 min** each.
- The seconds ring round the screensaver clock now also shows over pictures,
  and has six styles: Bullets, Bar, Wiggly, Ticks, Comet or None (an
  optional sixth `SAVER` field). The wiggly ring grows smoothly at about 25
  frames a second: only its tip sways, and the body behind it stays still.
  Picking a ring style while the screensaver is on changes it in place.
- Every seconds ring style now moves smoothly between seconds: the next bullet
  or tick fades in, the bar and the comet glide on, and at the end of each
  minute the ring fades out instead of vanishing at once.
- Removing every picture and sending the empty collection takes the knob back
  to its menu instead of the last screen.
- The screensaver preview in the app no longer draws a coloured bezel inside
  the seconds ring, so only one ring shows, as on the knob.
- Settings sits with the other screens in the sidebar.

## 1.0.1 - 2026-09-30

- Simpler back icon on the dial: a plain chevron instead of an arrow in a ring.
- Firmware text buffers sized for ESP-IDF's stricter warnings; release
  firmware is now built with ESP-IDF 5.5.2 in CI.

## 1.0.0 - 2026-09-30

First public release.

- Custom firmware for the Waveshare ESP32-S3-Knob-Touch-LCD-1.8 with a
  Nest-style sculpted dial and a full-ring gauge.
- Windows companion app with the same dial, kept in sync with the knob.
- Controls: volume, scrolling, brightness, microphone, zoom and media
  (title, artist, progress, play/pause, previous, next, seek).
- Radial icon menu opened from the back icon at the top or the centre; knob to choose,
  tap to confirm.
- Pomodoro screen: focus and break lengths, start/pause from the app or by
  tapping the knob, a countdown ring on the device and a chime on the PC at
  each change of phase.
- Dashboard as the app's first page: live values for every screen and a
  switch per screen to hide it from the knob's menu and swipes (`SCREENS`).
- Screensaver: pictures, animated GIFs and videos are cropped to the round
  screen, stored in a 12.9 MB `media` flash partition and shown
  in rotation after a chosen idle time; a touch or a turn wakes the dial.
  Videos are read by FFmpeg (LGPL build), which the app downloads once, with
  your permission, the first time you add one; it isn't bundled.
  The screensaver can show the date and time instead (`TIME`, `SAVER`).
- Idle dimming: after 10 minutes without input the backlight drops 10 points
  every 5 minutes until it is off; any touch or turn restores it (`DIM`).
- Screen backlight slider in **Settings > Device** (`BACKLIGHT`).
- Settings: device name, automatic device detection, screen orientation,
  bar colour (standard, preset or custom), number size, and separate
  **Invert scroll** / **Invert zoom** switches for the knob direction, and a
  **Swipe between screens** switch to turn off swiping on the knob (`SWIPES`).
- Optional minimise to the notification area (tray), also used when started
  at sign-in.
- About page: app and firmware versions, the latest GitHub release, and a
  one-click firmware update over USB. The firmware reports its version with
  `VERSION,<x.y.z>`; it's taken from `revo1/__init__.py` at build time.
  **Install from file...** flashes a downloaded or locally built image, after
  checking that it really is Revo1 firmware.
- The knob keeps its last control, orientation, colour, number size,
  backlight, visible screens and swipe, dimming and screensaver settings in
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
