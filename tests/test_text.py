"""Tests for the text renderer used by the show_text service."""

from __future__ import annotations

import pytest

from custom_components.surplife_ble.core import curtain_c2, text

BLACK = (0, 0, 0)
YELLOW = (255, 200, 0)


def test_every_glyph_has_seven_rows_of_equal_width() -> None:
    for font in (text.FONT, text.BOLD_FONT):
        for ch, bits in font.items():
            rows = bits.split()
            assert len(rows) == 7, ch
            assert len({len(row) for row in rows}) == 1, ch
            assert set("".join(rows)) <= {"0", "1"}, ch


def test_normalize_upper_cases_drops_accents_and_unknown_characters() -> None:
    assert text.normalize("Perché no?") == "PERCHE NO?"
    assert text.normalize("a~b") == "A B"


def test_bold_widens_strokes_without_closing_the_letter_a() -> None:
    assert text.glyph("I", bold=True) == ["1111", "0110", "0110", "0110", "0110", "0110", "1111"]
    assert text.glyph("A", bold=True)[1] == "110011"
    assert text.glyph("N", bold=True) == text.BOLD_FONT["N"].split()


def test_short_text_is_one_centered_frame() -> None:
    rendered = text.render_text("CIAO", cols=32, rows=16)
    assert rendered.step == 0
    assert len(rendered.frames) == 1
    frame = rendered.frames[0]
    assert len(frame) == 32 * 16
    lit = [i for i, pixel in enumerate(frame) if pixel != BLACK]
    assert {frame[i] for i in lit} == {YELLOW}
    rows = {i // 32 for i in lit}
    assert (min(rows), max(rows)) == (3, 12)  # 10 LEDs tall, 3 dark rows above and below
    columns = {i % 32 for i in lit}
    assert min(columns) == 31 - max(columns)  # centered


def test_long_text_scrolls_and_stays_within_the_frame_limit() -> None:
    rendered = text.render_text("BUON NATALE!", cols=32, rows=16, max_frames=100)
    width = len(rendered.strip[0])
    assert width > 32
    assert rendered.step == -(-(width + 32) // 100)
    assert len(rendered.frames) <= 100
    assert all(pixel == BLACK for pixel in rendered.frames[0])  # the text enters from the right
    assert any(pixel != BLACK for pixel in rendered.frames[len(rendered.frames) // 2])
    very_long = text.render_text("A" * 150, cols=32, rows=16, max_frames=100)
    assert len(very_long.frames) <= 100
    assert very_long.step > 1


def test_static_text_that_does_not_fit_is_refused() -> None:
    with pytest.raises(ValueError, match="wide"):
        text.render_text("BUON NATALE", cols=32, rows=16, scroll=False)
    with pytest.raises(ValueError, match="no printable"):
        text.render_text("   ", cols=32, rows=16)


def test_small_grids_use_seven_rows_and_frames_fit_the_upload() -> None:
    rendered = text.render_text("HI", cols=20, rows=20)
    assert len(rendered.frames[0]) == 400
    mapped = curtain_c2.image_to_frame(rendered.frames[0])
    assert len(curtain_c2.build_upload([mapped])) == 4
    assert text.row_repeats(8) == [1] * 7
    with pytest.raises(ValueError):
        text.row_repeats(6)


def test_strip_png_is_the_whole_text() -> None:
    rendered = text.render_text("OK", cols=32, rows=16)
    png = text.render_strip_png(rendered.strip, scale=2)
    assert png.startswith(b"\x89PNG")


def test_sizes_set_the_letter_height_and_large_doubles_the_width() -> None:
    def height(size: str) -> int:
        frame = text.render_text("H", cols=32, rows=16, size=size).frames[0]
        lit_rows = {i // 32 for i, pixel in enumerate(frame) if pixel != BLACK}
        return max(lit_rows) - min(lit_rows) + 1

    assert [height(size) for size in text.SIZES] == [7, 10, 14]
    plain = len(text.render_text("HI", cols=32, rows=16, size="small", bold=False).strip[0])
    assert len(text.render_text("HI", cols=32, rows=16, size="large").strip[0]) == 2 * plain
    with pytest.raises(ValueError, match="rows"):
        text.render_text("H", cols=20, rows=12, size="large")
    with pytest.raises(ValueError, match="size must be"):
        text.render_text("H", cols=32, rows=16, size="huge")
