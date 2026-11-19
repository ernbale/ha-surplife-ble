"""Async BLE client with guarded probe, control, raw-write, and replay paths."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any, Protocol

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from . import curtain_c2
from .calibration import IDENTITY, ColorCalibration
from .capture import JsonlCapture
from .framing import NotificationReassembler, SequenceCounter, wrap_magichome_segments
from .models import (
    GattCharacteristic,
    GattProfile,
    GattService,
    LightState,
    ProtocolResolution,
    TrafficRecord,
    rgb_state_matches,
)
from .protocol import (
    CURTAIN_C2_CODEC,
    ProbeFrame,
    byte_to_percent,
    classic_power,
    classic_rgb,
    classic_white,
    classify_packet,
    experimental_e122_fill,
    extended_e0_rgb,
    extended_e0_white,
    extended_zone_power_off,
    frame_for_transport,
    iotbt_3b_white,
    iotbt_e1_segment_rgb,
    iotbt_power,
    original_power,
    parse_state,
    probe_frames,
)

ClientFactory = Callable[[BLEDevice], Any | Awaitable[Any]]


class BleakClientLike(Protocol):
    is_connected: bool
    services: Any

    async def connect(self) -> bool: ...
    async def disconnect(self) -> bool: ...
    async def start_notify(self, char_specifier: Any, callback: Callable[..., Any]) -> None: ...
    async def stop_notify(self, char_specifier: Any) -> None: ...
    async def write_gatt_char(
        self, char_specifier: Any, data: bytes, response: bool | None = None
    ) -> None: ...
    async def read_gatt_char(self, char_specifier: Any) -> bytearray: ...


def _uuid_is(uuid: str, short: str) -> bool:
    compact = uuid.lower().replace("-", "")
    return compact == short.lower() or compact.startswith(f"0000{short.lower()}")


class LightClient:
    """One BLE light connection and its resolved transport/protocol state."""

    def __init__(
        self,
        device: BLEDevice,
        advertisement: AdvertisementData | None = None,
        *,
        capture_path: str | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.device = device
        self.advertisement = advertisement
        self.capture = JsonlCapture(capture_path)
        self._client_factory = client_factory or BleakClient
        self._client: BleakClientLike | None = None
        self._profile: GattProfile | None = None
        self._notifications: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue()
        self._reassemblers: dict[str, NotificationReassembler] = {}
        self._notifying: set[str] = set()
        self._sequence = SequenceCounter()
        self._write_characteristic: GattCharacteristic | None = None
        self._probe_frame: ProbeFrame | None = None
        self.resolution: ProtocolResolution | None = None
        self.state: LightState | None = None
        # IOTBT curtain only: the device never reports color or brightness, so the last
        # color sent is remembered here as assumed state.
        self._curtain_rgb: tuple[int, int, int] | None = None
        self._curtain_percent: int | None = None
        # Color calibration for curtain colors and uploads (identity: no change).
        self.curtain_calibration: ColorCalibration = IDENTITY

    @property
    def connected(self) -> bool:
        return bool(self._client and self._client.is_connected)

    def set_ble_device(
        self,
        device: BLEDevice,
        advertisement: AdvertisementData | None = None,
    ) -> None:
        """Refresh the platform BLE object while preserving protocol resolution."""
        self.device = device
        self.advertisement = advertisement

    async def connect(self) -> None:
        if self.connected:
            return
        self.mark_disconnected()
        created = self._client_factory(self.device)
        self._client = await created if inspect.isawaitable(created) else created
        if not self._client.is_connected:
            await self._client.connect()
        self._profile = self._build_profile()
        self._write_characteristic = self._choose_write_characteristic(self._profile)

    def mark_disconnected(self, client: Any | None = None) -> None:
        """Clear state that belongs to the previous BLE connection."""
        if client is not None and client is not self._client:
            return
        self._notifying.clear()
        self._flush_notifications()

    async def disconnect(self) -> None:
        if self._client is None:
            return
        for uuid in tuple(self._notifying):
            with suppress(Exception):
                await self._client.stop_notify(uuid)
        self.mark_disconnected()
        if self._client.is_connected:
            await self._client.disconnect()

    async def __aenter__(self) -> LightClient:
        await self.connect()
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.disconnect()

    def _require_client(self) -> BleakClientLike:
        if self._client is None or not self._client.is_connected:
            raise ConnectionError("BLE client is not connected")
        return self._client

    def _build_profile(self) -> GattProfile:
        client = self._require_client()
        services: list[GattService] = []
        for service in client.services:
            characteristics: list[GattCharacteristic] = []
            for characteristic in service.characteristics:
                descriptors = [
                    str(descriptor.uuid).lower() for descriptor in characteristic.descriptors
                ]
                characteristics.append(
                    GattCharacteristic(
                        uuid=str(characteristic.uuid).lower(),
                        handle=int(characteristic.handle),
                        properties=sorted(str(value) for value in characteristic.properties),
                        descriptors=descriptors,
                    )
                )
            services.append(
                GattService(
                    uuid=str(service.uuid).lower(),
                    handle=int(service.handle),
                    characteristics=characteristics,
                )
            )
        return GattProfile(device_id=self.device.address, services=services)

    async def inspect_gatt(self) -> GattProfile:
        if not self.connected:
            await self.connect()
        assert self._profile is not None
        return self._profile

    @staticmethod
    def _choose_write_characteristic(profile: GattProfile) -> GattCharacteristic | None:
        writable = profile.writable
        return next((item for item in writable if _uuid_is(item.uuid, "ff01")), None) or (
            writable[0] if writable else None
        )

    async def _start_notifications(self, only: str | None = None) -> None:
        client = self._require_client()
        assert self._profile is not None
        ordered = sorted(
            self._profile.notifiable,
            key=lambda item: (not _uuid_is(item.uuid, "ff02"), item.uuid),
        )
        for characteristic in ordered:
            if characteristic.uuid in self._notifying:
                continue
            if only is not None and not _uuid_is(characteristic.uuid, only):
                continue

            def callback(sender: Any, data: bytearray, *, uuid: str = characteristic.uuid) -> None:
                sender_uuid = str(getattr(sender, "uuid", uuid)).lower()
                payload = bytes(data)
                self.capture.write(
                    TrafficRecord(
                        device_id=self.device.address,
                        direction="rx",
                        payload_hex=payload.hex(),
                        characteristic=sender_uuid,
                        note="notification",
                    )
                )
                reassembler = self._reassemblers.setdefault(sender_uuid, NotificationReassembler())
                complete = reassembler.feed(payload)
                if complete:
                    for packet in complete:
                        self._notifications.put_nowait((sender_uuid, packet))

            try:
                await client.start_notify(characteristic.uuid, callback)
            except Exception as err:
                self.capture.write(
                    TrafficRecord(
                        device_id=self.device.address,
                        direction="diagnostic",
                        payload_hex="",
                        characteristic=characteristic.uuid,
                        note=f"start_notify failed: {err}",
                    )
                )
                continue
            self._notifying.add(characteristic.uuid)

    def _flush_notifications(self) -> None:
        while not self._notifications.empty():
            with suppress(asyncio.QueueEmpty):
                self._notifications.get_nowait()
        for reassembler in self._reassemblers.values():
            reassembler.reset()

    async def _write(
        self,
        payload: bytes,
        *,
        characteristic: GattCharacteristic | None = None,
        framing: str | None = None,
        note: str | None = None,
    ) -> None:
        client = self._require_client()
        target = characteristic or self._write_characteristic
        if target is None:
            raise RuntimeError("device exposes no writable GATT characteristic")
        response = (
            "write-without-response" not in target.properties and "write" in target.properties
        )
        await client.write_gatt_char(target.uuid, payload, response=response)
        self.capture.write(
            TrafficRecord(
                device_id=self.device.address,
                direction="tx",
                payload_hex=payload.hex(),
                characteristic=target.uuid,
                framing=framing,
                note=note,
            )
        )

    async def _send_inner(
        self,
        payload: bytes,
        transport: str,
        *,
        note: str,
        characteristic: GattCharacteristic | None = None,
        command_family: int = 0x0A,
    ) -> None:
        await self._start_notifications()
        framed = frame_for_transport(
            payload,
            transport,
            self._sequence.next(),
            command_family=command_family,
        )
        await self._write(
            framed,
            characteristic=characteristic,
            framing=transport,
            note=note,
        )

    # ------------------------------------------------------------------
    # Raw-frame helpers for the `ble-rgb curtain` test commands. They skip
    # protocol resolution on purpose and only ever touch FF01 / FF02.
    # ------------------------------------------------------------------

    async def acquire_mtu(self) -> int | None:
        """Acquire the ATT MTU on BlueZ (bleak reports 23 until this is awaited).

        Returns the MTU if the backend reports one. Other backends have no
        ``_acquire_mtu`` and are left alone.
        """
        client = self._require_client()
        acquire = getattr(getattr(client, "_backend", None), "_acquire_mtu", None)
        if acquire is not None:
            with suppress(Exception):
                await acquire()
        mtu = getattr(client, "mtu_size", None)
        return int(mtu) if isinstance(mtu, int) else None

    async def subscribe_ff02(self) -> None:
        """Subscribe to FF02 only. Call before writing so no reply is missed."""
        if not self.connected:
            await self.connect()
        await self._start_notifications(only="ff02")
        if not any(_uuid_is(uuid, "ff02") for uuid in self._notifying):
            raise RuntimeError("device exposes no FF02 notify characteristic")

    def _ff01(self) -> GattCharacteristic:
        assert self._profile is not None
        target = next(
            (item for item in self._profile.writable if _uuid_is(item.uuid, "ff01")), None
        )
        if target is None:
            raise RuntimeError("device exposes no writable FF01 characteristic")
        return target

    async def send_frames(
        self,
        frames: list[bytes],
        *,
        note: str,
        gap: float = 0.02,
    ) -> None:
        """Write already-framed bytes to FF01 (never to the OTA FF11 channel)."""
        if not self.connected:
            await self.connect()
        target = self._ff01()
        for index, frame in enumerate(frames):
            await self._write(
                frame,
                characteristic=target,
                framing="magichome2",
                note=f"{note} [{index + 1}/{len(frames)}]",
            )
            if gap and index + 1 < len(frames):
                await asyncio.sleep(gap)

    def next_sequence(self) -> int:
        return self._sequence.next()

    def flush_notifications(self) -> None:
        self._flush_notifications()

    async def wait_notification(self, wait_seconds: float) -> bytes | None:
        """Return the next complete notification packet, or None after ``wait_seconds``."""
        try:
            _uuid, packet = await asyncio.wait_for(
                self._notifications.get(), timeout=wait_seconds
            )
        except TimeoutError:
            return None
        return packet

    async def _read_candidates(self) -> list[tuple[str, bytes]]:
        client = self._require_client()
        assert self._profile is not None
        packets: list[tuple[str, bytes]] = []
        for service in self._profile.services:
            for characteristic in service.characteristics:
                if "read" not in characteristic.properties:
                    continue
                with suppress(Exception):
                    data = bytes(await client.read_gatt_char(characteristic.uuid))
                    if data:
                        packets.append((characteristic.uuid, data))
                        self.capture.write(
                            TrafficRecord(
                                device_id=self.device.address,
                                direction="rx",
                                payload_hex=data.hex(),
                                characteristic=characteristic.uuid,
                                note="read fallback",
                            )
                        )
        return packets

    async def _await_classification(
        self,
        wait_seconds: float,
        *,
        allow_reads: bool = True,
    ) -> tuple[ProtocolResolution, LightState | None] | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait_seconds
        while (remaining := deadline - loop.time()) > 0:
            try:
                _characteristic, packet = await asyncio.wait_for(
                    self._notifications.get(), timeout=remaining
                )
            except TimeoutError:
                break
            classified = classify_packet(packet)
            if classified:
                resolution, _inner, framing = classified
                resolution.notes.append(f"Response interpretation: {framing}")
                return resolution, parse_state(packet)
        if allow_reads:
            for _characteristic, packet in await self._read_candidates():
                classified = classify_packet(packet)
                if classified:
                    resolution, _inner, framing = classified
                    resolution.notes.append(f"Read interpretation: {framing}")
                    return resolution, parse_state(packet)
        return None

    async def probe(
        self,
        *,
        allow_writes: bool,
        response_timeout: float = 1.25,
    ) -> ProtocolResolution | None:
        """Send known state queries and require a repeatable response for control."""
        if not allow_writes:
            raise PermissionError("probing requires allow_writes=True")
        if not self.connected:
            await self.connect()
        await self._start_notifications()
        best: tuple[ProtocolResolution, LightState | None, ProbeFrame] | None = None
        assert self._profile is not None
        write_targets = sorted(
            self._profile.writable,
            key=lambda item: (not _uuid_is(item.uuid, "ff01"), item.uuid),
        )
        for write_target in write_targets:
            for candidate in probe_frames():
                self._flush_notifications()
                try:
                    await self._send_inner(
                        candidate.payload,
                        candidate.transport,
                        note=candidate.name,
                        characteristic=write_target,
                    )
                except Exception as err:
                    self.capture.write(
                        TrafficRecord(
                            device_id=self.device.address,
                            direction="diagnostic",
                            payload_hex=candidate.payload.hex(),
                            characteristic=write_target.uuid,
                            framing=candidate.transport,
                            note=f"probe write failed: {err}",
                        )
                    )
                    continue
                first = await self._await_classification(response_timeout)
                if first is None:
                    continue
                resolution, state = first
                resolution.notes.append(f"Probe candidate: {candidate.name}")
                resolution.notes.append(f"Write characteristic: {write_target.uuid}")
                best = (resolution, state, candidate)

                self._flush_notifications()
                await self._send_inner(
                    candidate.payload,
                    candidate.transport,
                    note=f"{candidate.name}:confirmation",
                    characteristic=write_target,
                )
                confirmation = await self._await_classification(response_timeout)
                if confirmation:
                    confirmed_resolution, confirmed_state = confirmation
                    same_identity = (
                        confirmed_resolution.frame_family == resolution.frame_family
                        and confirmed_resolution.model_num == resolution.model_num
                    )
                    if same_identity:
                        resolution.repeatable = True
                        resolution.transport = candidate.transport
                        resolution.confidence = 1.0
                        resolution.notes.append(
                            "State response repeated with the same frame family/model."
                        )
                        self.resolution = resolution
                        self.state = confirmed_state or state
                        self._probe_frame = candidate
                        self._write_characteristic = write_target
                        self.capture.write(
                            {
                                "timestamp": TrafficRecord(
                                    self.device.address, "diagnostic", ""
                                ).timestamp,
                                "device_id": self.device.address,
                                "direction": "resolution",
                                **resolution.to_dict(),
                            }
                        )
                        return resolution
        if best:
            self.resolution, self.state, self._probe_frame = best
            self.resolution.transport = self._probe_frame.transport
            self.resolution.notes.append("A matching response was seen once but not confirmed.")
            return self.resolution
        return None

    async def query_state(
        self,
        *,
        response_timeout: float = 1.5,
        allow_reads: bool = True,
    ) -> LightState | None:
        """Refresh state with the resolved query path, probing when necessary."""
        if not self.connected:
            await self.connect()
        if self._probe_frame is None:
            await self.probe(allow_writes=True)
            return self.state
        await self._start_notifications()
        self._flush_notifications()
        await self._send_inner(
            self._probe_frame.payload,
            self._probe_frame.transport,
            note="state refresh",
        )
        result = await self._await_classification(
            response_timeout,
            allow_reads=allow_reads,
        )
        if result is None:
            return None
        resolution, state = result
        resolution.repeatable = bool(self.resolution and self.resolution.repeatable)
        resolution.transport = self.resolution.transport if self.resolution else None
        self.resolution = resolution
        self.state = state
        return state

    async def query_raw_state(self) -> bytes | None:
        """Query and return the raw state packet bytes, or None if no response."""
        state = await self.query_state()
        if state is not None and state.raw_hex:
            return bytes.fromhex(state.raw_hex)
        return None

    def _require_control_resolution(self) -> tuple[ProtocolResolution, ProbeFrame]:
        if self.resolution is None or self._probe_frame is None or not self.resolution.repeatable:
            raise RuntimeError("control requires a repeatable state response from this connection")
        if self.resolution.codec == "unresolved-ea81":
            raise RuntimeError(
                "control remains locked until the IOTBT Telink or segment "
                "command family is resolved"
            )
        return self.resolution, self._probe_frame

    async def set_power(self, turn_on: bool) -> None:
        resolution, probe = self._require_control_resolution()
        if resolution.codec.startswith("classic"):
            await self._send_inner(classic_power(turn_on), probe.transport, note="power")
        elif resolution.codec == "original-ledenet":
            await self._send_inner(original_power(turn_on), probe.transport, note="power")
        elif resolution.codec == "iotbt-ea81":
            await self._send_inner(iotbt_power(turn_on), probe.transport, note="power")
        elif resolution.codec == CURTAIN_C2_CODEC:
            await self._send_curtain(curtain_c2.power(turn_on), "curtain power")
        elif turn_on:
            brightness = (
                byte_to_percent(self.state.brightness)
                if self.state and self.state.brightness
                else 100
            )
            await self._send_inner(extended_e0_white(brightness), probe.transport, note="power on")
        else:
            for zone in (0x24, 0x23):
                await self._send_inner(
                    extended_zone_power_off(zone), probe.transport, note=f"power off zone {zone:#x}"
                )
                await asyncio.sleep(0.05)
        if self.state is None:
            self.state = LightState()
        self.state.power = turn_on
        self.state.assumed = True

    async def set_rgb(
        self,
        red: int,
        green: int,
        blue: int,
        *,
        brightness: int = 100,
        experimental_e122: bool = False,
    ) -> None:
        resolution, probe = self._require_control_resolution()
        brightness = max(1, min(100, brightness))
        if resolution.codec.startswith("classic"):
            scale = brightness / 100
            payload = classic_rgb(
                round(red * scale),
                round(green * scale),
                round(blue * scale),
                nine_byte=resolution.codec == "classic-9byte",
            )
            await self._send_inner(payload, probe.transport, note="set rgb")
        elif resolution.codec == CURTAIN_C2_CODEC:
            await self._set_curtain_rgb(red, green, blue, brightness)
            return
        elif resolution.codec == "iotbt-ea81":
            payload = iotbt_e1_segment_rgb(red, green, blue, brightness)
            expected_brightness = round(brightness * 255 / 100)
            self._flush_notifications()
            await self._send_inner(
                payload,
                probe.transport,
                note="set rgb e1 03",
                command_family=0x0B,
            )
            self.state = LightState(
                power=True,
                rgb=(red, green, blue),
                brightness=expected_brightness,
                white=0,
                model_num=resolution.model_num,
                firmware_version=resolution.firmware_version,
                assumed=True,
            )
            await self._confirm_rgb_state((red, green, blue), expected_brightness)
            return
        elif experimental_e122:
            if "candidate-e122" not in resolution.capabilities:
                raise RuntimeError("E1 22 is only enabled for a matching extended candidate")
            scale = brightness / 100
            payload = experimental_e122_fill(
                round(red * scale), round(green * scale), round(blue * scale)
            )
            await self._send_inner(payload, probe.transport, note="set rgb")
        else:
            payload = extended_e0_rgb(red, green, blue, brightness)
            await self._send_inner(payload, probe.transport, note="set rgb")
        self.state = LightState(
            power=True,
            rgb=(red, green, blue),
            brightness=round(brightness * 255 / 100),
            white=0,
            model_num=resolution.model_num,
            firmware_version=resolution.firmware_version,
            assumed=True,
        )

    async def _confirm_rgb_state(
        self,
        expected_rgb: tuple[int, int, int],
        expected_brightness: int,
    ) -> None:
        """Complete the state round trip required between segment writes."""
        optimistic = self.state
        result = await self._await_classification(0.15, allow_reads=False)
        if result is not None:
            resolution, confirmed = result
            resolution.repeatable = bool(self.resolution and self.resolution.repeatable)
            resolution.transport = self.resolution.transport if self.resolution else None
            self.resolution = resolution
            if confirmed is not None and rgb_state_matches(
                confirmed, expected_rgb, expected_brightness
            ):
                confirmed.assumed = False
                self.state = confirmed
                return
        for attempt in range(2):
            confirmed = await self.query_state(response_timeout=0.75, allow_reads=False)
            if confirmed is None:
                break
            if rgb_state_matches(confirmed, expected_rgb, expected_brightness):
                confirmed.assumed = False
                self.state = confirmed
                return
            if attempt == 0:
                await asyncio.sleep(0.15)
        self.state = optimistic

    async def set_white(
        self,
        brightness: int,
        *,
        experimental_e122: bool = False,
    ) -> None:
        resolution, probe = self._require_control_resolution()
        if resolution.codec == CURTAIN_C2_CODEC:
            raise RuntimeError("the IOTBT curtain is RGB-only and has no white channel")
        brightness = max(1, min(100, brightness))
        white_byte = round(brightness * 255 / 100)
        if resolution.codec.startswith("classic"):
            payload = classic_white(
                white_byte,
                nine_byte=resolution.codec == "classic-9byte",
            )
            await self._send_inner(payload, probe.transport, note="set white")
        elif resolution.codec == "iotbt-ea81":
            payload = iotbt_3b_white(brightness)
            await self._send_inner(payload, probe.transport, note="set white")
        elif experimental_e122:
            if "candidate-e122" not in resolution.capabilities:
                raise RuntimeError("E1 22 is only enabled for a matching extended candidate")
            payload = experimental_e122_fill(0, 0, 0, white=white_byte)
            await self._send_inner(payload, probe.transport, note="set white")
        else:
            payload = extended_e0_white(brightness)
            await self._send_inner(payload, probe.transport, note="set white")
        self.state = LightState(
            power=True,
            rgb=(0, 0, 0),
            brightness=white_byte,
            white=white_byte,
            model_num=resolution.model_num,
            firmware_version=resolution.firmware_version,
            assumed=True,
        )

    async def set_brightness(self, brightness: int) -> None:
        brightness = max(1, min(100, brightness))
        if self.resolution and self.resolution.codec == CURTAIN_C2_CODEC:
            await self._set_curtain_brightness(brightness)
            return
        if self.resolution and self.resolution.codec == "iotbt-ea81":
            # The 3B 01 standalone brightness command is not accepted by this
            # device. Re-send the current color or white command with the new
            # brightness, which is what the official app does.
            if self.state and self.state.white:
                await self.set_white(brightness)
            else:
                rgb = self.state.rgb if self.state and self.state.rgb else (255, 255, 255)
                await self.set_rgb(*rgb, brightness=brightness)
            return
        if self.state and self.state.white:
            await self.set_white(brightness)
            return
        rgb = self.state.rgb if self.state and self.state.rgb else (255, 255, 255)
        await self.set_rgb(*rgb, brightness=brightness)

    # ------------------------------------------------------------------
    # IOTBT curtain (product 0xC2). All frames go to FF01 as MagicHome2 transport frames.
    # ------------------------------------------------------------------

    @property
    def is_curtain(self) -> bool:
        return bool(self.resolution and self.resolution.codec == CURTAIN_C2_CODEC)

    @property
    def curtain_grid(self) -> tuple[int, int]:
        """(columns, rows) of the resolved curtain or net: 20 x 20, or 32 x 16 for 0x0071."""
        if not self.resolution or not self.resolution.source_packet_hex:
            return curtain_c2.DEFAULT_GRID
        state = curtain_c2.parse_state(bytes.fromhex(self.resolution.source_packet_hex))
        return curtain_c2.grid_for_product(state.product_id if state else None)

    @property
    def curtain_rgb(self) -> tuple[int, int, int] | None:
        """The last color sent, or None. The device never reports it (assumed state)."""
        return self._curtain_rgb

    @property
    def curtain_percent(self) -> int | None:
        """The last brightness percent sent, or None. The device never reports it."""
        return self._curtain_percent

    def _require_curtain(self) -> None:
        if not self.is_curtain:
            raise RuntimeError("this device is not an IOTBT curtain (product 0xC2)")
        if not self.resolution or not self.resolution.repeatable:
            raise RuntimeError("control requires a repeatable state response from this connection")

    async def _ensure_ff02(self) -> None:
        if not any(_uuid_is(uuid, "ff02") for uuid in self._notifying):
            await self._start_notifications(only="ff02")

    async def _send_curtain(self, command: curtain_c2.CurtainCommand, note: str) -> None:
        """Frame a verified curtain command (segmented if long) and write it to FF01."""
        await self._ensure_ff02()
        frames = wrap_magichome_segments(
            command.payload, self._sequence.next(), command_family=command.cmd_id
        )
        await self.send_frames(frames, note=note)

    async def _curtain_ensure_on(self) -> None:
        """Send power on first if the last known state is off."""
        if self.state is not None and self.state.power is False:
            await self._send_curtain(curtain_c2.power(True), "curtain power on")
            await asyncio.sleep(0.15)

    async def _set_curtain_rgb(self, red: int, green: int, blue: int, brightness: int) -> None:
        command = curtain_c2.color_rgb(
            red, green, blue, brightness, calibration=self.curtain_calibration
        )
        await self._curtain_ensure_on()
        await self._send_curtain(command, "curtain color")
        self._curtain_rgb = (red, green, blue)
        self._curtain_percent = brightness
        self.state = LightState(
            power=True,
            rgb=(red, green, blue),
            brightness=round(brightness * 255 / 100),
            white=0,
            assumed=True,
            mode=curtain_c2.MODE_COLOR,
        )

    async def _set_curtain_brightness(self, brightness: int) -> None:
        """Brightness is part of every command: resend the active color, effect or animation."""
        state = self.state
        if state is not None and state.mode == curtain_c2.MODE_SCENE and state.effect:
            await self.set_effect(state.effect, state.speed or 50, brightness)
        elif state is not None and state.mode == curtain_c2.MODE_DIY:
            play_mode = state.play_mode
            if play_mode is None:
                play_mode = curtain_c2.DEFAULT_PLAY_MODE
            await self.play_animation(play_mode, state.speed or 50, brightness)
        else:
            red, green, blue = self._curtain_rgb or (255, 255, 255)
            await self._set_curtain_rgb(red, green, blue, brightness)

    async def set_effect(self, effect_id: int, speed: int = 50, brightness: int = 100) -> None:
        """Start a built-in curtain effect (``E0 02``). Effects 1 and 10 are verified."""
        self._require_curtain()
        speed = max(1, min(100, speed))
        brightness = max(1, min(100, brightness))
        command = curtain_c2.effect(effect_id, speed, brightness)
        await self._curtain_ensure_on()
        await self._send_curtain(command, "curtain effect")
        self._curtain_percent = brightness
        self.state = LightState(
            power=True,
            brightness=round(brightness * 255 / 100),
            assumed=True,
            mode=curtain_c2.MODE_SCENE,
            effect=effect_id,
            speed=speed,
        )

    async def play_animation(
        self,
        mode: int = curtain_c2.DEFAULT_PLAY_MODE,
        speed: int = 50,
        brightness: int = 100,
    ) -> None:
        """Play the uploaded animation (``E2 09``): mode 0 and 1 loop, 2 and up hold frame 1."""
        self._require_curtain()
        speed = max(1, min(100, speed))
        brightness = max(1, min(100, brightness))
        command = curtain_c2.play(mode, speed, brightness)
        await self._curtain_ensure_on()
        await self._send_curtain(command, "curtain play")
        self._curtain_percent = brightness
        self.state = LightState(
            power=True,
            brightness=round(brightness * 255 / 100),
            assumed=True,
            mode=curtain_c2.MODE_DIY,
            play_mode=mode,
            speed=speed,
        )

    async def upload_steps(
        self,
        steps: list[curtain_c2.UploadStep],
        *,
        ack_timeout: float = 4.0,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        """Send prepared upload steps (``EA 01``..``EA 04``) and check the device replies.

        This writes the animation to the device flash. It does not check the codec: the
        caller must know the device is an IOTBT curtain.

        An acked step is not followed by the next one until its reply arrives. For a
        content frame that is ``EA 03 <u16 index> <status>`` with the index of the frame
        just sent, so the device is never sent more than one frame at a time. Raises
        :class:`curtain_c2.CurtainUploadError` if an acked step gets no matching reply
        within ``ack_timeout`` seconds or any reply has a non-zero status (status 2 means
        the upload is too big for the device).
        """
        report = progress or (lambda _line: None)
        await self._ensure_ff02()
        self._flush_notifications()
        for step in steps:
            segments = wrap_magichome_segments(
                step.payload, self._sequence.next(), command_family=curtain_c2.CMD_UPLOAD
            )
            preview = step.payload[:16].hex() + ("..." if len(step.payload) > 16 else "")
            report(f"{step.name}: {len(step.payload)} B in {len(segments)} frame(s) {preview}")
            await self.send_frames(segments, note=f"curtain upload {step.name}")
            if step.acked:
                await self._wait_upload_ack(step, ack_timeout, report)
            else:
                await self._drain_upload_replies(0.05, report)

    async def upload_frames(
        self,
        frames: list[list[tuple[int, int, int]]],
        *,
        ack_timeout: float = 4.0,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        """Upload buffer-order frames to the device flash (at most 128 at 20 x 20).

        The frames must match :attr:`curtain_grid`. The color calibration of this client
        is applied to every pixel.
        """
        cols, rows = self.curtain_grid
        steps = curtain_c2.build_upload(frames, self.curtain_calibration, cols=cols, rows=rows)
        await self.upload_steps(steps, ack_timeout=ack_timeout, progress=progress)

    async def upload_curtain_animation(
        self,
        frames: list[list[tuple[int, int, int]]],
        *,
        mode: int = curtain_c2.DEFAULT_PLAY_MODE,
        speed: int = 50,
        brightness: int = 100,
        ack_timeout: float = 4.0,
    ) -> None:
        """Upload frames to flash, then play them. For a resolved curtain only."""
        self._require_curtain()
        await self.upload_frames(frames, ack_timeout=ack_timeout)
        await self.play_animation(mode, speed, brightness)

    async def _drain_upload_replies(
        self, wait_seconds: float, report: Callable[[str], None]
    ) -> None:
        while (packet := await self.wait_notification(wait_seconds)) is not None:
            reply = curtain_c2.parse_upload_reply(packet)
            if reply is not None:
                curtain_c2.check_upload_reply(reply)
                report(f"  reply: EA {reply.step:02x} status {reply.status:#04x}")

    async def _wait_upload_ack(
        self,
        step: curtain_c2.UploadStep,
        wait_seconds: float,
        report: Callable[[str], None],
    ) -> None:
        """Wait for the reply to ``step``: ``EA <step> <status>``, or ``EA 03 <index> <status>``.

        A reply for another content frame does not count as the ack: it is logged and the
        wait continues until the deadline. A non-zero status in any reply is an error.
        """
        expected = step.payload[1]
        expected_index = int.from_bytes(step.payload[2:4], "big") if expected == 3 else None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + wait_seconds
        while (remaining := deadline - loop.time()) > 0:
            packet = await self.wait_notification(remaining)
            if packet is None:
                break
            reply = curtain_c2.parse_upload_reply(packet)
            if reply is None:
                continue
            curtain_c2.check_upload_reply(reply)
            if reply.step == expected and reply.index == expected_index:
                report(f"  reply: EA {reply.step:02x} status {reply.status:#04x}")
                return
            report(
                f"  ignoring reply EA {reply.step:02x}"
                + (f" for frame {reply.index}" if reply.index is not None else "")
                + f" while waiting for '{step.name}'"
            )
        raise curtain_c2.CurtainUploadError(
            f"no reply to upload step '{step.name}' within {wait_seconds:g}s"
        )

    async def raw_write(
        self,
        characteristic_uuid: str,
        payload: bytes,
        *,
        allow_raw_write: bool,
    ) -> None:
        if not allow_raw_write:
            raise PermissionError("raw writes require allow_raw_write=True")
        if not 1 <= len(payload) <= 512:
            raise ValueError("raw payload must contain 1 to 512 bytes")
        profile = await self.inspect_gatt()
        normalized_uuid = characteristic_uuid.casefold()
        target = next(
            (item for item in profile.writable if item.uuid.casefold() == normalized_uuid),
            None,
        )
        if target is None:
            raise ValueError("the selected characteristic is not writable")
        await self._write(payload, characteristic=target, framing="raw", note="explicit raw write")

    async def replay(
        self,
        records: list[TrafficRecord],
        *,
        allow_raw_write: bool,
        delay: float = 0.05,
    ) -> None:
        """Replay reviewed TX records through their exact characteristics."""
        if not allow_raw_write:
            raise PermissionError("replay requires allow_raw_write=True")
        if delay < 0:
            raise ValueError("replay delay cannot be negative")
        profile = await self.inspect_gatt()
        writable_uuids = {char.uuid.casefold() for char in profile.writable}
        for index, record in enumerate(records, 1):
            if not record.characteristic:
                raise ValueError(
                    f"record {index}: every replay TX record must name a characteristic"
                )
            if record.characteristic.casefold() not in writable_uuids:
                raise ValueError(
                    f"record {index}: characteristic {record.characteristic} "
                    "is not writable on this device"
                )
            bytes.fromhex(record.payload_hex)
        for record in records:
            await self.raw_write(
                record.characteristic,
                bytes.fromhex(record.payload_hex),
                allow_raw_write=True,
            )
            if delay:
                await asyncio.sleep(delay)
