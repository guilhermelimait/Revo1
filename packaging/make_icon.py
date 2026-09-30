"""Builds roundscreen/assets/roundscreen.ico. Large sizes use the real dial
renderer, so the icon is the dial the device shows; small sizes use a bolder
drawing of the same dial, because a 164 px ring's thin arc disappears at 16 px."""

from pathlib import Path

from PIL import Image, ImageDraw

from roundscreen import dial

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "roundscreen" / "assets"
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
FILL = 0.72
ACCENT = dial.ACCENTS["Volume"]
SS = 8


def mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def disc_alpha(size, inset):
    big = Image.new("L", (size * SS, size * SS), 0)
    ImageDraw.Draw(big).ellipse((inset * SS, inset * SS, (size - inset) * SS - 1,
                                 (size - inset) * SS - 1), fill=255)
    return big.resize((size, size), Image.LANCZOS)


# A lightning bolt on the cap, in a unit box (x, y from the top left).
BOLT = [(0.56, 0.00), (0.16, 0.58), (0.46, 0.58), (0.36, 1.00),
        (0.84, 0.40), (0.54, 0.40), (0.74, 0.00)]


def add_bolt(image, height, shadow=True):
    """Draws the bolt in the middle of `image`, shaded from the ring's deep
    tail colour at the bottom to its bright accent at the top."""
    n = image.width
    big = n * SS
    width = height * 0.78
    x0, y0 = (big - width * SS) / 2, (big - height * SS) / 2
    points = [(x0 + x * width * SS, y0 + y * height * SS) for x, y in BOLT]
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    mask = mask.resize((n, n), Image.LANCZOS)
    if shadow:
        offset = max(1, round(n * 0.012))
        soft = Image.new("L", (n, n), 0)
        soft.paste(mask.point(lambda v: v * 0.22), (0, offset))
        image.paste(Image.new("RGBA", (n, n), (40, 40, 60, 255)), (0, 0), soft)
    tail = tuple(v * c // 255 for v, c in zip(ACCENT, dial.TAIL))
    shade = Image.new("RGBA", (n, n))
    top, bottom = n / 2 - height / 2, n / 2 + height / 2
    draw = ImageDraw.Draw(shade)
    for y in range(n):
        t = min(max((y - top) / max(bottom - top, 1), 0), 1)
        draw.line((0, y, n, y), fill=mix(ACCENT, tail, t * 0.85) + (255,))
    image.paste(shade, (0, 0), mask)
    return image


def detailed(size):
    frame = dial.DialRenderer(background=(236, 236, 240)).level(ACCENT, FILL)
    art = frame.convert("RGBA")
    art.putalpha(disc_alpha(dial.SIZE, 1))
    art = art.resize((size, size), Image.LANCZOS)
    return add_bolt(art, size * 0.29)


def bold(size):
    n = size * SS
    image = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((0, 0, n - 1, n - 1), fill=(150, 150, 162, 255))
    edge = max(SS, n // 32)
    draw.ellipse((edge, edge, n - 1 - edge, n - 1 - edge), fill=(236, 236, 240, 255))
    band = n * 0.17
    box = (edge + band * 0.2, edge + band * 0.2, n - 1 - edge - band * 0.2, n - 1 - edge - band * 0.2)
    draw.arc(box, 0, 360, fill=(206, 206, 214, 255), width=round(band))
    tail = tuple(v * c // 255 for v, c in zip(ACCENT, dial.TAIL))
    steps = 120
    sweep = 360 * FILL
    for i in range(steps):
        start = 90 + sweep * i / steps
        draw.arc(box, start, start + sweep / steps + 0.8,
                 fill=mix(tail, ACCENT, i / steps) + (255,), width=round(band))
    cap = n * 0.26
    c = n / 2
    draw.ellipse((c - cap, c - cap, c + cap, c + cap), fill=(248, 248, 250, 255))
    image = image.resize((size, size), Image.LANCZOS)
    return add_bolt(image, size * 0.36, shadow=size >= 32)


def main():
    images = [bold(s) if s <= 48 else detailed(s) for s in SIZES]
    target = ASSETS / "roundscreen.ico"
    images[-1].save(target, format="ICO", sizes=[(s, s) for s in SIZES],
                    append_images=images[:-1])
    images[-1].save(ASSETS / "roundscreen.png")
    print(target, target.stat().st_size)


if __name__ == "__main__":
    main()
