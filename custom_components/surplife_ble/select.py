"""Text size, scrolling and color selectors for the IOTBT curtain and net."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import animation
from .coordinator import SurplifeCoordinator
from .core import effects
from .light import curtain_device_info

# key -> (coordinator attribute, options, icon)
SELECTS: dict[str, tuple[str, list[str], str]] = {
    "text_size": ("text_size", ["auto", "small", "medium", "large"], "mdi:format-size"),
    "text_scroll": ("text_scroll", ["auto", "always", "never"], "mdi:arrow-left-bold-box-outline"),
    "text_color": (
        "text_color",
        [*SurplifeCoordinator.TEXT_COLORS, SurplifeCoordinator.RAINBOW],
        "mdi:palette",
    ),
    "text_background": (
        "text_background",
        ["black", *SurplifeCoordinator.TEXT_COLORS],
        "mdi:format-color-fill",
    ),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the text selectors once the device is resolved as an IOTBT curtain or net."""
    coordinator: SurplifeCoordinator = entry.runtime_data.coordinator
    added = False

    @callback
    def _async_add_if_curtain() -> None:
        nonlocal added
        if not added and coordinator.is_curtain:
            added = True
            async_add_entities(
                [
                    SurplifeAnimationSelect(coordinator),
                    *(SurplifeTextSelect(coordinator, key) for key in SELECTS),
                    *(SurplifeLayoutSelect(coordinator, key) for key in LAYOUT_SELECTS),
                ]
            )

    entry.async_on_unload(coordinator.async_add_listener(_async_add_if_curtain))
    _async_add_if_curtain()


class SurplifeTextSelect(SelectEntity, RestoreEntity):
    """One setting of the text. Changing it redraws the text of the Text box."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: SurplifeCoordinator, key: str) -> None:
        self._coordinator = coordinator
        self._attribute, options, icon = SELECTS[key]
        self._attr_translation_key = key
        self._attr_options = options
        self._attr_icon = icon
        self._attr_unique_id = f"{coordinator.address}_{key}"
        self._attr_device_info = curtain_device_info(coordinator)

    @property
    def current_option(self) -> str:
        return getattr(self._coordinator, self._attribute)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self._attr_options:
            setattr(self._coordinator, self._attribute, last.state)

    async def async_select_option(self, option: str) -> None:
        setattr(self._coordinator, self._attribute, option)
        self.async_write_ha_state()
        self._coordinator.async_refresh_text()


LINES = [str(n) for n in range(13)]
LAYOUT_SELECTS: dict[str, tuple[list[str], str]] = {
    "layout_rotation": (["0", "90", "180", "270"], "mdi:screen-rotation"),
    "layout_top": (LINES, "mdi:border-top-variant"),
    "layout_bottom": (LINES, "mdi:border-bottom-variant"),
    "layout_left": (LINES, "mdi:border-left-variant"),
    "layout_right": (LINES, "mdi:border-right-variant"),
}


class SurplifeLayoutSelect(SelectEntity, RestoreEntity):
    """Rotation of the picture, or lines of LEDs left dark on one side.

    For a net hung sideways, or partly hidden (a railing, a folded edge). Changing it draws
    again the text or effect shown last.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: SurplifeCoordinator, key: str) -> None:
        self._coordinator = coordinator
        self._key = key
        self._attr_options, self._attr_icon = LAYOUT_SELECTS[key]
        self._attr_translation_key = key
        self._attr_unique_id = f"{coordinator.address}_{key}"
        self._attr_device_info = curtain_device_info(coordinator)

    @property
    def current_option(self) -> str:
        return getattr(self._coordinator, self._key)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self._attr_options:
            setattr(self._coordinator, self._key, last.state)
            try:
                _ = self._coordinator.canvas
            except ValueError:
                setattr(self._coordinator, self._key, "0")

    async def async_select_option(self, option: str) -> None:
        previous = getattr(self._coordinator, self._key)
        setattr(self._coordinator, self._key, option)
        try:
            width, height = self._coordinator.canvas
            if width < 8 or height < 5:
                raise ValueError(f"only {width}x{height} LEDs would be left")
        except ValueError as err:
            setattr(self._coordinator, self._key, previous)
            raise HomeAssistantError(f"too many lines excluded: {err}") from err
        self.async_write_ha_state()
        self._coordinator.async_update_listeners()
        self._coordinator.async_refresh_layout()


class SurplifeAnimationSelect(CoordinatorEntity[SurplifeCoordinator], SelectEntity, RestoreEntity):
    """Built-in effects drawn for the grid of the device. Choosing one uploads and plays it.

    Every choice writes the flash of the device. The selection is only a reminder of the
    last effect chosen here: the device may be showing something uploaded another way.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "animation"
    _attr_icon = "mdi:animation-play"

    def __init__(self, coordinator: SurplifeCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_animation"
        self._attr_device_info = curtain_device_info(coordinator)

    @property
    def options(self) -> list[str]:
        """The effects that fit the LEDs the layout leaves."""
        try:
            return effects.available(*self.coordinator.canvas)
        except ValueError:
            return effects.available(*self.coordinator.curtain_grid)

    @property
    def current_option(self) -> str | None:
        name = self.coordinator.animation_name
        return name if name in self.options else None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in effects.EFFECTS:
            self.coordinator.animation_name = last.state

    async def async_select_option(self, option: str) -> None:
        self.coordinator.async_stop_sequence()
        await animation.async_show_effect(self.hass, self.coordinator, option)
        self.coordinator.animation_name = option
        self.async_write_ha_state()
