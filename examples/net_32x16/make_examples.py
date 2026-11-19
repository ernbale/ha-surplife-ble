"""Build example animations for the 32 x 16 net light (product 0x0071).

Every GIF is drawn pixel by pixel at 32 x 16, so one image pixel is one LED. Upload them
with the `surplife_ble.upload_animation` service and `resample: nearest`.

The LEDs are 10 cm apart, so small details are lost. What reads well: one or two big
filled shapes, few saturated colors, no one-pixel lines.

Usage, from the repository root:
    python examples/net_32x16/make_examples.py [output directory] [scrolling text]
Requires Pillow.
"""

from __future__ import annotations

import colorsys
import random
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from custom_components.surplife_ble.core import text as text_render  # noqa: E402

COLS, ROWS = 32, 16
RGB = tuple[int, int, int]
Grid = list[list[RGB]]
K, R, W, Y = (0, 0, 0), (255, 0, 0), (255, 255, 255), (255, 200, 0)
G, ORANGE, B, M = (0, 220, 0), (255, 110, 0), (0, 80, 255), (255, 0, 170)


def blank() -> Grid:
    return [[K] * COLS for _ in range(ROWS)]


def rect(g: Grid, x0: int, y0: int, w: int, h: int, color: RGB) -> None:
    for y in range(max(y0, 0), min(y0 + h, ROWS)):
        for x in range(max(x0, 0), min(x0 + w, COLS)):
            g[y][x] = color


def stamp(g: Grid, rows: list[str], x0: int, y0: int, palette: dict[str, RGB]) -> None:
    for r, line in enumerate(rows):
        for c, ch in enumerate(line):
            x, y = x0 + c, y0 + r
            if ch in palette and 0 <= x < COLS and 0 <= y < ROWS:
                g[y][x] = palette[ch]


def save(out: Path, name: str, frames: list[Grid], ms: int) -> None:
    images = [
        Image.frombytes("RGB", (COLS, ROWS), bytes(c for row in g for p in row for c in p))
        for g in frames
    ]
    images[0].save(
        out / f"{name}.gif", save_all=True, append_images=images[1:], duration=ms, loop=0
    )
    print(f"{name}.gif: {len(frames)} frames")


HEART = ["..XXX...XXX..", ".XXXXX.XXXXX.", "XXXXXXXXXXXXX", "XXXXXXXXXXXXX", "XXXXXXXXXXXXX",
         ".XXXXXXXXXXX.", "..XXXXXXXXX..", "...XXXXXXX...", "....XXXXX....", ".....XXX.....",
         "......X......"]
HEART_SMALL = ["..XX..XX..", ".XXXXXXXX.", "XXXXXXXXXX", "XXXXXXXXXX", ".XXXXXXXX.",
               "..XXXXXX..", "...XXXX...", "....XX...."]
STAR = [".......X.......", ".......X.......", "......XXX......", "......XXX......",
        "XXXXXXXXXXXXXXX", ".XXXXXXXXXXXXX.", "..XXXXXXXXXXX..", "...XXXXXXXXX...",
        "...XXXXXXXXX...", "..XXXXXXXXXXX..", "..XXXXX.XXXXX..", ".XXXX.....XXXX.",
        ".XX.........XX."]
STAR_PHASES = (0, 0, 0, 1, 2, 3, 2, 1)


def draw_heart(g: Grid, big: bool, x_center: int) -> None:
    shape = HEART if big else HEART_SMALL
    stamp(g, shape, x_center - len(shape[0]) // 2, (ROWS - len(shape)) // 2, {"X": R})


def draw_star(g: Grid, phase: int, x0: int) -> None:
    """A yellow star whose white core grows and shrinks with ``phase`` (0-3)."""
    for r, line in enumerate(STAR):
        for c, ch in enumerate(line):
            if ch == "X":
                core = phase and abs(c - 7) + abs(r - 6) <= phase * 2
                g[1 + r][x0 + c] = W if core else Y


def heart() -> list[Grid]:
    frames = []
    for big in [True] * 4 + [False] * 2 + [True] * 2 + [False] * 4:
        g = blank()
        draw_heart(g, big, COLS // 2)
        frames.append(g)
    return frames


def star() -> list[Grid]:
    frames = []
    for phase in STAR_PHASES:
        g = blank()
        draw_star(g, phase, (COLS - 15) // 2)
        frames.append(g)
    return frames


def heart_and_star() -> list[Grid]:
    frames = []
    for i, phase in enumerate(STAR_PHASES):
        g = blank()
        draw_heart(g, i < 5, 7)
        draw_star(g, phase, 16)
        frames.append(g)
    return frames


def tree() -> list[Grid]:
    half_widths = {2: 1, 3: 2, 4: 3, 5: 2, 6: 4, 7: 5, 8: 6, 9: 4, 10: 5, 11: 6, 12: 7}
    balls = [(14, 4, R), (17, 7, Y), (12, 8, B), (18, 10, M), (11, 11, Y), (15, 11, R),
             (20, 11, B)]
    frames = []
    for i in range(12):
        g = blank()
        for y, hw in half_widths.items():
            rect(g, 16 - hw, y, 2 * hw, 1, G)
        top = Y if (i // 2) % 2 == 0 else W
        rect(g, 15, 0, 2, 2, top)
        rect(g, 14, 1, 4, 1, top)
        for n, (x, y, color) in enumerate(balls):
            if (n + i // 3) % 2 == 0:
                rect(g, x, y, 2, 2, color)
        rect(g, 14, 13, 4, 2, ORANGE)
        rect(g, 1, 10, 6, 5, R)
        rect(g, 3, 10, 2, 5, Y)
        rect(g, 1, 12, 6, 1, Y)
        rect(g, 25, 11, 6, 4, B)
        rect(g, 27, 11, 2, 4, Y)
        rect(g, 25, 12, 6, 1, Y)
        rect(g, 0, 15, COLS, 1, W)
        frames.append(g)
    return frames


def comet() -> list[Grid]:
    tail = ((1, Y), (2, Y), (3, Y), (4, ORANGE), (5, ORANGE), (6, ORANGE), (7, R), (8, R), (9, R))
    frames = []
    for i in range(COLS + 16):
        g = blank()
        cx, cy = -4 + i, 7 + (1 if (i // 5) % 2 else 0)
        for d, color in tail:
            thin = d >= 7
            rect(g, cx - 3 - d, cy - 1 + (1 if thin else 0), 1, 1 if thin else 3, color)
        for dy, hw in ((-3, 0), (-2, 1), (-1, 2), (0, 3), (1, 2), (2, 1), (3, 0)):
            rect(g, cx - hw, cy + dy, 2 * hw + 1, 1, W)
        rect(g, cx - 1, cy - 1, 3, 3, Y)
        frames.append(g)
    return frames


SLEIGH = ["....RR.................W.W..", "....WW.................W.W..",
          "RR.RRRR...............OOOO..", "RRRRRRRRRRR...........OOOOR.",
          "RRRRRRRRRRYYYYOOOOOOOOOO....", "RRRRRRRRRR.....OOOOOOOOO....",
          ".RRRRRRRR......OOOOOOOOO....", "..W....W.......", "WWWWWWWWWWW...."]
LEGS = [("OO....OO.....", "OO....OO....."), ("O......OO....", ".OO.....OO..."),
        ("OO....OO.....", "OO....OO....."), (".OO..OO......", "..OO.OO......")]


def sleigh() -> list[Grid]:
    palette = {"R": R, "W": W, "Y": Y, "O": ORANGE}
    moon = ((28, 0), (29, 0), (27, 1), (28, 1), (29, 1), (30, 1), (28, 2), (29, 2))
    frames = []
    for i in range(28 + COLS):
        g = blank()
        for x, y in moon:
            g[y][x] = (255, 220, 90)
        upper, lower = LEGS[(i // 2) % 4]
        sprite = [*SLEIGH[:7], SLEIGH[7] + upper, SLEIGH[8] + lower]
        stamp(g, sprite, -28 + i, 4 + (1 if (i // 4) % 2 else 0), palette)
        rect(g, 0, 15, COLS, 1, W)
        frames.append(g)
    return frames


def rainbow() -> list[Grid]:
    """Diagonal rainbow bands that move sideways. 24 frames loop exactly."""
    frames = []
    for i in range(24):
        g = blank()
        for y in range(ROWS):
            for x in range(COLS):
                hue = ((x + y) / 24 - i / 24) % 1.0
                r, gr, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
                g[y][x] = (round(r * 255), round(gr * 255), round(b * 255))
        frames.append(g)
    return frames


def snow() -> list[Grid]:
    """Big 2 x 2 snowflakes falling at two speeds over a white ground. 16 frames loop."""
    flakes = [(1, 0, 1), (5, 9, 2), (9, 4, 1), (13, 12, 2), (17, 2, 1), (21, 7, 2),
              (25, 11, 1), (29, 5, 2), (11, 15, 1), (23, 14, 1)]
    frames = []
    for i in range(16):
        g = blank()
        for x, y0, speed in flakes:
            rect(g, x, (y0 + i * speed) % 16 - 1, 2, 2, W)
        rect(g, 0, 15, COLS, 1, W)
        frames.append(g)
    return frames


def sparkle(colors: tuple[RGB, ...], seed: int = 7) -> list[Grid]:
    """Many lights that flash at random places. 48 frames loop exactly.

    Every LED gets its own period (a divisor of 48) and phase. It is at full brightness
    for one frame and at a third for the next one, then dark.
    """
    rng = random.Random(seed)
    leds = [
        (x, y, rng.choice((8, 12, 16, 24)), rng.randrange(48), rng.choice(colors))
        for y in range(ROWS)
        for x in range(COLS)
    ]
    frames = []
    for i in range(48):
        g = blank()
        for x, y, period, phase, color in leds:
            step = (i + phase) % period
            if step == 0:
                g[y][x] = color
            elif step == 1:
                g[y][x] = (color[0] // 3, color[1] // 3, color[2] // 3)
        frames.append(g)
    return frames


def scrolling_text(text: str, color: RGB = Y) -> list[Grid]:
    """Bold scrolling text, rendered by the integration's own text module."""
    rendered = text_render.render_text(text, cols=COLS, rows=ROWS, color=color, max_frames=100)
    return [[frame[y * COLS : (y + 1) * COLS] for y in range(ROWS)] for frame in rendered.frames]


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
    text = sys.argv[2] if len(sys.argv) > 2 else "BENVENUTI"
    out.mkdir(parents=True, exist_ok=True)
    save(out, "heart", heart(), 200)
    save(out, "star", star(), 220)
    save(out, "heart_and_star", heart_and_star(), 220)
    save(out, "tree", tree(), 300)
    save(out, "comet", comet(), 120)
    save(out, "sleigh", sleigh(), 120)
    save(out, "rainbow", rainbow(), 100)
    save(out, "snow", snow(), 200)
    save(out, "sparkle", sparkle((W, Y, R, G, B, M, (0, 220, 220))), 120)
    save(out, "sparkle_white", sparkle((W, W, Y), seed=11), 120)
    save(out, "scrolling_text", scrolling_text(text), 80)


if __name__ == "__main__":
    main()
