#!/usr/bin/env python3
"""Generate the default Raspberry Pi background image for pod-status.

Writes /opt/pod-status/background.png: a stylized berry (8 circles in a
heart-shape cluster) with two long pointed leaves curving outward from the
top. Rendered at 3× and Lanczos-downscaled to 320×240 for smooth edges on
the rotated leaf polygons.

Skip if file exists unless --force is passed.
"""

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

WIDTH = 320
HEIGHT = 240
OUTPUT = Path("/opt/pod-status/background.png")
SUPERSAMPLE = 3

BG = (0, 0, 0)
BERRY = (200, 30, 50)
LEAF = (117, 169, 40)


def draw_berry(draw, cx, cy, r):
    spacing = r * 1.35
    positions = [
        (-0.75, -1.6),
        (0.75, -1.6),
        (-1.50, -0.5),
        (0.00, -0.5),
        (1.50, -0.5),
        (-0.80, 0.6),
        (0.80, 0.6),
        (0.00, 1.7),
    ]
    for px, py in positions:
        x = cx + px * spacing
        y = cy + py * spacing
        draw.ellipse((x - r, y - r, x + r, y + r), fill=BERRY)


def leaf_polygon(cx, cy, length, width, angle_deg):
    """12-point teardrop, tip at +x, rotated by angle_deg about (cx, cy)."""
    a = math.radians(angle_deg)
    cos_a, sin_a = math.cos(a), math.sin(a)
    raw = [
        (length * 0.55, 0.00),
        (length * 0.40, width * 0.18),
        (length * 0.20, width * 0.30),
        (length * 0.00, width * 0.40),
        (-length * 0.20, width * 0.35),
        (-length * 0.40, width * 0.20),
        (-length * 0.50, 0.00),
        (-length * 0.40, -width * 0.20),
        (-length * 0.20, -width * 0.35),
        (length * 0.00, -width * 0.40),
        (length * 0.20, -width * 0.30),
        (length * 0.40, -width * 0.18),
    ]
    return [
        (cx + x * cos_a - y * sin_a, cy + x * sin_a + y * cos_a)
        for x, y in raw
    ]


def draw_leaves(draw, cx, base_y, leaf_length, leaf_width):
    left = leaf_polygon(cx - 8, base_y - 5, leaf_length, leaf_width, 135)
    right = leaf_polygon(cx + 8, base_y - 5, leaf_length, leaf_width, 45)
    draw.polygon(left, fill=LEAF)
    draw.polygon(right, fill=LEAF)


def main():
    force = "--force" in sys.argv
    if OUTPUT.exists() and not force:
        print(f"{OUTPUT} already exists; skipping (use --force to overwrite)")
        return

    big = Image.new("RGB", (WIDTH * SUPERSAMPLE, HEIGHT * SUPERSAMPLE), BG)
    draw = ImageDraw.Draw(big)

    cx = (WIDTH // 2) * SUPERSAMPLE
    cy = (HEIGHT // 2 + 16) * SUPERSAMPLE
    r = 22 * SUPERSAMPLE
    leaf_length = 70 * SUPERSAMPLE
    leaf_width = 26 * SUPERSAMPLE

    draw_berry(draw, cx, cy, r)
    draw_leaves(draw, cx, cy - int(r * 2.3), leaf_length, leaf_width)

    img = big.resize((WIDTH, HEIGHT), Image.LANCZOS)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUTPUT)
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
