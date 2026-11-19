"""Text box for the IOTBT curtain and net: type a text and it is shown on the device."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import animation
from .coordinator import SurplifeCoordinator
from .core import sequence
from .light import curtain_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the text box once the device is resolved as an IOTBT curtain or net."""
    coordinator: SurplifeCoordinator = entry.runtime_data.coordinator
    added = False

    @callback
    def _async_add_if_curtain() -> None:
        nonlocal added
        if not added and coordinator.is_curtain:
            added = True
            async_add_entities([SurplifeText(coordinator), SurplifeSequenceText(coordinator)])

    entry.async_on_unload(coordinator.async_add_listener(_async_add_if_curtain))
    _async_add_if_curtain()


class SurplifeText(CoordinatorEntity[SurplifeCoordinator], TextEntity, RestoreEntity):
    """The text on the screen. Setting it renders the text and uploads it.

    Size, scrolling, color and bold come from the other text controls of the device. The
    speed is the Animation speed slider. Every new text writes the flash of the device.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "text"
    _attr_native_min = 1
    _attr_native_max = 200
    _attr_icon = "mdi:format-text"

    def __init__(self, coordinator: SurplifeCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.address}_text"
        self._attr_device_info = curtain_device_info(coordinator)
        self._attr_native_value = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in ("unknown", "unavailable", ""):
            self._attr_native_value = last.state

    async def async_set_value(self, value: str) -> None:
        self.coordinator.async_stop_sequence()
        await animation.async_show_text(
            self.hass, self.coordinator, value, **self.coordinator.text_settings(value)
        )
        self._attr_native_value = value
        self.async_write_ha_state()


class SurplifeSequenceText(TextEntity, RestoreEntity):
    """The sequence, as one line: ``heart 30s; BUON NATALE 1m; rain``.

    Writing it only stores it. The Sequence switch starts and stops it. If the sequence
    is running, a new line restarts it.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "sequence"
    _attr_native_min = 0
    _attr_native_max = 255
    _attr_icon = "mdi:playlist-edit"

    def __init__(self, coordinator: SurplifeCoordinator) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{coordinator.address}_sequence"
        self._attr_device_info = curtain_device_info(coordinator)

    @property
    def native_value(self) -> str:
        return self._coordinator.sequence_text

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in ("unknown", "unavailable"):
            self._coordinator.sequence_text = last.state

    async def async_set_value(self, value: str) -> None:
        steps = None
        if value.strip():
            try:
                steps = sequence.parse(value)
            except ValueError as err:
                raise HomeAssistantError(str(err)) from err
        was_running = self._coordinator.sequence_running
        self._coordinator.sequence_text = value
        if was_running:
            if steps:
                self._coordinator.async_start_sequence(steps)
            else:
                self._coordinator.async_stop_sequence()
        self.async_write_ha_state()
