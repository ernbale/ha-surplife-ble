"""Bold switch for the text of the IOTBT curtain and net."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import SurplifeCoordinator
from .core import sequence
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
            async_add_entities([SurplifeTextBold(coordinator), SurplifeSequenceSwitch(coordinator)])

    entry.async_on_unload(coordinator.async_add_listener(_async_add_if_curtain))
    _async_add_if_curtain()


class SurplifeTextBold(SwitchEntity, RestoreEntity):
    """Bold letters. Changing it redraws the text of the Text box."""

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
        self._coordinator.async_refresh_text()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._coordinator.text_bold = False
        self.async_write_ha_state()
        self._coordinator.async_refresh_text()


class SurplifeSequenceSwitch(CoordinatorEntity[SurplifeCoordinator], SwitchEntity):
    """Runs the line of the Sequence text box, over and over, until it is turned off.

    It is off after Home Assistant restarts. The step being shown is in the ``step``
    attribute.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "sequence"
    _attr_icon = "mdi:playlist-play"

    def __init__(self, coordinator: SurplifeCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_sequence_running"
        self._attr_device_info = curtain_device_info(coordinator)

    @property
    def is_on(self) -> bool:
        return self.coordinator.sequence_running

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        index = self.coordinator.sequence_index
        return {"step": None if index is None else index + 1}

    async def async_turn_on(self, **kwargs: Any) -> None:
        try:
            steps = sequence.parse(self.coordinator.sequence_text)
        except ValueError as err:
            raise HomeAssistantError(f"write the sequence first: {err}") from err
        if not self.coordinator.is_curtain:
            raise HomeAssistantError("the device is not connected yet")
        self.coordinator.async_start_sequence(steps)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.async_stop_sequence()
