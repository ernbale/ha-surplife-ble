"""Text rendering for the IOTBT curtain and net lights: a 5 x 7 font and scrolling frames.

Pure Python. The frames are row-major image pixels (index ``y * cols + x``), the same
layout :func:`curtain_c2.image_to_frame` takes.
"""

from __future__ import annotations

import unicodedata
from typing import NamedTuple

RGB = tuple[int, int, int]
BLACK: RGB = (0, 0, 0)
GLYPH_ROWS = 7
LETTER_GAP = 2

# 5 x 7 glyphs, one string of bits per row, top to bottom.
FONT: dict[str, str] = {
    "A": "01110 10001 10001 11111 10001 10001 10001",
    "B": "11110 10001 10001 11110 10001 10001 11110",
    "C": "01110 10001 10000 10000 10000 10001 01110",
    "D": "11110 10001 10001 10001 10001 10001 11110",
    "E": "11111 10000 10000 11110 10000 10000 11111",
    "F": "11111 10000 10000 11110 10000 10000 10000",
    "G": "01110 10001 10000 10111 10001 10001 01111",
    "H": "10001 10001 10001 11111 10001 10001 10001",
    "I": "111 010 010 010 010 010 111",
    "J": "00111 00010 00010 00010 00010 10010 01100",
    "K": "10001 10010 10100 11000 10100 10010 10001",
    "L": "10000 10000 10000 10000 10000 10000 11111",
    "M": "10001 11011 10101 10101 10001 10001 10001",
    "N": "10001 11001 10101 10011 10001 10001 10001",
    "O": "01110 10001 10001 10001 10001 10001 01110",
    "P": "11110 10001 10001 11110 10000 10000 10000",
    "Q": "01110 10001 10001 10001 10101 10010 01101",
    "R": "11110 10001 10001 11110 10100 10010 10001",
    "S": "01111 10000 10000 01110 00001 00001 11110",
    "T": "11111 00100 00100 00100 00100 00100 00100",
    "U": "10001 10001 10001 10001 10001 10001 01110",
    "V": "10001 10001 10001 10001 10001 01010 00100",
    "W": "10001 10001 10001 10101 10101 11011 10001",
    "X": "10001 10001 01010 00100 01010 10001 10001",
    "Y": "10001 10001 01010 00100 00100 00100 00100",
    "Z": "11111 00001 00010 00100 01000 10000 11111",
    "0": "01110 10001 10001 10001 10001 10001 01110",
    "1": "010 110 010 010 010 010 111",
    "2": "01110 10001 00001 00010 00100 01000 11111",
    "3": "11110 00001 00001 01110 00001 00001 11110",
    "4": "10010 10010 10010 11111 00010 00010 00010",
    "5": "11111 10000 11110 00001 00001 10001 01110",
    "6": "00110 01000 10000 11110 10001 10001 01110",
    "7": "11111 00001 00010 00100 01000 01000 01000",
    "8": "01110 10001 10001 01110 10001 10001 01110",
    "9": "01110 10001 10001 01111 00001 00010 01100",
    " ": "000 000 000 000 000 000 000",
    ".": "0 0 0 0 0 0 1",
    ",": "00 00 00 00 00 01 10",
    "!": "1 1 1 1 1 0 1",
    "?": "01110 10001 00001 00010 00100 00000 00100",
    "-": "000 000 000 111 000 000 000",
    "+": "000 000 010 111 010 000 000",
    ":": "0 0 1 0 1 0 0",
    "'": "1 1 0 0 0 0 0",
    "/": "001 001 010 010 010 100 100",
}
# Bold is made by widening every stroke to two pixels. Glyphs whose strokes are one pixel
# apart would fill in, so they are drawn by hand.
BOLD_FONT: dict[str, str] = {
    "G": "011110 110011 110000 110111 110011 110011 011111",
    "M": "1100011 1110111 1111111 1101011 1100011 1100011 1100011",
    "N": "110011 111011 111011 110111 110111 110011 110011",
    "Q": "011110 110011 110011 110011 110111 110110 011011",
    "W": "1100011 1100011 1100011 1101011 1111111 1110111 1100011",
    " ": "000 000 000 000 000 000 000",
}


def normalize(text: str) -> str:
    """Upper-case ``text`` and drop accents. Characters without a glyph become spaces."""
    decomposed = unicodedata.normalize("NFKD", text.upper())
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return "".join(ch if ch in FONT else " " for ch in plain)


def glyph(ch: str, *, bold: bool = False) -> list[str]:
    """Return the 7 rows of ``ch`` as strings of ``0`` and ``1``."""
    if not bold:
        return FONT[ch].split()
    if ch in BOLD_FONT:
        return BOLD_FONT[ch].split()
    return [
        "".join(
            "1" if (c < len(row) and row[c] == "1") or (c > 0 and row[c - 1] == "1") else "0"
            for c in range(len(row) + 1)
        )
        for row in FONT[ch].split()
    ]


def text_columns(text: str, *, bold: bool = False) -> list[list[bool]]:
    """Return the text as a list of columns, each with 7 booleans (top to bottom)."""
    columns: list[list[bool]] = []
    for ch in normalize(text):
        rows = glyph(ch, bold=bold)
        for c in range(len(rows[0])):
            columns.append([rows[r][c] == "1" for r in range(GLYPH_ROWS)])
        columns.extend([[False] * GLYPH_ROWS] * LETTER_GAP)
    return columns[:-LETTER_GAP] if columns else []


SIZES = ("small", "medium", "large")
_ROW_REPEATS = {
    "small": [1] * GLYPH_ROWS,  # 7 LEDs tall
    "medium": [2, 1, 1, 2, 1, 1, 2],  # 10 LEDs tall: top, middle and bottom rows doubled
    "large": [2] * GLYPH_ROWS,  # 14 LEDs tall, and every column is doubled too
}


def row_repeats(rows: int, size: str | None = None) -> list[int]:
    """How many LED rows each of the 7 glyph rows covers.

    ``size`` is small (7 LEDs tall), medium (10) or large (14, twice as wide too). Without
    a size, the letters are medium from 14 rows up, which reads better on a coarse grid
    than small and leaves a margin, and small below that.
    """
    if rows < GLYPH_ROWS:
        raise ValueError(f"text needs at least {GLYPH_ROWS} rows")
    if size is None:
        size = "medium" if rows >= 14 else "small"
    if size not in _ROW_REPEATS:
        raise ValueError(f"size must be one of {', '.join(SIZES)}")
    repeats = _ROW_REPEATS[size]
    if sum(repeats) > rows:
        raise ValueError(f"{size} text is {sum(repeats)} LEDs tall and the screen has {rows} rows")
    return repeats


class TextAnimation(NamedTuple):
    frames: list[list[RGB]]  # row-major image pixels, one list per frame
    strip: list[list[RGB]]  # the whole text as rows of pixels, for a preview
    step: int  # LEDs the text moves per frame (0 for static text)


def render_text(
    text: str,
    *,
    cols: int,
    rows: int,
    color: RGB = (255, 200, 0),
    bold: bool = True,
    max_frames: int = 100,
    scroll: bool | None = None,
    size: str | None = None,
) -> TextAnimation:
    """Render ``text`` as one static frame or as a right-to-left scrolling animation.

    Text that fits the width is centered in one frame, unless ``scroll`` is True. Longer
    text scrolls in from the right and out on the left. If one LED per frame needs more
    than ``max_frames`` frames, the text moves 2, 3 or more LEDs per frame instead.

    ``size`` is described in :func:`row_repeats`. Large text doubles every pixel of the
    plain glyph, so its strokes are already two LEDs wide and ``bold`` is ignored.
    """
    repeats = row_repeats(rows, size)
    large = repeats == _ROW_REPEATS["large"]
    columns = text_columns(text, bold=bold and not large)
    if large:
        columns = [column for column in columns for _ in range(2)]
    if not columns or not any(any(column) for column in columns):
        raise ValueError("the text has no printable characters")
    if max_frames < 1:
        raise ValueError("max_frames must be at least 1")
    height = sum(repeats)
    top = (rows - height) // 2

    def paint(source: list[list[bool]], width: int) -> list[list[RGB]]:
        grid = [[BLACK] * width for _ in range(rows)]
        for x in range(width):
            y = top
            for r, repeat in enumerate(repeats):
                for _ in range(repeat):
                    if source[x][r]:
                        grid[y][x] = color
                    y += 1
        return grid

    strip = paint(columns, len(columns))
    blank = [False] * GLYPH_ROWS
    if scroll is None:
        scroll = len(columns) > cols
    if not scroll:
        if len(columns) > cols:
            raise ValueError(f"the text is {len(columns)} LEDs wide and the screen is {cols}")
        left = (cols - len(columns)) // 2
        padded = [blank] * left + columns + [blank] * (cols - left - len(columns))
        frame = paint(padded, cols)
        return TextAnimation([[pixel for row in frame for pixel in row]], strip, 0)
    band = [blank] * cols + columns + [blank] * cols
    travel = len(columns) + cols
    step = -(-travel // max_frames)
    frames = []
    for offset in range(0, travel, step):
        frame = paint(band[offset : offset + cols], cols)
        frames.append([pixel for row in frame for pixel in row])
    return TextAnimation(frames, strip, step)


def render_strip_png(strip: list[list[RGB]], scale: int = 10) -> bytes:
    """Render the whole text strip as a PNG, scaled up with nearest-neighbor."""
    try:
        import io

        from PIL import Image
    except ImportError as err:
        raise RuntimeError("Pillow is required to render a preview") from err
    height, width = len(strip), len(strip[0])
    image = Image.frombytes(
        "RGB", (width, height), bytes(c for row in strip for pixel in row for c in pixel)
    )
    image = image.resize((width * scale, height * scale), Image.Resampling.NEAREST)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
