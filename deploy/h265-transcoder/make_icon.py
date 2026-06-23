"""Generate app.ico (multi-size) for the installer exe, using Pillow only.

A real .ico with several embedded sizes so Windows picks a crisp one at every
scale. Kept dependency-light (no SVG rasteriser) — draws a simple H.265 badge.

Run:  python deploy/h265-transcoder/make_icon.py  ->  app.ico
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "app.ico"
SIZES = [16, 24, 32, 48, 64, 128, 256]
BG = (37, 99, 235)   # blue
FG = (255, 255, 255)


def _render(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = max(1, size // 16)
    radius = max(2, size // 6)
    d.rounded_rectangle([pad, pad, size - pad, size - pad], radius=radius, fill=BG)
    text = "265"
    try:
        font = ImageFont.truetype("arialbd.ttf", int(size * 0.42))
    except Exception:
        font = ImageFont.load_default()
    tb = d.textbbox((0, 0), text, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    d.text(((size - tw) / 2 - tb[0], (size - th) / 2 - tb[1]), text, font=font, fill=FG)
    return img


def make(out: Path = OUT) -> Path:
    base = _render(256)
    base.save(out, format="ICO", sizes=[(s, s) for s in SIZES])
    print(f"[icon] wrote {out} ({', '.join(str(s) for s in SIZES)})")
    return out


if __name__ == "__main__":
    make()
