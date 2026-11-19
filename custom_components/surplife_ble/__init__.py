"""Set up the Surplife BLE integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Surplife BLE device from a config entry."""
    from homeassistant.components import bluetooth
    from homeassistant.const import CONF_ADDRESS
    from homeassistant.core import callback

    from .const import PLATFORMS
    from .coordinator import SurplifeCoordinator, SurplifeRuntimeData

    address = entry.data[CONF_ADDRESS]
    coordinator = SurplifeCoordinator(hass, entry)
    entry.runtime_data = SurplifeRuntimeData(coordinator=coordinator)

    @callback
    def _async_update_ble(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        _change: bluetooth.BluetoothChange,
    ) -> None:
        coordinator.async_set_ble_device(service_info.device, service_info.advertisement)

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _async_update_ble,
            {"address": address},
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
    )

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await coordinator.async_restore_preview()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(
        hass,
        coordinator.async_refresh(),
        "Surplife BLE initial refresh",
    )
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply changed options (curtain color calibration and orientation) without a reload."""
    entry.runtime_data.coordinator.async_update_options()


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the entity and close any BLE connection."""
    from .const import PLATFORMS

    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.coordinator.async_disconnect()
    return unload_ok
