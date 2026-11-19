"""Built-in animations for the IOTBT curtain and net lights, drawn in code.

Every effect is a function ``(cols, rows) -> frames``. A frame is a list of row-major RGB
pixels (index ``y * cols + x``), the layout :func:`curtain_c2.image_to_frame` takes. The
effects are deterministic and loop without a jump. Pure Python, no Pillow.

The patterns (sparkle, rain, snow, rainbow, fire, plasma...) fit any grid. The pictures
(heart, star, tree, comet, sleigh) are drawn for 32 x 16 and are centered on bigger grids.
"""

from __future__ import annotations

import colorsys
import math
import random
from collections.abc import Callable
from typing import NamedTuple

RGB = tuple[int, int, int]
Grid = list[list[RGB]]
Frames = list[list[RGB]]

K: RGB = (0, 0, 0)
R: RGB = (255, 0, 0)
W: RGB = (255, 255, 255)
Y: RGB = (255, 200, 0)
G: RGB = (0, 220, 0)
ORANGE: RGB = (255, 110, 0)
B: RGB = (0, 80, 255)
M: RGB = (255, 0, 170)
CYAN: RGB = (0, 220, 220)


def _blank(cols: int, rows: int) -> Grid:
    return [[K] * cols for _ in range(rows)]


def _flat(grid: Grid) -> list[RGB]:
    return [pixel for row in grid for pixel in row]


def _rect(g: Grid, x0: int, y0: int, w: int, h: int, color: RGB) -> None:
    for y in range(max(y0, 0), min(y0 + h, len(g))):
        for x in range(max(x0, 0), min(x0 + w, len(g[0]))):
            g[y][x] = color


def _stamp(g: Grid, shape: list[str], x0: int, y0: int, palette: dict[str, RGB]) -> None:
    for r, line in enumerate(shape):
        for c, ch in enumerate(line):
            x, y = x0 + c, y0 + r
            if ch in palette and 0 <= x < len(g[0]) and 0 <= y < len(g):
                g[y][x] = palette[ch]


def _dim(color: RGB, factor: float) -> RGB:
    return (round(color[0] * factor), round(color[1] * factor), round(color[2] * factor))


def _hue(hue: float, value: float = 1.0) -> RGB:
    r, g, b = colorsys.hsv_to_rgb(hue % 1.0, 1.0, value)
    return (round(r * 255), round(g * 255), round(b * 255))


# ---------------------------------------------------------------------------
# Patterns: any grid size
# ---------------------------------------------------------------------------


def _sparkle(cols: int, rows: int, colors: tuple[RGB, ...], seed: int) -> Frames:
    """Lights that flash at random places. Each LED has its own period and phase."""
    rng = random.Random(seed)
    leds = [
        (x, y, rng.choice((8, 12, 16, 24)), rng.randrange(48), rng.choice(colors))
        for y in range(rows)
        for x in range(cols)
    ]
    frames = []
    for i in range(48):
        g = _blank(cols, rows)
        for x, y, period, phase, color in leds:
            step = (i + phase) % period
            if step == 0:
                g[y][x] = color
            elif step == 1:
                g[y][x] = _dim(color, 0.33)
        frames.append(_flat(g))
    return frames


def sparkle(cols: int, rows: int) -> Frames:
    return _sparkle(cols, rows, (W, Y, R, G, B, M, CYAN), 7)


def sparkle_gold(cols: int, rows: int) -> Frames:
    return _sparkle(cols, rows, (W, W, Y), 11)


def _falling(cols: int, rows: int, tail: tuple[RGB, ...], seed: int, density: float) -> Frames:
    """Drops with a bright head and a fading tail, one LED per frame."""
    rng = random.Random(seed)
    period = rows + len(tail) + 4
    drops = [
        (x, rng.randrange(period))
        for x in range(cols)
        for _ in range(2 if rng.random() < density - 1 else 1)
        if rng.random() < density
    ]
    frames = []
    for i in range(period):
        g = _blank(cols, rows)
        for x, phase in drops:
            head = (i + phase) % period
            for n, color in enumerate(tail):
                y = head - n
                if 0 <= y < rows:
                    g[y][x] = color
        frames.append(_flat(g))
    return frames


def rain(cols: int, rows: int) -> Frames:
    return _falling(cols, rows, ((170, 210, 255), B, (0, 30, 120)), 3, 0.8)


def matrix(cols: int, rows: int) -> Frames:
    tail = (W, G, G, (0, 140, 0), (0, 90, 0), (0, 50, 0))
    return _falling(cols, rows, tail, 5, 0.9)


def snow(cols: int, rows: int) -> Frames:
    """2 x 2 snowflakes falling at two speeds over a white ground."""
    rng = random.Random(9)
    flakes = [(x, rng.randrange(rows), rng.choice((1, 1, 2))) for x in range(1, cols - 1, 4)]
    flakes += [(x, rng.randrange(rows), 1) for x in range(3, cols - 1, 8)]
    frames = []
    for i in range(rows):
        g = _blank(cols, rows)
        for x, y0, speed in flakes:
            _rect(g, x, (y0 + i * speed) % rows - 1, 2, 2, W)
        _rect(g, 0, rows - 1, cols, 1, W)
        frames.append(_flat(g))
    return frames


def rainbow(cols: int, rows: int) -> Frames:
    """Diagonal rainbow bands that move sideways."""
    return [
        _flat([[_hue((x + y) / 24 - i / 24) for x in range(cols)] for y in range(rows)])
        for i in range(24)
    ]


def plasma(cols: int, rows: int) -> Frames:
    """Soft blobs of color that drift."""
    frames = []
    for i in range(32):
        t = 2 * math.pi * i / 32
        frames.append(
            _flat(
                [
                    [
                        _hue(
                            (
                                math.sin(x / 5 + t)
                                + math.sin(y / 3 - t)
                                + math.sin((x + y) / 7 + t)
                            )
                            / 6
                            + 0.5
                        )
                        for x in range(cols)
                    ]
                    for y in range(rows)
                ]
            )
        )
    return frames


def fire(cols: int, rows: int) -> Frames:
    """Flames rising from the bottom: white-yellow at the base, then orange and red."""
    frames = []
    for i in range(24):
        t = 2 * math.pi * i / 24
        g = _blank(cols, rows)
        for x in range(cols):
            height = rows * (
                0.5 + 0.22 * math.sin(t + x * 0.9) + 0.14 * math.sin(2 * t + x * 2.3)
            )
            for n in range(max(1, round(height))):
                y = rows - 1 - n
                if y < 0:
                    break
                level = n / max(height, 1)
                g[y][x] = (
                    (255, 230, 120) if level < 0.2 else Y if level < 0.45
                    else ORANGE if level < 0.75 else R
                )
        frames.append(_flat(g))
    return frames


def fireworks(cols: int, rows: int) -> Frames:
    """Three rockets that rise and burst in turn."""
    bursts = [
        (cols // 5, rows // 3, R),
        (cols // 2, rows // 4, Y),
        (4 * cols // 5, rows // 3, CYAN),
    ]
    rays = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)]
    frames = []
    for i in range(36):
        g = _blank(cols, rows)
        for n, (cx, cy, color) in enumerate(bursts):
            t = (i - n * 12) % 36
            if t < 4:  # the rocket climbs
                y = rows - 1 - (rows - 1 - cy) * t // 4
                _rect(g, cx, y, 1, 2, W)
            elif t < 12:  # the burst opens and fades
                radius = t - 3
                fade = 1.0 if t < 8 else (12 - t) / 5
                for dx, dy in rays:
                    for step in (radius, radius - 1):
                        x, y = cx + dx * step, cy + dy * step
                        if step > 0 and 0 <= x < cols and 0 <= y < rows:
                            g[y][x] = _dim(color, fade if step == radius else fade * 0.5)
                if t < 6:
                    _rect(g, cx, cy, 1, 1, W)
        frames.append(_flat(g))
    return frames


def flag_italy(cols: int, rows: int) -> Frames:
    """Green, white and red bands with a wave of light that moves across."""
    third = cols / 3
    frames = []
    for i in range(16):
        g = _blank(cols, rows)
        for x in range(cols):
            color = (0, 200, 0) if x < third else W if x < 2 * third else R
            wave = 0.85 + 0.15 * math.sin(2 * math.pi * (x / 12 - i / 16))
            for y in range(rows):
                g[y][x] = _dim(color, wave)
        frames.append(_flat(g))
    return frames


def color_fade(cols: int, rows: int) -> Frames:
    """The whole screen moves slowly through all colors."""
    return [[_hue(i / 36)] * (cols * rows) for i in range(36)]


# ---------------------------------------------------------------------------
# Pictures: drawn for 32 x 16, centered on bigger grids
# ---------------------------------------------------------------------------

SCENE_COLS, SCENE_ROWS = 32, 16

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
SLEIGH = ["....RR.................W.W..", "....WW.................W.W..",
          "RR.RRRR...............OOOO..", "RRRRRRRRRRR...........OOOOR.",
          "RRRRRRRRRRYYYYOOOOOOOOOO....", "RRRRRRRRRR.....OOOOOOOOO....",
          ".RRRRRRRR......OOOOOOOOO....", "..W....W.......", "WWWWWWWWWWW...."]
SLEIGH_LEGS = [("OO....OO.....", "OO....OO....."), ("O......OO....", ".OO.....OO..."),
               ("OO....OO.....", "OO....OO....."), (".OO..OO......", "..OO.OO......")]


def _scene() -> Grid:
    return _blank(SCENE_COLS, SCENE_ROWS)


def _draw_heart(g: Grid, big: bool, x_center: int) -> None:
    shape = HEART if big else HEART_SMALL
    _stamp(g, shape, x_center - len(shape[0]) // 2, (SCENE_ROWS - len(shape)) // 2, {"X": R})


def _draw_star(g: Grid, phase: int, x0: int) -> None:
    for r, line in enumerate(STAR):
        for c, ch in enumerate(line):
            if ch == "X":
                core = phase and abs(c - 7) + abs(r - 6) <= phase * 2
                g[1 + r][x0 + c] = W if core else Y


def _heart_scenes() -> list[Grid]:
    scenes = []
    for big in [True] * 4 + [False] * 2 + [True] * 2 + [False] * 4:
        g = _scene()
        _draw_heart(g, big, SCENE_COLS // 2)
        scenes.append(g)
    return scenes


def _star_scenes() -> list[Grid]:
    scenes = []
    for phase in STAR_PHASES:
        g = _scene()
        _draw_star(g, phase, (SCENE_COLS - 15) // 2)
        scenes.append(g)
    return scenes


def _heart_and_star_scenes() -> list[Grid]:
    scenes = []
    for i, phase in enumerate(STAR_PHASES):
        g = _scene()
        _draw_heart(g, i < 5, 7)
        _draw_star(g, phase, 16)
        scenes.append(g)
    return scenes


def _tree_scenes() -> list[Grid]:
    half_widths = {2: 1, 3: 2, 4: 3, 5: 2, 6: 4, 7: 5, 8: 6, 9: 4, 10: 5, 11: 6, 12: 7}
    balls = [(14, 4, R), (17, 7, Y), (12, 8, B), (18, 10, M), (11, 11, Y), (15, 11, R),
             (20, 11, B)]
    scenes = []
    for i in range(12):
        g = _scene()
        for y, hw in half_widths.items():
            _rect(g, 16 - hw, y, 2 * hw, 1, G)
        top = Y if (i // 2) % 2 == 0 else W
        _rect(g, 15, 0, 2, 2, top)
        _rect(g, 14, 1, 4, 1, top)
        for n, (x, y, color) in enumerate(balls):
            if (n + i // 3) % 2 == 0:
                _rect(g, x, y, 2, 2, color)
        _rect(g, 14, 13, 4, 2, ORANGE)
        _rect(g, 1, 10, 6, 5, R)
        _rect(g, 3, 10, 2, 5, Y)
        _rect(g, 1, 12, 6, 1, Y)
        _rect(g, 25, 11, 6, 4, B)
        _rect(g, 27, 11, 2, 4, Y)
        _rect(g, 25, 12, 6, 1, Y)
        _rect(g, 0, 15, SCENE_COLS, 1, W)
        scenes.append(g)
    return scenes


def _comet_scenes() -> list[Grid]:
    tail = ((1, Y), (2, Y), (3, Y), (4, ORANGE), (5, ORANGE), (6, ORANGE), (7, R), (8, R), (9, R))
    scenes = []
    for i in range(SCENE_COLS + 16):
        g = _scene()
        cx, cy = -4 + i, 7 + (1 if (i // 5) % 2 else 0)
        for d, color in tail:
            thin = d >= 7
            _rect(g, cx - 3 - d, cy - 1 + (1 if thin else 0), 1, 1 if thin else 3, color)
        for dy, hw in ((-3, 0), (-2, 1), (-1, 2), (0, 3), (1, 2), (2, 1), (3, 0)):
            _rect(g, cx - hw, cy + dy, 2 * hw + 1, 1, W)
        _rect(g, cx - 1, cy - 1, 3, 3, Y)
        scenes.append(g)
    return scenes


def _sleigh_scenes() -> list[Grid]:
    palette = {"R": R, "W": W, "Y": Y, "O": ORANGE}
    moon = ((28, 0), (29, 0), (27, 1), (28, 1), (29, 1), (30, 1), (28, 2), (29, 2))
    scenes = []
    for i in range(28 + SCENE_COLS):
        g = _scene()
        for x, y in moon:
            g[y][x] = (255, 220, 90)
        upper, lower = SLEIGH_LEGS[(i // 2) % 4]
        sprite = [*SLEIGH[:7], SLEIGH[7] + upper, SLEIGH[8] + lower]
        _stamp(g, sprite, -28 + i, 4 + (1 if (i // 4) % 2 else 0), palette)
        _rect(g, 0, 15, SCENE_COLS, 1, W)
        scenes.append(g)
    return scenes


def _picture(scenes: Callable[[], list[Grid]]) -> Callable[[int, int], Frames]:
    """Wrap a 32 x 16 scene builder as an effect that centers it on the grid."""

    def effect(cols: int, rows: int) -> Frames:
        if cols < SCENE_COLS or rows < SCENE_ROWS:
            raise ValueError(f"this picture needs at least {SCENE_COLS}x{SCENE_ROWS} LEDs")
        x0, y0 = (cols - SCENE_COLS) // 2, (rows - SCENE_ROWS) // 2
        frames = []
        for scene in scenes():
            g = _blank(cols, rows)
            for y, row in enumerate(scene):
                g[y0 + y][x0 : x0 + SCENE_COLS] = row
            frames.append(_flat(g))
        return frames

    return effect


class Effect(NamedTuple):
    build: Callable[[int, int], Frames]
    speed: int  # playback speed that looks right, 1-100
    picture: bool = False  # needs at least 32 x 16


EFFECTS: dict[str, Effect] = {
    "sparkle": Effect(sparkle, 70),
    "sparkle_gold": Effect(sparkle_gold, 70),
    "rain": Effect(rain, 80),
    "snow": Effect(snow, 55),
    "matrix": Effect(matrix, 75),
    "fire": Effect(fire, 75),
    "fireworks": Effect(fireworks, 75),
    "rainbow": Effect(rainbow, 70),
    "plasma": Effect(plasma, 65),
    "color_fade": Effect(color_fade, 50),
    "flag_italy": Effect(flag_italy, 65),
    "heart": Effect(_picture(_heart_scenes), 55, True),
    "star": Effect(_picture(_star_scenes), 55, True),
    "heart_and_star": Effect(_picture(_heart_and_star_scenes), 55, True),
    "tree": Effect(_picture(_tree_scenes), 45, True),
    "comet": Effect(_picture(_comet_scenes), 70, True),
    "sleigh": Effect(_picture(_sleigh_scenes), 70, True),
}


def available(cols: int, rows: int) -> list[str]:
    """Effect names that fit a grid: all patterns, and the pictures from 32 x 16 up."""
    fits = cols >= SCENE_COLS and rows >= SCENE_ROWS
    return [name for name, effect in EFFECTS.items() if fits or not effect.picture]


def build(name: str, cols: int, rows: int) -> Frames:
    """Return the frames of effect ``name`` for a grid."""
    if name not in EFFECTS:
        raise ValueError(f"unknown effect: {name!r}")
    return EFFECTS[name].build(cols, rows)
