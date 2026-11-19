"""Bold switch for the text of the IOTBT curtain and net."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .coordinator import SurplifeCoordinator
from .light import curtain_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the bold switch once the device is resolved as an IOTBT curtain or net."""
    coordinator: SurplifeCoordinator = entry.runtime_data.coordinator
    added = False

    @callback
    def _async_add_if_curtain() -> None:
        nonlocal added
        if not added and coordinator.is_curtain:
            added = True
            async_add_entities([SurplifeTextBold(coordinator)])

    entry.async_on_unload(coordinator.async_add_listener(_async_add_if_curtain))
    _async_add_if_curtain()


class SurplifeTextBold(SwitchEntity, RestoreEntity):
    """Bold letters the next time a text is shown. Changing it sends nothing."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "text_bold"
    _attr_icon = "mdi:format-bold"

    def __init__(self, coordinator: SurplifeCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.address}_text_bold"
        self._attr_device_info = curtain_device_info(coordinator)

    @property
    def is_on(self) -> bool:
        return self._coordinator.text_bold

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state in ("on", "off"):
            self._coordinator.text_bold = last.state == "on"

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._coordinator.text_bold = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._coordinator.text_bold = False
        self.async_write_ha_state()
