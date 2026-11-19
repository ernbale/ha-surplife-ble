"""Command builders and state parser for the IOTBT curtain (product 0x00C2).

These are hardware-verified on an IOTBT437 (2026-10-17). The ``ble-rgb curtain`` commands
and the Home Assistant integration (light, Screen media player, services) both use them
through ``LightClient``. See docs/IOTBT_CURTAIN_0xC2_FINDINGS.md.
"""

from __future__ import annotations

import colorsys
import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, BinaryIO, NamedTuple

from .calibration import ColorCalibration
from .framing import MAGIC_MARKER, with_checksum
from .lz4_block import compress as lz4_compress

PRODUCT_ID = 0x00C2

CMD_QUERY = 0x0A
CMD_EFFECT = 0x0A
CMD_COMMAND = 0x0B
CMD_PLAY = 0x0A
CMD_UPLOAD = 0x0A

POWER_ON = 0x23
POWER_OFF = 0x24

MODE_INITIAL = 0x62
MODE_COLOR = 0x66
MODE_SCENE = 0x67
MODE_DIY = 0x74
MODE_NAMES = {
    MODE_INITIAL: "initial",
    MODE_COLOR: "color",
    MODE_SCENE: "scene",
    MODE_DIY: "diy",
}

# Built-in effect IDs. Effects 1 and 10 are verified on hardware. The device echoes any ID
# from 0 to 255 in its state, so the real number of effects is unknown. 100 is a
# tentative upper bound for the Home Assistant effect list.
CURTAIN_EFFECT_COUNT = 100
EFFECT_ANIMATION = "Animation (uploaded)"
EFFECT_PREFIX = "Effect "

# Play modes for `E2 09`: 0 loops all frames, 1 loops all frames (what the app sends, the
# default), 2 and above hold frame 1.
PLAY_MODE_LOOP = 0
PLAY_MODE_LOOP_APP = 1
DEFAULT_PLAY_MODE = PLAY_MODE_LOOP_APP

GRID = 20
PIXELS_PER_FRAME = GRID * GRID
BYTES_PER_FRAME = PIXELS_PER_FRAME * 2
# Product 0x0071 is a 32 x 16 net light (512 LEDs, local name IOTBT + three hex digits).
# It uses the same commands, the same column-major pixel order and the same EA 01..04 upload, with
# 32 * 16 * 2 = 1024 bytes per frame. Hardware-verified on 2026-11-19: power, effect
# and a one-frame text upload.
PRODUCT_ID_NET_71 = 0x0071
DEFAULT_GRID = (GRID, GRID)
# product ID -> (columns, rows). A column is one string; column 0 is nearest the controller.
GRIDS: dict[int, tuple[int, int]] = {
    PRODUCT_ID: DEFAULT_GRID,
    PRODUCT_ID_NET_71: (32, 16),
}


def grid_for_product(product_id: int | None) -> tuple[int, int]:
    """Return (columns, rows) for a product ID. Unknown products get 20 x 20."""
    if product_id is None:
        return DEFAULT_GRID
    return GRIDS.get(product_id, DEFAULT_GRID)


def max_upload_frames(cols: int = GRID, rows: int = GRID) -> int:
    """Frames that fit in the 102400-byte device limit (128 at 20 x 20, 100 at 32 x 16).

    The limit is hardware-verified on product 0x00C2 only.
    """
    return MAX_UPLOAD_BYTES // (cols * rows * 2)
# The device rejects a header whose total is above 102400 bytes (reply EA 01 02,
# "too big"). At 20 x 20 that is 128 frames. 128 frames (102400) is accepted and 129
# (103200) is rejected.
MAX_UPLOAD_BYTES = 102400
MAX_UPLOAD_FRAMES = MAX_UPLOAD_BYTES // BYTES_PER_FRAME
STATUS_TOO_BIG = 0x02
RGB = tuple[int, int, int]
CONTROLLER_SIDES = ("left", "right")


def _mirrored(controller_side: str, mirror: bool) -> bool:
    """Return True when image columns must be reversed (x -> 19 - x).

    The curtain has no front or back, so the controller ends up on the left or right
    depending on how it is hung. Image column x = 0 maps to the string nearest the
    controller when the controller is on the left. ``mirror`` flips the choice.
    """
    if controller_side not in CONTROLLER_SIDES:
        raise ValueError(f"controller_side must be one of {', '.join(CONTROLLER_SIDES)}")
    return (controller_side == "right") != mirror


class CurtainCommand(NamedTuple):
    """An inner payload and the command ID to put in the transport header."""

    payload: bytes
    cmd_id: int


def _check_range(name: str, value: int, low: int, high: int) -> int:
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}")
    return value


def effect_list() -> list[str]:
    """Names for the Home Assistant effect list: the uploaded animation, then Effect 1..N."""
    return [EFFECT_ANIMATION, *(f"{EFFECT_PREFIX}{i}" for i in range(1, CURTAIN_EFFECT_COUNT + 1))]


def effect_id_from_name(name: str) -> int:
    """Return the effect ID for ``"Effect <n>"``. Raises ValueError for other names."""
    if name.startswith(EFFECT_PREFIX) and name[len(EFFECT_PREFIX) :].isdigit():
        effect_id = int(name[len(EFFECT_PREFIX) :])
        if 1 <= effect_id <= CURTAIN_EFFECT_COUNT:
            return effect_id
    raise ValueError(f"unknown curtain effect: {name!r}")


def effect_name_for_state(mode: int | None, effect_id: int | None) -> str | None:
    """Return the active effect name from EA 81 mode (byte 7) and byte 8, or None.

    Mode 0x67 is a built-in effect (byte 8 is its ID). Mode 0x74 is the uploaded
    animation. Mode 0x66 (color) and the initial mode have no effect. An effect ID
    outside 1..N has no name in the list.
    """
    if mode == MODE_DIY:
        return EFFECT_ANIMATION
    if mode == MODE_SCENE and effect_id is not None and 1 <= effect_id <= CURTAIN_EFFECT_COUNT:
        return f"{EFFECT_PREFIX}{effect_id}"
    return None


def state_query() -> CurtainCommand:
    """EA 81 8A 8B, answered with a 25-byte EA 81 state notification."""
    return CurtainCommand(bytes.fromhex("ea818a8b"), CMD_QUERY)


def power(on: bool) -> CurtainCommand:
    """3B 23|24 ... 32 00 00 plus a sum8 checksum, cmdId 0x0B."""
    state = POWER_ON if on else POWER_OFF
    inner = bytes((0x3B, state, 0, 0, 0, 0, 0, 0, 0, 0x32, 0, 0))
    return CurtainCommand(with_checksum(inner), CMD_COMMAND)


def color_hsv(hue: int, saturation: int, brightness: int = 100) -> CurtainCommand:
    """3B A1 <hs_hi> <hs_lo> <bri> 00 x7 plus sum8, cmdId 0x0B.

    ``packed = (hue << 7) | saturation`` with hue 0-359 and saturation 0-100.
    The standalone 3B 01 brightness command is ignored by this device, so
    brightness is always sent together with the color.
    """
    _check_range("hue", hue, 0, 359)
    _check_range("saturation", saturation, 0, 100)
    _check_range("brightness", brightness, 0, 100)
    packed = (hue << 7) | saturation
    inner = bytes((0x3B, 0xA1, packed >> 8, packed & 0xFF, brightness, 0, 0, 0, 0, 0, 0, 0))
    return CurtainCommand(with_checksum(inner), CMD_COMMAND)


def color_rgb(
    red: int,
    green: int,
    blue: int,
    brightness: int = 100,
    calibration: ColorCalibration | None = None,
) -> CurtainCommand:
    """Convert RGB to hue/saturation, then send it like :func:`color_hsv`.

    The value component of the RGB color is ignored. ``brightness`` (0-100)
    sets the brightness. The lamp is RGB-only: white is saturation 0. An optional
    ``calibration`` adjusts the RGB color first (see :mod:`.calibration`).
    """
    _check_range("red", red, 0, 255)
    _check_range("green", green, 0, 255)
    _check_range("blue", blue, 0, 255)
    if calibration is not None:
        red, green, blue = calibration.apply(red, green, blue)
    h, s, _v = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
    return color_hsv(round(h * 360) % 360, round(s * 100), brightness)


def effect(
    effect_id: int,
    speed: int = 50,
    brightness: int = 100,
    *,
    preview: bool = False,
) -> CurtainCommand:
    """E0 02 <preview> <effect> <speed> <bright>, no checksum, cmdId 0x0A.

    Effect 1 is a whole-curtain color cycle. Effect 10 is a multi-color
    per-pixel pattern. Other IDs are untested.
    """
    _check_range("effect_id", effect_id, 0, 255)
    _check_range("speed", speed, 0, 100)
    _check_range("brightness", brightness, 0, 100)
    inner = bytes((0xE0, 0x02, 0x01 if preview else 0x00, effect_id, speed, brightness))
    return CurtainCommand(inner, CMD_EFFECT)


@dataclass(frozen=True, slots=True)
class CurtainState:
    """Decoded EA 81 state. Color and brightness are not reported by the device."""

    power: bool | None
    mode: int
    effect: int | None
    speed: int | None
    product_id: int
    led_version: int
    raw: bytes
    byte8: int = 0
    byte9: int = 0

    @property
    def mode_name(self) -> str:
        return MODE_NAMES.get(self.mode, "unknown")

    def to_dict(self) -> dict[str, Any]:
        return {
            "power": self.power,
            "mode": f"0x{self.mode:02x}",
            "mode_name": self.mode_name,
            "effect": self.effect,
            "speed": self.speed,
            "play_mode": self.byte8 if self.mode == MODE_DIY else None,
            "byte8": self.byte8,
            "byte9": self.byte9,
            "product_id": f"0x{self.product_id:04x}",
            "led_version": self.led_version,
            "raw_hex": self.raw.hex(),
        }


def extract_state_frame(packet: bytes) -> bytes | None:
    """Return the EA 81 body from a bare or transport-wrapped notification.

    Pushed notifications use ctrl 0x04 and cmd 0x15/0x16. The cmd byte is
    ignored: the body is always the state.
    """
    if packet[:2] == b"\xea\x81":
        return packet
    if len(packet) >= 10 and packet[2:4] == MAGIC_MARKER and packet[8:10] == b"\xea\x81":
        return packet[8:]
    return None


def parse_state(packet: bytes) -> CurtainState | None:
    """Decode a curtain EA 81 state, or return None if it is not one.

    - byte 6: power (0x23 on, 0x24 off)
    - byte 7: mode (0x62 initial, 0x66 after a color command, 0x67 scene, 0x74 DIY
      playback of an uploaded animation)
    - bytes 8-9: effect ID and speed in scene mode, play mode argument and speed in DIY
      mode. Both are also returned unchanged as ``byte8`` and ``byte9``.
    """
    body = extract_state_frame(packet)
    if body is None or len(body) < 10:
        return None
    power_byte = body[6]
    power_state = True if power_byte == POWER_ON else False if power_byte == POWER_OFF else None
    in_scene = body[7] == MODE_SCENE
    has_speed = body[7] in (MODE_SCENE, MODE_DIY)
    return CurtainState(
        power=power_state,
        mode=body[7],
        effect=body[8] if in_scene else None,
        speed=body[9] if has_speed else None,
        product_id=body[3] << 8 | body[4],
        led_version=body[5],
        raw=body,
        byte8=body[8],
        byte9=body[9],
    )


# ---------------------------------------------------------------------------
# Images and animations: BLE file upload (EA 01..04) and DIY playback (E2 09)
#
# Hardware-verified on an IOTBT437 (20 x 20) on 2026-10-17. The upload is stored
# in flash and survives power cycles. See docs/IOTBT_CURTAIN_0xC2_FINDINGS.md.
# ---------------------------------------------------------------------------


def pixel_hsv16(red: int, green: int, blue: int) -> int:
    """Pack an RGB color into the 16-bit HSV pixel the curtain stores.

    ``(H << 9) | (S << 5) | V`` with H = hue * 120 // 360 (7 bits), S = sat * 15 // 100
    (4 bits) and V = val * 31 // 100 (5 bits). Hue is whole degrees, saturation and
    value are whole percent. Red is ``0x01FF``, green ``0x51FF``, blue ``0xA1FF``
    and black ``0x0000``.
    """
    _check_range("red", red, 0, 255)
    _check_range("green", green, 0, 255)
    _check_range("blue", blue, 0, 255)
    h, s, v = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
    hue, sat, val = round(h * 360) % 360, round(s * 100), round(v * 100)
    hue_bits, sat_bits, val_bits = hue * 120 // 360, sat * 15 // 100, val * 31 // 100
    return ((hue_bits & 0x7F) << 9) | ((sat_bits & 0x0F) << 5) | (val_bits & 0x1F)


def pixel_index(
    x: int,
    y: int,
    *,
    controller_side: str = "left",
    mirror: bool = False,
    flip: bool = False,
    cols: int = GRID,
    rows: int = GRID,
) -> int:
    """Return the buffer index of image pixel (x, y).

    The strings hang vertically. Index = column * 20 + row. Row 0 is the TOP of a
    string and the index runs down it. Column 0 is the string nearest the controller.
    The order is not serpentine. In the image, y = 0 is the top.

    ``controller_side`` says where the controller box hangs when the image is viewed.
    With ``"left"`` (the default) image column x = 0 is the controller-side string. With
    ``"right"`` the columns are reversed (x -> 19 - x), so x = 19 is the controller-side
    string. ``mirror`` flips that choice (an alias for switching the side). ``flip`` maps
    y to 19 - y.
    """
    _check_range("x", x, 0, cols - 1)
    _check_range("y", y, 0, rows - 1)
    column = cols - 1 - x if _mirrored(controller_side, mirror) else x
    row = rows - 1 - y if flip else y
    return column * rows + row


def image_to_frame(
    pixels: Sequence[RGB],
    *,
    controller_side: str = "left",
    mirror: bool = False,
    flip: bool = False,
    cols: int = GRID,
    rows: int = GRID,
) -> list[RGB]:
    """Map row-major image pixels (index ``y * cols + x``) to buffer order.

    See :func:`pixel_index` for ``controller_side``, ``mirror`` and ``flip``.
    """
    count = cols * rows
    if len(pixels) != count:
        raise ValueError(f"an image frame needs {count} pixels, got {len(pixels)}")
    frame: list[RGB] = [(0, 0, 0)] * count
    for y in range(rows):
        for x in range(cols):
            index = pixel_index(
                x,
                y,
                controller_side=controller_side,
                mirror=mirror,
                flip=flip,
                cols=cols,
                rows=rows,
            )
            frame[index] = pixels[y * cols + x]
    return frame


def frame_to_image(
    frame: Sequence[RGB],
    *,
    controller_side: str = "left",
    mirror: bool = False,
    flip: bool = False,
    cols: int = GRID,
    rows: int = GRID,
) -> list[RGB]:
    """Invert :func:`image_to_frame`: buffer-order pixels back to row-major image pixels."""
    if len(frame) != cols * rows:
        raise ValueError(f"a frame needs {cols * rows} pixels, got {len(frame)}")
    return [
        frame[
            pixel_index(
                x,
                y,
                controller_side=controller_side,
                mirror=mirror,
                flip=flip,
                cols=cols,
                rows=rows,
            )
        ]
        for y in range(rows)
        for x in range(cols)
    ]


def render_preview_png(
    pixels: Sequence[RGB], scale: int = 10, *, cols: int = GRID, rows: int = GRID
) -> bytes:
    """Render row-major pixels as a PNG, scaled up with nearest-neighbor (200 x 200 at 20 x 20)."""
    if len(pixels) != cols * rows:
        raise ValueError(f"a preview needs {cols * rows} pixels, got {len(pixels)}")
    try:
        import io

        from PIL import Image
    except ImportError as err:
        raise RuntimeError("Pillow is required to render a preview") from err
    image = Image.frombytes("RGB", (cols, rows), bytes(c for pixel in pixels for c in pixel))
    image = image.resize((cols * scale, rows * scale), Image.Resampling.NEAREST)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def solid_frame(color: RGB, *, cols: int = GRID, rows: int = GRID) -> list[RGB]:
    """A frame with every pixel set to ``color`` (buffer order does not matter)."""
    return [color] * (cols * rows)


def frame_blob(
    pixels: Sequence[RGB],
    calibration: ColorCalibration | None = None,
    *,
    cols: int = GRID,
    rows: int = GRID,
) -> bytes:
    """Pack buffer-order pixels into a big-endian blob (800 bytes at 20 x 20).

    An optional ``calibration`` adjusts every pixel before the coarse HSV conversion.
    """
    if len(pixels) != cols * rows:
        raise ValueError(f"a frame needs {cols * rows} pixels, got {len(pixels)}")
    if calibration is None or calibration.is_identity:
        return b"".join(pixel_hsv16(*pixel).to_bytes(2, "big") for pixel in pixels)
    cache: dict[RGB, bytes] = {}
    out = bytearray()
    for pixel in pixels:
        packed = cache.get(pixel)
        if packed is None:
            packed = pixel_hsv16(*calibration.apply(*pixel)).to_bytes(2, "big")
            cache[pixel] = packed
        out += packed
    return bytes(out)


def lz4_block(blob: bytes) -> bytes:
    """Compress with a raw LZ4 block (no frame header, no size prefix)."""
    return lz4_compress(blob)


class CurtainUploadError(RuntimeError):
    """The device rejected an upload step or did not answer it."""


class UploadStep(NamedTuple):
    """One upload payload. ``acked`` steps get a device reply the caller must wait for.

    Every step of :func:`build_upload` is acked, content frames included. The reply is the
    flow control: the next step is only sent after it arrives.
    """

    name: str
    payload: bytes
    acked: bool


def upload_header(frame_count: int, *, cols: int = GRID, rows: int = GRID) -> bytes:
    """``EA 01 01 <u32 total bytes> 00 x16 <u16 frames> 00 x15`` (40 bytes).

    ``total`` is 800 * frames (20 * 20 * 2 bytes per frame), not the pixel count. The
    device answers ``EA 01 02`` if it is above 102400.
    """
    total = cols * rows * 2 * frame_count
    return (
        bytes((0xEA, 0x01, 0x01))
        + total.to_bytes(4, "big")
        + bytes(16)
        + frame_count.to_bytes(2, "big")
        + bytes(15)
    )


def upload_address(block_lengths: Sequence[int]) -> bytes:
    """``EA 02`` and per frame ``<u32 BE offset> <u16 BE compressed length>``.

    Entries are 6 bytes with NO padding. The offset is the sum of the earlier lengths.
    Using 8-byte entries (two extra zero bytes) makes the controller reboot when
    playback reaches frame 3.
    """
    address = bytearray((0xEA, 0x02))
    offset = 0
    for length in block_lengths:
        address += offset.to_bytes(4, "big") + length.to_bytes(2, "big")
        offset += length
    return bytes(address)


def build_upload(
    frames: Sequence[Sequence[RGB]],
    calibration: ColorCalibration | None = None,
    *,
    cols: int = GRID,
    rows: int = GRID,
) -> list[UploadStep]:
    """Build the header, address, content and end payloads for an upload.

    Every frame is a list of 400 buffer-order pixels and is compressed separately.
    All payloads are sent with cmdId 0x0A. At most ``MAX_UPLOAD_FRAMES`` (128) frames
    fit in the device. An optional ``calibration`` adjusts the pixel colors first.

    Every step is acked, so the sender waits for the device reply before it sends the next
    step. This is the flow control of the upload: without it a weak Bluetooth link loses
    frames silently.

    1. Header, see :func:`upload_header` (reply ``EA 01 <status>``).
    2. Address, see :func:`upload_address` (reply ``EA 02 <status>``).
    3. Content ``EA 03 <u16 index from 1> <lz4 block>`` per frame. The device answers each
       frame with ``EA 03 <u16 index> <status>``.
    4. End ``EA 04 00`` (reply ``EA 04 <status>``).
    """
    limit = max_upload_frames(cols, rows)
    if not 1 <= len(frames) <= limit:
        raise ValueError(
            f"an upload needs 1 to {limit} frames "
            f"({MAX_UPLOAD_BYTES} bytes at {cols}x{rows}), got {len(frames)}"
        )
    blocks = [
        lz4_block(frame_blob(frame, calibration, cols=cols, rows=rows)) for frame in frames
    ]
    steps = [
        UploadStep("header", upload_header(len(blocks), cols=cols, rows=rows), True),
        UploadStep("address", upload_address([len(block) for block in blocks]), True),
    ]
    for index, block in enumerate(blocks, 1):
        payload = bytes((0xEA, 0x03)) + index.to_bytes(2, "big") + block
        steps.append(UploadStep(f"content {index}", payload, True))
    steps.append(UploadStep("end", bytes((0xEA, 0x04, 0x00)), True))
    return steps


@dataclass(frozen=True, slots=True)
class UploadReply:
    """A device reply to an upload step: ``EA 01|02|04 <status>`` or ``EA 03 <idx16> <status>``."""

    step: int
    status: int
    index: int | None = None

    @property
    def ok(self) -> bool:
        return self.status == 0


def parse_upload_reply(packet: bytes) -> UploadReply | None:
    """Decode an upload acknowledgment from a bare or transport-wrapped notification.

    Replies arrive as normal notifications (ctrl 0x04, cmd 0x15). The body is the
    payload. Status 0 means ok. Anything else, including state frames, gives None
    unless it is an EA 01..04 reply.
    """
    body = packet
    if len(packet) >= 8 and packet[2:4] == MAGIC_MARKER:
        length = max(packet[6] - 1, 0)
        body = packet[8 : 8 + length]
    if len(body) < 3 or body[0] != 0xEA or body[1] not in (1, 2, 3, 4):
        return None
    step = body[1]
    if step == 3:
        if len(body) < 5:
            return None
        return UploadReply(step, body[4], int.from_bytes(body[2:4], "big"))
    return UploadReply(step, body[2])


def check_upload_reply(reply: UploadReply) -> None:
    """Raise :class:`CurtainUploadError` unless the reply status is 0 (ok)."""
    if reply.ok:
        return
    suffix = f" (frame {reply.index})" if reply.index is not None else ""
    if reply.status == STATUS_TOO_BIG:
        raise CurtainUploadError(
            f"device rejected upload step EA {reply.step:02x}{suffix}: status 0x02, "
            f"too big for device memory (at most {MAX_UPLOAD_FRAMES} frames "
            f"of 20x20, {MAX_UPLOAD_BYTES} bytes)"
        )
    raise CurtainUploadError(
        f"device rejected upload step EA {reply.step:02x}{suffix}: status {reply.status:#04x}"
    )


def play(mode: int = 1, speed: int = 50, brightness: int = 100) -> CurtainCommand:
    """E2 09 <mode> <speed 0-100> <brightness 0-100> 00, cmdId 0x0A.

    Mode 1 loops all frames at a constant rate; it is what the Surplife app sends
    (``E2 09 01 <speed> <bright> 00``). Mode 0 also loops all frames. Mode 2 and up
    hold frame 1. Speed 0-10 is about 5 s per frame,
    50 about 0.5-1 s per frame and 100 very fast. The device pushes an EA 81 state with
    mode 0x74, byte 8 = mode and byte 9 = speed. The last play command is restored at
    boot.
    """
    _check_range("mode", mode, 0, 255)
    _check_range("speed", speed, 0, 100)
    _check_range("brightness", brightness, 0, 100)
    return CurtainCommand(bytes((0xE2, 0x09, mode, speed, brightness, 0x00)), CMD_PLAY)


class ImageFrames(NamedTuple):
    frames: list[list[RGB]]  # buffer-order frames, already mapped
    total: int  # frames found in the file before truncation


def load_image_frames(
    path: str | os.PathLike[str] | BinaryIO,
    *,
    resample: str = "box",
    max_frames: int = 60,
    controller_side: str = "left",
    mirror: bool = False,
    flip: bool = False,
    count_all: bool = True,
    cols: int = GRID,
    rows: int = GRID,
) -> ImageFrames:
    """Read every frame of a PNG, JPEG, GIF or WebP file as buffer-order 20 x 20 frames.

    ``path`` is a file name or a binary file object. Frames are composited on black,
    converted to RGB and resized to 20 x 20 (stretched). ``resample`` is nearest, box or
    lanczos. The device shows every frame for the same time, so an animation frame that
    lasts N times the shortest frame duration is repeated N times. At most ``max_frames``
    frames are kept. ``controller_side``, ``mirror`` and
    ``flip`` are described in :func:`pixel_index`. With ``count_all=False`` decoding stops
    one frame after ``max_frames``, so ``total`` is then only a lower bound
    (``max_frames + 1`` means "more than ``max_frames``").
    """
    try:
        from PIL import Image, ImageSequence
    except ImportError as err:
        raise RuntimeError(
            "Pillow is required for --image: pip install 'surplife-ble[curtain]'"
        ) from err
    filters = {
        "nearest": Image.Resampling.NEAREST,
        "box": Image.Resampling.BOX,
        "lanczos": Image.Resampling.LANCZOS,
    }
    if resample not in filters:
        raise ValueError(f"resample must be one of {', '.join(filters)}")
    _mirrored(controller_side, mirror)  # validate early
    if max_frames < 1:
        raise ValueError("max_frames must be at least 1")
    frames: list[list[RGB]] = []
    total = 0
    try:
        opened = Image.open(path)
    except (OSError, ValueError) as err:  # includes UnidentifiedImageError
        raise ValueError(f"not a readable image: {err}") from err
    with opened as image:
        # The curtain shows every frame for the same time, so a frame that lasts N times
        # the shortest frame duration is repeated N times.
        sources = [(f.copy(), f.info.get("duration") or 0) for f in ImageSequence.Iterator(image)]
    known = [d for _f, d in sources if d > 0]
    base = min(known) if known else 0
    for source, duration in sources:
        repeats = max(1, round(duration / base)) if base and duration else 1
        for _ in range(repeats):
            total += 1
            if len(frames) >= max_frames:
                if count_all:
                    continue
                break
            rgba = source.convert("RGBA")
            background = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
            rgb = Image.alpha_composite(background, rgba).convert("RGB")
            small = rgb.resize((cols, rows), filters[resample])
            data = small.tobytes()
            pixels = [(data[i], data[i + 1], data[i + 2]) for i in range(0, len(data), 3)]
            frames.append(
                image_to_frame(
                    pixels,
                    controller_side=controller_side,
                    mirror=mirror,
                    flip=flip,
                    cols=cols,
                    rows=rows,
                )
            )
        if not count_all and len(frames) >= max_frames and total > max_frames:
            break
    if not frames:
        raise ValueError("the image contains no frames")
    return ImageFrames(frames, total)
