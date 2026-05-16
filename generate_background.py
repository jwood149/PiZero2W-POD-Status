#!/usr/bin/env python3
"""Generate a stylized greyscale raspberry background for pod-status.

Writes /opt/pod-status/background.png. Skips if the file already exists,
so a user's custom image isn't overwritten on a re-install — pass --force
to regenerate anyway.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

WIDTH = 320
HEIGHT = 240
OUTPUT = Path("/opt/pod-status/background.png")

BG = (0, 0, 0)
BERRY = (200, 200, 200)
LEAF = (240, 240, 240)


def draw_berry(draw, cx, cy):
    r = 14
    spacing = int(r * 1.7)

    rows = [
        (-2.5, [-1.0, 1.0]),
        (-1.5, [-1.7, -0.5, 0.5, 1.7]),
        (-0.5, [-2.0, -1.0, 0.0, 1.0, 2.0]),
        (0.5, [-1.5, -0.5, 0.5, 1.5]),
        (1.5, [-1.0, 0.0, 1.0]),
        (2.5, [0.0]),
    ]
    for ry, cols in rows:
        for rx in cols:
            x = cx + rx * spacing
            y = cy + ry * spacing
            draw.ellipse((x - r, y - r, x + r, y + r), fill=BERRY)

    leaf_y = cy - 4 * spacing
    for direction in (-1, 1):
        x0 = cx + direction * 8
        leaf_pts = [
            (x0, leaf_y + 12),
            (x0 + direction * 18, leaf_y - 8),
            (x0 + direction * 38, leaf_y - 12),
            (x0 + direction * 36, leaf_y + 12),
            (x0 + direction * 10, leaf_y + 22),
        ]
        draw.polygon(leaf_pts, fill=LEAF)


def main():
    force = "--force" in sys.argv
    if OUTPUT.exists() and not force:
        print(f"{OUTPUT} already exists; skipping (use --force to overwrite)")
        return

    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    draw_berry(draw, WIDTH // 2, HEIGHT // 2 + 12)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUTPUT)
    print(f"Wrote {OUTPUT}")


if __name__ == "__main__":
    main()
