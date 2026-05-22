"""Render the PocketDRS launcher icon from the Material `sports_cricket` glyph.

Matches the in-app "About" mark: a solid ink-black tile with a bone-white
cricket glyph. Emits a full-bleed icon (iOS / legacy Android) and a
transparent foreground sized for the Android adaptive safe zone.

Run from app/pocket_drs:  python3 tool/gen_app_icon.py
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

FONT = (
    "/opt/homebrew/Caskroom/flutter/3.29.0/flutter/"
    "bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf"
)
GLYPH = chr(0xE5E7)  # Icons.sports_cricket
INK_BLACK = (10, 10, 11, 255)  # AppColors.inkBlack
BONE = (244, 244, 240, 255)  # AppColors.bone
SIZE = 1024
OUT_DIR = "assets/icon"


def _draw_glyph(canvas: Image.Image, coverage: float) -> None:
    """Center the glyph on canvas so its bbox spans `coverage` of the width."""
    draw = ImageDraw.Draw(canvas)
    # Binary-search a font size whose glyph bbox width hits the target.
    target = SIZE * coverage
    lo, hi, best = 1, SIZE * 2, 1
    while lo <= hi:
        mid = (lo + hi) // 2
        font = ImageFont.truetype(FONT, mid)
        l, t, r, b = draw.textbbox((0, 0), GLYPH, font=font)
        w = max(r - l, b - t)
        if w <= target:
            best, lo = mid, mid + 1
        else:
            hi = mid - 1
    font = ImageFont.truetype(FONT, best)
    l, t, r, b = draw.textbbox((0, 0), GLYPH, font=font)
    x = (SIZE - (r - l)) / 2 - l
    y = (SIZE - (b - t)) / 2 - t
    draw.text((x, y), GLYPH, font=font, fill=BONE)


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)

    full = Image.new("RGBA", (SIZE, SIZE), INK_BLACK)
    _draw_glyph(full, coverage=0.58)
    full.save(os.path.join(OUT_DIR, "app_icon.png"))

    # Adaptive foreground: transparent, glyph kept inside the inner 66% safe
    # zone Android crops to (circle / squircle / rounded masks).
    fg = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    _draw_glyph(fg, coverage=0.42)
    fg.save(os.path.join(OUT_DIR, "app_icon_foreground.png"))

    print("wrote", os.path.join(OUT_DIR, "app_icon.png"))
    print("wrote", os.path.join(OUT_DIR, "app_icon_foreground.png"))


if __name__ == "__main__":
    main()
