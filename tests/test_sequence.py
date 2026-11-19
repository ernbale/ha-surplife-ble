"""Tests for the sequence line parser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.surplife_ble.core import effects, sequence
from custom_components.surplife_ble.core.sequence import Step

INTEGRATION = Path(__file__).parents[1] / "custom_components" / "surplife_ble"


def test_parse_reads_effects_texts_and_durations() -> None:
    line = 'cuore 30s; BUON NATALE 1m; Pioggia; "neve" 45s; AUGURI 2027; sparkle_gold 2 min'
    assert sequence.parse(line) == [
        Step("effect", "heart", 30),
        Step("text", "BUON NATALE", 60),
        Step("effect", "rain", 60),
        Step("text", "neve", 45),  # quoted: a text even if it is an effect name
        Step("text", "AUGURI 2027", 60),  # a plain number belongs to the text
        Step("effect", "sparkle_gold", 120),
    ]


def test_parse_applies_the_default_and_the_limits() -> None:
    assert sequence.parse("rain", 90) == [Step("effect", "rain", 90)]
    assert sequence.parse("rain 5s")[0].seconds == sequence.MIN_SECONDS
    assert sequence.parse("rain 99999m")[0].seconds == sequence.MAX_SECONDS
    assert sequence.parse("  ;rain;; ") == [Step("effect", "rain", 60)]
    two = [Step("effect", "rain", 60), Step("effect", "snow", 30)]
    assert sequence.parse("rain\nsnow 30s") == two


def test_parse_refuses_an_empty_or_too_long_sequence() -> None:
    for line in ("", " ; ; "):
        with pytest.raises(ValueError, match="no steps"):
            sequence.parse(line)
    with pytest.raises(ValueError, match="empty"):
        sequence.parse('"" 30s')
    with pytest.raises(ValueError, match="at most"):
        sequence.parse(";".join(["rain"] * (sequence.MAX_STEPS + 1)))


def test_from_dicts_matches_names_and_checks_the_steps() -> None:
    steps = sequence.from_dicts(
        [{"effect": "Stella cometa", "seconds": 40}, {"text": " ciao "}, {"effect": "FIRE"}], 30
    )
    assert steps == [
        Step("effect", "comet", 40),
        Step("text", "ciao", 30),
        Step("effect", "fire", 30),
    ]
    with pytest.raises(ValueError, match="unknown effect"):
        sequence.from_dicts([{"effect": "nope"}])
    with pytest.raises(ValueError, match="effect or a text"):
        sequence.from_dicts([{"seconds": 30}])
    with pytest.raises(ValueError, match="no steps"):
        sequence.from_dicts([])


def test_effect_names_match_the_translations() -> None:
    assert set(effects.NAMES) == set(effects.EFFECTS)
    english = json.loads((INTEGRATION / "translations" / "en.json").read_text(encoding="utf-8"))
    italian = json.loads((INTEGRATION / "translations" / "it.json").read_text(encoding="utf-8"))
    for key, (en, it) in effects.NAMES.items():
        assert english["entity"]["select"]["animation"]["state"][key] == en
        assert italian["entity"]["select"]["animation"]["state"][key] == it
        assert sequence.effect_key(en) == key
        assert sequence.effect_key(it.upper()) == key
