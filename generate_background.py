#!/usr/bin/env python3
"""Generate a Raspberry Pi-themed background for pod-status.

Writes /opt/pod-status/background.png — a stylized berry (hexagonal cluster
of red circles) with two green leaves curving up from the top. Rendered at
2x and downscaled to 320×240 for cheap anti-aliasing. Skips if the file
already exists so a user's custom image isn't overwritten on re-install
(pass --force to regenerate anyway).
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

WIDTH = 320
HEIGHT = 240
OUTPUT = Path("/opt/pod-status/background.png")
SUPERSAMPLE = 2

BG = (0, 0, 0)
BERRY = (220, 40, 80)
LEAF = (120, 180, 60)


def draw_berry(draw, cx, cy, r):
    positions = [
        (0.00, 0.00),
        (0.00, -1.50),
        (1.30, -0.75),
        (1.30, 0.75),
        (0.00, 1.50),
        (-1.30, 0.75),
        (-1.30, -0.75),
    ]
    for px, py in positions:
        x = cx + px * r
        y = cy + py * r
        draw.ellipse((x - r, y - r, x + r, y + r), fill=BERRY)


def draw_leaves(draw, cx, base_y, unit):
    """Two comma-shaped leaves curving up-and-outward from base_y. `unit`
    scales the leaf size so the function works for any render scale."""
    for direction in (-1, 1):
        pts = [
            (cx + direction * 4 * unit, base_y + 4 * unit),
            (cx + direction * 8 * unit, base_y - 2 * unit),
            (cx + direction * 22 * unit, base_y - 14 * unit),
            (cx + direction * 36 * unit, base_y - 26 * unit),
            (cx + direction * 48 * unit, base_y - 28 * unit),
            (cx + direction * 50 * unit, base_y - 20 * unit),
            (cx + direction * 42 * unit, base_y - 10 * unit),
            (cx + direction * 26 * unit, base_y - 2 * unit),
            (cx + direction * 14 * unit, base_y + 2 * unit),
        ]
        draw.polygon(pts, fill=LEAF)


def main():
    force = "--force" in sys.argv
    if OUTPUT.exists() and not force:
        print(f"{OUTPUT} already exists; skipping (use --force to overwrite)")
        return

    big = Image.new("RGB", (WIDTH * SUPERSAMPLE, HEIGHT * SUPERSAMPLE), BG)
    draw = ImageDraw.Draw(big)

    cx = (WIDTH // 2) * SUPERSAMPLE
    cy = (HEIGHT // 2 + 14) * SUPERSAMPLE
    r = 22 * SUPERSAMPLE

    draw_berry(draw, cx, cy, r)
    draw_leaves(draw, cx, cy - int(r * 1.6), SUPERSAMPLE)

    img = big.resize((WIDTH, HEIGHT), Image.LANCZOS)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUTPUT)
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
