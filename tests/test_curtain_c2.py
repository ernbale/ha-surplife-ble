"""Tests for the IOTBT curtain (product 0xC2) builders and state parser.

Frame vectors are hardware-verified on an IOTBT437 (2026-10-17).
"""

from __future__ import annotations

import random

import pytest

from custom_components.surplife_ble.core import curtain_c2
from custom_components.surplife_ble.core.framing import with_checksum, wrap_magichome


def _frame(command: curtain_c2.CurtainCommand, sequence: int) -> str:
    return wrap_magichome(command.payload, sequence, command_family=command.cmd_id).hex()


def test_power_frames_match_hardware_verified_vectors() -> None:
    assert _frame(curtain_c2.power(False), 1) == "00018000000d0e0b3b240000000000000032000091"
    assert _frame(curtain_c2.power(True), 2) == "00028000000d0e0b3b230000000000000032000090"
    assert curtain_c2.power(True).cmd_id == 0x0B


@pytest.mark.parametrize(
    ("rgb", "brightness", "sequence", "expected"),
    [
        ((255, 0, 0), 100, 3, "00038000000d0e0b3ba100646400000000000000a4"),
        ((0, 0, 255), 50, 4, "00048000000d0e0b3ba178643200000000000000ea"),
        ((0, 0, 255), 10, 5, "00058000000d0e0b3ba178640a00000000000000c2"),
        ((0, 0, 255), 100, 7, "00078000000d0e0b3ba1786464000000000000001c"),
        ((0, 255, 0), 100, 8, "00088000000d0e0b3ba13c646400000000000000e0"),
        ((255, 255, 255), 100, 9, "00098000000d0e0b3ba10000640000000000000040"),
    ],
)
def test_color_rgb_matches_hardware_verified_vectors(
    rgb: tuple[int, int, int], brightness: int, sequence: int, expected: str
) -> None:
    command = curtain_c2.color_rgb(*rgb, brightness)
    assert command.cmd_id == 0x0B
    assert _frame(command, sequence) == expected


def test_color_hsv_packs_hue_and_saturation() -> None:
    command = curtain_c2.color_hsv(240, 100, 50)
    assert command.payload[:5] == bytes.fromhex("3ba1786432")
    assert command.payload == curtain_c2.color_rgb(0, 0, 255, 50).payload
    # packed = (120 << 7) | 100 for hue 120.
    assert curtain_c2.color_hsv(120, 100, 100).payload[2:4] == bytes.fromhex("3c64")


def test_color_inputs_are_validated() -> None:
    with pytest.raises(ValueError):
        curtain_c2.color_hsv(360, 100, 100)
    with pytest.raises(ValueError):
        curtain_c2.color_hsv(0, 101, 100)
    with pytest.raises(ValueError):
        curtain_c2.color_hsv(0, 100, 101)
    with pytest.raises(ValueError):
        curtain_c2.color_rgb(256, 0, 0)


def test_standalone_brightness_vector_is_documented_but_not_a_builder() -> None:
    # Verified to be IGNORED by the device; kept only to pin the documented frame.
    inner = with_checksum(bytes.fromhex("3b0100006400640000000000"))
    assert wrap_magichome(inner, 6, command_family=0x0B).hex() == (
        "00068000000d0e0b3b010000640064000000000004"
    )
    assert not hasattr(curtain_c2, "brightness")


def test_effect_has_no_checksum_and_uses_cmd_0a() -> None:
    command = curtain_c2.effect(10, speed=80, brightness=100)
    assert command == (bytes.fromhex("e002000a5064"), 0x0A)
    assert curtain_c2.effect(1, 50, 100, preview=True).payload == bytes.fromhex("e00201013264")
    assert _frame(command, 1) == "000180000006070ae002000a5064"


def test_effect_inputs_are_validated() -> None:
    with pytest.raises(ValueError):
        curtain_c2.effect(256)
    with pytest.raises(ValueError):
        curtain_c2.effect(1, speed=101)
    with pytest.raises(ValueError):
        curtain_c2.effect(1, brightness=101)


def test_state_query() -> None:
    assert curtain_c2.state_query() == (bytes.fromhex("ea818a8b"), 0x0A)


def test_parse_initial_state() -> None:
    raw = bytes.fromhex("ea810100c20323620164f00000000000010190000001020300")
    state = curtain_c2.parse_state(raw)
    assert state is not None
    assert state.power is True
    assert state.mode == 0x62
    assert state.mode_name == "initial"
    assert state.effect is None
    assert state.speed is None
    assert state.product_id == 0x00C2
    assert state.led_version == 3
    assert state.raw == raw


def test_parse_off_and_after_color_states() -> None:
    off = curtain_c2.parse_state(
        bytes.fromhex("ea810100c20324620164f00000000000010190000001020300")
    )
    assert off is not None
    assert off.power is False
    color = curtain_c2.parse_state(
        bytes.fromhex("ea810100c20323666e64f00000000000010190000001020300")
    )
    assert color is not None
    assert color.power is True
    assert color.mode == 0x66
    assert color.mode_name == "color"
    assert color.effect is None


def test_parse_scene_state_reports_effect_and_speed() -> None:
    state = curtain_c2.parse_state(
        bytes.fromhex("ea810100c20323670a50f00000000000010190000001020300")
    )
    assert state is not None
    assert state.mode == 0x67
    assert state.mode_name == "scene"
    assert state.effect == 10
    assert state.speed == 80
    assert state.to_dict()["effect"] == 10


@pytest.mark.parametrize("cmd_byte", [0x15, 0x16])
def test_parse_wrapped_notification_ignores_cmd_byte(cmd_byte: int) -> None:
    body = bytes.fromhex("ea810100c20323670a50f00000000000010190000001020300")
    packet = bytes((0x04, 0x01, 0x80, 0x00, 0x00, len(body), len(body) + 1, cmd_byte)) + body
    state = curtain_c2.parse_state(packet)
    assert state is not None
    assert state.effect == 10
    assert state.raw == body


def test_parse_rejects_other_packets() -> None:
    assert curtain_c2.parse_state(b"") is None
    assert curtain_c2.parse_state(bytes.fromhex("818a8b96")) is None
    assert curtain_c2.parse_state(bytes.fromhex("ea8101")) is None
    assert curtain_c2.parse_state(bytes.fromhex("0001800000050607deadbeef")) is None


# ---------------------------------------------------------------------------
# Images and animations (hardware-verified 2026-10-17)
# ---------------------------------------------------------------------------

RED_LZ4 = "2f01ff0200ffffff0950ff01ff01ff"
BLUE_LZ4 = "2fa1ff0200ffffff0950ffa1ffa1ff"
RED = (255, 0, 0)
BLUE = (0, 0, 255)


@pytest.mark.parametrize(
    ("rgb", "expected"),
    [
        ((255, 0, 0), 0x01FF),
        ((0, 255, 0), 0x51FF),
        ((0, 0, 255), 0xA1FF),
        ((0, 0, 0), 0x0000),
    ],
)
def test_pixel_hsv16_vectors(rgb: tuple[int, int, int], expected: int) -> None:
    assert curtain_c2.pixel_hsv16(*rgb) == expected


def test_pixel_hsv16_validates_channels() -> None:
    with pytest.raises(ValueError):
        curtain_c2.pixel_hsv16(256, 0, 0)


def test_frame_blob_is_400_big_endian_pixels() -> None:
    blob = curtain_c2.frame_blob(curtain_c2.solid_frame(RED))
    assert blob == bytes.fromhex("01ff") * 400
    assert len(blob) == 800
    with pytest.raises(ValueError):
        curtain_c2.frame_blob([RED] * 399)


def test_lz4_vectors_match_hardware() -> None:
    assert curtain_c2.lz4_block(bytes.fromhex("01ff") * 400).hex() == RED_LZ4
    assert curtain_c2.lz4_block(bytes.fromhex("a1ff") * 400).hex() == BLUE_LZ4


def test_pixel_index_mapping() -> None:
    assert curtain_c2.pixel_index(0, 0) == 0
    assert curtain_c2.pixel_index(0, 1) == 1
    assert curtain_c2.pixel_index(0, 19) == 19
    assert curtain_c2.pixel_index(1, 0) == 20
    assert curtain_c2.pixel_index(19, 19) == 399
    # mirror: x -> 19 - x ; flip: y -> 19 - y
    assert curtain_c2.pixel_index(0, 0, mirror=True) == 380
    assert curtain_c2.pixel_index(19, 0, mirror=True) == 0
    assert curtain_c2.pixel_index(0, 0, flip=True) == 19
    assert curtain_c2.pixel_index(0, 19, flip=True) == 0
    assert curtain_c2.pixel_index(0, 0, mirror=True, flip=True) == 399
    with pytest.raises(ValueError):
        curtain_c2.pixel_index(20, 0)


def test_image_to_frame_places_pixels_by_column_then_row() -> None:
    black = (0, 0, 0)
    pixels = [black] * 400
    pixels[0 * 20 + 0] = (1, 0, 0)  # x=0, y=0
    pixels[1 * 20 + 0] = (0, 1, 0)  # x=0, y=1 -> index 1
    pixels[0 * 20 + 1] = (0, 0, 1)  # x=1, y=0 -> index 20
    frame = curtain_c2.image_to_frame(pixels)
    assert frame[0] == (1, 0, 0)
    assert frame[1] == (0, 1, 0)
    assert frame[20] == (0, 0, 1)
    mirrored = curtain_c2.image_to_frame(pixels, mirror=True)
    assert mirrored[380] == (1, 0, 0)
    assert mirrored[381] == (0, 1, 0)
    assert mirrored[360] == (0, 0, 1)
    flipped = curtain_c2.image_to_frame(pixels, flip=True)
    assert flipped[19] == (1, 0, 0)
    assert flipped[18] == (0, 1, 0)
    assert flipped[39] == (0, 0, 1)
    with pytest.raises(ValueError):
        curtain_c2.image_to_frame([black] * 399)


def test_build_upload_one_red_frame() -> None:
    steps = curtain_c2.build_upload([curtain_c2.solid_frame(RED)])
    assert [(step.name, step.acked) for step in steps] == [
        ("header", True),
        ("address", True),
        ("content 1", True),
        ("end", True),
    ]
    header = steps[0].payload
    assert len(header) == 40
    assert header == (
        bytes.fromhex("ea0101")
        + (800).to_bytes(4, "big")  # total = 800 bytes per frame, not 400 pixels
        + bytes(16)
        + bytes.fromhex("0001")
        + bytes(15)
    )
    assert header.hex().startswith("ea010100000320" + "00" * 16)
    # Address entries are 6 bytes: u32 offset + u16 length, no padding.
    assert steps[1].payload.hex() == "ea0200000000000f"
    assert steps[2].payload.hex() == "ea030001" + RED_LZ4
    assert steps[3].payload.hex() == "ea0400"


def test_every_upload_step_is_acked_including_every_content_frame() -> None:
    steps = curtain_c2.build_upload([curtain_c2.solid_frame(RED)] * 5)
    assert [step.name for step in steps] == [
        "header",
        "address",
        "content 1",
        "content 2",
        "content 3",
        "content 4",
        "content 5",
        "end",
    ]
    assert all(step.acked for step in steps)


def test_build_upload_two_frames() -> None:
    steps = curtain_c2.build_upload([curtain_c2.solid_frame(RED), curtain_c2.solid_frame(BLUE)])
    assert steps[0].payload[3:7] == (1600).to_bytes(4, "big")
    assert steps[0].payload[23:25] == bytes.fromhex("0002")
    assert steps[1].payload.hex() == "ea0200000000000f0000000f000f"
    assert steps[2].payload.hex() == "ea030001" + RED_LZ4
    assert steps[3].payload.hex() == "ea030002" + BLUE_LZ4
    assert [step.name for step in steps][-1] == "end"
    assert all(step.payload for step in steps)


def test_build_upload_validates_frame_count() -> None:
    with pytest.raises(ValueError):
        curtain_c2.build_upload([])
    with pytest.raises(ValueError):
        curtain_c2.build_upload([[RED] * 399])


def test_parse_upload_reply() -> None:
    assert curtain_c2.parse_upload_reply(bytes.fromhex("ea0100")) == curtain_c2.UploadReply(1, 0)
    assert curtain_c2.parse_upload_reply(bytes.fromhex("ea0200")).ok  # type: ignore[union-attr]
    third = curtain_c2.parse_upload_reply(bytes.fromhex("ea030002" + "00"))
    assert third == curtain_c2.UploadReply(3, 0, 2)
    failed = curtain_c2.parse_upload_reply(bytes.fromhex("ea0401"))
    assert failed is not None
    assert failed.step == 4
    assert not failed.ok
    body = bytes.fromhex("ea0300010000")[:5]
    wrapped = bytes((0x04, 0x07, 0x80, 0x00, 0x00, len(body), len(body) + 1, 0x15)) + body
    assert curtain_c2.parse_upload_reply(wrapped) == curtain_c2.UploadReply(3, 0, 1)
    assert curtain_c2.parse_upload_reply(
        bytes((0x04, 0x07, 0x80, 0x00, 0x00, 3, 4, 0x15)) + bytes.fromhex("ea0100")
    ) == curtain_c2.UploadReply(1, 0)


def test_parse_upload_reply_ignores_other_packets() -> None:
    state = bytes.fromhex("ea810100c20323670a50f00000000000010190000001020300")
    assert curtain_c2.parse_upload_reply(state) is None
    assert curtain_c2.parse_upload_reply(b"") is None
    assert curtain_c2.parse_upload_reply(bytes.fromhex("ea0300")) is None


def test_play_command() -> None:
    assert curtain_c2.play(0, 50, 100) == (bytes.fromhex("e20900326400"), 0x0A)
    assert curtain_c2.play(1, 10, 1).payload == bytes.fromhex("e209010a0100")
    assert curtain_c2.play(2, 0, 0).payload == bytes.fromhex("e20902000000")
    with pytest.raises(ValueError):
        curtain_c2.play(0, 101, 100)
    with pytest.raises(ValueError):
        curtain_c2.play(0, 50, 101)
    with pytest.raises(ValueError):
        curtain_c2.play(256, 50, 100)


def test_parse_diy_playback_state() -> None:
    state = curtain_c2.parse_state(
        bytes.fromhex("ea810100c203237400" + "32" + "f00000000000010190000001020300")
    )
    assert state is not None
    assert state.mode == 0x74
    assert state.mode_name == "diy"
    assert state.speed == 0x32
    assert state.effect is None
    assert (state.byte8, state.byte9) == (0, 0x32)
    assert state.to_dict()["play_mode"] == 0
    assert state.to_dict()["byte9"] == 0x32


def _make_gif(path, colors: list[tuple[int, int, int]]) -> None:  # type: ignore[no-untyped-def]
    from PIL import Image

    images = [Image.new("RGB", (40, 40), color) for color in colors]
    images[0].save(path, save_all=True, append_images=images[1:], duration=100, loop=0)


def test_load_image_frames_from_animated_gif(tmp_path) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("PIL")
    path = tmp_path / "anim.gif"
    _make_gif(path, [(255, 0, 0), (0, 0, 255)])
    loaded = curtain_c2.load_image_frames(str(path))
    assert loaded.total == 2
    assert len(loaded.frames) == 2
    assert all(len(frame) == 400 for frame in loaded.frames)
    assert curtain_c2.pixel_hsv16(*loaded.frames[0][0]) == 0x01FF
    assert curtain_c2.pixel_hsv16(*loaded.frames[1][399]) == 0xA1FF
    steps = curtain_c2.build_upload(loaded.frames)
    assert steps[2].payload.hex() == "ea030001" + RED_LZ4
    assert steps[3].payload.hex() == "ea030002" + BLUE_LZ4


def test_load_image_frames_repeats_frames_by_duration(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The curtain plays every frame for the same time, so long GIF frames are repeated."""
    pil = pytest.importorskip("PIL.Image")
    path = tmp_path / "timed.gif"
    images = [pil.new("RGB", (20, 20), c) for c in ((255, 0, 0), (0, 255, 0), (0, 0, 255))]
    images[0].save(path, save_all=True, append_images=images[1:], duration=[100, 300, 100], loop=0)
    loaded = curtain_c2.load_image_frames(str(path))
    assert loaded.total == 5
    assert [curtain_c2.pixel_hsv16(*frame[0]) for frame in loaded.frames] == [
        0x01FF, 0x51FF, 0x51FF, 0x51FF, 0xA1FF,
    ]
    capped = curtain_c2.load_image_frames(str(path), max_frames=3)
    assert len(capped.frames) == 3
    assert capped.total == 5


def test_load_image_frames_max_frames_and_resample(tmp_path) -> None:  # type: ignore[no-untyped-def]
    pytest.importorskip("PIL")
    path = tmp_path / "anim.gif"
    _make_gif(path, [(255, 0, 0), (0, 255, 0), (0, 0, 255)])
    loaded = curtain_c2.load_image_frames(str(path), max_frames=2, resample="nearest")
    assert (loaded.total, len(loaded.frames)) == (3, 2)
    with pytest.raises(ValueError):
        curtain_c2.load_image_frames(str(path), resample="cubic")


def test_load_image_frames_mirror_and_flip_use_buffer_order(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from PIL import Image

    pytest.importorskip("PIL")
    image = Image.new("RGB", (20, 20), (0, 0, 0))
    image.putpixel((0, 0), (255, 0, 0))  # x=0 (controller side), y=0 (top)
    path = tmp_path / "marker.png"
    image.save(path)
    plain = curtain_c2.load_image_frames(str(path), resample="nearest").frames[0]
    mirrored = curtain_c2.load_image_frames(str(path), resample="nearest", mirror=True).frames[0]
    flipped = curtain_c2.load_image_frames(str(path), resample="nearest", flip=True).frames[0]
    assert plain[0] == (255, 0, 0)
    assert mirrored[380] == (255, 0, 0)
    assert flipped[19] == (255, 0, 0)


def test_load_image_frames_flattens_transparency_on_black(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from PIL import Image

    pytest.importorskip("PIL")
    path = tmp_path / "clear.png"
    Image.new("RGBA", (20, 20), (255, 0, 0, 0)).save(path)
    frame = curtain_c2.load_image_frames(str(path), resample="nearest").frames[0]
    assert set(frame) == {(0, 0, 0)}


def test_random_noise_frame_compresses_to_more_than_one_ble_write() -> None:
    rng = random.Random(1)
    frame = [(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(400)]
    steps = curtain_c2.build_upload([frame])
    assert len(steps[2].payload) > 174  # needs the segmented transport


def test_pixel_index_controller_side() -> None:
    # left (default): image column 0 is the controller-side string.
    assert curtain_c2.pixel_index(0, 0, controller_side="left") == 0
    assert curtain_c2.pixel_index(19, 0, controller_side="left") == 380
    # right: image column 19 is the controller-side string.
    assert curtain_c2.pixel_index(19, 0, controller_side="right") == 0
    assert curtain_c2.pixel_index(0, 0, controller_side="right") == 380
    assert curtain_c2.pixel_index(18, 5, controller_side="right") == 25
    assert curtain_c2.pixel_index(0, 19, controller_side="right") == 399
    # The default is left.
    assert curtain_c2.pixel_index(3, 4) == curtain_c2.pixel_index(3, 4, controller_side="left")
    # Right is the same as mirroring a left mapping.
    for x, y in ((0, 0), (5, 7), (19, 19)):
        assert curtain_c2.pixel_index(x, y, controller_side="right") == (
            curtain_c2.pixel_index(x, y, mirror=True)
        )
    with pytest.raises(ValueError):
        curtain_c2.pixel_index(0, 0, controller_side="middle")


def test_mirror_flips_the_controller_side_choice() -> None:
    assert curtain_c2.pixel_index(19, 0, controller_side="left", mirror=True) == 0
    assert curtain_c2.pixel_index(0, 0, controller_side="right", mirror=True) == 0
    assert curtain_c2.pixel_index(
        4, 9, controller_side="right", mirror=True, flip=True
    ) == curtain_c2.pixel_index(4, 9, flip=True)


def test_image_to_frame_controller_side() -> None:
    pixels = [(0, 0, 0)] * 400
    pixels[0 * 20 + 0] = (1, 0, 0)  # x=0, y=0
    pixels[0 * 20 + 19] = (0, 1, 0)  # x=19, y=0
    left = curtain_c2.image_to_frame(pixels, controller_side="left")
    assert left[0] == (1, 0, 0)
    assert left[380] == (0, 1, 0)
    right = curtain_c2.image_to_frame(pixels, controller_side="right")
    assert right[0] == (0, 1, 0)
    assert right[380] == (1, 0, 0)
    assert curtain_c2.image_to_frame(pixels) == left


def test_load_image_frames_controller_side(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from PIL import Image

    pytest.importorskip("PIL")
    image = Image.new("RGB", (20, 20), (0, 0, 0))
    image.putpixel((0, 0), (255, 0, 0))  # left edge, top
    path = tmp_path / "edge.png"
    image.save(path)
    left = curtain_c2.load_image_frames(str(path), resample="nearest").frames[0]
    right = curtain_c2.load_image_frames(
        str(path), resample="nearest", controller_side="right"
    ).frames[0]
    assert left[0] == (255, 0, 0)
    assert right[380] == (255, 0, 0)
    assert right[0] == (0, 0, 0)
    with pytest.raises(ValueError):
        curtain_c2.load_image_frames(str(path), controller_side="front")


# ---------------------------------------------------------------------------
# Upload format corrections (verified against the Surplife app capture, 2026-10-17)
# ---------------------------------------------------------------------------


def test_upload_header_matches_app_capture_for_10_frames() -> None:
    header = curtain_c2.upload_header(10)
    assert len(header) == 40
    assert header == (
        bytes.fromhex("ea010100001f40") + bytes(16) + bytes.fromhex("000a") + bytes(15)
    )


def test_upload_address_matches_app_capture_for_10_frames() -> None:
    lengths = [0x111, 0x113, 0x11B, 0x11A, 0x10F, 0x11A, 0x119, 0x125, 0x123, 0x12E]
    address = curtain_c2.upload_address(lengths)
    assert len(address) == 62  # 2 + 10 * 6
    assert address.hex() == (
        "ea0200000000011100000111011300000224011b0000033f011a00000459010f"
        "00000568011a0000068201190000079b0125000008c00123000009e3012e"
    )


def test_three_solid_frames_use_six_byte_entries_and_total_2400() -> None:
    green = (0, 255, 0)
    steps = curtain_c2.build_upload(
        [curtain_c2.solid_frame(color) for color in (RED, green, BLUE)]
    )
    assert steps[0].payload[3:7].hex() == "00000960"
    assert int.from_bytes(steps[0].payload[3:7], "big") == 2400
    assert steps[1].payload.hex() == "ea0200000000000f0000000f000f0000001e000f"
    assert len(steps[1].payload) == 2 + 3 * 6
    assert [len(step.payload) for step in steps[2:5]] == [4 + 15] * 3


def test_address_entries_are_never_padded() -> None:
    lengths = [15, 15, 15, 15]
    address = curtain_c2.upload_address(lengths)
    assert len(address) == 2 + 6 * 4
    assert address[2 + 6 * 2 : 2 + 6 * 3].hex() == "0000001e000f"  # entry 3 offset is 30


def test_frame_capacity_is_128_frames_and_102400_bytes() -> None:
    assert curtain_c2.MAX_UPLOAD_BYTES == 102400
    assert curtain_c2.MAX_UPLOAD_FRAMES == 128
    assert curtain_c2.MAX_UPLOAD_FRAMES == 102400 // (20 * 20 * 2)
    frames = [curtain_c2.solid_frame(RED)] * 128
    steps = curtain_c2.build_upload(frames)
    assert steps[0].payload[3:7] == (102400).to_bytes(4, "big")
    assert steps[0].payload[23:25] == (128).to_bytes(2, "big")
    assert len(steps[1].payload) == 2 + 128 * 6
    with pytest.raises(ValueError, match="128 frames"):
        curtain_c2.build_upload([curtain_c2.solid_frame(RED)] * 129)


def test_too_big_status_is_a_failed_reply() -> None:
    reply = curtain_c2.parse_upload_reply(bytes.fromhex("ea0102"))
    assert reply == curtain_c2.UploadReply(1, curtain_c2.STATUS_TOO_BIG)
    assert reply is not None
    assert not reply.ok


def test_play_defaults_to_the_app_mode_1() -> None:
    assert curtain_c2.play() == (bytes.fromhex("e20901326400"), 0x0A)
    assert curtain_c2.play(speed=75).payload == bytes.fromhex("e209014b6400")


# ---------------------------------------------------------------------------
# Home Assistant helpers
# ---------------------------------------------------------------------------


def test_effect_names_round_trip() -> None:
    names = curtain_c2.effect_list()
    assert names[0] == "Animation (uploaded)"
    assert names[1:3] == ["Effect 1", "Effect 2"]
    assert len(names) == curtain_c2.CURTAIN_EFFECT_COUNT + 1
    assert curtain_c2.effect_id_from_name("Effect 10") == 10
    for bad in ("Effect 0", "Effect 101", "Effect x", "Animation (uploaded)", "effect 1"):
        with pytest.raises(ValueError):
            curtain_c2.effect_id_from_name(bad)


@pytest.mark.parametrize(
    ("mode", "effect_id", "name"),
    [
        (0x67, 10, "Effect 10"),
        (0x67, 0, None),
        (0x67, 101, None),
        (0x74, 1, "Animation (uploaded)"),
        (0x66, 10, None),
        (0x62, 1, None),
        (None, None, None),
    ],
)
def test_effect_name_for_state(mode: int | None, effect_id: int | None, name: str | None) -> None:
    assert curtain_c2.effect_name_for_state(mode, effect_id) == name


def test_check_upload_reply_messages() -> None:
    curtain_c2.check_upload_reply(curtain_c2.UploadReply(1, 0))
    with pytest.raises(curtain_c2.CurtainUploadError, match="too big for device memory"):
        curtain_c2.check_upload_reply(curtain_c2.UploadReply(1, 2))
    with pytest.raises(curtain_c2.CurtainUploadError, match=r"EA 03 \(frame 4\): status 0x05"):
        curtain_c2.check_upload_reply(curtain_c2.UploadReply(3, 5, 4))
    assert issubclass(curtain_c2.CurtainUploadError, RuntimeError)


def test_frame_to_image_inverts_image_to_frame() -> None:
    rng = random.Random(7)
    pixels = [(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(400)]
    for side in ("left", "right"):
        for flip in (False, True):
            frame = curtain_c2.image_to_frame(pixels, controller_side=side, flip=flip)
            assert curtain_c2.frame_to_image(frame, controller_side=side, flip=flip) == pixels
    with pytest.raises(ValueError):
        curtain_c2.frame_to_image([RED] * 399)


def test_render_preview_png_is_200_by_200_nearest() -> None:
    from PIL import Image

    pixels = [(0, 0, 0)] * 400
    pixels[0] = RED
    pixels[399] = BLUE
    import io

    image = Image.open(io.BytesIO(curtain_c2.render_preview_png(pixels))).convert("RGB")
    assert image.size == (200, 200)
    assert image.getpixel((0, 0)) == RED
    assert image.getpixel((9, 9)) == RED  # each LED is a 10 x 10 block
    assert image.getpixel((10, 0)) == (0, 0, 0)
    assert image.getpixel((199, 199)) == BLUE
    with pytest.raises(ValueError):
        curtain_c2.render_preview_png([RED] * 399)


def test_load_image_frames_accepts_a_file_object_and_can_stop_early(tmp_path) -> None:  # type: ignore[no-untyped-def]
    import io

    pytest.importorskip("PIL")
    path = tmp_path / "anim.gif"
    _make_gif(path, [(255, 0, 0), (0, 255, 0), (0, 0, 255)])
    data = path.read_bytes()
    loaded = curtain_c2.load_image_frames(io.BytesIO(data), max_frames=2, count_all=False)
    assert len(loaded.frames) == 2
    assert loaded.total == 3  # one more than max_frames: "more than 2"
    full = curtain_c2.load_image_frames(io.BytesIO(data), max_frames=3, count_all=False)
    assert (len(full.frames), full.total) == (3, 3)
    with pytest.raises(ValueError, match="not a readable image"):
        curtain_c2.load_image_frames(io.BytesIO(b"nope"))


# ---------------------------------------------------------------------------
# Product 0x0071: 32 x 16 net light, hardware-verified 2026-11-19.
# ---------------------------------------------------------------------------

NET_71_STATE = bytes.fromhex("ea810100710623666e64f0000000000001020000000102010071")


def test_net_71_grid_and_state() -> None:
    state = curtain_c2.parse_state(NET_71_STATE)
    assert state is not None
    assert state.product_id == curtain_c2.PRODUCT_ID_NET_71
    assert state.power is True
    assert curtain_c2.grid_for_product(state.product_id) == (32, 16)
    assert curtain_c2.grid_for_product(curtain_c2.PRODUCT_ID) == (20, 20)
    assert curtain_c2.grid_for_product(0x1234) == (20, 20)
    assert curtain_c2.max_upload_frames(32, 16) == 100
    assert curtain_c2.max_upload_frames() == curtain_c2.MAX_UPLOAD_FRAMES


def test_net_71_pixel_order_is_column_major_with_16_rows() -> None:
    assert curtain_c2.pixel_index(0, 0, cols=32, rows=16) == 0
    assert curtain_c2.pixel_index(0, 15, cols=32, rows=16) == 15
    assert curtain_c2.pixel_index(1, 0, cols=32, rows=16) == 16
    assert curtain_c2.pixel_index(31, 15, cols=32, rows=16) == 511
    assert curtain_c2.pixel_index(31, 0, cols=32, rows=16, controller_side="right") == 0
    pixels = [(x, y, 0) for y in range(16) for x in range(32)]
    frame = curtain_c2.image_to_frame(pixels, cols=32, rows=16)
    assert frame[16] == (1, 0, 0)
    assert curtain_c2.frame_to_image(frame, cols=32, rows=16) == pixels


def test_net_71_upload_matches_the_frames_accepted_by_the_device() -> None:
    """The header and address the real net acknowledged on 2026-11-19 (one frame)."""
    frame = curtain_c2.solid_frame((255, 0, 0), cols=32, rows=16)
    steps = curtain_c2.build_upload([frame], cols=32, rows=16)
    assert steps[0].payload.hex() == "ea01010000040000" + "00" * 15 + "0001" + "00" * 15
    block = steps[2].payload[4:]
    assert steps[1].payload == bytes.fromhex("ea0200000000") + len(block).to_bytes(2, "big")
    assert steps[3].payload == bytes.fromhex("ea0400")
    with pytest.raises(ValueError):
        curtain_c2.build_upload([frame] * 101, cols=32, rows=16)
    with pytest.raises(ValueError):
        curtain_c2.build_upload([frame])  # a 512-pixel frame is not a 20 x 20 frame
