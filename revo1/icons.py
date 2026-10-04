"""Menu icons as small vector shapes, rasterised with signed distances so they
stay crisp at any size. firmware/main/main.c holds the same table
(menu_icon_parts); keep the two in step.

Coordinates are device pixels relative to the icon centre, y pointing down.
Parts:
    ("seg", x0, y0, x1, y1, width)            stroked line, round caps
    ("capsule", x0, y0, x1, y1, radius, width) outline of a stadium
    ("arc", cx, cy, radius, width, a0, a1)     stroked arc, degrees, y down
    ("disc", cx, cy, radius)                   filled circle
    ("poly", x0, y0, x1, y1, x2, y2, x3, y3)   filled convex quad (repeat a
                                               vertex for a triangle)
"""

import math

import numpy as np

ICONS = {
    "Volume": [
        ("poly", -12, -4.5, -7, -4.5, -7, 4.5, -12, 4.5),
        ("poly", -7, -4.5, 0, -11, 0, 11, -7, 4.5),
        ("arc", 0, 0, 6, 2.4, -50, 50),
        ("arc", 0, 0, 11.5, 2.4, -50, 50),
    ],
    "Scroll": [
        ("capsule", 0, -5, 0, 5, 9, 2.4),
        ("seg", 0, -9, 0, -4, 2.8),
    ],
    "Brightness": [("disc", 0, 0, 5.5)] + [
        ("seg", 9 * math.cos(a), 9 * math.sin(a), 13 * math.cos(a), 13 * math.sin(a), 2.4)
        for a in (i * math.pi / 4 for i in range(8))
    ],
    "Mic": [
        ("seg", 0, -9, 0, -1, 9),
        ("arc", 0, -3, 8.5, 2.4, 0, 180),
        ("seg", 0, 5.5, 0, 11, 2.4),
        ("seg", -5, 11.5, 5, 11.5, 2.4),
    ],
    "Zoom": [
        ("arc", -3, -3, 8, 2.6, -180, 180),
        ("seg", 3.2, 3.2, 11, 11, 3.6),
        ("seg", -6.5, -3, 0.5, -3, 2),
        ("seg", -3, -6.5, -3, 0.5, 2),
    ],
    "Media": [
        ("poly", -12.5, -9, 0.5, 0, 0.5, 0, -12.5, 9),
        ("seg", 5.5, -8, 5.5, 8, 3.4),
        ("seg", 11, -8, 11, 8, 3.4),
    ],
    "Pomodoro": [
        ("arc", 0, 2, 9.5, 2.4, -180, 180),
        ("seg", 0, 2, 0, -3.5, 2.4),
        ("seg", 0, 2, 3.5, 4.5, 2.4),
        ("seg", 0, -11, 0, -7.5, 2.4),
        ("seg", -3.5, -11.5, 3.5, -11.5, 2.8),
    ],
    "Games": [
        ("capsule", -6, 1, 6, 1, 7.5, 2.4),
        ("seg", -9, 1, -4, 1, 2.2),
        ("seg", -6.5, -1.5, -6.5, 3.5, 2.2),
        ("disc", 4.5, -0.5, 1.5),
        ("disc", 7.5, 2.5, 1.5),
    ],
}

# Shapes the PC window also draws, in the same distance-field style; the
# firmware draws its own versions of these, so they are not mirrored there.
SHAPES = {
    "Power": [
        ("poly", 2, -11, -7, 1, 0, 1, 2, -11),
        ("poly", 0, -1, 7, -1, -2, 11, 0, -1),
    ],
    "Battery": [
        ("seg", -10, -6, 8, -6, 2),
        ("seg", -10, 6, 8, 6, 2),
        ("seg", -10, -6, -10, 6, 2),
        ("seg", 8, -6, 8, 6, 2),
        ("seg", 11, -2, 11, 2, 2),
        ("poly", -7, -3, -3, -3, -3, 3, -7, 3),
    ],
    "Prev": [
        ("poly", 15, -13, 15, 13, -7, 0, -7, 0),
        ("poly", -14, -13, -12, -13, -12, 13, -14, 13),
    ],
    "Next": [
        ("poly", -15, -13, 7, 0, 7, 0, -15, 13),
        ("poly", 12, -13, 14, -13, 14, 13, 12, 13),
    ],
    "Play": [("poly", -11, -13, 11, 0, 11, 0, -11, 13)],
    "Pause": [
        ("poly", -9, -13, -3, -13, -3, 13, -9, 13),
        ("poly", 3, -13, 9, -13, 9, 13, 3, 13),
    ],
    "Settings": [("arc", 0, 0, 7, 4.2, -180, 180)] + [
        ("seg", 8 * math.cos(a), 8 * math.sin(a), 11.5 * math.cos(a), 11.5 * math.sin(a), 4)
        for a in (i * math.pi / 4 + math.pi / 8 for i in range(8))
    ],
    "Search": [("arc", -2, -2, 7, 2.4, -180, 180), ("seg", 3.5, 3.5, 10, 10, 3)],
    "Check": [("seg", -7, 0, -2.5, 5, 2.6), ("seg", -2.5, 5, 7.5, -5.5, 2.6)],
    # Four tiles.
    "Dashboard": [
        ("poly", -10, -10, -2, -10, -2, -2, -10, -2),
        ("poly", 2, -10, 10, -10, 10, -2, 2, -2),
        ("poly", -10, 2, -2, 2, -2, 10, -10, 10),
        ("poly", 2, 2, 10, 2, 10, 10, 2, 10),
    ],
    # A framed landscape: two hills and a sun.
    "Screensaver": [
        ("seg", -11, -9, 11, -9, 2.2),
        ("seg", -11, 9, 11, 9, 2.2),
        ("seg", -11, -9, -11, 9, 2.2),
        ("seg", 11, -9, 11, 9, 2.2),
        ("poly", -8, 6, -3, -1, -3, -1, 2, 6),
        ("poly", 0, 6, 4.5, 1, 4.5, 1, 9, 6),
        ("disc", 5, -4, 2),
    ],
    # The back button on every screen; firmware/main/main.c has it as icon_back.
    "Back": [
        ("seg", -3.5, 0, 2.5, -7, 2.6),
        ("seg", -3.5, 0, 2.5, 7, 2.6),
    ],
    # Whack-a-Mole's hole and mole, as the knob draws them (draw_card_art).
    "HoleRim": [("disc", 0, 0, 12.5)],
    "HoleDirt": [("disc", 0, 0, 10.5)],
    "MoleBody": [("disc", 0, 0, 8.5)],
    "MoleFace": [("disc", 0, 3, 4.8)],
    "MoleEyes": [("disc", -3.2, -2.5, 1.3), ("disc", 3.2, -2.5, 1.3)],
    "MoleNose": [("disc", 0, 1.6, 1.6)],
    "Plus": [("seg", -7, 0, 7, 0, 2.4), ("seg", 0, -7, 0, 7, 2.4)],
    "Close": [("seg", -5, -5, 5, 5, 2.2), ("seg", 5, -5, -5, 5, 2.2)],
    "Clock": [
        ("arc", 0, 0, 11, 2.4, -180, 180),
        ("seg", 0, 0, 0, -6.5, 2.4),
        ("seg", 0, 0, 4.5, 2.5, 2.4),
    ],
    "VolumeMuted": [
        ("poly", -13, -4.5, -8, -4.5, -8, 4.5, -13, 4.5),
        ("poly", -8, -4.5, -1, -11, -1, 11, -8, 4.5),
        ("seg", 4, -5, 12, 5, 2.4),
        ("seg", 12, -5, 4, 5, 2.4),
    ],
    "MicMuted": [
        ("seg", 0, -9, 0, -1, 9),
        ("arc", 0, -3, 8.5, 2.4, 0, 180),
        ("seg", 0, 5.5, 0, 11, 2.4),
        ("seg", -5, 11.5, 5, 11.5, 2.4),
        ("seg", -11, -12, 11, 12, 2.4),
    ],
    # The Wireless settings: the Bluetooth rune, a USB plug and a padlock.
    "Bluetooth": [
        ("seg", 0, -12, 0, 12, 2.4),
        ("seg", 0, -12, 6, -6, 2.4),
        ("seg", 6, -6, -6, 6, 2.4),
        ("seg", 0, 12, 6, 6, 2.4),
        ("seg", 6, 6, -6, -6, 2.4),
    ],
    "Usb": [
        ("seg", 0, -10, 0, 8, 2.4),
        ("disc", 0, 10, 3),
        ("poly", -3, -10, 3, -10, 0, -14, 0, -14),
        ("seg", 0, 4, -6, -1, 2.4),
        ("seg", -6, -1, -6, -4, 2.4),
        ("disc", -6, -6, 2.4),
        ("seg", 0, 0, 6, -4, 2.4),
        ("poly", 4, -9, 8, -9, 8, -5, 4, -5),
    ],
    "Lock": [
        ("poly", -7.5, -1, 7.5, -1, 7.5, 11, -7.5, 11),
        ("arc", 0, -2, 5, 2.6, -180, 0),
        ("seg", -5, -2, -5, 0, 2.6),
        ("seg", 5, -2, 5, 0, 2.6),
    ],
}

EXTENT = 16
# Icons are drawn at this multiple of their table coordinates.
ICON_SIZE = 1.25


def _segment_distance(px, py, x0, y0, x1, y1):
    dx, dy = x1 - x0, y1 - y0
    length = dx * dx + dy * dy
    t = 0.0 if length == 0 else np.clip(((px - x0) * dx + (py - y0) * dy) / length, 0, 1)
    return np.hypot(px - (x0 + t * dx), py - (y0 + t * dy))


def _part_distance(part, px, py):
    kind, v = part[0], part[1:]
    if kind == "seg":
        return _segment_distance(px, py, *v[:4]) - v[4] / 2
    if kind == "capsule":
        return np.abs(_segment_distance(px, py, *v[:4]) - v[4]) - v[5] / 2
    if kind == "disc":
        return np.hypot(px - v[0], py - v[1]) - v[2]
    if kind == "arc":
        cx, cy, r, w, a0, a1 = v
        rx, ry = px - cx, py - cy
        angle = np.degrees(np.arctan2(ry, rx))
        inside = (angle >= a0) & (angle <= a1)
        on_arc = np.abs(np.hypot(rx, ry) - r) - w / 2
        ends = [np.hypot(px - (cx + r * math.cos(math.radians(a))),
                         py - (cy + r * math.sin(math.radians(a)))) - w / 2
                for a in (a0, a1)]
        return np.where(inside, on_arc, np.minimum(*ends))
    if kind == "poly":
        points = [(v[i], v[i + 1]) for i in range(0, 8, 2)]
        area = sum(points[i][0] * points[(i + 1) % 4][1] - points[(i + 1) % 4][0] * points[i][1]
                   for i in range(4))
        sign = 1.0 if area > 0 else -1.0
        distance = np.full(px.shape, -1e9, dtype=np.float32)
        for i in range(4):
            (x0, y0), (x1, y1) = points[i], points[(i + 1) % 4]
            ex, ey = x1 - x0, y1 - y0
            length = math.hypot(ex, ey)
            if length == 0:
                continue
            # Outward normal of this edge, whichever way the quad winds.
            nx, ny = sign * ey / length, -sign * ex / length
            distance = np.maximum(distance, (px - x0) * nx + (py - y0) * ny)
        return distance
    raise ValueError(kind)


def draw(image, name, cx, cy, colour, scale=1.0, size=ICON_SIZE):
    """Blends icon `name` into an RGB uint8 array, centred on (cx, cy) in
    device pixels; `scale` maps device pixels to image pixels."""
    parts = ICONS.get(name) or SHAPES[name]
    half = int(math.ceil((EXTENT * size + 1) * scale))
    ox, oy = round(cx * scale), round(cy * scale)
    y0, x0 = max(oy - half, 0), max(ox - half, 0)
    y1, x1 = min(oy + half, image.shape[0]), min(ox + half, image.shape[1])
    ys, xs = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    px = ((xs + 0.5) / scale - cx) / size
    py = ((ys + 0.5) / scale - cy) / size
    distance = np.full(px.shape, 1e9, dtype=np.float32)
    for part in parts:
        distance = np.minimum(distance, _part_distance(part, px, py))
    cover = np.clip(0.5 - distance * size * scale, 0, 1)[..., None]
    region = image[y0:y1, x0:x1].astype(np.float32)
    image[y0:y1, x0:x1] = (region + (np.array(colour, np.float32) - region) * cover).astype(np.uint8)
