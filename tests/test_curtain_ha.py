"""Home Assistant behavior for the IOTBT curtain, with fake HA modules and a fake device."""

from __future__ import annotations

import asyncio
import io
import struct
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import voluptuous as vol
from curtain_fakes import FF01, FakeCurtain
from fake_homeassistant import FakeEntry, FakeHass, HomeAssistantError, install, make_coordinator
from test_client import FakeIotbtBleakClient

from custom_components.surplife_ble.core import curtain_c2, effects
from custom_components.surplife_ble.core.calibration import ColorCalibration

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def ha(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    return install(monkeypatch)


async def make_curtain(
    ha: SimpleNamespace,
    hass: FakeHass | None = None,
    fake: FakeCurtain | None = None,
    options: dict[str, Any] | None = None,
) -> tuple[Any, FakeCurtain]:
    fake = fake or FakeCurtain()
    coordinator = make_coordinator(ha, fake, hass, options)
    await coordinator.client.connect()
    await coordinator.client.probe(allow_writes=True, response_timeout=0.05)  # fast resolve
    coordinator.data = await coordinator._async_update_data()
    assert coordinator.is_curtain
    fake.writes.clear()
    fake.payloads.clear()
    return coordinator, fake


async def make_dx23012(
    ha: SimpleNamespace, options: dict[str, Any] | None = None
) -> tuple[Any, FakeIotbtBleakClient]:
    fake = FakeIotbtBleakClient()
    coordinator = make_coordinator(ha, fake, None, options)
    await coordinator.client.connect()
    await coordinator.client.probe(allow_writes=True, response_timeout=0.05)  # fast resolve
    coordinator.data = await coordinator._async_update_data()
    assert not coordinator.is_curtain
    fake.writes.clear()
    return coordinator, fake


def gif(path: Path, colors: list[tuple[int, int, int]], size: int = 40) -> Path:
    from PIL import Image

    images = [Image.new("RGB", (size, size), color) for color in colors]
    images[0].save(path, save_all=True, append_images=images[1:], duration=100, loop=0)
    return path


def png_size(data: bytes) -> tuple[int, int]:
    assert data.startswith(PNG_SIGNATURE)
    return struct.unpack(">II", data[16:24])  # type: ignore[return-value]


def png_pixel(data: bytes, x: int, y: int) -> tuple[int, ...]:
    from PIL import Image

    return Image.open(io.BytesIO(data)).convert("RGB").getpixel((x, y))  # type: ignore[return-value]


def frame_bytes(fake: FakeCurtain, index: int = -1) -> bytes:
    uuid, data = fake.writes[index]
    assert uuid == FF01
    return data


# ---------------------------------------------------------------------------
# Light entity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_curtain_light_is_rgb_only_with_effects(ha: SimpleNamespace) -> None:
    coordinator, _fake = await make_curtain(ha)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    assert light._attr_supported_color_modes == {ha.ColorMode.RGB}
    assert light._attr_color_mode == ha.ColorMode.RGB
    assert light._attr_supported_features == ha.LightEntityFeature.EFFECT
    assert light._attr_effect_list[0] == "Animation (uploaded)"
    assert light._attr_effect_list[1] == "Effect 1"
    assert light._attr_effect_list[-1] == f"Effect {curtain_c2.CURTAIN_EFFECT_COUNT}"
    assert len(light._attr_effect_list) == curtain_c2.CURTAIN_EFFECT_COUNT + 1
    assert light._attr_effect is None
    assert light._attr_is_on is True
    assert light._attr_device_info["model"] == "Curtain lights (IOTBT, product 0xC2)"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fields", "effect"),
    [
        (dict(mode=0x67, effect=10, speed=0x50), "Effect 10"),
        (dict(mode=0x67, effect=1, speed=0x50), "Effect 1"),
        (dict(mode=0x67, effect=250, speed=0x50), None),  # not in the tentative list
        (dict(mode=0x74, effect=1, speed=0x32), "Animation (uploaded)"),
        (dict(mode=0x66, effect=0x6E, speed=0x64), None),
        (dict(mode=0x62, effect=1, speed=0x64), None),
    ],
)
async def test_curtain_light_reports_the_active_effect(
    ha: SimpleNamespace, fields: dict[str, int], effect: str | None
) -> None:
    fake = FakeCurtain()
    for name, value in fields.items():
        setattr(fake, name, value)
    coordinator, _ = await make_curtain(ha, fake=fake)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    assert light._attr_effect == effect


@pytest.mark.asyncio
async def test_curtain_light_turn_on_paths_send_exact_bytes(ha: SimpleNamespace) -> None:
    coordinator, fake = await make_curtain(ha)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())

    await light.async_turn_on(rgb_color=(0, 0, 255), brightness=128)  # 128/255 = 50 %
    assert frame_bytes(fake)[2:] == bytes.fromhex("8000000d0e0b3ba178643200000000000000ea")

    await light.async_turn_on(effect="Effect 10", brightness=255)
    assert frame_bytes(fake)[2:] == bytes.fromhex("80000006070ae002000a3264")

    await light.async_turn_on(effect="Animation (uploaded)")
    assert frame_bytes(fake)[2:] == bytes.fromhex("80000006070ae20901326400")

    await light.async_turn_on()
    assert frame_bytes(fake)[2:] == bytes.fromhex("8000000d0e0b3b230000000000000032000090")
    await light.async_turn_off()
    assert frame_bytes(fake)[2:] == bytes.fromhex("8000000d0e0b3b240000000000000032000091")
    assert {uuid for uuid, _ in fake.writes} == {FF01}


@pytest.mark.asyncio
async def test_curtain_light_brightness_only_resends_the_color(ha: SimpleNamespace) -> None:
    coordinator, fake = await make_curtain(ha)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    await light.async_turn_on(rgb_color=(0, 0, 255), brightness=255)
    await light.async_turn_on(brightness=26)  # about 10 %
    assert fake.payloads[-1] == curtain_c2.color_rgb(0, 0, 255, 10).payload


@pytest.mark.asyncio
async def test_curtain_light_unknown_effect_is_an_error(ha: SimpleNamespace) -> None:
    coordinator, fake = await make_curtain(ha)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    with pytest.raises(HomeAssistantError, match="unknown curtain effect"):
        await light.async_turn_on(effect="Disco")
    assert fake.writes == []


@pytest.mark.asyncio
async def test_curtain_light_shows_assumed_color_and_brightness(ha: SimpleNamespace) -> None:
    coordinator, fake = await make_curtain(ha)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    await light.async_turn_on(rgb_color=(0, 0, 255), brightness=128)
    state = await coordinator._async_update_data()
    coordinator.data = state
    light._handle_coordinator_update()
    assert state.mode == 0x66
    assert state.rgb == (0, 0, 255)
    assert state.brightness == 128
    assert state.assumed
    assert light._attr_rgb_color == (0, 0, 255)
    assert light._attr_assumed_state is True
    assert light.writes == 1
    # An effect carries no color: the polled state drops it.
    await light.async_turn_on(effect="Effect 10")
    state = await coordinator._async_update_data()
    assert (state.mode, state.effect, state.rgb) == (0x67, 10, None)
    assert state.speed == 50


@pytest.mark.asyncio
async def test_dx23012_light_is_unchanged(ha: SimpleNamespace) -> None:
    coordinator, fake = await make_dx23012(ha)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    assert light._attr_supported_color_modes == {ha.ColorMode.RGB, ha.ColorMode.WHITE}
    assert getattr(light, "_attr_effect_list", None) is None
    assert getattr(light, "_attr_supported_features", None) is None
    assert light._attr_device_info["model"].startswith("DX23012")
    await light.async_turn_on(rgb_color=(255, 0, 0), brightness=255)
    sent = next(data for _uuid, data, _ in reversed(fake.writes) if data[8:10] == b"\xe1\x03")
    assert sent[7] == 0x0B
    with pytest.raises(HomeAssistantError, match="not an IOTBT curtain"):
        await light.async_play_animation(mode=1, speed=50, brightness=100)


# ---------------------------------------------------------------------------
# Platform setup and services registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_light_setup_registers_the_services(ha: SimpleNamespace) -> None:
    coordinator, _ = await make_curtain(ha)
    entry = FakeEntry()
    entry.runtime_data = SimpleNamespace(coordinator=coordinator)
    added: list[Any] = []
    await ha.light.async_setup_entry(FakeHass(), entry, added.extend)
    assert len(added) == 1
    assert ha.platform.services == {
        "upload_animation": (ha.services.UPLOAD_SCHEMA, "async_upload_animation"),
        "play_animation": (ha.services.PLAY_SCHEMA, "async_play_animation"),
        "show_text": (ha.services.TEXT_SCHEMA, "async_show_text"),
        "show_effect": (ha.services.EFFECT_SCHEMA, "async_show_effect"),
        "play_sequence": (ha.services.SEQUENCE_SCHEMA, "async_play_sequence"),
        "stop_sequence": ({}, "async_stop_sequence"),
    }


@pytest.mark.asyncio
async def test_service_schemas_validate_ranges_and_fill_defaults(ha: SimpleNamespace) -> None:
    schema = vol.Schema(ha.services.UPLOAD_SCHEMA)
    assert schema({"path": "/config/a.gif"}) == {
        "path": "/config/a.gif",
        "mode": 1,
        "speed": 50,
        "brightness": 100,
        "max_frames": 128,
        "resample": "box",
    }
    # No default for the orientation: a missing field means "use the device option".
    assert "controller_side" not in schema({"path": "/config/a.gif"})
    assert "flip" not in schema({"path": "/config/a.gif"})
    assert (
        schema({"path": "/a.gif", "controller_side": "right", "flip": "true"})["controller_side"]
        == "right"
    )
    assert schema({"url": "https://x/a.gif", "speed": "75", "flip": "true"})["speed"] == 75
    for bad in (
        {"speed": 0},
        {"speed": 101},
        {"brightness": 0},
        {"mode": 256},
        {"max_frames": 129},
        {"max_frames": 0},
        {"controller_side": "front"},
        {"resample": "cubic"},
    ):
        with pytest.raises(vol.Invalid):
            schema({"path": "/config/a.gif", **bad})
    play = vol.Schema(ha.services.PLAY_SCHEMA)
    assert play({}) == {"mode": 1, "speed": 50, "brightness": 100}
    with pytest.raises(vol.Invalid):
        play({"speed": 101})


@pytest.mark.asyncio
@pytest.mark.parametrize("platform_name", ["media_player", "image", "number"])
async def test_screen_platforms_add_entities_only_for_the_curtain(
    ha: SimpleNamespace, platform_name: str
) -> None:
    module = getattr(ha, platform_name)
    # A DX23012 never gets Screen entities, even after its state updates.
    dx, _ = await make_dx23012(ha)
    entry = FakeEntry()
    entry.runtime_data = SimpleNamespace(coordinator=dx)
    added: list[Any] = []
    await module.async_setup_entry(FakeHass(), entry, added.extend)
    dx.async_update_listeners()
    assert added == []
    # A curtain gets exactly one entity, as soon as it is resolved.
    coordinator = ha.coordinator.SurplifeCoordinator(FakeHass(), FakeEntry())
    entry = FakeEntry()
    entry.runtime_data = SimpleNamespace(coordinator=coordinator)
    added = []
    await module.async_setup_entry(FakeHass(), entry, added.extend)
    assert added == []  # not resolved yet
    from curtain_fakes import _Device

    from custom_components.surplife_ble.core.client import LightClient

    fake = FakeCurtain()
    coordinator._ble_device = _Device()
    coordinator.client = LightClient(
        coordinator._ble_device,  # type: ignore[arg-type]
        client_factory=lambda _device: fake,
    )
    await coordinator.client.connect()
    await coordinator.client.probe(allow_writes=True, response_timeout=0.05)
    coordinator.data = await coordinator._async_update_data()
    coordinator.async_update_listeners()
    coordinator.async_update_listeners()
    assert len(added) == 1


@pytest.mark.asyncio
async def test_all_curtain_entities_share_one_device(ha: SimpleNamespace) -> None:
    coordinator, _ = await make_curtain(ha)
    entry = FakeEntry()
    light = ha.light.SurplifeLight(coordinator, entry)
    screen = ha.media_player.SurplifeScreen(coordinator)
    preview = ha.image.SurplifeScreenPreview(FakeHass(), coordinator)
    speed = ha.number.SurplifeAnimationSpeed(coordinator)
    identifiers = {
        frozenset(entity._attr_device_info["identifiers"])
        for entity in (light, screen, preview, speed)
    }
    assert identifiers == {frozenset({("surplife_ble", "DEVICE")})}
    unique_ids = {e._attr_unique_id for e in (light, screen, preview, speed)}
    assert len(unique_ids) == 4


# ---------------------------------------------------------------------------
# upload_animation / play_animation services
# ---------------------------------------------------------------------------


async def call_upload(light: Any, ha: SimpleNamespace, **data: Any) -> None:
    await light.async_upload_animation(**vol.Schema(ha.services.UPLOAD_SCHEMA)(data))


@pytest.mark.asyncio
async def test_upload_animation_from_a_path_uploads_and_plays(
    ha: SimpleNamespace, tmp_path: Path
) -> None:
    hass = FakeHass(allowed=(str(tmp_path),))
    coordinator, fake = await make_curtain(ha, hass)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    path = gif(tmp_path / "anim.gif", [(255, 0, 0), (0, 0, 255)])
    await call_upload(light, ha, path=str(path))
    assert [payload[:2].hex() for payload in fake.payloads] == [
        "ea01", "ea02", "ea03", "ea03", "ea04", "e209",
    ]  # fmt: skip
    red = "2f01ff0200ffffff0950ff01ff01ff"
    blue = "2fa1ff0200ffffff0950ffa1ffa1ff"
    assert fake.payloads[1].hex() == "ea0200000000000f0000000f000f"
    assert fake.payloads[2].hex() == "ea030001" + red
    assert fake.payloads[3].hex() == "ea030002" + blue
    assert fake.payloads[0][3:7] == (1600).to_bytes(4, "big")
    assert fake.payloads[-1] == bytes.fromhex("e20901326400")
    assert {uuid for uuid, _ in fake.writes} == {FF01}
    assert coordinator.animation_title == "anim.gif"
    assert coordinator.preview_png is not None
    assert coordinator.preview_updated is not None


@pytest.mark.asyncio
async def test_upload_animation_passes_speed_brightness_and_mode(
    ha: SimpleNamespace, tmp_path: Path
) -> None:
    hass = FakeHass(allowed=(str(tmp_path),))
    coordinator, fake = await make_curtain(ha, hass)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    path = gif(tmp_path / "one.gif", [(0, 255, 0)])
    await call_upload(light, ha, path=str(path), speed=75, brightness=20, mode=0)
    assert fake.payloads[-1] == bytes.fromhex("e209004b1400")
    assert coordinator.animation_speed == 75


@pytest.mark.asyncio
async def test_upload_animation_controller_side_and_preview_orientation(
    ha: SimpleNamespace, tmp_path: Path
) -> None:
    from PIL import Image

    hass = FakeHass(allowed=(str(tmp_path),))
    coordinator, fake = await make_curtain(ha, hass)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    image = Image.new("RGB", (20, 20), (0, 0, 0))
    image.putpixel((0, 0), (255, 0, 0))  # top-left of the picture
    path = tmp_path / "marker.png"
    image.save(path)
    await call_upload(light, ha, path=str(path), resample="nearest", controller_side="right")
    pixels = [(0, 0, 0)] * 400
    pixels[380] = (255, 0, 0)  # controller on the right: column 0 is the far string
    expected = curtain_c2.build_upload([pixels])
    assert fake.payloads[2] == expected[2].payload
    # The preview shows the picture as it is seen, whatever the hanging side.
    assert png_pixel(coordinator.preview_png, 0, 0) == (255, 0, 0)
    assert png_pixel(coordinator.preview_png, 199, 199) == (0, 0, 0)


@pytest.mark.asyncio
async def test_upload_animation_rejects_paths_outside_the_allowlist(
    ha: SimpleNamespace, tmp_path: Path
) -> None:
    coordinator, fake = await make_curtain(ha, FakeHass(allowed=("/config/www",)))
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    path = gif(tmp_path / "a.gif", [(1, 2, 3)])
    with pytest.raises(HomeAssistantError, match="allowlist_external_dirs"):
        await call_upload(light, ha, path=str(path))
    assert fake.writes == []


@pytest.mark.asyncio
async def test_upload_animation_needs_exactly_one_source(ha: SimpleNamespace) -> None:
    coordinator, fake = await make_curtain(ha)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    with pytest.raises(HomeAssistantError, match="exactly one of path or url"):
        await call_upload(light, ha)
    with pytest.raises(HomeAssistantError, match="exactly one of path or url"):
        await call_upload(light, ha, path="/a.gif", url="https://x/a.gif")
    assert fake.writes == []


@pytest.mark.asyncio
async def test_upload_animation_from_a_url(ha: SimpleNamespace, tmp_path: Path) -> None:
    coordinator, fake = await make_curtain(ha)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    data = gif(tmp_path / "a.gif", [(255, 0, 0)]).read_bytes()
    half = len(data) // 2
    ha.session.responses["https://example.com/fire.gif"] = (
        200,
        {"Content-Length": str(len(data))},
        [data[:half], data[half:]],
    )
    await call_upload(light, ha, url="https://example.com/fire.gif")
    assert ha.session.requested == ["https://example.com/fire.gif"]
    assert fake.payloads[2].hex() == "ea030001" + "2f01ff0200ffffff0950ff01ff01ff"
    assert coordinator.animation_title == "fire.gif"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "response", "message"),
    [
        ("ftp://example.com/a.gif", None, "http:// or https://"),
        ("https://example.com/missing.gif", (404, {}, []), "HTTP status 404"),
        (
            "https://example.com/big.gif",
            (200, {"Content-Length": str(6 * 1024 * 1024)}, [b"x"]),
            "too large",
        ),
        (
            "https://example.com/stream.gif",
            (200, {}, [b"x" * (1024 * 1024)] * 6),
            "too large",
        ),
    ],
)
async def test_upload_animation_url_validation(
    ha: SimpleNamespace, url: str, response: Any, message: str
) -> None:
    coordinator, fake = await make_curtain(ha)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    if response is not None:
        ha.session.responses[url] = response
    with pytest.raises(HomeAssistantError, match=message):
        await call_upload(light, ha, url=url)
    assert fake.writes == []


@pytest.mark.asyncio
async def test_upload_animation_too_many_frames(ha: SimpleNamespace, tmp_path: Path) -> None:
    hass = FakeHass(allowed=(str(tmp_path),))
    coordinator, fake = await make_curtain(ha, hass)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    path = gif(tmp_path / "three.gif", [(255, 0, 0), (0, 255, 0), (0, 0, 255)])
    with pytest.raises(HomeAssistantError, match="too many frames"):
        await call_upload(light, ha, path=str(path), max_frames=2)
    assert fake.writes == []
    await call_upload(light, ha, path=str(path), max_frames=3)
    assert sum(1 for payload in fake.payloads if payload[:2] == b"\xea\x03") == 3


@pytest.mark.asyncio
async def test_upload_animation_device_says_too_big(ha: SimpleNamespace, tmp_path: Path) -> None:
    hass = FakeHass(allowed=(str(tmp_path),))
    fake = FakeCurtain()
    fake.statuses = {1: 2}
    coordinator, _ = await make_curtain(ha, hass, fake)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    path = gif(tmp_path / "a.gif", [(255, 0, 0)])
    with pytest.raises(HomeAssistantError, match="too big for device memory"):
        await call_upload(light, ha, path=str(path))
    assert [payload[:2].hex() for payload in fake.payloads] == ["ea01"]
    assert coordinator.animation_title is None


@pytest.mark.asyncio
async def test_upload_animation_missing_ack_is_a_clear_error(
    ha: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hass = FakeHass(allowed=(str(tmp_path),))
    fake = FakeCurtain()
    fake.silent_steps = {2}
    coordinator, _ = await make_curtain(ha, hass, fake)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    path = gif(tmp_path / "a.gif", [(255, 0, 0)])
    original = coordinator.client.upload_curtain_animation

    async def quick(*args: Any, **kwargs: Any) -> None:
        await original(*args, ack_timeout=0.1, **kwargs)

    monkeypatch.setattr(coordinator.client, "upload_curtain_animation", quick)
    with pytest.raises(HomeAssistantError, match="no reply to upload step 'address'"):
        await call_upload(light, ha, path=str(path))


@pytest.mark.asyncio
async def test_upload_animation_missing_content_ack_names_the_frame(
    ha: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hass = FakeHass(allowed=(str(tmp_path),))
    fake = FakeCurtain()
    fake.silent_steps = {3}
    coordinator, _ = await make_curtain(ha, hass, fake)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    path = gif(tmp_path / "two.gif", [(255, 0, 0), (0, 0, 255)])
    original = coordinator.client.upload_curtain_animation

    async def quick(*args: Any, **kwargs: Any) -> None:
        await original(*args, ack_timeout=0.1, **kwargs)

    monkeypatch.setattr(coordinator.client, "upload_curtain_animation", quick)
    with pytest.raises(HomeAssistantError, match="no reply to upload step 'content 1'"):
        await call_upload(light, ha, path=str(path))
    # The sender stops at the unacknowledged frame instead of sending the rest.
    assert [payload[:2].hex() for payload in fake.payloads] == ["ea01", "ea02", "ea03"]
    assert coordinator.animation_title is None


@pytest.mark.asyncio
async def test_upload_animation_rejected_content_frame_is_reported(
    ha: SimpleNamespace, tmp_path: Path
) -> None:
    hass = FakeHass(allowed=(str(tmp_path),))
    fake = FakeCurtain()
    fake.statuses = {3: 2}
    coordinator, _ = await make_curtain(ha, hass, fake)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    path = gif(tmp_path / "two.gif", [(255, 0, 0), (0, 0, 255)])
    with pytest.raises(HomeAssistantError, match=r"rejected upload step EA 03 \(frame 1\)"):
        await call_upload(light, ha, path=str(path))
    assert [payload[:2].hex() for payload in fake.payloads] == ["ea01", "ea02", "ea03"]


@pytest.mark.asyncio
async def test_upload_animation_rejects_unreadable_files(
    ha: SimpleNamespace, tmp_path: Path
) -> None:
    hass = FakeHass(allowed=(str(tmp_path),))
    coordinator, fake = await make_curtain(ha, hass)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    bad = tmp_path / "bad.gif"
    bad.write_bytes(b"not an image")
    with pytest.raises(HomeAssistantError, match="not a readable image"):
        await call_upload(light, ha, path=str(bad))
    with pytest.raises(HomeAssistantError, match="file not found"):
        await call_upload(light, ha, path=str(tmp_path / "nope.gif"))
    huge = tmp_path / "huge.gif"
    huge.write_bytes(b"0" * (5 * 1024 * 1024 + 1))
    with pytest.raises(HomeAssistantError, match="too large"):
        await call_upload(light, ha, path=str(huge))
    assert fake.writes == []


@pytest.mark.asyncio
async def test_upload_animation_on_a_non_curtain_device(
    ha: SimpleNamespace, tmp_path: Path
) -> None:
    hass = FakeHass(allowed=(str(tmp_path),))
    coordinator, fake = await make_dx23012(ha)
    coordinator.hass = hass
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    light.hass = hass
    path = gif(tmp_path / "a.gif", [(255, 0, 0)])
    with pytest.raises(HomeAssistantError, match="not an IOTBT curtain"):
        await call_upload(light, ha, path=str(path))
    assert fake.writes == []


@pytest.mark.asyncio
async def test_play_animation_service(ha: SimpleNamespace) -> None:
    coordinator, fake = await make_curtain(ha)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    data = vol.Schema(ha.services.PLAY_SCHEMA)({"mode": 2, "speed": 10, "brightness": 40})
    await light.async_play_animation(**data)
    assert fake.payloads[-1] == bytes.fromhex("e209020a2800")
    assert frame_bytes(fake)[2:] == bytes.fromhex("80000006070ae209020a2800")


# ---------------------------------------------------------------------------
# Screen media player
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_screen_features(ha: SimpleNamespace) -> None:
    coordinator, _ = await make_curtain(ha)
    screen = ha.media_player.SurplifeScreen(coordinator)
    flags = ha.MediaPlayerEntityFeature
    assert screen._attr_supported_features == (
        flags.PLAY_MEDIA | flags.PLAY | flags.PAUSE | flags.STOP
        | flags.TURN_ON | flags.TURN_OFF | flags.BROWSE_MEDIA
    )  # fmt: skip
    assert screen._attr_name == "Screen"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fields", "state"),
    [
        (dict(power=False, mode=0x62, effect=1, speed=0x64), "off"),
        (dict(power=True, mode=0x74, effect=1, speed=0x32), "playing"),
        (dict(power=True, mode=0x74, effect=0, speed=0x32), "playing"),
        (dict(power=True, mode=0x74, effect=2, speed=0x32), "paused"),
        (dict(power=True, mode=0x74, effect=7, speed=0x32), "paused"),
        (dict(power=True, mode=0x67, effect=10, speed=0x50), "on"),
        (dict(power=True, mode=0x66, effect=0x6E, speed=0x64), "on"),
        (dict(power=True, mode=0x62, effect=1, speed=0x64), "on"),
    ],
)
async def test_screen_state_mapping(
    ha: SimpleNamespace, fields: dict[str, Any], state: str
) -> None:
    fake = FakeCurtain()
    for name, value in fields.items():
        setattr(fake, name, value)
    coordinator, _ = await make_curtain(ha, fake=fake)
    coordinator.animation_title = "fire.gif"
    screen = ha.media_player.SurplifeScreen(coordinator)
    assert screen._attr_state == state
    assert screen._attr_media_title == "fire.gif"
    screen._handle_coordinator_update()
    assert screen.writes == 1


@pytest.mark.asyncio
async def test_screen_transport_controls_send_exact_bytes(ha: SimpleNamespace) -> None:
    fake = FakeCurtain()
    fake.mode, fake.effect, fake.speed = 0x74, 0x01, 0x32
    coordinator, _ = await make_curtain(ha, fake=fake)
    screen = ha.media_player.SurplifeScreen(coordinator)

    await screen.async_media_pause()  # hold frame 1
    assert fake.payloads[-1] == bytes.fromhex("e20902326400")
    await screen.async_media_play()  # loop (mode 1)
    assert fake.payloads[-1] == bytes.fromhex("e20901326400")
    await screen.async_media_stop()
    assert fake.payloads[-1] == curtain_c2.power(False).payload
    await screen.async_turn_on()
    assert fake.payloads[-1] == curtain_c2.power(True).payload
    await screen.async_turn_off()
    assert fake.payloads[-1] == curtain_c2.power(False).payload
    assert {uuid for uuid, _ in fake.writes} == {FF01}


@pytest.mark.asyncio
async def test_screen_play_media_from_a_url(ha: SimpleNamespace, tmp_path: Path) -> None:
    coordinator, fake = await make_curtain(ha)
    screen = ha.media_player.SurplifeScreen(coordinator)
    data = gif(tmp_path / "a.gif", [(0, 0, 255)]).read_bytes()
    ha.session.responses["https://example.com/blue.gif"] = (200, {}, [data])
    await screen.async_play_media("image/gif", "https://example.com/blue.gif")
    assert fake.payloads[2].hex() == "ea030001" + "2fa1ff0200ffffff0950ffa1ffa1ff"
    assert fake.payloads[-1] == bytes.fromhex("e20901326400")  # mode 1
    assert coordinator.animation_title == "blue.gif"


@pytest.mark.asyncio
async def test_screen_play_media_from_a_media_source(ha: SimpleNamespace, tmp_path: Path) -> None:
    coordinator, fake = await make_curtain(ha, FakeHass())
    screen = ha.media_player.SurplifeScreen(coordinator)
    # A resolved media source with a local file path is read directly (HA vetted it).
    local = gif(tmp_path / "local.gif", [(255, 0, 0)])
    media_id = "media-source://media_source/local/local.gif"
    ha.media.resolved[media_id] = ha.PlayMedia("/media/local/local.gif", "image/gif", path=local)
    await screen.async_play_media("image/gif", media_id)
    assert ha.media.resolve_calls == [(media_id, "light.test")]
    assert fake.payloads[2].hex() == "ea030001" + "2f01ff0200ffffff0950ff01ff01ff"
    assert coordinator.animation_title == "local.gif"
    # Without a path, the URL is fetched from the instance.
    data = local.read_bytes()
    other = "media-source://media_source/local/remote.gif"
    ha.media.resolved[other] = ha.PlayMedia("/media/local/remote.gif", "image/gif")
    ha.session.responses["http://ha.local:8123/media/local/remote.gif"] = (200, {}, [data])
    fake.payloads.clear()
    await screen.async_play_media("image/gif", other)
    assert ha.session.requested[-1] == "http://ha.local:8123/media/local/remote.gif"
    assert coordinator.animation_title == "remote.gif"


@pytest.mark.asyncio
async def test_screen_play_media_from_an_allowed_local_path(
    ha: SimpleNamespace, tmp_path: Path
) -> None:
    hass = FakeHass(allowed=(str(tmp_path),))
    coordinator, fake = await make_curtain(ha, hass)
    screen = ha.media_player.SurplifeScreen(coordinator)
    path = gif(tmp_path / "a.gif", [(0, 255, 0)])
    await screen.async_play_media("url", str(path))
    assert sum(1 for payload in fake.payloads if payload[:2] == b"\xea\x03") == 1
    other = gif(tmp_path.parent / "elsewhere.gif", [(0, 255, 0)])
    with pytest.raises(HomeAssistantError, match="allowlist_external_dirs"):
        await screen.async_play_media("image/gif", str(other))


@pytest.mark.asyncio
async def test_screen_play_media_validates_the_media_type(ha: SimpleNamespace) -> None:
    coordinator, fake = await make_curtain(ha)
    screen = ha.media_player.SurplifeScreen(coordinator)
    with pytest.raises(HomeAssistantError, match="unsupported media type"):
        await screen.async_play_media("video/mp4", "https://example.com/a.mp4")
    assert fake.writes == []


@pytest.mark.asyncio
async def test_screen_browse_media_shows_images_only(ha: SimpleNamespace) -> None:
    coordinator, _ = await make_curtain(ha)
    screen = ha.media_player.SurplifeScreen(coordinator)
    screen.hass = FakeHass()
    assert await screen.async_browse_media(None, "media-source://media_source") == "browse-result"
    _media_id, content_filter = ha.media.browse_calls[-1]
    assert content_filter(SimpleNamespace(media_content_type="image/png"))
    assert content_filter(SimpleNamespace(media_content_type="image/gif"))
    assert not content_filter(SimpleNamespace(media_content_type="video/mp4"))
    assert not content_filter(SimpleNamespace(media_content_type="audio/mpeg"))


# ---------------------------------------------------------------------------
# Screen preview image
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_is_empty_until_an_upload(ha: SimpleNamespace, tmp_path: Path) -> None:
    hass = FakeHass(allowed=(str(tmp_path),))
    coordinator, _ = await make_curtain(ha, hass)
    preview = ha.image.SurplifeScreenPreview(hass, coordinator)
    assert preview._attr_content_type == "image/png"
    assert await preview.async_image() is None
    assert preview._attr_image_last_updated is None

    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    path = gif(tmp_path / "a.gif", [(255, 0, 0), (0, 0, 255)])
    await call_upload(light, ha, path=str(path))
    preview._handle_coordinator_update()
    image = await preview.async_image()
    assert image is not None
    assert png_size(image) == (200, 200)
    assert png_pixel(image, 100, 100) == (255, 0, 0)  # first frame
    assert preview._attr_image_last_updated == coordinator.preview_updated
    assert preview._attr_image_last_updated is not None
    assert preview.writes == 1


@pytest.mark.asyncio
async def test_preview_updates_after_each_upload(ha: SimpleNamespace, tmp_path: Path) -> None:
    hass = FakeHass(allowed=(str(tmp_path),))
    coordinator, _ = await make_curtain(ha, hass)
    preview = ha.image.SurplifeScreenPreview(hass, coordinator)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    await call_upload(light, ha, path=str(gif(tmp_path / "a.gif", [(255, 0, 0)])))
    preview._handle_coordinator_update()
    first = preview._attr_image_last_updated
    await call_upload(light, ha, path=str(gif(tmp_path / "b.gif", [(0, 255, 0)])))
    preview._handle_coordinator_update()
    assert preview._attr_image_last_updated > first
    assert png_pixel(await preview.async_image(), 0, 0) == (0, 255, 0)


# ---------------------------------------------------------------------------
# Animation speed number
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_speed_number_definition(ha: SimpleNamespace) -> None:
    coordinator, _ = await make_curtain(ha)
    number = ha.number.SurplifeAnimationSpeed(coordinator)
    assert number._attr_name == "Animation speed"
    assert (number._attr_native_min_value, number._attr_native_max_value) == (1, 100)
    assert number._attr_native_step == 1
    assert number._attr_mode == ha.NumberMode.SLIDER


@pytest.mark.asyncio
async def test_speed_number_reflects_ea81_byte_9_while_the_animation_plays(
    ha: SimpleNamespace,
) -> None:
    fake = FakeCurtain()
    fake.mode, fake.effect, fake.speed = 0x74, 0x01, 0x4B
    coordinator, _ = await make_curtain(ha, fake=fake)
    number = ha.number.SurplifeAnimationSpeed(coordinator)
    assert number._attr_native_value == 75.0
    fake.speed = 0x14
    coordinator.data = await coordinator._async_update_data()
    number._handle_coordinator_update()
    assert number._attr_native_value == 20.0
    # Outside animation mode it keeps the last animation speed.
    fake.mode, fake.effect, fake.speed = 0x67, 0x0A, 0x50
    coordinator.data = await coordinator._async_update_data()
    number._handle_coordinator_update()
    assert number._attr_native_value == 20.0
    assert number.writes == 2


@pytest.mark.asyncio
async def test_speed_number_defaults_to_50(ha: SimpleNamespace) -> None:
    coordinator, _ = await make_curtain(ha)
    assert ha.number.SurplifeAnimationSpeed(coordinator)._attr_native_value == 50.0


@pytest.mark.asyncio
async def test_speed_number_sets_speed_with_the_current_mode_and_brightness(
    ha: SimpleNamespace,
) -> None:
    fake = FakeCurtain()
    fake.mode, fake.effect, fake.speed = 0x74, 0x02, 0x32  # animation held on frame 1
    coordinator, _ = await make_curtain(ha, fake=fake)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    await light.async_turn_on(brightness=128)  # remembers 50 % (resends the animation)
    number = ha.number.SurplifeAnimationSpeed(coordinator)
    await number.async_set_native_value(75.0)
    assert fake.payloads[-1] == bytes.fromhex("e209024b3200")  # mode 2 kept, speed 75, 50 %
    assert frame_bytes(fake)[2:] == bytes.fromhex("80000006070ae209024b3200")


@pytest.mark.asyncio
async def test_speed_number_outside_animation_mode_starts_the_animation(
    ha: SimpleNamespace,
) -> None:
    coordinator, fake = await make_curtain(ha)
    number = ha.number.SurplifeAnimationSpeed(coordinator)
    await number.async_set_native_value(30.0)
    assert fake.payloads[-1] == bytes.fromhex("e209011e6400")
    assert number.coordinator.animation_speed == 30


# ---------------------------------------------------------------------------
# Coordinator and unchanged paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coordinator_curtain_state_uses_remembered_percent(ha: SimpleNamespace) -> None:
    coordinator, fake = await make_curtain(ha)
    await coordinator.async_set_effect(10, brightness_percent=40)
    state = await coordinator._async_update_data()
    assert (state.mode, state.effect, state.speed) == (0x67, 10, 50)
    assert state.brightness == round(40 * 255 / 100)
    assert state.assumed
    assert bytes.fromhex("e002000a3228") in fake.payloads


@pytest.mark.asyncio
async def test_dx23012_coordinator_state_is_not_touched(ha: SimpleNamespace) -> None:
    coordinator, fake = await make_dx23012(ha)
    state = await coordinator._async_update_data()
    assert state.mode is None and state.effect is None and state.speed is None
    assert state.rgb is not None
    assert not coordinator.is_curtain


# ---------------------------------------------------------------------------
# Color calibration (config entry options)
# ---------------------------------------------------------------------------

GREEN_HALF = {"red_gain": 1.0, "green_gain": 0.5, "blue_gain": 1.0, "gamma": 1.0}
GAMMA_2 = {"gamma": 2.0}


@pytest.mark.asyncio
async def test_calibration_comes_from_the_entry_options(
    ha: SimpleNamespace, caplog: pytest.LogCaptureFixture
) -> None:
    coordinator, _ = await make_curtain(ha)
    assert coordinator.calibration.is_identity
    assert coordinator.client.curtain_calibration.is_identity
    coordinator.config_entry.options = {**GREEN_HALF, "unrelated": "kept out"}
    coordinator.async_update_options()
    assert coordinator.calibration == ColorCalibration(green_gain=0.5)
    assert coordinator.client.curtain_calibration == ColorCalibration(green_gain=0.5)
    # Invalid stored values are ignored with a warning, not applied.
    coordinator.config_entry.options = {"gamma": 9.0}
    with caplog.at_level("WARNING"):
        coordinator.async_update_options()
    assert coordinator.calibration.is_identity
    assert "Ignoring invalid color calibration options" in caplog.text


@pytest.mark.asyncio
async def test_new_clients_start_with_the_configured_calibration(ha: SimpleNamespace) -> None:
    coordinator, _ = await make_curtain(ha, options=GREEN_HALF)
    assert coordinator.client.curtain_calibration == ColorCalibration(green_gain=0.5)


@pytest.mark.asyncio
async def test_light_colors_use_the_calibration(ha: SimpleNamespace) -> None:
    coordinator, fake = await make_curtain(ha, options=GREEN_HALF)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    await light.async_turn_on(rgb_color=(0, 255, 255), brightness=255)
    # (0, 255, 255) is calibrated to (0, 128, 255): hue 210 instead of 180.
    assert frame_bytes(fake)[2:] == bytes.fromhex("8000000d0e0b3ba1696464000000000000000d")
    await light.async_turn_on(brightness=128)  # resends the same color at 50 %
    assert fake.payloads[-1].hex().startswith("3ba169643200")
    # Home Assistant still shows the color it asked for.
    state = await coordinator._async_update_data()
    assert state.rgb == (0, 255, 255)
    # Effects and the stored animation carry no color and are not calibrated.
    await light.async_turn_on(effect="Effect 10", brightness=255)
    assert fake.payloads[-1][:4] == bytes.fromhex("e002000a")
    assert fake.payloads[-1][5] == 100  # the effect command has no color to calibrate


@pytest.mark.asyncio
async def test_options_listener_updates_the_calibration_live(ha: SimpleNamespace) -> None:
    import custom_components.surplife_ble as integration

    coordinator, fake = await make_curtain(ha)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    await light.async_turn_on(rgb_color=(0, 255, 255), brightness=255)
    assert fake.payloads[-1].hex().startswith("3ba15a64")  # hue 180, uncalibrated
    entry = coordinator.config_entry
    entry.runtime_data = SimpleNamespace(coordinator=coordinator)
    entry.options = dict(GREEN_HALF)
    await integration._async_options_updated(FakeHass(), entry)
    await light.async_turn_on(rgb_color=(0, 255, 255), brightness=255)
    assert fake.payloads[-1].hex().startswith("3ba16964")  # hue 210
    entry.options = {}
    await integration._async_options_updated(FakeHass(), entry)
    await light.async_turn_on(rgb_color=(0, 255, 255), brightness=255)
    assert fake.payloads[-1].hex().startswith("3ba15a64")


def solid_png(path: Path, color: tuple[int, int, int]) -> Path:
    from PIL import Image

    Image.new("RGB", (20, 20), color).save(path)
    return path


@pytest.mark.asyncio
async def test_upload_animation_service_applies_the_calibration(
    ha: SimpleNamespace, tmp_path: Path
) -> None:
    hass = FakeHass(allowed=(str(tmp_path),))
    coordinator, fake = await make_curtain(ha, hass, options=GAMMA_2)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    path = solid_png(tmp_path / "orange.png", (255, 120, 0))
    await call_upload(light, ha, path=str(path), resample="nearest")
    calibrated = [p for p in fake.payloads if p[:2] == b"\xea\x03"]
    # gamma 2 turns (255, 120, 0) into (255, 56, 0): pixel 0x09ff instead of 0x13ff.
    block = curtain_c2.lz4_block(bytes.fromhex("09ff") * 400)
    assert calibrated == [bytes.fromhex("ea030001") + block]
    assert calibrated == [
        curtain_c2.build_upload([[(255, 120, 0)] * 400], ColorCalibration(gamma=2.0))[2].payload
    ]
    # The preview shows the picture, not the calibrated pixels.
    assert png_pixel(coordinator.preview_png, 100, 100) == (255, 120, 0)


@pytest.mark.asyncio
async def test_screen_play_media_applies_the_calibration(
    ha: SimpleNamespace, tmp_path: Path
) -> None:
    coordinator, fake = await make_curtain(ha, options=GAMMA_2)
    screen = ha.media_player.SurplifeScreen(coordinator)
    data = solid_png(tmp_path / "o.png", (255, 120, 0)).read_bytes()
    ha.session.responses["https://example.com/o.png"] = (200, {}, [data])
    await screen.async_play_media("image/png", "https://example.com/o.png")
    content = [p for p in fake.payloads if p[:2] == b"\xea\x03"]
    block = curtain_c2.lz4_block(bytes.fromhex("09ff") * 400)
    assert content == [bytes.fromhex("ea030001") + block]


@pytest.mark.asyncio
async def test_calibration_does_not_touch_the_dx23012(ha: SimpleNamespace) -> None:
    extreme = {"red_gain": 0.3, "green_gain": 0.1, "blue_gain": 2.0, "gamma": 3.0}
    coordinator, fake = await make_dx23012(ha, options=extreme)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    await light.async_turn_on(rgb_color=(255, 120, 0), brightness=255)
    sent = next(data for _uuid, data, _ in reversed(fake.writes) if data[8:10] == b"\xe1\x03")
    from custom_components.surplife_ble.core.protocol import iotbt_e1_segment_rgb

    assert sent[8:] == iotbt_e1_segment_rgb(255, 120, 0, 100)
    state = await coordinator._async_update_data()
    assert state.rgb is not None


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------


def option_flow(ha: SimpleNamespace, entry: FakeEntry) -> Any:
    return ha.config_flow.SurplifeBleConfigFlow.async_get_options_flow(entry)


def schema_fields(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(key.schema): key.default() for key in result["data_schema"].schema}


@pytest.mark.asyncio
async def test_options_flow_shows_the_identity_by_default(ha: SimpleNamespace) -> None:
    entry = FakeEntry()
    flow = option_flow(ha, entry)
    assert isinstance(flow, ha.config_flow.SurplifeOptionsFlow)
    result = await flow.async_step_init()
    assert (result["type"], result["step_id"], result["errors"]) == ("form", "init", {})
    assert schema_fields(result) == {
        "controller_side": "left",
        "flip": False,
        "red_gain": 1.0,
        "green_gain": 1.0,
        "blue_gain": 1.0,
        "gamma": 1.0,
    }
    validators = {
        str(key.schema): validator.config
        for key, validator in result["data_schema"].schema.items()
        if hasattr(validator, "config") and "min" in validator.config
    }
    for name in ("red_gain", "green_gain", "blue_gain"):
        assert (validators[name]["min"], validators[name]["max"], validators[name]["step"]) == (
            0.0,
            2.0,
            0.05,
        )
    gamma = validators["gamma"]
    assert (gamma["min"], gamma["max"], gamma["step"]) == (0.2, 4.0, 0.05)
    # The selectors keep values in range.
    with pytest.raises(vol.Invalid):
        result["data_schema"]({"red_gain": 2.5})
    assert result["data_schema"]({"gamma": 1.5})["gamma"] == 1.5


@pytest.mark.asyncio
async def test_options_flow_defaults_follow_the_stored_options(ha: SimpleNamespace) -> None:
    entry = FakeEntry({"green_gain": 0.55, "gamma": 1.4, "ignored": 1})
    result = await option_flow(ha, entry).async_step_init()
    assert schema_fields(result) == {
        "controller_side": "left",
        "flip": False,
        "red_gain": 1.0,
        "green_gain": 0.55,
        "blue_gain": 1.0,
        "gamma": 1.4,
    }


@pytest.mark.asyncio
async def test_options_flow_saves_valid_values(ha: SimpleNamespace) -> None:
    values = {"red_gain": 0.9, "green_gain": 0.6, "blue_gain": 1.1, "gamma": 1.3}
    result = await option_flow(ha, FakeEntry()).async_step_init(values)
    assert result == {"type": "create_entry", "data": values, "title": ""}
    assert ColorCalibration.from_dict(result["data"]) == ColorCalibration(0.9, 0.6, 1.1, 1.3)


@pytest.mark.asyncio
async def test_options_flow_rejects_out_of_range_values(ha: SimpleNamespace) -> None:
    values = {"red_gain": 2.5, "green_gain": 1.0, "blue_gain": 1.0, "gamma": 1.0}
    result = await option_flow(ha, FakeEntry()).async_step_init(values)
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_calibration"}
    assert schema_fields(result)["red_gain"] == 2.5  # the form keeps what was typed


@pytest.mark.asyncio
async def test_options_flow_is_only_for_curtains(ha: SimpleNamespace) -> None:
    dx, _ = await make_dx23012(ha)
    entry = dx.config_entry
    entry.runtime_data = SimpleNamespace(coordinator=dx)
    result = await option_flow(ha, entry).async_step_init()
    assert result == {"type": "abort", "reason": "not_curtain"}
    curtain, _ = await make_curtain(ha)
    curtain.config_entry.runtime_data = SimpleNamespace(coordinator=curtain)
    assert (await option_flow(ha, curtain.config_entry).async_step_init())["type"] == "form"
    # Before the device is known (entry not loaded yet) the form is shown too.
    assert (await option_flow(ha, FakeEntry()).async_step_init())["type"] == "form"


def test_options_flow_texts_exist() -> None:
    import json

    root = Path(__file__).parents[1] / "custom_components" / "surplife_ble"
    strings = json.loads((root / "strings.json").read_text(encoding="utf-8"))
    init = strings["options"]["step"]["init"]
    assert set(init["data"]) == {
        "controller_side",
        "flip",
        "red_gain",
        "green_gain",
        "blue_gain",
        "gamma",
    }
    assert init["data"]["controller_side"] == "Controller side (swap left/right)"
    assert init["data"]["flip"] == "Upside down"
    assert strings["selector"]["controller_side"]["options"] == {"left": "Left", "right": "Right"}
    assert "invalid_orientation" in strings["options"]["error"]
    assert set(init["data_description"]) == set(init["data"])
    assert "invalid_calibration" in strings["options"]["error"]
    assert "not_curtain" in strings["options"]["abort"]


# ---------------------------------------------------------------------------
# Orientation (controller side and upside down), the default for every upload
# ---------------------------------------------------------------------------


def marker_png(path: Path) -> Path:
    """A 20x20 picture with a red pixel at its top-left corner (x=0, y=0)."""
    from PIL import Image

    image = Image.new("RGB", (20, 20), (0, 0, 0))
    image.putpixel((0, 0), (255, 0, 0))
    image.save(path)
    return path


def marker_content(index: int) -> bytes:
    """The first content payload of an upload whose only red pixel is at buffer ``index``."""
    pixels = [(0, 0, 0)] * 400
    pixels[index] = (255, 0, 0)
    return curtain_c2.build_upload([pixels])[2].payload


def uploaded_content(fake: FakeCurtain) -> list[bytes]:
    return [payload for payload in fake.payloads if payload[:2] == b"\xea\x03"]


ORIENTATIONS = [
    ({}, 0),  # controller on the left, right side up: the default
    ({"controller_side": "left", "flip": False}, 0),
    ({"controller_side": "right"}, 380),  # column 0 becomes the far string
    ({"flip": True}, 19),  # row 0 becomes the bottom of the string
    ({"controller_side": "right", "flip": True}, 399),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("options", "index"), ORIENTATIONS)
async def test_screen_play_media_follows_the_orientation_options(
    ha: SimpleNamespace, tmp_path: Path, options: dict[str, Any], index: int
) -> None:
    coordinator, fake = await make_curtain(ha, options=options)
    screen = ha.media_player.SurplifeScreen(coordinator)
    data = marker_png(tmp_path / "marker.png").read_bytes()
    ha.session.responses["https://example.com/marker.png"] = (200, {}, [data])
    await screen.async_play_media("image/png", "https://example.com/marker.png")
    assert uploaded_content(fake) == [marker_content(index)]


@pytest.mark.asyncio
@pytest.mark.parametrize(("options", "index"), ORIENTATIONS)
async def test_upload_service_uses_the_options_when_the_fields_are_missing(
    ha: SimpleNamespace, tmp_path: Path, options: dict[str, Any], index: int
) -> None:
    hass = FakeHass(allowed=(str(tmp_path),))
    coordinator, fake = await make_curtain(ha, hass, options=options)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    path = marker_png(tmp_path / "marker.png")
    await call_upload(light, ha, path=str(path), resample="nearest")
    assert uploaded_content(fake) == [marker_content(index)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("options", "fields", "index"),
    [
        ({"controller_side": "right"}, {"controller_side": "left"}, 0),
        ({}, {"controller_side": "right"}, 380),
        ({"flip": True}, {"flip": False}, 0),
        ({}, {"flip": True}, 19),
        ({"controller_side": "right", "flip": True}, {"controller_side": "left"}, 19),
        ({"controller_side": "right", "flip": True}, {"flip": False}, 380),
        ({"controller_side": "right", "flip": True}, {"controller_side": "left", "flip": False}, 0),
    ],
)
async def test_service_fields_override_the_options(
    ha: SimpleNamespace,
    tmp_path: Path,
    options: dict[str, Any],
    fields: dict[str, Any],
    index: int,
) -> None:
    hass = FakeHass(allowed=(str(tmp_path),))
    coordinator, fake = await make_curtain(ha, hass, options=options)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    path = marker_png(tmp_path / "marker.png")
    await call_upload(light, ha, path=str(path), resample="nearest", **fields)
    assert uploaded_content(fake) == [marker_content(index)]
    # The override is for this call only: the options stay as they were.
    assert coordinator.controller_side == options.get("controller_side", "left")
    assert coordinator.flip == options.get("flip", False)


@pytest.mark.asyncio
@pytest.mark.parametrize(("options", "index"), ORIENTATIONS)
async def test_preview_shows_the_picture_in_viewer_orientation(
    ha: SimpleNamespace, tmp_path: Path, options: dict[str, Any], index: int
) -> None:
    hass = FakeHass(allowed=(str(tmp_path),))
    coordinator, fake = await make_curtain(ha, hass, options=options)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    await call_upload(light, ha, path=str(marker_png(tmp_path / "m.png")), resample="nearest")
    assert uploaded_content(fake) == [marker_content(index)]  # the curtain gets it mirrored
    preview = await ha.image.SurplifeScreenPreview(hass, coordinator).async_image()
    assert preview is not None
    # The preview is the source picture as the user sees it: the marker stays top-left, so
    # the orientation is not applied a second time.
    assert png_pixel(preview, 0, 0) == (255, 0, 0)
    assert png_pixel(preview, 199, 0) == (0, 0, 0)
    assert png_pixel(preview, 0, 199) == (0, 0, 0)
    assert png_pixel(preview, 199, 199) == (0, 0, 0)


@pytest.mark.asyncio
async def test_orientation_options_update_live(ha: SimpleNamespace, tmp_path: Path) -> None:
    import custom_components.surplife_ble as integration

    hass = FakeHass(allowed=(str(tmp_path),))
    coordinator, fake = await make_curtain(ha, hass)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    path = str(marker_png(tmp_path / "marker.png"))
    assert (coordinator.controller_side, coordinator.flip) == ("left", False)
    await call_upload(light, ha, path=path, resample="nearest")
    entry = coordinator.config_entry
    entry.runtime_data = SimpleNamespace(coordinator=coordinator)
    entry.options = {"controller_side": "right", "flip": True}
    await integration._async_options_updated(hass, entry)
    assert (coordinator.controller_side, coordinator.flip) == ("right", True)
    await call_upload(light, ha, path=path, resample="nearest")
    assert uploaded_content(fake) == [marker_content(0), marker_content(399)]


@pytest.mark.asyncio
async def test_invalid_orientation_option_falls_back_to_left(
    ha: SimpleNamespace, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING"):
        coordinator, _ = await make_curtain(ha, options={"controller_side": "front"})
    assert coordinator.controller_side == "left"
    assert "Ignoring invalid controller side option 'front'" in caplog.text


@pytest.mark.asyncio
async def test_orientation_does_not_change_other_commands_or_devices(
    ha: SimpleNamespace,
) -> None:
    coordinator, fake = await make_curtain(ha, options={"controller_side": "right", "flip": True})
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    await light.async_turn_on(rgb_color=(0, 0, 255), brightness=128)
    assert frame_bytes(fake)[2:] == bytes.fromhex("8000000d0e0b3ba178643200000000000000ea")
    await light.async_turn_on(effect="Effect 10", brightness=255)
    assert fake.payloads[-1][:4] == bytes.fromhex("e002000a")
    # A DX23012 ignores the options.
    dx, dx_fake = await make_dx23012(ha, options={"controller_side": "right", "flip": True})
    dx_light = ha.light.SurplifeLight(dx, FakeEntry())
    await dx_light.async_turn_on(rgb_color=(255, 120, 0), brightness=255)
    from custom_components.surplife_ble.core.protocol import iotbt_e1_segment_rgb

    sent = next(d for _u, d, _r in reversed(dx_fake.writes) if d[8:10] == b"\xe1\x03")
    assert sent[8:] == iotbt_e1_segment_rgb(255, 120, 0, 100)


@pytest.mark.asyncio
async def test_options_flow_saves_the_orientation(ha: SimpleNamespace) -> None:
    values = {
        "controller_side": "right",
        "flip": True,
        "red_gain": 1.0,
        "green_gain": 0.8,
        "blue_gain": 1.0,
        "gamma": 1.0,
    }
    flow = option_flow(ha, FakeEntry())
    result = await flow.async_step_init(values)
    assert result == {"type": "create_entry", "data": values, "title": ""}
    form = await option_flow(ha, FakeEntry(values)).async_step_init()
    assert schema_fields(form)["controller_side"] == "right"
    assert schema_fields(form)["flip"] is True
    schema = form["data_schema"]
    assert schema({"controller_side": "left", "flip": False})["controller_side"] == "left"
    with pytest.raises(vol.Invalid):
        schema({"controller_side": "front"})
    with pytest.raises(vol.Invalid):
        schema({"flip": "yes"})


@pytest.mark.asyncio
async def test_options_flow_rejects_an_invalid_controller_side(ha: SimpleNamespace) -> None:
    result = await option_flow(ha, FakeEntry()).async_step_init({"controller_side": "front"})
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_orientation"}


# ---------------------------------------------------------------------------
# Text, built-in effects and sequences
# ---------------------------------------------------------------------------


def uploads(fake: FakeCurtain) -> list[int]:
    """Frame counts of the uploads the fake received, from the EA 01 headers."""
    return [int.from_bytes(p[23:25], "big") for p in fake.payloads if p[:2] == b"\xea\x01"]


@pytest.mark.asyncio
async def test_show_text_service_uploads_and_sets_the_preview(ha: SimpleNamespace) -> None:
    coordinator, fake = await make_curtain(ha)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    data = vol.Schema(ha.services.TEXT_SCHEMA)({"text": "hi", "speed": 40})
    await light.async_show_text(**data)
    assert uploads(fake) == [1]  # two letters fit 20 LEDs: one still frame
    assert fake.payloads[-1] == bytes.fromhex("e20901286400")
    assert coordinator.preview_png.startswith(PNG_SIGNATURE)
    assert coordinator.animation_title == "hi"


@pytest.mark.asyncio
async def test_show_text_preview_only_sends_nothing(ha: SimpleNamespace) -> None:
    coordinator, fake = await make_curtain(ha)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    data = vol.Schema(ha.services.TEXT_SCHEMA)(
        {"text": "buon natale", "preview_only": True, "background": [0, 0, 255]}
    )
    await light.async_show_text(**data)
    assert fake.payloads == []
    assert png_pixel(coordinator.preview_png, 0, 0) == (0, 0, 255)


@pytest.mark.asyncio
async def test_show_effect_service_uploads_the_effect_at_its_speed(ha: SimpleNamespace) -> None:
    coordinator, fake = await make_curtain(ha)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    await light.async_show_effect(**vol.Schema(ha.services.EFFECT_SCHEMA)({"effect": "rain"}))
    assert uploads(fake) == [len(effects.build("rain", 20, 20))]
    assert fake.payloads[-1] == bytes((0xE2, 0x09, 1, effects.EFFECTS["rain"].speed, 100, 0))
    assert coordinator.animation_name == "rain"


@pytest.mark.asyncio
async def test_sequence_shows_every_step_for_its_time_and_stops(ha: SimpleNamespace) -> None:
    coordinator, fake = await make_curtain(ha)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    waits: list[float] = []

    async def fast_sleep(seconds: float) -> None:
        waits.append(seconds)

    coordinator._sequence_sleep = fast_sleep
    data = vol.Schema(ha.services.SEQUENCE_SCHEMA)(
        {"sequence": "rain 30s; hi 1m; snow", "seconds": 45, "repeat": False}
    )
    await light.async_play_sequence(**data)
    assert coordinator.sequence_running
    await coordinator._sequence_task
    assert waits == [30, 60, 45]
    assert uploads(fake) == [
        len(effects.build("rain", 20, 20)), 1, len(effects.build("snow", 20, 20))
    ]  # fmt: skip
    assert not coordinator.sequence_running
    assert coordinator.sequence_index is None


@pytest.mark.asyncio
async def test_sequence_repeats_until_it_is_stopped(ha: SimpleNamespace) -> None:
    coordinator, fake = await make_curtain(ha)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    rounds = 0

    async def sleep_then_stop(seconds: float) -> None:
        nonlocal rounds
        rounds += 1
        if rounds == 3:
            await light.async_stop_sequence()
            await asyncio.sleep(0)  # the cancellation is delivered here

    coordinator._sequence_sleep = sleep_then_stop
    steps = [{"effect": "Pioggia", "seconds": 20}, {"text": "ok"}]
    await light.async_play_sequence(**vol.Schema(ha.services.SEQUENCE_SCHEMA)({"steps": steps}))
    task = coordinator._sequence_task
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(uploads(fake)) == 3  # rain, ok, rain again
    assert not coordinator.sequence_running


@pytest.mark.asyncio
async def test_sequence_errors_are_reported_before_it_starts(ha: SimpleNamespace) -> None:
    coordinator, _ = await make_curtain(ha)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    with pytest.raises(ha.animation.AnimationError, match="no steps"):
        await light.async_play_sequence(**vol.Schema(ha.services.SEQUENCE_SCHEMA)({}))
    assert not coordinator.sequence_running


@pytest.mark.asyncio
async def test_sequence_scrolls_a_text_too_wide_for_never_scroll(ha: SimpleNamespace) -> None:
    coordinator, fake = await make_curtain(ha)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    coordinator.text_scroll = "never"
    waits: list[float] = []

    async def fast_sleep(seconds: float) -> None:
        waits.append(seconds)

    coordinator._sequence_sleep = fast_sleep
    data = vol.Schema(ha.services.SEQUENCE_SCHEMA)(
        {"sequence": "hi 20s; buon natale 40s", "repeat": False}
    )
    await light.async_play_sequence(**data)
    await coordinator._sequence_task
    assert waits == [20, 40]  # no retries: both steps got on the device
    assert uploads(fake)[0] == 1  # the short text stays still
    assert uploads(fake)[1] > 1  # the long one scrolls instead of failing


@pytest.mark.asyncio
async def test_never_scroll_fits_the_text_or_scrolls_instead_of_failing(
    ha: SimpleNamespace,
) -> None:
    coordinator, _ = await make_curtain(ha)
    coordinator.text_scroll = "never"
    coordinator.text_size = "small"
    assert coordinator.text_settings("hi") == coordinator.text_settings()
    # 22 LEDs in bold and the screen is 20: the renderer narrows it, it stays still.
    assert coordinator.text_settings("abc")["scroll"] is False
    assert coordinator.text_settings("buon natale a tutti")["scroll"] is None


@pytest.mark.asyncio
async def test_changing_a_text_control_redraws_the_text_box(ha: SimpleNamespace) -> None:
    coordinator, fake = await make_curtain(ha)
    coordinator._text_refresh_delay = 0
    coordinator.async_refresh_text()  # the Text box is empty: nothing to draw
    assert coordinator._text_refresh_task is None
    coordinator.text_value = "hi"
    coordinator.text_scroll = "always"
    coordinator.async_refresh_text()
    coordinator.text_color = "red"
    coordinator.async_refresh_text()  # two quick changes are sent together
    await coordinator._text_refresh_task
    assert len(uploads(fake)) == 1
    assert uploads(fake)[0] > 1  # it scrolls now
    assert coordinator.animation_title == "hi"


@pytest.mark.asyncio
async def test_sequence_random_step_shows_a_built_in_effect(ha: SimpleNamespace) -> None:
    coordinator, fake = await make_curtain(ha)
    light = ha.light.SurplifeLight(coordinator, FakeEntry())

    async def fast_sleep(seconds: float) -> None:
        return None

    coordinator._sequence_sleep = fast_sleep
    data = vol.Schema(ha.services.SEQUENCE_SCHEMA)({"sequence": "casuale 20s", "repeat": False})
    await light.async_play_sequence(**data)
    await coordinator._sequence_task
    assert coordinator.animation_name in effects.available(20, 20)
    assert uploads(fake) == [len(effects.build(coordinator.animation_name, 20, 20))]


@pytest.mark.asyncio
async def test_layout_change_redraws_what_was_shown_last(ha: SimpleNamespace) -> None:
    coordinator, fake = await make_curtain(ha)
    coordinator._text_refresh_delay = 0
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    await light.async_show_effect(**vol.Schema(ha.services.EFFECT_SCHEMA)({"effect": "rain"}))
    assert coordinator.last_shown == ("effect", "rain")
    coordinator.layout_top, coordinator.layout_bottom = "4", "6"
    assert coordinator.canvas == (20, 10)
    coordinator.async_refresh_layout()
    await coordinator._text_refresh_task
    assert uploads(fake) == [len(effects.build("rain", 20, 20)), len(effects.build("rain", 20, 10))]
    coordinator.layout_rotation = "90"
    coordinator.text_value = "hi"
    coordinator.async_refresh_text()
    await coordinator._text_refresh_task
    assert coordinator.last_shown == ("text", "hi")
    assert len(uploads(fake)) == 3


@pytest.mark.asyncio
async def test_preview_survives_a_restart(ha: SimpleNamespace, tmp_path: Path) -> None:
    coordinator, _ = await make_curtain(ha)
    coordinator.hass.config.path = lambda *parts: str(tmp_path.joinpath(*parts))
    (tmp_path / ".storage").mkdir()
    light = ha.light.SurplifeLight(coordinator, FakeEntry())
    await light.async_show_effect(**vol.Schema(ha.services.EFFECT_SCHEMA)({"effect": "rain"}))
    saved = coordinator.preview_png
    restarted, _ = await make_curtain(ha)
    restarted.hass.config.path = coordinator.hass.config.path
    assert restarted.preview_png is None
    await restarted.async_restore_preview()
    assert restarted.preview_png == saved
    assert restarted.animation_title == "rain"
    assert restarted.last_shown == ("effect", "rain")
