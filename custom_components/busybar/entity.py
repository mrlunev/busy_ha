"""Base entity for BUSY Bar."""

from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import BusyBarCoordinator


def device_error(err: Exception) -> HomeAssistantError:
    """Wrap a device/API failure as a translated HomeAssistantError."""
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="device_error",
        translation_placeholders={"error": str(err)},
    )


class BusyBarEntity(CoordinatorEntity[BusyBarCoordinator]):
    """Base class."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BusyBarCoordinator, key: str | None = None) -> None:
        super().__init__(coordinator)
        key = key or getattr(self, "_attr_translation_key", None) or "entity"
        # Anchor identity on the hardware serial (config-entry unique_id), NOT the
        # device name or entry_id. This survives: renaming the bar via its web UI,
        # IP changes, and even deleting + re-adding the integration (re-links to the
        # same physical device & its history). Fallback to entry_id only if the
        # device somehow reported no serial.
        serial = coordinator.config_entry.unique_id or coordinator.config_entry.entry_id
        self._attr_unique_id = f"{serial}_{key}"
        # Network MACs link this device to its router/device-tracker presence and
        # to the Matter device of the same bar. wifi_mac is also what DHCP
        # discovery matches on (manifest dhcp OUI).
        connections = {
            (CONNECTION_NETWORK_MAC, format_mac(mac))
            for mac in (coordinator.data.wifi_mac, coordinator.data.usb_mac)
            if mac
        }
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            connections=connections,
            name=coordinator.data.device_name,
            manufacturer=MANUFACTURER,
            model="BUSY Bar",
            sw_version=coordinator.data.firmware_version,
            serial_number=coordinator.data.serial_number,
        )
