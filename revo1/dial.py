"""Renders the same sculpted dial the device draws, so the companion window
matches the screen. The maths mirrors render_dial_chrome, draw_gauge_track,
build_arc_ramp and draw_arc in firmware/main/main.c; keep them in step."""

import math

import numpy as np
from PIL import Image

SIZE = 360
CENTER = 180
RADIUS = 179
CAP_R = 76
ARC_R = 164
GROOVE = 9
BAND = 15
SEGMENTS = 1024
MASK = SEGMENTS - 1
# The gauge is the whole ring: it starts at 6 o'clock and runs clockwise all
# the way round, so at 100% the colour meets itself. A back button sits on the
# upper face instead of in a gap.
GAUGE_START = 768
GAUGE_SPAN = SEGMENTS
FOOTER_Y = -118
# Tapping the back button on the upper face goes back to the menu.
FOOTER_HIT_W = 30
FOOTER_HIT_H = 30
BACK_ICON_SIZE = 1.0
MENU_SEGMENT_HALF = 456
# Scroll/zoom comet, identical to the firmware so both rest on the same
# segment: positions in q8 segments, a fixed move per detent, eased a quarter
# of the remaining way each 40 ms frame and snapped when within two segments.
COMET_STEP_Q8 = 32 << 8
COMET_SNAP_Q8 = 2 << 8
COMET_TAIL = 300
FRAME_MS = 40
# Media: play/pause fills the cap's centre, previous and next sit on the face
# either side of it, and the track text is in the band below the cap. Offsets
# are from the centre.
MEDIA_BUTTON_SPACING = 114
MEDIA_PLAY_SIZE = 1.9
MEDIA_SKIP_SIZE = 1.35
MEDIA_HIT = 30
MEDIA_TITLE_Y = 98
MEDIA_ARTIST_Y = 120
MEDIA_TIME_Y = 52
MENU_LABEL_R = 120
CHEVRON_X = 124
# Tail of the arc as a fraction of the accent per channel, halo strength, and
# the colour of the tick at the live end.
TAIL = (150, 90, 70)
GLOW = 0.35
HEAD = (255, 252, 244)

# Same order as config.MODES and the firmware's mode_accents.
ACCENTS = {
    "Volume": (0, 176, 255),
    "Scroll": (124, 104, 255),
    "Brightness": (255, 168, 40),
    "Mic": (255, 64, 116),
    "Zoom": (0, 226, 158),
    "Media": (255, 116, 56),
    "Pomodoro": (232, 58, 58),
    "Games": (150, 200, 30),
}

# Swatches offered for a single custom bar colour.
PRESET_ACCENTS = ("#00B0FF", "#7C68FF", "#FFA828", "#FF4074",
                  "#00E29E", "#FF7438", "#FF3B30", "#3A3A48")

VALUE_INK = "#2A2A34"
ARTIST_INK = "#76768A"
TIME_INK = "#3C3C4A"
# Volume and Mic while muted, as the knob draws them.
MUTED_VALUE_INK = "#A4A4B0"
MUTED_INK = "#E5484D"
# The mute icon under the level, and MUTED above it (offsets from the centre).
MUTE_ICON_Y = 46
MUTE_ICON_SIZE = 0.8
MUTE_LABEL_Y = -46
FOOTER_INK = "#8A8A98"
MENU_INK = "#8A8A9A"
ICON_INK = "#5A5A68"
CHEVRON_INK = "#9696A4"

_BAYER = np.array([-8, 0, -6, 2, 4, -4, 6, -2, -5, 3, -7, 1, 7, -1, 5, -3],
                  dtype=np.float32).reshape(4, 4)


def label_ink(accent):
    """The accent deepened enough to stay legible on the pale face."""
    return "#%02X%02X%02X" % tuple(v * 3 // 4 for v in accent)


def _grid():
    ys, xs = np.mgrid[0:SIZE, 0:SIZE]
    dx = (xs - CENTER).astype(np.float32)
    dy = (ys - CENTER).astype(np.float32)
    return ys, xs, dx, dy, np.sqrt(dx * dx + dy * dy)


def _chrome(background):
    """The whole disc is the light face; the arc runs in a shallow channel cut
    into it just inside the rim, so no screen area is spent on a dark bezel."""
    ys, xs, dx, dy, radius = _grid()
    lit = 128 - ((dx + dy) * 104) / (2 * RADIUS)
    bias = 128 + ((dx + dy) * 127) / (2 * RADIUS)

    face = 212 + (lit * 34) / 255 + (RADIUS - radius) * 12.0 / RADIUS

    # A raised centre cap, shadowed on the side away from the light.
    cap = radius - CAP_R
    face = np.where(cap < 0, face + 8.0 * np.clip(-cap, 0, 1), face)
    cap_fade = 1.0 - cap / 12.0
    face = np.where((cap >= 0) & (cap < 12.0),
                    face - cap_fade * cap_fade * 16.0 * bias / 255.0, face)

    # The channel: a flat floor with soft walls. Light catches the far wall
    # of a recess and the near wall falls into shadow.
    groove = radius - ARC_R
    wall = np.clip((GROOVE - np.abs(groove)) / 2.5, 0, 1)
    face = face - wall * 30.0
    near = (groove > 0) & (np.abs(groove) < GROOVE)
    shade = np.where(near, 1.0 - groove / GROOVE, 0) ** 2
    face = face - shade * 10.0 * bias / 255.0

    # The rim rolls away from the viewer.
    rim = np.clip((radius - (RADIUS - 4.0)) / 4.0, 0, 1)
    face = face - rim * rim * 26.0

    face = np.clip(face, 0, 255)
    r = face
    g = np.maximum(face - 3, 0)
    b = np.maximum(face - 1, 0)

    noise = _BAYER[ys % 4, xs % 4]
    image = np.stack([r + noise, g + noise, b + noise], axis=-1)
    # Off the device there is no black glass around the dial, so its rim is
    # feathered into whatever it sits on.
    edge = np.clip(RADIUS + 0.5 - radius, 0, 1)[..., None]
    backdrop = np.array(background, dtype=np.float32)
    return np.clip(backdrop + (image - backdrop) * edge, 0, 255)


def _band():
    _, _, dx, dy, radius = _grid()
    offset = radius - ARC_R
    mask = np.abs(offset) <= BAND
    angle = np.arctan2(-dy, dx)
    angle = np.where(angle < 0, angle + 2 * math.pi, angle)
    segment = np.rint(angle * (SEGMENTS / (2 * math.pi))).astype(np.int32) & MASK
    quarters = np.clip(np.rint(np.abs(offset) * 4).astype(np.int32), 0, BAND * 4)
    ys, xs = np.nonzero(mask)
    return ys, xs, segment[mask], quarters[mask]


def menu_sector_of(segment, count=6):
    """The menu slot each ring segment belongs to (-1 in the gaps), for a menu
    of `count` equal slots starting at 12 o'clock and running clockwise."""
    whole = count * 1024
    clockwise = (256 - segment) & MASK
    sector = ((clockwise * count + 512) // 1024) % count
    offset = clockwise * count - sector * 1024
    offset = np.where(offset > whole // 2, offset - whole, offset)
    offset = np.where(offset < -(whole // 2), offset + whole, offset)
    return np.where(np.abs(offset) <= MENU_SEGMENT_HALF, sector, -1)


def _in_gauge(segment):
    return ((GAUGE_START - segment) & MASK) <= GAUGE_SPAN


class DialRenderer:
    """Composes frames: static chrome (cached per track style) plus the arc.
    Geometry is always the device's 360 px; `scale` resamples the finished
    frame so it stays crisp on high-DPI monitors."""

    def __init__(self, background=(0, 0, 0), scale=1.0):
        self.scale = scale
        self.size = round(SIZE * scale)
        self._band_y, self._band_x, self._segment, self._quarters = _band()
        distance = np.arange(BAND * 4 + 1, dtype=np.float32) * 0.25
        self._core = np.clip((GROOVE - distance) / 3.0, 0, 1)
        self._glow = (1.0 - distance / BAND) ** 2
        self._base = _chrome(background)
        self._chrome = {"gauge": self._with_track(self._base, _in_gauge(self._segment))}
        self._menus = {}

    def _menu(self, count):
        """Slot map and chrome for a menu of `count` slots, built once each."""
        if count not in self._menus:
            sectors = menu_sector_of(self._segment, count)
            self._menus[count] = (sectors, self._with_track(self._base, sectors >= 0))
        return self._menus[count]

    def _with_track(self, base, on_track):
        """A faint etched line along the track, so its unlit part still reads."""
        image = base.copy()
        pick = on_track & (self._quarters <= 8)
        lift = -np.where(self._quarters[pick] <= 4, 16.0, 8.0)[:, None] + [0, 0, 2]
        ys, xs = self._band_y[pick], self._band_x[pick]
        image[ys, xs] = np.clip(image[ys, xs] + lift, 0, 255)
        return image

    def _composite(self, chrome, accent, level, shade, head=None):
        image = chrome.copy()
        accent = np.array(accent, dtype=np.float32)
        tail = accent * (np.array(TAIL, dtype=np.float32) / 255.0)
        ramp = tail + (accent - tail) * (shade[:, None] / 255.0)

        lit = level > 0
        ys, xs = self._band_y[lit], self._band_x[lit]
        quarters = self._quarters[lit]
        weight = (level[lit] / 255.0)[:, None]
        colour = ramp[lit]
        pixel = image[ys, xs]
        pixel = pixel + (colour - pixel) * (self._core[quarters][:, None] * weight)
        # On a light face, additive bloom would only wash out to white, so the
        # halo is a soft tint of the arc colour instead.
        pixel = pixel + (colour - pixel) * (self._glow[quarters][:, None] * weight) * GLOW
        image[ys, xs] = np.clip(pixel, 0, 255)

        if head is not None:
            delta = ((self._segment - head + SEGMENTS + SEGMENTS // 2) & MASK) - SEGMENTS // 2
            tick = (np.abs(delta) <= 1) & (self._quarters <= (GROOVE - 1) * 4)
            image[self._band_y[tick], self._band_x[tick]] = HEAD
        frame = Image.fromarray(image.astype(np.uint8))
        if self.size != SIZE:
            frame = frame.resize((self.size, self.size), Image.LANCZOS)
        return frame

    def level(self, accent, fraction):
        """A gauge filled along the sweep, deep at the tail and hottest at the head."""
        filled = int(GAUGE_SPAN * max(0.0, min(1.0, fraction)))
        swept = (GAUGE_START - self._segment) & MASK
        on = (swept <= filled) & _in_gauge(self._segment)
        level = np.where(on, 255, 0)
        shade = np.where(on, (swept * 255) // max(filled, 1), 0)
        head = (GAUGE_START - filled) & MASK if filled > 0 else None
        return self._composite(self._chrome["gauge"], accent, level, shade, head)

    def comet(self, accent, position, direction):
        """Scroll and zoom have no absolute value, so they show momentum."""
        tail = COMET_TAIL
        behind = ((position - self._segment) * direction) & MASK
        fade = 255 - (behind * 255) // tail
        # The firmware stops the tail once it has faded to almost nothing.
        on = (behind < tail) & ((fade * fade) // 255 > 4)
        level = np.where(on, (fade * fade) // 255, 0)
        shade = np.where(on, fade, 0)
        return self._composite(self._chrome["gauge"], accent, level, shade,
                               position & MASK)

    def menu(self, accent, selected, count=6):
        """One segment per screen on the knob, `selected` (a slot) lit in its
        own accent."""
        sectors, chrome = self._menu(count)
        on = sectors == selected
        level = np.where(on, 255, 0)
        shade = np.full(self._segment.shape, 255)
        return self._composite(chrome, accent, level, shade)
