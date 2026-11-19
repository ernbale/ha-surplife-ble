"""Light entity for a verified Surplife BLE device."""

from __future__ import annotations

from typing import Any, cast

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    ATTR_RGB_COLOR,
    ATTR_WHITE,
    ColorMode,
    LightEntity,
    LightEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_platform
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import animation
from .const import DOMAIN
from .coordinator import SurplifeCoordinator
from .core import curtain_c2
from .services import async_register_entity_services


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create one whole-lamp entity and register the curtain services."""
    async_add_entities([SurplifeLight(entry.runtime_data.coordinator, entry)])
    async_register_entity_services(entity_platform.async_get_current_platform())


def curtain_device_info(coordinator: SurplifeCoordinator) -> DeviceInfo:
    """Device info shared by every curtain entity, so they sit under one device."""
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.address)},
        connections={(dr.CONNECTION_BLUETOOTH, coordinator.address)},
        manufacturer="MIHEAL / Surplife",
        model=(
            "Net lights 32x16 (IOTBT, product 0x71)"
            if coordinator.curtain_grid == (32, 16)
            else "Curtain lights (IOTBT, product 0xC2)"
        ),
        name=coordinator.config_entry.title,
    )


class SurplifeLight(CoordinatorEntity[SurplifeCoordinator], LightEntity):
    """Whole-lamp RGB/single-white controls. The IOTBT curtain is RGB-only with effects."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_color_modes = {ColorMode.RGB, ColorMode.WHITE}

    def __init__(self, coordinator: SurplifeCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = coordinator.address
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            connections={(dr.CONNECTION_BLUETOOTH, coordinator.address)},
            manufacturer="MIHEAL / Surplife",
            name=entry.title,
        )
        self._async_update_attrs()

    @callback
    def _async_update_attrs(self) -> None:
        state = self.coordinator.data
        if state is None:
            return
        self._attr_is_on = state.power
        self._attr_brightness = state.brightness
        self._attr_rgb_color = state.rgb
        self._attr_assumed_state = state.assumed
        if self.coordinator.is_curtain:
            self._async_update_curtain_attrs(state)
            return
        # White mode is indicated by white > 0 (the IOTBT codec sets white=0
        # in color mode). RGB may be non-zero in white mode since HSV is still
        # computed, so we rely on the white field as the authoritative signal.
        is_white = bool(state.white and state.white > 0)
        self._attr_color_mode = ColorMode.WHITE if is_white else ColorMode.RGB
        model = (
            f"DX23012 ({state.model_num:#04x})"
            if state.model_num is not None
            else "DX23012"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.address)},
            connections={(dr.CONNECTION_BLUETOOTH, self.coordinator.address)},
            manufacturer="MIHEAL / Surplife",
            model=model,
            name=self.coordinator.config_entry.title,
            sw_version=str(state.firmware_version) if state.firmware_version is not None else None,
        )

    @callback
    def _async_update_curtain_attrs(self, state: Any) -> None:
        """The curtain is RGB-only. It has effects and a stored animation."""
        self._attr_supported_color_modes = {ColorMode.RGB}
        self._attr_color_mode = ColorMode.RGB
        self._attr_supported_features = LightEntityFeature.EFFECT
        self._attr_effect_list = curtain_c2.effect_list()
        self._attr_effect = curtain_c2.effect_name_for_state(state.mode, state.effect)
        self._attr_device_info = curtain_device_info(self.coordinator)

    async def async_turn_on(self, **kwargs: Any) -> None:
        requested_brightness = cast(int | None, kwargs.get(ATTR_BRIGHTNESS))
        brightness = (
            requested_brightness
            if requested_brightness is not None
            else self.brightness if self.brightness is not None else 255
        )
        if self.coordinator.is_curtain:
            await self._async_turn_on_curtain(requested_brightness, brightness, kwargs)
            return
        if ATTR_RGB_COLOR in kwargs:
            await self.coordinator.async_set_rgb(kwargs[ATTR_RGB_COLOR], brightness)
        elif ATTR_WHITE in kwargs:
            requested_white = cast(int | None, kwargs[ATTR_WHITE])
            await self.coordinator.async_set_white(
                requested_white if requested_white is not None else 255
            )
        elif ATTR_BRIGHTNESS in kwargs:
            await self.coordinator.async_set_brightness(brightness)
        else:
            await self.coordinator.async_set_power(True)

    async def _async_turn_on_curtain(
        self, requested: int | None, brightness: int, kwargs: dict[str, Any]
    ) -> None:
        percent = None if requested is None else max(1, round(requested / 255 * 100))
        if (effect := kwargs.get(ATTR_EFFECT)) is not None:
            if effect == curtain_c2.EFFECT_ANIMATION:
                await self.coordinator.async_play_animation(brightness_percent=percent)
            else:
                try:
                    effect_id = curtain_c2.effect_id_from_name(effect)
                except ValueError as err:
                    raise HomeAssistantError(str(err)) from err
                await self.coordinator.async_set_effect(effect_id, percent)
        elif ATTR_RGB_COLOR in kwargs:
            await self.coordinator.async_set_rgb(kwargs[ATTR_RGB_COLOR], brightness)
        elif requested is not None:
            await self.coordinator.async_set_brightness(requested)
        else:
            await self.coordinator.async_set_power(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_power(False)

    async def async_upload_animation(self, **kwargs: Any) -> None:
        """Service: upload an image or GIF to the curtain's flash and play it."""
        source = await animation.async_read_source(
            self.hass, path=kwargs.get("path"), url=kwargs.get("url")
        )
        await animation.async_upload(
            self.hass,
            self.coordinator,
            source,
            mode=kwargs["mode"],
            speed=kwargs["speed"],
            brightness=kwargs["brightness"],
            controller_side=kwargs.get("controller_side"),
            flip=kwargs.get("flip"),
            max_frames=kwargs["max_frames"],
            resample=kwargs["resample"],
        )

    async def async_show_text(self, **kwargs: Any) -> None:
        """Service: render text, show it in the Screen preview and upload it."""
        await animation.async_show_text(
            self.hass,
            self.coordinator,
            kwargs["text"],
            color=tuple(kwargs["color"]),
            bold=kwargs["bold"],
            scroll=kwargs.get("scroll"),
            size=kwargs.get("size"),
            background=tuple(kwargs["background"]),
            speed=kwargs["speed"],
            brightness=kwargs["brightness"],
            preview_only=kwargs["preview_only"],
        )

    async def async_show_effect(self, **kwargs: Any) -> None:
        """Service: draw a built-in effect, upload it and play it."""
        await animation.async_show_effect(
            self.hass,
            self.coordinator,
            kwargs["effect"],
            speed=kwargs.get("speed"),
            brightness=kwargs["brightness"],
        )
        self.coordinator.animation_name = kwargs["effect"]
        self.coordinator.async_update_listeners()

    async def async_play_animation(self, **kwargs: Any) -> None:
        """Service: play the animation stored in the curtain's flash."""
        if not self.coordinator.is_curtain:
            raise animation.AnimationError(
                "this device is not an IOTBT curtain (product 0xC2), or it is not connected yet"
            )
        try:
            await self.coordinator.async_play_animation(
                kwargs["mode"], kwargs["speed"], kwargs["brightness"]
            )
        except (RuntimeError, ValueError, OSError, TimeoutError) as err:
            raise animation.AnimationError(str(err)) from err

    @callback
    def _handle_coordinator_update(self) -> None:
        self._async_update_attrs()
        self.async_write_ha_state()
