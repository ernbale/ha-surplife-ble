"""Built-in animations for the IOTBT curtain and net lights, drawn in code.

Every effect is a function ``(cols, rows) -> frames``. A frame is a list of row-major RGB
pixels (index ``y * cols + x``), the layout :func:`curtain_c2.image_to_frame` takes. The
effects are deterministic and loop without a jump. Pure Python, no Pillow.

The patterns (sparkle, rain, snow, rainbow, fire, plasma...) fit any grid. The pictures
(heart, star, tree, comet, sleigh) are drawn for 32 x 16 and are centered on bigger grids.
"""

from __future__ import annotations

import colorsys
import functools
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


# ---------------------------------------------------------------------------
# More patterns: any grid size
# ---------------------------------------------------------------------------


def _blend(a: RGB, b: RGB, f: float) -> RGB:
    return (
        round(a[0] + (b[0] - a[0]) * f),
        round(a[1] + (b[1] - a[1]) * f),
        round(a[2] + (b[2] - a[2]) * f),
    )


def _ramp(stops: tuple[RGB, ...]) -> Callable[[float], RGB]:
    """A color scale through ``stops`` for values from 0 to 1."""

    def color(value: float) -> RGB:
        value = min(max(value, 0.0), 1.0) * (len(stops) - 1)
        n = min(int(value), len(stops) - 2)
        return _blend(stops[n], stops[n + 1], value - n)

    return color


def _clouds(cols: int, rows: int, palette: Callable[[float], RGB]) -> Frames:
    """The drifting blobs of ``plasma`` in the colors of ``palette``."""
    frames = []
    for i in range(32):
        t = 2 * math.pi * i / 32
        frames.append(
            [
                palette(
                    (math.sin(x / 5 + t) + math.sin(y / 3 - t) + math.sin((x + y) / 7 + t)) / 4
                    + 0.5
                )
                for y in range(rows)
                for x in range(cols)
            ]
        )
    return frames


def lava(cols: int, rows: int) -> Frames:
    return _clouds(cols, rows, _ramp(((70, 0, 0), R, ORANGE, (255, 220, 0))))


def ocean(cols: int, rows: int) -> Frames:
    return _clouds(cols, rows, _ramp(((0, 0, 70), (0, 60, 200), (0, 200, 220), (200, 255, 255))))


def aurora(cols: int, rows: int) -> Frames:
    stops = ((0, 0, 30), (0, 160, 80), (0, 255, 120), (120, 0, 200), (20, 0, 60))
    return _clouds(cols, rows, _ramp(stops))


def confetti(cols: int, rows: int) -> Frames:
    """Pieces of every color falling, two LEDs tall."""
    rng = random.Random(21)
    period = rows + 3
    colors = (R, Y, G, B, M, CYAN, ORANGE, W)
    pieces = [
        (x, rng.randrange(period), rng.choice(colors))
        for x in range(cols)
        for _ in range(2)
        if rng.random() < 0.6
    ]
    frames = []
    for i in range(period):
        g = _blank(cols, rows)
        for x, phase, color in pieces:
            _rect(g, x, (i + phase) % period - 1, 1, 2, color)
        frames.append(_flat(g))
    return frames


MINI_HEART = [".X.X.", "XXXXX", "XXXXX", ".XXX.", "..X.."]


def hearts_rain(cols: int, rows: int) -> Frames:
    """Small red and pink hearts falling."""
    rng = random.Random(29)
    period = rows + len(MINI_HEART) + 1
    hearts = [
        (x, rng.randrange(period), rng.choice((R, R, (255, 90, 150))))
        for x in range(1, cols - 5, 7)
        for _ in range(2)
    ]
    frames = []
    for i in range(period):
        g = _blank(cols, rows)
        for x, phase, color in hearts:
            _stamp(g, MINI_HEART, x, (i + phase) % period - len(MINI_HEART), {"X": color})
        frames.append(_flat(g))
    return frames


def waves(cols: int, rows: int) -> Frames:
    """The sea: a white crest that rolls over deepening blue."""
    frames = []
    for i in range(24):
        t = 2 * math.pi * i / 24
        g = _blank(cols, rows)
        for x in range(cols):
            crest = rows * 0.45 + 2.5 * math.sin(2 * math.pi * x / 16 - t)
            crest += 1.2 * math.sin(2 * math.pi * x / 8 + t)
            for y in range(rows):
                if y >= crest:
                    depth = (y - crest) / max(rows - crest, 1)
                    g[y][x] = W if y < crest + 1 else _blend((0, 130, 255), (0, 20, 90), depth)
        frames.append(_flat(g))
    return frames


def starry_night(cols: int, rows: int) -> Frames:
    """Stars that twinkle slowly on a dark blue sky."""
    rng = random.Random(13)
    sky = (0, 0, 40)
    stars = [
        (rng.randrange(cols), rng.randrange(rows), rng.choice((12, 16, 24)), rng.randrange(48))
        for _ in range(cols * rows // 12)
    ]
    frames = []
    for i in range(48):
        g = [[sky] * cols for _ in range(rows)]
        for x, y, period, phase in stars:
            glow = 0.5 + 0.5 * math.cos(2 * math.pi * (i + phase) / period)
            g[y][x] = _blend(sky, W, glow)
        frames.append(_flat(g))
    return frames


def meteors(cols: int, rows: int) -> Frames:
    """Shooting stars that cross the screen slantwise."""
    rng = random.Random(17)
    tail = (W, (200, 220, 255), (120, 160, 255), (60, 90, 200), (20, 40, 120))
    period = rows + len(tail) + 7
    shots = [(rng.randrange(4, cols + rows), rng.randrange(period)) for _ in range(cols // 5)]
    frames = []
    for i in range(period):
        g = _blank(cols, rows)
        for x0, phase in shots:
            step = (i + phase) % period
            for n, color in enumerate(tail):
                x, y = x0 - step + n, step - n
                if 0 <= x < cols and 0 <= y < rows:
                    g[y][x] = color
        frames.append(_flat(g))
    return frames


def bouncing_ball(cols: int, rows: int) -> Frames:
    """A ball that bounces across the screen and back, changing color."""
    size = 3
    span = cols - size
    count = 2 * span
    frames = []
    for i in range(count):
        x = i if i <= span else count - i
        phase = (i * 4 / count) % 1
        y = round((rows - size) * (1 - 4 * phase * (1 - phase)))
        g = _blank(cols, rows)
        _rect(g, x, y, size, size, _hue(i / count))
        frames.append(_flat(g))
    return frames


def disco(cols: int, rows: int) -> Frames:
    """Big squares that change color at random."""
    rng = random.Random(23)
    colors = (R, Y, G, B, M, CYAN, ORANGE, K, K)
    frames = []
    for _ in range(16):
        g = _blank(cols, rows)
        for y in range(0, rows, 4):
            for x in range(0, cols, 4):
                _rect(g, x, y, 4, 4, rng.choice(colors))
        frames.append(_flat(g))
    return frames


def pinwheel(cols: int, rows: int) -> Frames:
    """All the colors turning around the center."""
    cx, cy = (cols - 1) / 2, (rows - 1) / 2
    return [
        [
            _hue(math.atan2(y - cy, x - cx) / (2 * math.pi) + i / 24)
            for y in range(rows)
            for x in range(cols)
        ]
        for i in range(24)
    ]


def ripples(cols: int, rows: int) -> Frames:
    """Rings that spread from the center, like a stone in water."""
    cx, cy = (cols - 1) / 2, (rows - 1) / 2
    frames = []
    for i in range(24):
        frame = []
        for y in range(rows):
            for x in range(cols):
                d = math.hypot(x - cx, y - cy)
                level = 0.5 + 0.5 * math.sin(2 * math.pi * (d / 8 - i / 24))
                frame.append(_dim(_hue(0.5 + d / 60), level * level))
        frames.append(frame)
    return frames


def christmas_lights(cols: int, rows: int) -> Frames:
    """Rows of colored bulbs that blink in turn."""
    colors = (R, G, Y, B)
    frames = []
    for i in range(8):
        g = _blank(cols, rows)
        for row, y in enumerate(range(1, rows - 1, 4)):
            for n, x in enumerate(range(1 + 2 * (row % 2), cols - 1, 4)):
                color = colors[(n + row) % len(colors)]
                lit = (n + row + i // 2) % 2 == 0
                _rect(g, x, y, 2, 2, color if lit else _dim(color, 0.12))
        frames.append(_flat(g))
    return frames


def candy_stripes(cols: int, rows: int) -> Frames:
    """Slanted red and white stripes that slide, like a candy cane."""
    return [
        [R if ((x + y + i) // 4) % 2 == 0 else W for y in range(rows) for x in range(cols)]
        for i in range(8)
    ]


def checkerboard(cols: int, rows: int) -> Frames:
    """A checkerboard of two colors that swap and slowly change."""
    frames = []
    for i in range(24):
        pair = (_hue(i / 24), _hue(i / 24 + 0.5))
        frames.append(
            [
                pair[(x // 4 + y // 4 + i // 3) % 2]
                for y in range(rows)
                for x in range(cols)
            ]
        )
    return frames


def warm_glow(cols: int, rows: int) -> Frames:
    """The whole screen in warm light that breathes slowly."""
    warm = (255, 150, 40)
    return [
        [_dim(warm, 0.6 + 0.4 * math.sin(2 * math.pi * i / 24))] * (cols * rows) for i in range(24)
    ]


# ---------------------------------------------------------------------------
# More pictures: 32 x 16
# ---------------------------------------------------------------------------


def _disc(g: Grid, cx: float, cy: float, radius: float, color: RGB) -> None:
    for y in range(len(g)):
        for x in range(len(g[0])):
            if (x - cx) ** 2 + (y - cy) ** 2 <= radius**2:
                g[y][x] = color


def _smiley_scenes() -> list[Grid]:
    scenes = []
    for i in range(12):
        g = _scene()
        _disc(g, 15.5, 7.5, 7.6, Y)
        eye = 1 if i == 10 else 2  # it blinks once per loop
        _rect(g, 12, 5 + (2 - eye), 2, eye, K)
        _rect(g, 18, 5 + (2 - eye), 2, eye, K)
        _rect(g, 11, 9, 1, 1, K)
        _rect(g, 20, 9, 1, 1, K)
        _rect(g, 12, 10, 8, 1, K)
        _rect(g, 13, 11, 6, 1, K)
        scenes.append(g)
    return scenes


def _moon_scenes() -> list[Grid]:
    stars = [(22, 3), (27, 8), (19, 11), (4, 3), (28, 13), (24, 14)]
    scenes = []
    for i in range(12):
        g = _scene()
        _disc(g, 11.0, 7.5, 6.6, Y)
        _disc(g, 14.0, 6.0, 5.6, K)
        for n, (x, y) in enumerate(stars):
            if (n + i // 3) % 2 == 0:
                _rect(g, x - 1, y, 3, 1, W)
                _rect(g, x, y - 1, 1, 3, W)
            else:
                _rect(g, x, y, 1, 1, W)
        scenes.append(g)
    return scenes


def _gift_scenes() -> list[Grid]:
    scenes = []
    for i in range(8):
        ribbon = Y if (i // 2) % 2 == 0 else W
        g = _scene()
        _rect(g, 9, 7, 14, 9, R)
        _rect(g, 8, 5, 16, 2, (200, 0, 0))
        _rect(g, 15, 5, 2, 11, ribbon)
        _rect(g, 9, 10, 14, 1, ribbon)
        _rect(g, 11, 1, 4, 3, ribbon)
        _rect(g, 17, 1, 4, 3, ribbon)
        _rect(g, 12, 2, 2, 1, K)
        _rect(g, 18, 2, 2, 1, K)
        _rect(g, 15, 3, 2, 2, ribbon)
        scenes.append(g)
    return scenes


def _snowman_scenes() -> list[Grid]:
    rng = random.Random(31)
    flakes = [(x, rng.randrange(SCENE_ROWS)) for x in (1, 4, 7, 24, 27, 30, 2, 28)]
    scenes = []
    for i in range(SCENE_ROWS):
        g = _scene()
        for x, y0 in flakes:
            g[(y0 + i) % SCENE_ROWS][x] = W
        _disc(g, 15.5, 11.5, 4.6, W)
        _disc(g, 15.5, 5.5, 3.1, W)
        _rect(g, 13, 0, 6, 2, R)
        _rect(g, 12, 2, 8, 1, R)
        _rect(g, 14, 4, 1, 1, K)
        _rect(g, 17, 4, 1, 1, K)
        _rect(g, 15, 6, 2, 1, ORANGE)
        _rect(g, 15, 10, 2, 1, K)
        _rect(g, 15, 13, 2, 1, K)
        scenes.append(g)
    return scenes


MIN_PICTURE_SCALE = 0.5  # below half size a picture is no longer recognizable


def _shrink(scene: Grid, box: tuple[int, int, int, int], width: int, height: int) -> Grid:
    """Scale the ``box`` part of ``scene`` down to ``width`` x ``height``.

    Each new pixel takes the most common color of the pixels it covers, and stays dark
    if fewer than half of them are lit, so thick shapes keep their outline.
    """
    x0, y0, x1, y1 = box
    out = _blank(width, height)
    for y in range(height):
        ys = range(y0 + y * (y1 - y0) // height, max(y0 + (y + 1) * (y1 - y0) // height, 1))
        for x in range(width):
            xs = range(x0 + x * (x1 - x0) // width, x0 + (x + 1) * (x1 - x0) // width)
            block = [scene[sy][sx] for sy in ys for sx in xs]
            lit = [pixel for pixel in block if pixel != K]
            if block and len(lit) * 2 >= len(block):
                out[y][x] = max(set(lit), key=lit.count)
    return out


def _picture(scenes: Callable[[], list[Grid]]) -> Callable[[int, int], Frames]:
    """Wrap a 32 x 16 scene builder as an effect for other grids too.

    On a bigger grid the scene is centered. On a smaller one, for example a net with
    lines excluded, the dark border of the scene is cut away, and if the lit part is
    still too big it is scaled down, to half size at most.
    """

    @functools.cache
    def bounds() -> tuple[int, int, int, int]:
        lit = [
            (x, y)
            for scene in scenes()
            for y, row in enumerate(scene)
            for x, pixel in enumerate(row)
            if pixel != K
        ]
        xs, ys = [x for x, _ in lit], [y for _, y in lit]
        return min(xs), min(ys), max(xs) + 1, max(ys) + 1

    def smallest() -> tuple[int, int]:
        x0, y0, x1, y1 = bounds()
        return (
            math.ceil((x1 - x0) * MIN_PICTURE_SCALE),
            math.ceil((y1 - y0) * MIN_PICTURE_SCALE),
        )

    def window(grid: int, scene: int, low: int, high: int) -> tuple[int, int, int]:
        """(first scene line, first grid line, lines) for one axis."""
        if grid >= scene:
            return 0, (grid - scene) // 2, scene
        return min(max((low + high - grid) // 2, 0), scene - grid), 0, grid

    def effect(cols: int, rows: int) -> Frames:
        x0, y0, x1, y1 = bounds()
        lit_width, lit_height = x1 - x0, y1 - y0
        frames = []
        if cols >= lit_width and rows >= lit_height:
            sx, dx, width = window(cols, SCENE_COLS, x0, x1)
            sy, dy, height = window(rows, SCENE_ROWS, y0, y1)
            for scene in scenes():
                g = _blank(cols, rows)
                for y in range(height):
                    g[dy + y][dx : dx + width] = scene[sy + y][sx : sx + width]
                frames.append(_flat(g))
            return frames
        scale = min(cols / lit_width, rows / lit_height)
        if scale < MIN_PICTURE_SCALE:
            width, height = smallest()
            raise ValueError(f"this picture needs at least {width}x{height} LEDs")
        width, height = max(int(lit_width * scale), 1), max(int(lit_height * scale), 1)
        dx, dy = (cols - width) // 2, (rows - height) // 2
        for scene in scenes():
            g = _blank(cols, rows)
            for y, row in enumerate(_shrink(scene, bounds(), width, height)):
                g[dy + y][dx : dx + width] = row
            frames.append(_flat(g))
        return frames

    effect.size = smallest  # type: ignore[attr-defined]
    return effect


class Effect(NamedTuple):
    build: Callable[[int, int], Frames]
    speed: int  # playback speed that looks right, 1-100
    picture: bool = False  # a drawing with a smallest size, see ``_picture``


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
    "christmas_lights": Effect(christmas_lights, 40),
    "candy_stripes": Effect(candy_stripes, 55),
    "confetti": Effect(confetti, 70),
    "hearts_rain": Effect(hearts_rain, 60),
    "starry_night": Effect(starry_night, 55),
    "meteors": Effect(meteors, 80),
    "aurora": Effect(aurora, 60),
    "lava": Effect(lava, 60),
    "ocean": Effect(ocean, 60),
    "waves": Effect(waves, 60),
    "ripples": Effect(ripples, 65),
    "pinwheel": Effect(pinwheel, 65),
    "checkerboard": Effect(checkerboard, 45),
    "disco": Effect(disco, 45),
    "bouncing_ball": Effect(bouncing_ball, 80),
    "warm_glow": Effect(warm_glow, 45),
    "smiley": Effect(_picture(_smiley_scenes), 40, True),
    "moon": Effect(_picture(_moon_scenes), 40, True),
    "gift": Effect(_picture(_gift_scenes), 45, True),
    "snowman": Effect(_picture(_snowman_scenes), 55, True),
}

# English and Italian names, for the sequence parser. They match the translations.
NAMES: dict[str, tuple[str, str]] = {
    "sparkle": ("Sparkling lights", "Luci che brillano a caso"),
    "sparkle_gold": ("Sparkling lights, white and gold", "Luci che brillano, bianco e oro"),
    "rain": ("Rain", "Pioggia"),
    "snow": ("Snow", "Neve"),
    "matrix": ("Green rain", "Pioggia verde"),
    "fire": ("Fire", "Fuoco"),
    "fireworks": ("Fireworks", "Fuochi d'artificio"),
    "rainbow": ("Rainbow", "Arcobaleno"),
    "plasma": ("Color clouds", "Nuvole di colore"),
    "color_fade": ("Color fade", "Tinta che cambia"),
    "flag_italy": ("Italian flag", "Tricolore"),
    "heart": ("Heart", "Cuore"),
    "star": ("Star", "Stella"),
    "heart_and_star": ("Heart and star", "Cuore e stella"),
    "tree": ("Christmas tree", "Albero di Natale"),
    "comet": ("Comet", "Stella cometa"),
    "sleigh": ("Sleigh", "Slitta"),
    "christmas_lights": ("Christmas lights", "Luci di Natale"),
    "candy_stripes": ("Candy stripes", "Strisce bianche e rosse"),
    "confetti": ("Confetti", "Coriandoli"),
    "hearts_rain": ("Falling hearts", "Pioggia di cuori"),
    "starry_night": ("Starry night", "Cielo stellato"),
    "meteors": ("Shooting stars", "Stelle cadenti"),
    "aurora": ("Northern lights", "Aurora boreale"),
    "lava": ("Lava", "Lava"),
    "ocean": ("Ocean", "Oceano"),
    "waves": ("Waves", "Onde del mare"),
    "ripples": ("Ripples", "Cerchi nell'acqua"),
    "pinwheel": ("Pinwheel", "Girandola"),
    "checkerboard": ("Checkerboard", "Scacchiera"),
    "disco": ("Disco", "Discoteca"),
    "bouncing_ball": ("Bouncing ball", "Palla che rimbalza"),
    "warm_glow": ("Warm glow", "Luce calda"),
    "smiley": ("Smiley", "Faccina"),
    "moon": ("Moon and stars", "Luna e stelle"),
    "gift": ("Gift", "Regalo"),
    "snowman": ("Snowman", "Pupazzo di neve"),
}


def available(cols: int, rows: int) -> list[str]:
    """Effect names that fit a grid: all patterns, and the pictures it has room for."""
    names = []
    for name, effect in EFFECTS.items():
        if effect.picture:
            width, height = effect.build.size()  # type: ignore[attr-defined]
            if cols < width or rows < height:
                continue
        names.append(name)
    return names


def build(name: str, cols: int, rows: int) -> Frames:
    """Return the frames of effect ``name`` for a grid."""
    if name not in EFFECTS:
        raise ValueError(f"unknown effect: {name!r}")
    return EFFECTS[name].build(cols, rows)
