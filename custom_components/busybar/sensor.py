"""Sensor platform."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
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
            BusyBarStateSensor(coordinator),
            BusyBarPhaseSensor(coordinator),
            BusyBarTimeRemainingSensor(coordinator),
            BusyBarCurrentIntervalSensor(coordinator),
            BusyBarBatterySensor(coordinator),
            BusyBarWifiSensor(coordinator),
            BusyBarFirmwareSensor(coordinator),
        ]
    )


class BusyBarStateSensor(BusyBarEntity, SensorEntity):
    _attr_translation_key = "state"
    _attr_device_class = "enum"
    _attr_options = ["not_started", "infinite", "simple", "interval"]

    @property
    def native_value(self) -> str:
        return (self.coordinator.data.snapshot_type or "NOT_STARTED").lower()


class BusyBarPhaseSensor(BusyBarEntity, SensorEntity):
    _attr_translation_key = "phase"

    @property
    def native_value(self) -> str:
        return self.coordinator.data.phase


class BusyBarTimeRemainingSensor(BusyBarEntity, SensorEntity):
    _attr_translation_key = "time_remaining"
    _attr_native_unit_of_measurement = "s"
    _attr_device_class = "duration"
    _attr_state_class = "measurement"

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.time_remaining_sec


class BusyBarCurrentIntervalSensor(BusyBarEntity, SensorEntity):
    _attr_translation_key = "current_interval"
    _attr_state_class = "measurement"

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.current_interval


class BusyBarBatterySensor(BusyBarEntity, SensorEntity):
    _attr_translation_key = "battery"
    _attr_native_unit_of_measurement = "%"
    _attr_device_class = "battery"
    _attr_state_class = "measurement"

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.battery


class BusyBarWifiSensor(BusyBarEntity, SensorEntity):
    _attr_translation_key = "wifi_signal"
    _attr_native_unit_of_measurement = "dBm"
    _attr_device_class = "signal_strength"
    _attr_state_class = "measurement"
    _attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.rssi


class BusyBarFirmwareSensor(BusyBarEntity, SensorEntity):
    _attr_translation_key = "firmware"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str:
        return self.coordinator.data.firmware_version
