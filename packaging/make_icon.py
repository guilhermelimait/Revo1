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


def detailed(size):
    frame = dial.DialRenderer(background=(236, 236, 240)).level(ACCENT, FILL)
    art = frame.convert("RGBA")
    art.putalpha(disc_alpha(dial.SIZE, 1))
    return art.resize((size, size), Image.LANCZOS)


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
    return image.resize((size, size), Image.LANCZOS)


def main():
    images = [bold(s) if s <= 48 else detailed(s) for s in SIZES]
    target = ASSETS / "roundscreen.ico"
    images[-1].save(target, format="ICO", sizes=[(s, s) for s in SIZES],
                    append_images=images[:-1])
    images[-1].save(ASSETS / "roundscreen.png")
    print(target, target.stat().st_size)


if __name__ == "__main__":
    main()
