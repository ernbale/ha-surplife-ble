"""Entity services for the IOTBT curtain: upload, play, show_text and show_effect."""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol
from homeassistant.helpers import config_validation as cv

from .core import curtain_c2, effects

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import EntityPlatform

SERVICE_UPLOAD_ANIMATION = "upload_animation"
SERVICE_PLAY_ANIMATION = "play_animation"
SERVICE_SHOW_TEXT = "show_text"
SERVICE_SHOW_EFFECT = "show_effect"

ATTR_PATH = "path"
ATTR_URL = "url"
ATTR_SPEED = "speed"
ATTR_BRIGHTNESS = "brightness"
ATTR_MODE = "mode"
ATTR_CONTROLLER_SIDE = "controller_side"
ATTR_FLIP = "flip"
ATTR_MAX_FRAMES = "max_frames"
ATTR_RESAMPLE = "resample"
ATTR_TEXT = "text"
ATTR_COLOR = "color"
ATTR_BOLD = "bold"
ATTR_SCROLL = "scroll"
ATTR_SIZE = "size"
ATTR_BACKGROUND = "background"
ATTR_EFFECT = "effect"
ATTR_PREVIEW_ONLY = "preview_only"

_PERCENT = vol.All(vol.Coerce(int), vol.Range(min=1, max=100))
_MODE = vol.All(vol.Coerce(int), vol.Range(min=0, max=255))

PLAY_SCHEMA = {
    vol.Optional(ATTR_MODE, default=curtain_c2.DEFAULT_PLAY_MODE): _MODE,
    vol.Optional(ATTR_SPEED, default=50): _PERCENT,
    vol.Optional(ATTR_BRIGHTNESS, default=100): _PERCENT,
}

UPLOAD_SCHEMA = {
    vol.Optional(ATTR_PATH): cv.string,
    vol.Optional(ATTR_URL): cv.string,
    **PLAY_SCHEMA,
    # No defaults: when a field is missing, the options of the config entry apply.
    vol.Optional(ATTR_CONTROLLER_SIDE): vol.In(["left", "right"]),
    vol.Optional(ATTR_FLIP): cv.boolean,
    vol.Optional(ATTR_MAX_FRAMES, default=curtain_c2.MAX_UPLOAD_FRAMES): vol.All(
        vol.Coerce(int), vol.Range(min=1, max=curtain_c2.MAX_UPLOAD_FRAMES)
    ),
    vol.Optional(ATTR_RESAMPLE, default="box"): vol.In(["nearest", "box", "lanczos"]),
}


_BYTE = vol.All(vol.Coerce(int), vol.Range(min=0, max=255))
_COLOR = vol.All(vol.ExactSequence((_BYTE, _BYTE, _BYTE)), vol.Coerce(tuple))

TEXT_SCHEMA = {
    vol.Required(ATTR_TEXT): vol.All(cv.string, vol.Length(min=1, max=200)),
    vol.Optional(ATTR_COLOR, default=[255, 200, 0]): _COLOR,
    vol.Optional(ATTR_BACKGROUND, default=[0, 0, 0]): _COLOR,
    vol.Optional(ATTR_BOLD, default=True): cv.boolean,
    # No default: short text is static and long text scrolls.
    vol.Optional(ATTR_SCROLL): cv.boolean,
    # No default: medium on screens with at least 14 rows, small otherwise.
    vol.Optional(ATTR_SIZE): vol.In(["small", "medium", "large"]),
    vol.Optional(ATTR_SPEED, default=75): _PERCENT,
    vol.Optional(ATTR_BRIGHTNESS, default=100): _PERCENT,
    vol.Optional(ATTR_PREVIEW_ONLY, default=False): cv.boolean,
}


EFFECT_SCHEMA = {
    vol.Required(ATTR_EFFECT): vol.In(list(effects.EFFECTS)),
    # No default: every effect has a speed that suits it.
    vol.Optional(ATTR_SPEED): _PERCENT,
    vol.Optional(ATTR_BRIGHTNESS, default=100): _PERCENT,
}


def async_register_entity_services(platform: EntityPlatform) -> None:
    """Register the curtain services on the light platform."""
    platform.async_register_entity_service(
        SERVICE_UPLOAD_ANIMATION, UPLOAD_SCHEMA, "async_upload_animation"
    )
    platform.async_register_entity_service(
        SERVICE_PLAY_ANIMATION, PLAY_SCHEMA, "async_play_animation"
    )
    platform.async_register_entity_service(SERVICE_SHOW_TEXT, TEXT_SCHEMA, "async_show_text")
    platform.async_register_entity_service(
        SERVICE_SHOW_EFFECT, EFFECT_SCHEMA, "async_show_effect"
    )
