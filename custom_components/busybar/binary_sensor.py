"""Binary sensor platform."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
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
            BusyBarActiveBinarySensor(coordinator),
            BusyBarPausedBinarySensor(coordinator),
            BusyBarChargingBinarySensor(coordinator),
        ]
    )


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
    _attr_device_class = "battery_charging"

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.charging
