"""Binary sensor platform."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import BusyBarCoordinator
from .entity import BusyBarEntity


PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BusyBarCoordinator = entry.runtime_data
    async_add_entities(
        [
            BusyBarConnectivityBinarySensor(coordinator),
            BusyBarActiveBinarySensor(coordinator),
            BusyBarPausedBinarySensor(coordinator),
            BusyBarChargingBinarySensor(coordinator),
        ]
    )


class BusyBarConnectivityBinarySensor(BusyBarEntity, BinarySensorEntity):
    """Reachability of the bar. Stays available so it can report 'offline'."""

    _attr_translation_key = "connectivity"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: BusyBarCoordinator) -> None:
        super().__init__(coordinator, "connectivity")

    @property
    def available(self) -> bool:
        # Unlike every other entity this one must NOT go unavailable when the
        # device is unreachable — otherwise it could never report "Disconnected".
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success


class BusyBarActiveBinarySensor(BusyBarEntity, BinarySensorEntity):
    _attr_translation_key = "active"

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.active


class BusyBarPausedBinarySensor(BusyBarEntity, BinarySensorEntity):
    _attr_translation_key = "paused"

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.paused


class BusyBarChargingBinarySensor(BusyBarEntity, BinarySensorEntity):
    _attr_translation_key = "charging"
    _attr_device_class = BinarySensorDeviceClass.BATTERY_CHARGING

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.charging
