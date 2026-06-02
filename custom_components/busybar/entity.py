"""Base entity for BUSY Bar."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import BusyBarCoordinator


class BusyBarEntity(CoordinatorEntity[BusyBarCoordinator]):
    """Base class."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: BusyBarCoordinator, key: str | None = None) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        key = key or getattr(self, "_attr_translation_key", None) or "entity"
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=coordinator.data.device_name,
            manufacturer=MANUFACTURER,
            model="BUSY Bar",
            sw_version=coordinator.data.firmware_version,
            serial_number=coordinator.data.serial_number,
        )
