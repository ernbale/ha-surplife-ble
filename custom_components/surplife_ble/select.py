"""Text size, scrolling and color selectors for the IOTBT curtain and net."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .coordinator import SurplifeCoordinator
from .light import curtain_device_info

# key -> (coordinator attribute, options, icon)
SELECTS: dict[str, tuple[str, list[str], str]] = {
    "text_size": ("text_size", ["auto", "small", "medium", "large"], "mdi:format-size"),
    "text_scroll": ("text_scroll", ["auto", "always", "never"], "mdi:arrow-left-bold-box-outline"),
    "text_color": ("text_color", list(SurplifeCoordinator.TEXT_COLORS), "mdi:palette"),
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
            async_add_entities([SurplifeTextSelect(coordinator, key) for key in SELECTS])

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
