# Revo1

**Turn a Waveshare round knob display into a beautiful volume, scroll,
brightness and media controller, app launcher, Pomodoro timer and photo frame for Windows.**

[![CI](https://github.com/guilhermelimait/Revo1/actions/workflows/ci.yml/badge.svg)](https://github.com/guilhermelimait/Revo1/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Windows](https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-0078D6)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-support-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/guilhermelimait)

Revo1 is custom firmware for the
[Waveshare ESP32-S3-Knob-Touch-LCD-1.8](https://link.amazon/B061NfG3G)
(a 360 x 360 round touch screen
with a rotary knob) plus a Windows
companion app. The screen and the app draw the same Nest-style dial: a light,
sculpted Light or Dark face with a glowing arc in the control's colour, and they stay in
sync as you turn the knob.

## Latest update: 1.1.1

Fixes clipped Settings and Screensaver tab labels, and coloured patches in
transparent GIFs and pictures. Reimport affected media and send the collection
again to update the knob. Existing 1.1.0 firmware remains compatible.

See the [1.1.1 release notes](docs/releases/1.1.1.md).

## What's new in 1.1.0

**A more personal, polished controller across your PC and round display.**
This release adds a seven-app launcher, Light/Dark/System themes, configurable
desktop feedback, Whack-a-Mole, richer screensavers, and Bluetooth-only wireless
controls. Settings now use consistent typography, spacing and accessible navigation.

See the [release overview and screenshots](docs/releases/1.1.0.md) for the highlights,
or the [changelog](CHANGELOG.md) for the full changes since 1.0.1.

<table>
  <tr>
    <th>Dashboard</th>
    <th>Pomodoro</th>
  </tr>
  <tr>
    <td><img src="./docs/images/app-dashboard.png" alt="Dashboard" width="400"></td>
    <td><img src="./docs/images/app-pomodoro.png" alt="Pomodoro timer" width="400"></td>
  </tr>
  <tr>
    <th>Volume</th>
    <th>Media</th>
  </tr>
  <tr>
    <td><img src="./docs/images/app-volume.png" alt="Volume dial" width="400"></td>
    <td><img src="./docs/images/app-media.png" alt="Media screen" width="400"></td>
  </tr>
  <tr>
    <th>Menu</th>
    <th>Settings</th>
  </tr>
  <tr>
    <td><img src="./docs/images/app-menu.png" alt="Radial menu" width="400"></td>
    <td><img src="./docs/images/app-settings.png" alt="Settings" width="400"></td>
  </tr>
  <tr>
    <th>Screensaver</th>
    <th>App launcher</th>
  </tr>
  <tr>
    <td><img src="./docs/images/app-screensaver.png" alt="Screensaver" width="400"></td>
    <td><img src="./docs/images/app-launcher.png" alt="Transparent app launcher icons in Dark mode" width="400"></td>
  </tr>
  <tr>
    <th>Dark mode</th>
    <th>Desktop feedback</th>
  </tr>
  <tr>
    <td><img src="./docs/images/app-dashboard-dark.png" alt="Dashboard in Dark mode" width="400"></td>
    <td><img src="./docs/images/app-overlays.png" alt="Bottom pill and top notch in Standard and Minimal layouts" width="400"></td>
  </tr>
</table>

*Screenshots of the Windows app; the device shows the same dial.*

## Features

- **Nine screens:** system volume, mouse-wheel scrolling, display brightness,
  microphone level, zoom (Ctrl + wheel), media playback, a Pomodoro timer and
  Games and App launcher.
- **App launcher:** choose up to seven desktop or Microsoft Store apps, or
  browse for an executable or app shortcut. On the knob, turn to select an
  app and tap the centre to open it on the PC. All configured icons are
  visible around the ring, like the home menu. Revo1 must be running,
  over USB or paired Bluetooth. Paths stay in this PC's local settings;
  only app names and icons are sent to the device.
- **Dashboard:** every screen at a glance with its live value, and a switch
  to hide the ones you don't use from the knob's menu and swipes.
- **Pomodoro:** pick the focus and break lengths, then tap the dial (on the
  knob or in the app) to start or pause. The ring counts down on the knob,
  and the PC plays a chime when it's time for a break and when the break
  ends. Once the timer has started, turning the knob adds or removes a
  minute per click.
- **Games:** a round card for each game, played on the knob; the app shows
  every game as a card in a grid, with your scores. The first is
  Whack-a-Mole: turn to aim at one of seven
  holes and touch to whack. Gold moles are worth 3 points and bombs cost 3.
  A round lasts 30 seconds and gets faster as it goes. The knob keeps your
  best score, and the app saves your last and best scores (and gives the
  best back to a reflashed knob).
- **Screensaver:** add pictures (JPEG, PNG, BMP, WebP, ...), animated GIFs
  or short videos (MP4, MOV, AVI, MKV, WebM). Revo1 crops them to the round
  screen and stores them on the knob (up to about 12.9 MB), which shows them
  in rotation after the minutes of idle time you choose. Or show the **date
  and time** instead, with a ring of second marks. A touch or a turn brings
  the dial back.
- **Screen backlight** adjustable from the app, and optional **idle dimming**:
  after 10 minutes without a touch or a turn the backlight drops by 10 points
  every 5 minutes until the screen is off, and comes straight back on the
  next touch or turn.
- **Media screen** for whatever is playing (Spotify, a browser tab, ...):
  title, artist, progress ring, and big play/pause, previous and next buttons.
  Turning the knob seeks 5 seconds per click. Players that don't report to
  Windows' media controls (Stremio, for example) are picked up from their
  sound: the knob shows the app's window title and how long it has been
  playing (counted from when Revo1 noticed it), play/pause, previous and next
  go straight to that app, and turning the knob seeks 10 seconds per click
  by sending the arrow keys to the player, which briefly comes to the front.
  Previous and next do what the player does with them: Stremio only skips
  between episodes.
- **Radial menu:** tap the centre or the back icon, turn to choose, tap to
  confirm. It opens on the control you used last.
- **Always in sync:** the knob, the screen and the app window show the same
  value, and volume changes made elsewhere in Windows show up on the knob.
- **Knows when the app is gone:** if Revo1 isn't running, or isn't reached
  over USB or Bluetooth, the knob shows **Not connected** instead of
  any screen, and opens its main menu as soon as the app answers.
- **Personalise it:** one colour per control or a single colour of your
  choice, four sizes for the big number, and screen orientation in 90 degree
  steps.
- **A real Windows app:** a one-click installer, Start Menu entry, optional
  start at sign-in, and a clean uninstall. It remembers all settings between
  runs, and can minimise to the notification area.
- **Light, Dark or System:** one saved appearance for the companion and device,
  with consistent controls and circular colour swatches.
- **Desktop feedback:** choose a translucent bottom pill or solid-black top notch,
  Standard detail or a centred Minimal icon/value, and exactly which actions appear.
  It works in the tray without taking focus or blocking clicks.
- **Wireless:** pair the knob once over USB, then use it over **Bluetooth**
  whenever the cable is unplugged (the knob still needs power,
  from a battery or a USB charger). Settings > Connection also lets you
  connect or disconnect Bluetooth explicitly. The wireless link is end-to-end encrypted with AES-256-GCM
  and a key only your PC and the knob hold.
- **Updates from the app:** the About page shows the newest release on GitHub
  and installs its firmware on the knob with one click.

## What you need

- A **Waveshare ESP32-S3-Knob-Touch-LCD-1.8**
  ([buy on Amazon](https://link.amazon/B061NfG3G)) and a USB-C data cable.
- Optional, for wireless use: Bluetooth on the PC, and power for the knob away from the PC (a battery or a USB charger).
- **Windows 10 or 11** (x64 or ARM64). Nothing else: Python is bundled.

*The Amazon link is an affiliate link: as an Amazon Associate I earn from
qualifying purchases, at no extra cost to you.*

## Get started

### 1. Install the app

Download **`Revo1-Setup-<version>.exe`** from the
[latest release](https://github.com/guilhermelimait/Revo1/releases/latest)
and run it. (On a Windows on ARM PC, `Revo1-Setup-<version>-arm64.exe`
is the native build; the regular one works too.)

- It installs for your user only, so no administrator prompt, into
  `%LOCALAPPDATA%\Programs\Revo1`.
- It adds **Revo1** to the Start Menu and, if you keep the box ticked,
  starts it when you sign in.
- Installing a newer version over it closes the running app and keeps your
  settings. Remove it any time from **Settings > Apps > Installed apps**.

The installer is not code-signed yet, so Windows SmartScreen may say
"Windows protected your PC". Click **More info > Run anyway**.

### 2. Flash the firmware (once)

**Upgrading from 1.0.x:** install the matching **1.1.0 app and firmware**.
The transparent launcher icons use a new alpha-aware format; older firmware
rejects it explicitly. Wireless is now Bluetooth only: former Wi-Fi settings are
removed. Existing PC preferences, app choices and valid Bluetooth pairing are
preserved. The swipe setting is no longer exposed in the app, but an existing
saved preference still applies.

Download `revo1-firmware-<version>.bin` from the same release, and this
repository (**Code > Download ZIP**) for the flashing script.

The knob's single USB-C socket reaches a **different chip depending on which
way round the plug is inserted**. Revo1 needs the ESP32-S3, which
Windows lists as a *USB Serial Device* (USB ID `303A:1001`). If it shows up as
a *CH340* port instead, unplug the cable, turn the plug over and plug it back in.

In PowerShell, in the downloaded folder:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\flash-firmware.ps1 -Firmware <path to revo1-firmware-*.bin>
```

The script finds the device, downloads Espressif's standalone `esptool` the
first time (no Python needed), **saves a full backup of the current flash** to
`backups\` before the first Revo1 flash, and then writes Revo1.
To go back to the original Waveshare firmware later:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\flash-firmware.ps1 -Restore .\backups\flash-backup-COM9.bin
```

(Use your own backup file name. Keep it: it is the only copy of the stock
firmware.)

Then start Revo1 from the Start Menu. The ring on the little knob beside
the name always shows your bar colour. Once the knob answers, the line
below it shows how the knob is linked: **On USB cable** or **On Bluetooth**.
Below **On Bluetooth**, a battery icon and percentage show a voltage-based charge estimate.
It is hidden on USB, when disconnected, or if the reading is unavailable or
stale. The knob shows the same estimate near the bottom of control screens,
not in its home menu, offline screen, screensaver or any Games view. On Media,
the estimate sits above the playback controls, clear of the track and artist.
The percentage is approximate: this is not a fuel gauge, and load, temperature
and battery condition affect the reading.
On USB, a lightning icon and **USB power** replace the battery estimate
on the PC dashboard only; the device shows no USB power label. This identifies the app's USB connection,
not verified charging status.

## Using it

**On the device**

- **Turn** the knob to change the current control.
- **Swipe** left or right to switch to the next or previous control (you can
  turn this off in **Settings > Controls**).
- **Tap the back icon** at the top (or the centre) to open the menu. Turn to
  move the highlight, then tap to confirm, or tap an icon directly.
- On the **Volume** and **Microphone** screens, tap the centre to mute or unmute the
  PC's sound or microphone. A speaker or microphone icon under the number
  marks the spot; while muted it turns into a red crossed-out icon, the
  number greys and **MUTED** shows above it.
  The back icon still opens the menu.
- On the **Pomodoro** screen, **FOCUS** or **BREAK** sits above the time and
  the timer icon below it. Tap the dial to start or pause the timer.
  Once it has started, turn the knob to add or remove a minute per click.
- The **Games** screen opens on the game cards. Turn the knob to pick a
  card (once there is more than one game) and tap it to play. In
  Whack-a-Mole, turn the knob to move the ring between the holes and touch
  anywhere to whack the hole under the ring (only the knob aims). The
  ring around the edge shows the time left. After a round, tap the centre to
  play again, or tap the back icon to return to the cards.
- The app's **Games** screen shows every game as a card in a grid, with your
  best and last scores. Cards marked **Soon** are games still to come.
- While the **screensaver** runs, or when idle dimming has turned the
  screen off, a touch or a turn wakes the dial (that first touch or turn
  does nothing else).
- On the **media** screen, tap play/pause, previous or next.
- Open **App launcher** from the main menu. Turn the knob to move through
  configured apps (empty slots are skipped), then tap the centre to launch.
  All app icons appear around the face; the coloured ring segment highlights
  the selected app, whose name appears in the centre. Tapping an app icon
  directly selects and launches it, just like the home menu.
  The separate back arrow stays at 12 o'clock, above the app icons, and
  returns to the main menu. Turning selects apps only, not Back.
  The USB power label is hidden on this submenu; the Bluetooth battery
  percentage remains visible.
  Launch feedback appears beneath the
  name; Windows may still ask for permission if the chosen app needs it.

The knob has no push button.

**In the app**

The dial in the window mirrors the device and accepts clicks the same way;
beside it are the screen's name, a short note on using it and its buttons.
The app opens on the **Dashboard**, a three-column grid of tiles: click a tile to
open that screen, or its switch to show or hide it on the knob (at least one stays on).
Each tile shows just its live value: the level (with **Muted** in red when
muted), the song playing (or **Paused**), the Pomodoro time left (with
**Break** during a break), and when the screensaver starts. Pick a control
in the left sidebar.

- **Volume and Microphone:** the **Mute sound** / **Mute microphone** button beside
  the dial (or a click on its centre) mutes the PC; it turns red with
  **Unmute** while muted. Muting from Windows shows up here and on the knob.
- **Pomodoro:** set the focus and break minutes with **-** / **+** (or turn
  the knob while the timer is stopped), then **Start**, **Pause** or
  **Reset**. The timer runs in the app, so keep Revo1 running (it can sit
  in the notification area).
- **App launcher:** seven slots with **Choose app**, **Replace** and **Clear**.
  Saved app rows have no added tile background. Windows icon transparency is
  preserved on the PC and transmitted to the device, where icons blend directly
  over the Light or Dark face; selection remains indicated by the ring segment.
  This requires the matching alpha-aware firmware. Backgrounds painted into an
  app's own artwork are preserved rather than deleting legitimate icon colours.
  Search the installed-app list with icons (including Microsoft Store apps).
  Everyday apps show by default; **Show all apps** reveals administrative
  tools, help files, uninstallers and developer utilities.
  Use **Browse...** to select `.exe`, `.lnk`
  or `.appref-ms` files. Choices are saved locally and names/icons sync on
  connection and after edits. An empty launcher tells you to choose apps in
  Revo1. Store apps use their registered Windows app identity rather than
  a path into the protected WindowsApps folder. Apps are not bundled or
  uploaded to GitHub.
- **Screensaver:** four tabs, each fitting the window. **General** switches the screensaver and
  **Dim the screen** on or off, with **At a glance** cards summing up the
  settings (click one to change it). **Timing** has **Start after** (1, 2, 5,
  10 or 30 minutes idle) and **Each picture** (10 s, 30 s, 1, 3 or 5
  minutes). **Display** picks what the knob shows: **Pictures**, **Date and
  time**, or **Pictures and time** (the time and date over your pictures,
  with the middle of each picture darkened so the time stays readable). A
  preview of the knob sits beside that choice's settings: **Clock**
  (**24-hour**, the default, or **AM/PM**), the **Seconds ring** round the
  edge, in two rows (**Bullets**, **Bar**, **Wiggly**, **Ticks**, **Comet**,
  the animated **Walker** (a little man walking round), **Snake**,
  **Sparkle** (a comet shedding twinkling sparks), **Orbit** (a planet with
  a moon circling it) and **Heartbeat** (a monitor trace), or **None**; on
  the knob every style moves smoothly between seconds, and **Wiggly** has a
  rippling tip) and **Time colour** (seven presets or **+** for any colour;
  the seconds ring, date, AM/PM and the ring's track follow it). **Date and time**
  also has **Background**, the clock face colour; **Pictures and time** has
  **Shade**, which darkens the picture behind the time (on by default). If
  the time and background are too close, the preview warns **Hard to read**.
  **Pictures** holds your pictures and clips. It starts with a built-in
  colourful **Moon**, centred with the new picture's black margin (remove it
  and it stays removed). This version replaces the previous built-in Moon
  without removing custom pictures; click **Add pictures or videos...** to add more. Pictures are
  cropped around their centre. Hover a thumbnail
  and click the cross to remove it. **Send to knob** copies the collection
  to the device (about 110 KB/s, so a full collection takes about two
  minutes); the line under the buttons says whether the knob is up to date.
  Sending an empty collection clears the knob, which then goes back to its
  menu.
  Transparent pictures and GIF frames are composited over black; transparent
  areas do not expose hidden palette colours or the previous picture.
  Videos keep their first 20 seconds at 10 frames per second. The first time
  you add a video, Revo1 asks to download FFmpeg (an LGPL build, about
  80 MB, into `%LOCALAPPDATA%\Revo1\tools`) to read it; if `ffmpeg` is
  already on your `PATH`, that one is used.

**Settings** has five tabs:

- **Device:** a dedicated **Device name** field at the top, followed by screen
  backlight and battery saver. Fresh installations use **Revo1**; upgrades keep
  existing custom names. Press Enter or leave the field to save. Blank names
  return to Revo1, and leading/trailing spaces are removed.
  USB discovery is automatic and verifies the companion firmware, including
  when several ESP32 serial ports are present; USB status and port controls
  are not shown in Settings.
  **Battery Saver** is a manual switch, for battery or USB use. It caps the
  backlight at 40% (20% in the screensaver), dims to at most 10% after
  30 seconds without touching or turning the knob, and switches the display
  off after five minutes. A touch or turn wakes it without triggering a
  control. Screensaver rings and videos run at up to five frames per second;
  decoding and animation stop while the display is off. Your normal
  brightness setting is kept, and the mode survives a device restart.
  Battery charge is estimated from voltage during Bluetooth use; charging
  detection and automatic battery-only activation are not available.
- **Controls:** the screen orientation (0, 90, 180 or 270 degrees) and
  **Knob direction**: **Invert scroll** and **Invert zoom** swap what a
  clockwise turn does (the comet on the dial still follows your hand).
  The swipe-between-screens option is no longer shown; existing preferences
  and device swipe behaviour are retained.
- **Interface:** **App appearance** offers **Light**, **Dark**, or **System**.
  Settings tabs stay visible above a scrollable content area, with larger
  controls, grouped sections, and wrapped help and error text. Use the mouse
  wheel or scrollbar on longer pages. Tab moves through controls; Enter or
  Space activates buttons, Left/Right switches focused Settings tabs, and
  Left/Right adjusts a focused device-backlight slider. Focusing a control
  below the viewport automatically brings it into view.
  Throughout the PC app, action buttons, choice cards and text fields share
  a 10-pixel soft corner radius. Action buttons use a 40-pixel height, while
  larger choices retain room for previews. Dashboard, Screensaver, Games,
  App launcher, Settings and app-owned dialogs share Montserrat typography,
  sentence-case labels, page margins, section spacing and selection colours.
  Settings and Screensaver tabs share the same height, text and underline
  treatment. Longer Screensaver pages also scroll beneath fixed tabs, with
  larger seconds-ring choices and no hidden bottom controls. Both themes use
  contrast-checked text and status colours.
  Circular switches, colour samples, sliders and round device previews keep
  their purpose-specific geometry.
  The choice is saved and applies immediately to every companion page,
  the app picker, and Revo1's confirmation and error windows. **System**
  follows the Windows app theme, including changes while Revo1 is running.
  The round device screen and its preview follow the same resolved theme,
  with the last theme saved on the device for disconnected use. Pictures,
  app icons, and your chosen screensaver clock colours remain unchanged.
  Windows-owned file and colour pickers use Windows styling.
  **Interface → Control overlay** offers an on/off switch, **Bottom pill**
  (the default, translucent above the taskbar) or **Top notch** (small, solid
  black, attached to the top centre of the foreground window's monitor).
  Both appear only during changes and disappear afterwards. **Show feedback for**
  lets you independently choose volume, scroll, brightness, microphone, zoom,
  media, Pomodoro, game scores and app-launch confirmations; these choices do
  not change the device menu. All start enabled, and you can deselect all.
  **Standard / Minimal** applies to either style: Standard (the default) keeps
  the control label and progress bar; Minimal uses a smaller surface showing
  only the icon and current value or action, centred together with smaller
  value text and no icon badge background. The detail preference is saved.
  Accent and screensaver clock colour swatches are circular, with a selection
  ring; other buttons keep the shared rounded-rectangle shape.
  Volume, microphone and PC brightness show their percentage;
  scrolling and zoom show direction rather than inventing a percentage. Media
  actions and Pomodoro adjustments show their action or time. The compact overlay
  uses a black background (62% opacity for the pill; opaque for the notch), regardless of the app theme, with
  your exact accent colour at full opacity for the icon and level bar (no tint or
  desaturation). It works while Revo1 is in the tray, does not take focus,
  and lets clicks pass through. It fades after 1.6 seconds without another change
  (no fade when Windows animations are disabled). Changes from Windows or other
  apps do not trigger it. Turn it off under **Interface → Control overlay**.
  **Standard** colours (one per control), a swatch, or
  **Custom...** for any single bar colour; the **bar style** (**Glowing
  tip**, the default, an even bar whose end brightens; **Fade to solid**, a
  deep-to-bright gradient that turns into one colour near 100%; **Soft
  gradient**; or **Solid**); and **Center text size** (Small, Medium,
  Large or X-Large). Under **Window**, turn on **Minimise to the notification
  area** to hide Revo1 next to the clock when you minimise it (click the
  icon to bring it back, right-click for **Quit**). When it's on, the
  start-at-sign-in shortcut starts it there too. Closing the window or
  choosing **Quit** asks first, since the knob stops working until Revo1
  runs again (and warns harder during a firmware update).
- **Connection:** shows Bluetooth only, with **Connect** and **Disconnect**.
  Status and the action sit together in one compact row, with pairing help
  directly underneath. Errors wrap below without expanding the status control.
  For first-time setup or recovery after forgetting a pairing, connect the
  cable and choose **Connect**. Revo1 creates an encrypted shared key and
  then connects over Bluetooth, even while the cable remains plugged in.
  The key is protected on the PC by Windows for your user account.
  **Disconnect** keeps the pairing but pauses Bluetooth reconnection, including
  after restarting the app, until **Connect** is chosen again. In automatic
  operation USB remains available internally, and Bluetooth takes over when
  the cable is unplugged. Discovery and connection errors are shown explicitly.
- **About:** links to GitHub, the releases, the licence and Ko-fi; the app
  description, update values and messages use padded, wrapping text so
  characters are not cut off at display scaling boundaries. Shows the app
  version, the firmware version on the knob, and the latest release on
  GitHub. When the release has newer firmware than the knob, **Update
  firmware** downloads and flashes it (the first time it also downloads
  Espressif's standalone `esptool`, about 65 MB); keep the cable plugged in
  until it says it's done. **Install from file...** flashes a
  `revo1-firmware-x.y.z.bin` you downloaded or built yourself; it's always
  there while a knob is connected, and it refuses files that aren't a Revo1
  image. **Update app** opens the release page when there's a newer
  installer. Updating keeps the knob's settings and its wireless pairing.

Settings are saved in `%LOCALAPPDATA%\Revo1\settings.json` straight
away. The knob also remembers its last control, orientation, colour, number
size, backlight, visible screens, swipe, dimming and screensaver settings, so
it comes back the same way after a restart, even before the app is running. Volume, microphone and brightness levels are always read from Windows,
never overwritten with old saved values.

## Troubleshooting

- **"Waiting for companion firmware".** The app found a serial port but no
  Revo1 firmware answered. Flash the firmware (step 2), and check you
  are on the ESP32-S3 side of the USB-C plug.
- **"Not connected" and no device in Settings.** Turn the USB-C plug over, or
  try another cable (some cables only charge).
- **Turning the knob changes nothing.** The screen only shows what the PC
  sends, so the app must be running. The control may also already be at its
  limit (brightness is often at 100%): turn the other way.
- **Brightness does nothing.** Brightness is set through Windows' WMI
  interface, which normally covers built-in laptop screens only. Most external
  desktop monitors are not supported yet.
- **Bluetooth doesn't connect.** Check Settings > Connection for the error.
  Choose **Connect** to resume a deliberately disconnected Bluetooth link.
  If pairing was forgotten or the keys do not match, plug in the cable and
  choose **Connect** to set it up again. The device's disconnected symbol
  means it has no companion link; it does not mean its screen has frozen.
  Make sure Bluetooth is on in Windows and keep the knob within a few metres
  of the PC.
- **Song titles show "?".** The device fonts only have Latin letters. Accents
  are removed ("Musica" for "Música"); other scripts, such as Japanese,
  show as "?".

## Limitations

- Windows only (it uses Windows audio, brightness and media APIs).
- Brightness works on screens Windows can dim through WMI (usually laptops).
- No album artwork yet: the serial link is line-based text.
- Games run on the knob only. The app shows the board and your scores but
  you can't play in the window.
- The Pomodoro timer and its chime run in the app: the knob shows the time
  but doesn't count on its own.
- The knob has no clock battery: the date and time screensaver starts once
  the app has connected after the knob was powered on.
- Video playback on the knob is 10 frames per second, without sound.
- Wireless links one PC at a time. Pairing and firmware updates need the
  USB cable. Bluetooth is about half as fast as USB (about 57 KB/s), so
  sending screensaver pictures over it takes longer.
- The knob stores its pairing key in plain flash (it has no flash
  encryption), so someone with the device in hand could read it.
  Revo1 has no Wi-Fi, so the knob never holds a
  network password (firmware from this version on also wipes one saved by
  earlier versions).

## Development

Needs Python 3.10 or newer.

```powershell
python -m pip install -r requirements.txt
python -m revo1                        # run from source
.\packaging\build.ps1                         # Revo1.exe + installer in dist\
```

- `packaging/build.ps1` bundles the app with PyInstaller
  (`packaging/Revo1.spec`) and wraps it with
  [Inno Setup 6](https://jrsoftware.org/isinfo.php)
  (`packaging/Revo1.iss`). The installer matches the architecture of the
  Python that builds it. `packaging/make_icon.py` regenerates the app icon
  from the dial renderer.

- `revo1/` is the Windows app (Tk + Pillow). `dial.py` is a Python copy
  of the firmware's dial renderer, so the window matches the screen pixel for
  pixel; keep it in step with `firmware/main/main.c`.
- `firmware/` is the ESP-IDF / PlatformIO project; see
  [firmware/README.md](firmware/README.md) for how to build it and how the
  renderer, encoder and touch handling work.
- GitHub Actions checks the code and builds the installers and the firmware on
  every push. Pushing a `v*` tag publishes a release with
  `Revo1-Setup-<version>.exe`, the ARM64 installer and the merged
  firmware image.

## Protocol

USB serial: 115200 baud, ASCII lines terminated by `\n`. The same lines run
over Bluetooth LE inside an encrypted session; see
[firmware/README.md](firmware/README.md#wireless) for the handshake and
framing.

| Direction | Message | Meaning |
| --- | --- | --- |
| Device to PC | `HELLO,REVO1,1` | Companion handshake, every second |
| PC to device | `APP` | Heartbeat: the app answers every `HELLO`; after 3.5 s without any line from the app the knob shows **Not connected** |
| Device to PC | `VERSION,<x.y.z>` | Firmware version, right after each `HELLO` |
| Device to PC | `SYNC` | Sent with `HELLO` until the first `STATE` after a restart; the app resends style and state |
| Device to PC | `ROT,<signed steps>` | Knob movement |
| Device to PC | `MENU` | Centre (except on Volume, Microphone, Pomodoro and App launcher) or back-icon tap opens the menu |
| Device to PC | `TAP,<0..8>` | Menu choice confirmed (mode index) |
| Device to PC | `CURSOR,<0..8>` | Knob moved the menu highlight (mode index) |
| Device to PC | `SWIPE,LEFT` or `SWIPE,RIGHT` | Change control |
| PC to device | `STATE,<MODE>,<0..100>,<0\|90\|180\|270>[,<1 keep>]` | Set screen state; with keep an open menu stays open (value updates and connecting), without it the knob opens `MODE` |
| PC to device | `SHOWMENU` | Show radial menu |
| PC to device | `COMETRESET` | Put the scroll/zoom comet back at its start (sent on connect) |
| PC to device | `STYLE,<STANDARD\|RRGGBB>,<24\|32\|40\|48>[,<bar style 0-3>]` | Bar colour, number size and bar style (0 glowing tip, 1 fade to solid, 2 soft gradient, 3 solid) |
| Device to PC | `MEDIA,PREV\|PLAYPAUSE\|NEXT` | Transport icon tapped |
| PC to device | `TRACK,<title>` | Now-playing title |
| PC to device | `ARTIST,<artist>` | Now-playing artist |
| PC to device | `PLAY,<0\|1\|2>,<position s>,<duration s>` | Playback state (0 stopped, 1 playing, 2 paused) |
| PC to device | `SCREENS,<mask>` | Screens shown on the knob (bit n = mode n); answered by `SCREENS_OK,<mask>` |
| PC to device | `BACKLIGHT,<5..100>` | Backlight percent; answered by `BACKLIGHT_OK,<percent>` |
| PC to device | `SWIPES,0` or `SWIPES,1` | Turn swiping between screens off or on; answered by `SWIPES_OK,<0 or 1>` |
| PC to device | `POMO,<0 focus\|1 break>,<remaining s>,<total s>,<0\|1 running>` | Pomodoro state |
| Device to PC | `POMO,TOGGLE` | Pomodoro dial tapped |
| PC to device | `MUTE,<0\|1 speakers>,<0\|1 microphone>` | Mute state, sent on connect and on every change |
| Device to PC | `MUTE,TOGGLE` | Centre of the Volume or Microphone dial tapped |
| Device to PC | `GAME,WHACK,<score>,<best>` | Whack-a-Mole round finished |
| PC to device | `GAMEBEST,<best>` | The app's saved Whack-a-Mole best, sent on connect; the knob keeps the higher one and answers `GAME,BEST,<best>` |
| PC to device | `LBEGIN`, `LITEM`, `LDATA`, `LEND` | Atomic launcher name/icon snapshot; see [firmware/README.md](firmware/README.md) |
| Device to PC | `LAUNCH,<snapshot token>,<slot 0..6>` | Launch the saved PC app only if the snapshot still matches |
| PC to device | `LRESULT,<snapshot token>,<slot>,<0 or 1>` | Launch failed or Windows accepted the launch request |
| PC to device | `SAVER,<0\|1>,<idle s>,<seconds per item>,<0 pictures\|1 clock\|2 both>[,<ring 0-10>]` | Screensaver settings; answered by `SAVER_OK` |
| PC to device | `SAVERLOOK,<shade 0\|1>,<time RRGGBB>,<background RRGGBB>` | Screensaver clock colours and picture shade; answered by `SAVERLOOK_OK` |
| PC to device | `TIME,<local seconds>,<1 for 24-hour\|0>` | Sets the knob's clock (local time counted as if it were UTC); answered by `TIME_OK` |
| PC to device | `DIM,0` or `DIM,1` | Idle dimming off or on; answered by `DIM_OK,<0 or 1>` |
| Device to PC | `SAVER,ON` or `SAVER,OFF` | Screensaver started or stopped |
| PC to device | `LIBRARY` | Ask for `LIBRARY,<capacity>,<items>,<bytes>,<CRC-32 hex>` (also sent after each change) |
| PC to device | `MEDIA_BEGIN,<bytes>`, `MD,<offset>,<base64>`, `MEDIA_END`, `MEDIA_CLEAR` | Screensaver upload; see [firmware/README.md](firmware/README.md) |
| PC to device | `PAIR,<key hex>` | USB only: store the 32-byte link key; answered by `PAIR_OK` or `PAIR_ERR,<FORMAT\|STORE\|USB>` |
| PC to device | `UNPAIR` | Forget the key; answered by `UNPAIR_OK` |
| Device to PC | `NET,<key id\|->,<name>,<0 or 1>` | Every second: the pairing key id, the Bluetooth name and whether the app is linked over Bluetooth |

Mode names, in sector order: `VOLUME`, `SCROLL`, `BRIGHTNESS`, `MIC`, `ZOOM`,
`MEDIA`, `POMODORO`, `GAMES`, `LAUNCHER` (the Microphone screen keeps `MIC` on the wire). The preview uses a neutral midpoint for non-percentage controls.

Each knob detent sends exactly one step. The encoder is not a quadrature
encoder and emits two pulses per detent, which the firmware divides down; see
`firmware\README.md` for the details.


## Support

If Revo1 is useful to you, you can buy me a coffee on
[Ko-fi](https://ko-fi.com/guilhermelimait). The link is also in the app under
**Settings > About**.

## Licence

Revo1 is released under the [MIT License](LICENSE). Bundled and
downloaded third-party components keep their own licences; see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). This project is not
affiliated with Waveshare or Espressif.
