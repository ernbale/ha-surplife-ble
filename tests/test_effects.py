"""Tests for the built-in effects of the animation selector and the show_effect service."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.surplife_ble.core import curtain_c2, effects

INTEGRATION = Path(__file__).parents[1] / "custom_components" / "surplife_ble"
BLACK = (0, 0, 0)


@pytest.mark.parametrize("name", list(effects.EFFECTS))
def test_every_effect_fits_the_32x16_net(name: str) -> None:
    frames = effects.build(name, 32, 16)
    assert 1 <= len(frames) <= curtain_c2.max_upload_frames(32, 16)
    assert all(len(frame) == 32 * 16 for frame in frames)
    assert all(0 <= c <= 255 for frame in frames for pixel in frame for c in pixel)
    assert any(pixel != BLACK for frame in frames for pixel in frame)
    assert frames == effects.build(name, 32, 16)  # deterministic
    assert 1 <= effects.EFFECTS[name].speed <= 100
    mapped = [curtain_c2.image_to_frame(frame, cols=32, rows=16) for frame in frames]
    assert len(curtain_c2.build_upload(mapped, cols=32, rows=16)) == len(frames) + 3


def test_patterns_fit_the_20x20_curtain_and_pictures_do_not() -> None:
    names = effects.available(20, 20)
    # The heart is 13 x 11 and fits. The sleigh crosses all 32 columns and does not.
    assert "sparkle" in names and "heart" in names and "sleigh" not in names
    for name in names:
        frames = effects.build(name, 20, 20)
        assert len(frames) <= curtain_c2.MAX_UPLOAD_FRAMES
        assert all(len(frame) == 400 for frame in frames)
    with pytest.raises(ValueError, match="at least 32x"):
        effects.build("sleigh", 20, 20)
    with pytest.raises(ValueError, match="unknown effect"):
        effects.build("nope", 32, 16)
    assert effects.available(32, 16) == list(effects.EFFECTS)


def test_pictures_are_centered_on_a_bigger_grid() -> None:
    small = effects.build("heart", 32, 16)[0]
    big = effects.build("heart", 40, 20)[0]
    for y in range(16):
        assert big[(y + 2) * 40 + 4 : (y + 2) * 40 + 36] == small[y * 32 : (y + 1) * 32]


def test_falling_effects_loop_without_a_jump() -> None:
    """The last frame moved one step down is the first frame again."""
    for name in ("rain", "matrix"):
        frames = effects.build(name, 32, 16)
        first, last = frames[0], frames[-1]
        for x in range(32):
            for y in range(1, 16):
                assert first[y * 32 + x] == last[(y - 1) * 32 + x], (name, x, y)


def test_every_effect_has_a_name_in_every_translation() -> None:
    for file in ("strings.json", "translations/en.json", "translations/it.json"):
        data = json.loads((INTEGRATION / file).read_text(encoding="utf-8"))
        assert set(data["entity"]["select"]["animation"]["state"]) == set(effects.EFFECTS), file
        assert set(data["selector"]["animation"]["options"]) == set(effects.EFFECTS), file
