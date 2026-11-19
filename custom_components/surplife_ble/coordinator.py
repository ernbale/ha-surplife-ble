"""Bluetooth connection and state coordination for Surplife BLE."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CALIBRATION_OPTIONS, CONF_CONTROLLER_SIDE, CONF_FLIP, UPDATE_INTERVAL
from .core import curtain_c2
from .core import text as text_render
from .core.calibration import IDENTITY, CalibrationError, ColorCalibration
from .core.client import LightClient
from .core.models import LightState, apply_assumed_rgb, rgb_state_matches

_LOGGER = logging.getLogger(__name__)
_ASSUMED_RGB_SECONDS = 5.0
_CONFIRMATION_DELAY_SECONDS = 0.3


@dataclass(slots=True)
class SurplifeRuntimeData:
    """Runtime data stored on the config entry."""

    coordinator: SurplifeCoordinator


class SurplifeCoordinator(DataUpdateCoordinator[LightState]):
    """Manage the resolved client and expose normalized state."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=UPDATE_INTERVAL,
            # BLE devices can't handle concurrent commands — serialize per device
            always_update=False,
        )
        self.address: str = entry.data[CONF_ADDRESS]
        self.client: LightClient | None = None
        self._ble_device: BLEDevice | None = None
        self._advertisement: AdvertisementData | None = None
        self._was_available: bool = False
        self._operation_lock = asyncio.Lock()
        self._assumed_rgb: tuple[int, int, int] | None = None
        self._assumed_rgb_brightness: int | None = None
        self._assumed_rgb_deadline: float | None = None
        self._confirmation_generation = 0
        self._calibration = self._load_calibration()
        self._controller_side, self._flip = self._load_orientation()
        # IOTBT curtain only: kept in memory for the Screen entities.
        self.animation_title: str | None = None
        self.preview_png: bytes | None = None
        self.preview_updated: datetime | None = None
        self._last_animation_speed: int = 50

    @property
    def calibration(self) -> ColorCalibration:
        """The curtain color calibration from the entry options (identity if unset)."""
        return self._calibration

    def _load_calibration(self) -> ColorCalibration:
        options = {
            key: value
            for key, value in dict(self.config_entry.options).items()
            if key in CALIBRATION_OPTIONS
        }
        try:
            return ColorCalibration.from_dict(options)
        except CalibrationError as err:
            _LOGGER.warning("Ignoring invalid color calibration options: %s", err)
            return IDENTITY

    @property
    def controller_side(self) -> str:
        """Which side of the picture the controller box hangs on: ``left`` or ``right``."""
        return self._controller_side

    @property
    def flip(self) -> bool:
        """True when the curtain hangs upside down (swap top and bottom)."""
        return self._flip

    def _load_orientation(self) -> tuple[str, bool]:
        options = self.config_entry.options
        side = options.get(CONF_CONTROLLER_SIDE, "left")
        if side not in curtain_c2.CONTROLLER_SIDES:
            _LOGGER.warning("Ignoring invalid controller side option %r", side)
            side = "left"
        return side, bool(options.get(CONF_FLIP, False))

    def async_update_options(self) -> None:
        """Apply changed options (calibration and orientation) without reconnecting."""
        self._calibration = self._load_calibration()
        self._controller_side, self._flip = self._load_orientation()
        if self.client is not None:
            self.client.curtain_calibration = self._calibration

    def async_set_ble_device(
        self, device: BLEDevice, advertisement: AdvertisementData | None
    ) -> None:
        """Refresh the nearest-adapter BLEDevice from Home Assistant's cache."""
        self._ble_device = device
        self._advertisement = advertisement
        if self.client:
            self.client.set_ble_device(device, advertisement)

    def _current_ble_device(self, fallback: BLEDevice | None = None) -> BLEDevice | None:
        return (
            bluetooth.async_ble_device_from_address(
                self.hass,
                self.address.upper(),
                True,
            )
            or self._ble_device
            or fallback
        )

    async def _async_client_factory(self, device: BLEDevice) -> BleakClientWithServiceCache:
        """Use Home Assistant's retrying connection helper and service cache."""
        return await establish_connection(
            BleakClientWithServiceCache,
            device,
            self.config_entry.title,
            lambda disconnected: (
                self.client.mark_disconnected(disconnected) if self.client else None
            ),
            use_services_cache=True,
            ble_device_callback=lambda: self._current_ble_device(device) or device,
        )

    async def _async_get_client(self) -> LightClient:
        if current_device := self._current_ble_device():
            self._ble_device = current_device
        if self._ble_device is None:
            raise UpdateFailed(f"Bluetooth device {self.address} is not currently reachable")
        if self.client is None:
            self.client = LightClient(
                self._ble_device,
                self._advertisement,
                client_factory=self._async_client_factory,
            )
        else:
            self.client.set_ble_device(self._ble_device, self._advertisement)
        self.client.curtain_calibration = self.calibration
        await self.client.connect()
        return self.client

    def _clear_assumed_rgb(self) -> None:
        self._assumed_rgb = None
        self._assumed_rgb_brightness = None
        self._assumed_rgb_deadline = None

    def _reconcile_assumed_rgb(self, state: LightState) -> LightState:
        if self._assumed_rgb is None or self._assumed_rgb_brightness is None:
            state.assumed = False
            return state
        if rgb_state_matches(state, self._assumed_rgb, self._assumed_rgb_brightness):
            self._clear_assumed_rgb()
            state.assumed = False
            return state
        deadline = self._assumed_rgb_deadline
        if deadline is None or asyncio.get_running_loop().time() >= deadline:
            self._clear_assumed_rgb()
            state.assumed = False
            return state
        return apply_assumed_rgb(
            state,
            self._assumed_rgb,
            self._assumed_rgb_brightness,
        )

    @property
    def is_curtain(self) -> bool:
        """True once the connected device is resolved as an IOTBT curtain (product 0xC2)."""
        return bool(self.client and self.client.is_curtain)

    @property
    def curtain_grid(self) -> tuple[int, int]:
        """(columns, rows) of the connected curtain or net. 20 x 20 until it is resolved."""
        return self.client.curtain_grid if self.client else curtain_c2.DEFAULT_GRID

    def _apply_curtain_assumed(self, state: LightState) -> LightState:
        """Add the color and brightness the curtain never reports.

        The last command sent is used: brightness always, and the color only while the
        device reports color mode. Effects and animations carry no color.
        """
        client = self.client
        if client is None or not client.is_curtain:
            return state
        if state.mode == curtain_c2.MODE_DIY and state.speed:
            self._last_animation_speed = state.speed
        percent = client.curtain_percent
        if percent is not None:
            state.brightness = round(percent * 255 / 100)
            state.assumed = True
        if (
            state.mode == curtain_c2.MODE_COLOR
            and client.curtain_rgb is not None
            and percent is not None
        ):
            state.rgb = client.curtain_rgb
            state.white = 0
        return state

    async def _refresh_after_assumed_deadline(self, deadline: float) -> None:
        await asyncio.sleep(max(0, deadline - asyncio.get_running_loop().time()))
        if self._assumed_rgb_deadline == deadline:
            await self.async_request_refresh()

    async def _refresh_after_command(self, generation: int) -> None:
        await asyncio.sleep(_CONFIRMATION_DELAY_SECONDS)
        if self._confirmation_generation == generation:
            await self.async_request_refresh()

    def _request_confirmation(self) -> None:
        self._confirmation_generation += 1
        self.hass.async_create_task(self._refresh_after_command(self._confirmation_generation))
        if self._assumed_rgb_deadline is not None:
            self.hass.async_create_task(
                self._refresh_after_assumed_deadline(self._assumed_rgb_deadline)
            )

    async def _async_update_data(self) -> LightState:
        try:
            async with self._operation_lock:
                client = await self._async_get_client()
                state = await client.query_state()
                if state is None:
                    raise UpdateFailed("device did not return a supported state frame")
                if not client.resolution or not client.resolution.repeatable:
                    raise UpdateFailed("device state response could not be repeated")
                state = self._reconcile_assumed_rgb(state)
                state = self._apply_curtain_assumed(state)
                if not self._was_available:
                    _LOGGER.info("Surplife BLE device %s is now available", self.address)
                    self._was_available = True
                return state
        except UpdateFailed:
            if self._was_available:
                _LOGGER.warning("Surplife BLE device %s is unavailable", self.address)
                self._was_available = False
            # Do not disconnect on transient errors. The bleak_retry_connector
            # will reconnect on the next attempt. Disconnecting here forces a
            # full reconnect (discover, subscribe, probe) on every poll failure,
            # which makes commands slow.
            raise
        except Exception as err:
            if self._was_available:
                _LOGGER.warning("Surplife BLE device %s is unavailable: %s", self.address, err)
                self._was_available = False
            # Do not disconnect on transient errors. Let the next poll or
            # command retry with the existing connection state.
            raise UpdateFailed(str(err)) from err

    async def _async_command(self, method: str, *args: Any, **kwargs: Any) -> LightState:
        async with self._operation_lock:
            try:
                client = await self._async_get_client()
                if not client.resolution or not client.resolution.repeatable:
                    await client.query_state()
                command = getattr(client, method)
                await command(*args, **kwargs)
            except (BleakError, TimeoutError, OSError) as err:
                _LOGGER.debug("Command %s failed, retrying: %s", method, err)
                if self.client:
                    with suppress(Exception):
                        await self.client.disconnect()
                client = await self._async_get_client()
                if not client.resolution or not client.resolution.repeatable:
                    await client.query_state()
                command = getattr(client, method)
                await command(*args, **kwargs)
            assert client.state is not None
            self.async_set_updated_data(client.state)
            return client.state

    async def async_set_power(self, turn_on: bool) -> None:
        await self._async_command("set_power", turn_on)

    async def async_set_rgb(self, rgb: tuple[int, int, int], brightness: int | None) -> None:
        if brightness is None:
            brightness = 255
        state = await self._async_command(
            "set_rgb", *rgb, brightness=max(1, round(brightness / 255 * 100))
        )
        if self.is_curtain:
            self._request_confirmation()
            return
        if state.assumed and state.rgb is not None and state.brightness is not None:
            self._assumed_rgb = state.rgb
            self._assumed_rgb_brightness = state.brightness
            self._assumed_rgb_deadline = asyncio.get_running_loop().time() + _ASSUMED_RGB_SECONDS
            self._request_confirmation()
        else:
            self._clear_assumed_rgb()

    async def async_set_white(self, brightness: int | None) -> None:
        if brightness is None:
            brightness = 255
        await self._async_command("set_white", max(1, round(brightness / 255 * 100)))
        self._clear_assumed_rgb()
        self._request_confirmation()

    async def async_set_brightness(self, brightness: int | None) -> None:
        if brightness is None:
            brightness = 255
        state = await self._async_command("set_brightness", max(1, round(brightness / 255 * 100)))
        if self.is_curtain:
            self._request_confirmation()
            return
        if state.assumed:
            if not state.white and state.rgb is not None and state.brightness is not None:
                self._assumed_rgb = state.rgb
                self._assumed_rgb_brightness = state.brightness
                self._assumed_rgb_deadline = (
                    asyncio.get_running_loop().time() + _ASSUMED_RGB_SECONDS
                )
            else:
                self._clear_assumed_rgb()
            self._request_confirmation()
        else:
            self._clear_assumed_rgb()

    def _curtain_speed(self) -> int:
        """Reuse the speed the device reports for an effect or animation, else 50."""
        state = self.data
        if state is not None and state.speed:
            return max(1, min(100, state.speed))
        return 50

    def curtain_percent(self, brightness_percent: int | None = None) -> int:
        """Use ``brightness_percent``, else the last brightness sent, else full."""
        if brightness_percent is not None:
            return max(1, min(100, brightness_percent))
        client = self.client
        return client.curtain_percent if client and client.curtain_percent else 100

    def _curtain_play_mode(self) -> int:
        """Keep the play mode the device reports while an animation plays, else mode 1."""
        state = self.data
        if state is not None and state.mode == curtain_c2.MODE_DIY and state.play_mode is not None:
            return state.play_mode
        return curtain_c2.DEFAULT_PLAY_MODE

    @property
    def animation_speed(self) -> int:
        """Speed of the playing animation, or the last one seen or sent (default 50)."""
        state = self.data
        if state is not None and state.mode == curtain_c2.MODE_DIY and state.speed:
            return state.speed
        return self._last_animation_speed

    async def async_set_effect(self, effect_id: int, brightness_percent: int | None = None) -> None:
        """Start a built-in curtain effect."""
        await self._async_command(
            "set_effect",
            effect_id,
            self._curtain_speed(),
            self.curtain_percent(brightness_percent),
        )
        self._request_confirmation()

    async def async_play_animation(
        self,
        mode: int | None = None,
        speed: int | None = None,
        brightness_percent: int | None = None,
    ) -> None:
        """Play the animation stored in the curtain's flash (``E2 09``).

        Mode 0 and 1 loop all frames and mode 2 and up hold frame 1. Missing arguments
        keep the current play mode and speed, and the last brightness.
        """
        speed = speed if speed is not None else self.animation_speed
        self._last_animation_speed = speed
        await self._async_command(
            "play_animation",
            mode if mode is not None else self._curtain_play_mode(),
            speed,
            self.curtain_percent(brightness_percent),
        )
        self._request_confirmation()

    async def async_upload_animation(
        self,
        frames: list[list[tuple[int, int, int]]],
        *,
        mode: int,
        speed: int,
        brightness_percent: int,
        title: str | None = None,
        preview_png: bytes | None = None,
    ) -> None:
        """Write frames to the curtain's flash and play them. This wears the flash.

        ``title`` and ``preview_png`` are kept in memory for the Screen entities.
        """
        await self._async_command(
            "upload_curtain_animation",
            frames,
            mode=mode,
            speed=speed,
            brightness=brightness_percent,
        )
        self._last_animation_speed = speed
        self.animation_title = title
        self.preview_png = preview_png
        self.preview_updated = datetime.now(UTC)
        self._request_confirmation()
        self.async_update_listeners()

    # Settings of the text controls (Text, Text size, Text scroll, Text color, Text bold).
    # They are kept here so the entities share them. The entities restore them at startup.
    TEXT_COLORS: dict[str, tuple[int, int, int]] = {
        "yellow": (255, 200, 0),
        "white": (255, 255, 255),
        "red": (255, 0, 0),
        "orange": (255, 110, 0),
        "green": (0, 220, 0),
        "cyan": (0, 220, 220),
        "blue": (0, 80, 255),
        "magenta": (255, 0, 170),
    }
    text_size: str = "auto"  # auto, small, medium, large
    text_scroll: str = "auto"  # auto, always, never
    text_color: str = "yellow"
    text_background: str = "black"
    text_bold: bool = True
    animation_name: str | None = None  # the built-in effect chosen last, for the selector
    sequence_text: str = ""  # the line of the Sequence text box
    sequence_index: int | None = None  # the step being shown, while a sequence runs
    _sequence_task: asyncio.Task[None] | None = None
    _sequence_sleep = staticmethod(asyncio.sleep)  # replaced in tests

    @property
    def sequence_running(self) -> bool:
        return self._sequence_task is not None and not self._sequence_task.done()

    def async_start_sequence(self, steps: list[Any], *, repeat: bool = True) -> None:
        """Show ``steps`` (``core.sequence.Step``) one after the other in the background."""
        self.async_stop_sequence()
        self._sequence_task = asyncio.get_running_loop().create_task(
            self._async_run_sequence(steps, repeat)
        )
        self.async_update_listeners()

    def async_stop_sequence(self) -> None:
        """Stop the running sequence. The device keeps showing the last step."""
        task, self._sequence_task = self._sequence_task, None
        self.sequence_index = None
        if task is not None and not task.done():
            task.cancel()
            self.async_update_listeners()

    async def _async_run_sequence(self, steps: list[Any], repeat: bool) -> None:
        # Imported here: animation imports this module for type checking only.
        from . import animation

        try:
            while True:
                for index, step in enumerate(steps):
                    self.sequence_index = index
                    self.async_update_listeners()
                    for _attempt in range(3):
                        try:
                            if step.kind == "text":
                                await animation.async_show_text(
                                    self.hass, self, step.value, **self.text_settings(step.value)
                                )
                            else:
                                await animation.async_show_effect(self.hass, self, step.value)
                                self.animation_name = step.value
                            break
                        except animation.AnimationError as err:
                            # Usually the Bluetooth link dropped. Wait for it and retry.
                            _LOGGER.warning("Sequence step %s failed: %s", index + 1, err)
                            await self._sequence_sleep(15)
                    else:
                        continue  # the step never got on the device: go to the next one
                    await self._sequence_sleep(step.seconds)
                if not repeat:
                    break
        finally:
            if self._sequence_task is asyncio.current_task():
                self._sequence_task = None
                self.sequence_index = None
                self.async_update_listeners()

    # The text controls redraw the text of the Text box when they change, so the user sees
    # what each one does. Changes made while one upload runs are sent together after it.
    text_value: str | None = None  # the line of the Text box
    _text_refresh_task: asyncio.Task[None] | None = None
    _text_refresh_dirty = False
    _text_refresh_delay = 1.0  # seconds to wait for more changes; 0 in tests

    def async_refresh_text(self) -> None:
        """Send the Text box again with the current text controls, in the background.

        Nothing is sent if the box is empty or a sequence is running: the sequence picks
        the new settings up at its next text step.
        """
        if not self.text_value or self.sequence_running or not self.is_curtain:
            return
        self._text_refresh_dirty = True
        if self._text_refresh_task is None or self._text_refresh_task.done():
            self._text_refresh_task = asyncio.get_running_loop().create_task(
                self._async_refresh_text()
            )

    async def _async_refresh_text(self) -> None:
        from . import animation

        while self._text_refresh_dirty:
            self._text_refresh_dirty = False
            await asyncio.sleep(self._text_refresh_delay)
            if self._text_refresh_dirty or not self.text_value or self.sequence_running:
                continue
            try:
                await animation.async_show_text(
                    self.hass, self, self.text_value, **self.text_settings(self.text_value)
                )
            except animation.AnimationError as err:
                _LOGGER.warning("Could not redraw the text: %s", err)

    def text_settings(self, value: str | None = None) -> dict[str, Any]:
        """Keyword arguments for ``animation.async_show_text`` from the text controls.

        With ``value``, "never scroll" is made to work for that text: the renderer drops
        the bold, narrows the letters or uses two lines to make it fit, and if it still
        does not fit the text scrolls. Refusing it would show an error and nothing else.
        """
        settings = self._text_settings()
        if value is not None and settings["scroll"] is False:
            cols, rows = self.curtain_grid
            try:
                text_render.render_text(
                    value,
                    cols=cols,
                    rows=rows,
                    bold=settings["bold"],
                    scroll=False,
                    size=settings["size"],
                )
            except ValueError:
                settings["scroll"] = None
        return settings

    def _text_settings(self) -> dict[str, Any]:
        return {
            "color": self.TEXT_COLORS.get(self.text_color, self.TEXT_COLORS["yellow"]),
            "background": (
                (0, 0, 0)
                if self.text_background == "black"
                else self.TEXT_COLORS.get(self.text_background, (0, 0, 0))
            ),
            "bold": self.text_bold,
            "scroll": {"always": True, "never": False}.get(self.text_scroll),
            "size": None if self.text_size == "auto" else self.text_size,
            "speed": self.animation_speed,
        }

    def async_set_preview(self, preview_png: bytes, title: str | None = None) -> None:
        """Show a picture in the Screen preview without sending anything to the device."""
        self.animation_title = title
        self.preview_png = preview_png
        self.preview_updated = datetime.now(UTC)
        self.async_update_listeners()

    async def async_disconnect(self) -> None:
        self.async_stop_sequence()
        self._text_refresh_dirty = False
        if self._text_refresh_task is not None:
            self._text_refresh_task.cancel()
        if self.client:
            await self.client.disconnect()
