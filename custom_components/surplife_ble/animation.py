"""Shared pipeline that turns an image or GIF into an uploaded curtain animation.

Used by the ``surplife_ble.upload_animation`` service and the Screen media player. Every
upload writes the device flash, so avoid calling it at a high rate.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from homeassistant.components import media_source
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import get_url

from .core import curtain_c2, effects
from .core import text as text_render

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import SurplifeCoordinator

MAX_SOURCE_BYTES = 5 * 1024 * 1024
_DOWNLOAD_CHUNK = 64 * 1024
# media_type values accepted by the Screen media player besides image/*.
_PLAIN_MEDIA_TYPES = {"url", "image", "animation"}


class AnimationError(HomeAssistantError):
    """A clear, user-facing animation error."""


@dataclass(frozen=True, slots=True)
class AnimationSource:
    """The raw bytes of an image file and a short name for it."""

    data: bytes
    name: str


@dataclass(frozen=True, slots=True)
class DecodedAnimation:
    """Buffer-order frames ready to upload, and a PNG preview of the first frame."""

    frames: list[list[curtain_c2.RGB]]
    preview_png: bytes


def decode_animation(
    data: bytes,
    *,
    resample: str = "box",
    max_frames: int = curtain_c2.MAX_UPLOAD_FRAMES,
    controller_side: str = "left",
    flip: bool = False,
    cols: int = curtain_c2.GRID,
    rows: int = curtain_c2.GRID,
) -> DecodedAnimation:
    """Decode image bytes into curtain frames and a preview. Blocking: run in an executor.

    Raises :class:`AnimationError` for unreadable images and for more than ``max_frames``
    frames (the device holds at most 128).
    """
    limit = curtain_c2.max_upload_frames(cols, rows)
    if not 1 <= max_frames <= limit:
        raise AnimationError(f"max_frames must be between 1 and {limit}")
    try:
        loaded = curtain_c2.load_image_frames(
            io.BytesIO(data),
            resample=resample,
            max_frames=max_frames,
            controller_side=controller_side,
            flip=flip,
            count_all=False,
            cols=cols,
            rows=rows,
        )
        if loaded.total > max_frames:
            raise AnimationError(
                f"too many frames: the animation has more than {max_frames} frames "
                f"(the device holds at most {limit}). "
                "Use fewer frames or a lower frame rate."
            )
        preview = curtain_c2.render_preview_png(
            curtain_c2.frame_to_image(
                loaded.frames[0],
                controller_side=controller_side,
                flip=flip,
                cols=cols,
                rows=rows,
            ),
            cols=cols,
            rows=rows,
        )
    except AnimationError:
        raise
    except (ValueError, RuntimeError) as err:
        raise AnimationError(str(err)) from err
    return DecodedAnimation(loaded.frames, preview)


def _read_file(path: str) -> bytes:
    file = Path(path)
    try:
        size = file.stat().st_size
        if size > MAX_SOURCE_BYTES:
            raise AnimationError(
                f"{file.name} is too large ({size} bytes, the limit is {MAX_SOURCE_BYTES})"
            )
        return file.read_bytes()
    except FileNotFoundError as err:
        raise AnimationError(f"file not found: {path}") from err
    except OSError as err:
        raise AnimationError(f"cannot read {path}: {err}") from err


async def _async_read_path(
    hass: HomeAssistant, path: str, *, check_allowed: bool = True
) -> AnimationSource:
    if check_allowed and not hass.config.is_allowed_path(path):
        raise AnimationError(
            f"{path} is not in an allowed directory. Add it to allowlist_external_dirs "
            "or use a media source."
        )
    data = await hass.async_add_executor_job(_read_file, path)
    return AnimationSource(data, Path(path).name)


async def _async_read_url(hass: HomeAssistant, url: str) -> AnimationSource:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise AnimationError("url must start with http:// or https://")
    session = async_get_clientsession(hass)
    try:
        async with session.get(url) as response:
            if response.status != 200:
                raise AnimationError(f"download failed with HTTP status {response.status}")
            length = response.headers.get("Content-Length")
            if length and length.isdigit() and int(length) > MAX_SOURCE_BYTES:
                raise AnimationError(
                    f"the download is too large ({length} bytes, the limit is "
                    f"{MAX_SOURCE_BYTES})"
                )
            data = bytearray()
            async for chunk in response.content.iter_chunked(_DOWNLOAD_CHUNK):
                data.extend(chunk)
                if len(data) > MAX_SOURCE_BYTES:
                    raise AnimationError(
                        f"the download is too large (the limit is {MAX_SOURCE_BYTES} bytes)"
                    )
    except AnimationError:
        raise
    except Exception as err:  # network errors from aiohttp or the OS
        raise AnimationError(f"could not download {url}: {err}") from err
    name = Path(parsed.path).name or parsed.netloc
    return AnimationSource(bytes(data), name)


async def async_read_source(
    hass: HomeAssistant, *, path: str | None = None, url: str | None = None
) -> AnimationSource:
    """Read an image from an allowed local path or download it from a URL (5 MB cap)."""
    if bool(path) == bool(url):
        raise AnimationError("provide exactly one of path or url")
    if path:
        return await _async_read_path(hass, path)
    assert url is not None
    return await _async_read_url(hass, url)


def is_supported_media_type(media_type: str | None) -> bool:
    """True for image/* and the plain types url, image and animation."""
    if not media_type:
        return False
    media_type = media_type.lower()
    return media_type.startswith("image/") or media_type in _PLAIN_MEDIA_TYPES


async def async_resolve_media(
    hass: HomeAssistant, media_id: str, entity_id: str | None = None
) -> AnimationSource:
    """Resolve a media-source ID, http(s) URL or allowed local path to image bytes."""
    if media_source.is_media_source_id(media_id):
        try:
            play = await media_source.async_resolve_media(hass, media_id, entity_id)
        except Exception as err:  # media_source raises its own error types
            raise AnimationError(f"cannot resolve media {media_id}: {err}") from err
        name = Path(media_id.split("?")[0]).name or media_id
        local_path = getattr(play, "path", None)
        if local_path:
            source = await _async_read_path(hass, str(local_path), check_allowed=False)
            return AnimationSource(source.data, name)
        url = play.url
        if url.startswith("/"):
            url = get_url(hass, allow_external=False) + url
        source = await _async_read_url(hass, url)
        return AnimationSource(source.data, name)
    if media_id.startswith(("http://", "https://")):
        return await _async_read_url(hass, media_id)
    return await _async_read_path(hass, media_id)


async def async_upload(
    hass: HomeAssistant,
    coordinator: SurplifeCoordinator,
    source: AnimationSource,
    *,
    mode: int = curtain_c2.DEFAULT_PLAY_MODE,
    speed: int = 50,
    brightness: int = 100,
    controller_side: str | None = None,
    flip: bool | None = None,
    max_frames: int = curtain_c2.MAX_UPLOAD_FRAMES,
    resample: str = "box",
) -> int:
    """Decode ``source``, upload it to the curtain's flash and play it. Returns the frame count.

    ``controller_side`` and ``flip`` default to the orientation options of the config entry.
    A value given here overrides the option for this call.

    Raises :class:`AnimationError` with a clear message if the device is not a curtain,
    the animation has too many frames, or the device says it is too big.
    """
    if not coordinator.is_curtain:
        raise AnimationError(
            "this device is not an IOTBT curtain (product 0xC2), or it is not connected yet"
        )
    cols, rows = coordinator.curtain_grid
    # The service default is the 20 x 20 limit (128). A larger grid holds fewer frames.
    max_frames = min(max_frames, curtain_c2.max_upload_frames(cols, rows))
    decoded = await hass.async_add_executor_job(
        partial(
            decode_animation,
            source.data,
            resample=resample,
            max_frames=max_frames,
            cols=cols,
            rows=rows,
            controller_side=controller_side or coordinator.controller_side,
            flip=coordinator.flip if flip is None else flip,
        )
    )
    try:
        await coordinator.async_upload_animation(
            decoded.frames,
            mode=mode,
            speed=speed,
            brightness_percent=brightness,
            title=source.name,
            preview_png=decoded.preview_png,
        )
    except (curtain_c2.CurtainUploadError, RuntimeError, ValueError, OSError, TimeoutError) as err:
        raise AnimationError(str(err)) from err
    return len(decoded.frames)


async def async_show_text(
    hass: HomeAssistant,
    coordinator: SurplifeCoordinator,
    text: str,
    *,
    color: tuple[int, int, int] = (255, 200, 0),
    bold: bool = True,
    scroll: bool | None = None,
    size: str | None = None,
    background: tuple[int, int, int] = (0, 0, 0),
    speed: int = 75,
    brightness: int = 100,
    preview_only: bool = False,
    rainbow: bool = False,
) -> int:
    """Render ``text``, show it in the Screen preview and upload it. Returns the frame count.

    Short text is one centered frame. Longer text scrolls from right to left. The preview
    is the whole text as one wide picture. With ``preview_only`` nothing is sent to the
    device, so the flash is not written.
    """
    if not coordinator.is_curtain:
        raise AnimationError(
            "this device is not an IOTBT curtain or net, or it is not connected yet"
        )
    cols, rows = coordinator.curtain_grid

    def _render() -> tuple[list[list[curtain_c2.RGB]], bytes]:
        rendered = text_render.render_text(
            text,
            cols=cols,
            rows=rows,
            color=color,
            bold=bold,
            scroll=scroll,
            size=size,
            background=background,
            rainbow=rainbow,
            max_frames=curtain_c2.max_upload_frames(cols, rows),
        )
        frames = [
            curtain_c2.image_to_frame(
                frame,
                controller_side=coordinator.controller_side,
                flip=coordinator.flip,
                cols=cols,
                rows=rows,
            )
            for frame in rendered.frames
        ]
        return frames, text_render.render_strip_png(rendered.strip)

    try:
        frames, preview = await hass.async_add_executor_job(_render)
    except (ValueError, RuntimeError) as err:
        raise AnimationError(str(err)) from err
    if preview_only:
        coordinator.async_set_preview(preview, text)
        return len(frames)
    try:
        await coordinator.async_upload_animation(
            frames,
            mode=curtain_c2.DEFAULT_PLAY_MODE,
            speed=speed,
            brightness_percent=brightness,
            title=text,
            preview_png=preview,
        )
    except (curtain_c2.CurtainUploadError, RuntimeError, ValueError, OSError, TimeoutError) as err:
        raise AnimationError(str(err)) from err
    return len(frames)


async def async_show_effect(
    hass: HomeAssistant,
    coordinator: SurplifeCoordinator,
    name: str,
    *,
    speed: int | None = None,
    brightness: int = 100,
) -> int:
    """Draw built-in effect ``name`` for the grid of the device, upload and play it.

    ``speed`` defaults to the speed that suits the effect. Returns the frame count.
    """
    if not coordinator.is_curtain:
        raise AnimationError(
            "this device is not an IOTBT curtain or net, or it is not connected yet"
        )
    cols, rows = coordinator.curtain_grid

    def _render() -> tuple[list[list[curtain_c2.RGB]], bytes]:
        images = effects.build(name, cols, rows)
        limit = curtain_c2.max_upload_frames(cols, rows)
        if len(images) > limit:
            raise ValueError(f"effect {name} has {len(images)} frames, the device holds {limit}")
        frames = [
            curtain_c2.image_to_frame(
                image,
                controller_side=coordinator.controller_side,
                flip=coordinator.flip,
                cols=cols,
                rows=rows,
            )
            for image in images
        ]
        preview = curtain_c2.render_preview_png(images[len(images) // 3], cols=cols, rows=rows)
        return frames, preview

    try:
        frames, preview = await hass.async_add_executor_job(_render)
        await coordinator.async_upload_animation(
            frames,
            mode=curtain_c2.DEFAULT_PLAY_MODE,
            speed=speed if speed is not None else effects.EFFECTS[name].speed,
            brightness_percent=brightness,
            title=name,
            preview_png=preview,
        )
    except (curtain_c2.CurtainUploadError, RuntimeError, ValueError, OSError, TimeoutError) as err:
        raise AnimationError(str(err)) from err
    return len(frames)
