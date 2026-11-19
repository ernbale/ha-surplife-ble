"""Text size, scrolling and color selectors for the IOTBT curtain and net."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
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
    "text_color": ("text_color", list(SurplifeCoordinator.TEXT_COLORS), "mdi:palette"),
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
                ]
            )

    entry.async_on_unload(coordinator.async_add_listener(_async_add_if_curtain))
    _async_add_if_curtain()


class SurplifeTextSelect(SelectEntity, RestoreEntity):
    """One setting used the next time a text is shown. Changing it sends nothing."""

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
        self._attr_options = effects.available(*coordinator.curtain_grid)

    @property
    def current_option(self) -> str | None:
        name = self.coordinator.animation_name
        return name if name in self._attr_options else None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in self._attr_options:
            self.coordinator.animation_name = last.state

    async def async_select_option(self, option: str) -> None:
        await animation.async_show_effect(self.hass, self.coordinator, option)
        self.coordinator.animation_name = option
        self.async_write_ha_state()
