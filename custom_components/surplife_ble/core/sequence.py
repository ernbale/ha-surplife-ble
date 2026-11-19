"""Sequences for the IOTBT curtain and net: effects and texts shown one after the other.

A sequence is written as one line, with the steps separated by ``;``::

    heart 30s; BUON NATALE 1m; rain; "snow" 45s

- A step that is the name of a built-in effect shows that effect. Names are matched in
  English or Italian, upper or lower case (``rain``, ``Pioggia``).
- Anything else is a text. Put a text in quotes to show a word that is also an effect name.
- A duration is a number followed by ``s`` or ``m`` at the end of the step. Without one
  the default applies. A plain number is part of the text, so ``AUGURI 2027`` is a text.

Every step is uploaded to the flash memory of the device when it starts, so a step lasts
at least :data:`MIN_SECONDS`.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from . import effects

MIN_SECONDS = 20
MAX_SECONDS = 24 * 3600
DEFAULT_SECONDS = 60
MAX_STEPS = 50
_DURATION = re.compile(r"^(?P<body>.*?)\s+(?P<amount>\d+)\s*(?P<unit>s|sec|m|min)$", re.IGNORECASE)
_QUOTES = {'"': '"', "'": "'", "«": "»", "“": "”"}


class Step(NamedTuple):
    kind: str  # "effect" or "text"
    value: str  # effect key or the text to show
    seconds: int


def _clamp(seconds: int) -> int:
    return max(MIN_SECONDS, min(MAX_SECONDS, seconds))


RANDOM = "random"  # a step that shows a different built-in effect every time
_RANDOM_NAMES = ("random", "casuale", "a caso")


def effect_key(name: str) -> str | None:
    """Return the effect key for a key or an English or Italian name, else None.

    ``random``, ``casuale`` and ``a caso`` give :data:`RANDOM`.
    """
    wanted = name.strip().casefold().replace("_", " ")
    if wanted in _RANDOM_NAMES:
        return RANDOM
    for key, names in effects.NAMES.items():
        if wanted in (key.replace("_", " "), *(n.casefold() for n in names)):
            return key
    return None


def parse(text: str, default_seconds: int = DEFAULT_SECONDS) -> list[Step]:
    """Parse a sequence line into steps. Raises ValueError if it has no steps."""
    steps: list[Step] = []
    for part in re.split(r"[;\n]", text):
        part = part.strip()
        if not part:
            continue
        seconds = default_seconds
        if match := _DURATION.match(part):
            amount = int(match["amount"])
            seconds = amount * 60 if match["unit"].lower().startswith("m") else amount
            part = match["body"].strip()
        quoted = len(part) >= 2 and _QUOTES.get(part[0]) == part[-1]
        if quoted:
            part = part[1:-1].strip()
        if not part:
            raise ValueError("a step of the sequence is empty")
        key = None if quoted else effect_key(part)
        steps.append(Step("effect" if key else "text", key or part, _clamp(seconds)))
    if not steps:
        raise ValueError("the sequence has no steps")
    if len(steps) > MAX_STEPS:
        raise ValueError(f"a sequence has at most {MAX_STEPS} steps")
    return steps


def from_dicts(items: list[dict], default_seconds: int = DEFAULT_SECONDS) -> list[Step]:
    """Build steps from service data: ``{"effect": ...}`` or ``{"text": ...}`` plus ``seconds``."""
    steps = []
    for item in items:
        seconds = _clamp(int(item.get("seconds", default_seconds)))
        if "effect" in item:
            key = effect_key(str(item["effect"]))
            if key is None:
                raise ValueError(f"unknown effect: {item['effect']!r}")
            steps.append(Step("effect", key, seconds))
        elif str(item.get("text", "")).strip():
            steps.append(Step("text", str(item["text"]).strip(), seconds))
        else:
            raise ValueError("every step needs an effect or a text")
    if not steps:
        raise ValueError("the sequence has no steps")
    if len(steps) > MAX_STEPS:
        raise ValueError(f"a sequence has at most {MAX_STEPS} steps")
    return steps
