"""Sensor platform."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

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
            BusyBarBluetoothSensor(coordinator),
            BusyBarFirmwareSensor(coordinator),
            BusyBarLastBootSensor(coordinator),
            BusyBarBatteryVoltageSensor(coordinator),
            BusyBarBatteryCurrentSensor(coordinator),
            BusyBarUsbVoltageSensor(coordinator),
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
    # Absolute finish time rather than a ticking duration: the frontend shows a
    # live relative "in N min" that counts down on its own, so the integration
    # doesn't have to poll fast just to move a number. Unknown while not running
    # or paused.
    _attr_translation_key = "time_remaining"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        return self.coordinator.data.finishes_at


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


class BusyBarBluetoothSensor(BusyBarEntity, SensorEntity):
    """Bluetooth (BLE) radio status, from /api/ble/status. Diagnostic."""

    _attr_translation_key = "bluetooth"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        "reset",
        "initialization",
        "disabled",
        "enabled",
        "connectable",
        "connected",
        "internal error",
    ]
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data.bluetooth


class BusyBarFirmwareSensor(BusyBarEntity, SensorEntity):
    _attr_translation_key = "firmware"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str:
        return self.coordinator.data.firmware_version


class BusyBarLastBootSensor(BusyBarEntity, SensorEntity):
    _attr_translation_key = "last_boot"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> datetime | None:
        boot = self.coordinator.data.boot_time
        return dt_util.utc_from_timestamp(boot) if boot else None


class BusyBarBatteryVoltageSensor(BusyBarEntity, SensorEntity):
    _attr_translation_key = "battery_voltage"
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_suggested_display_precision = 3

    @property
    def native_value(self) -> float | None:
        mv = self.coordinator.data.battery_voltage
        return mv / 1000 if mv is not None else None


class BusyBarBatteryCurrentSensor(BusyBarEntity, SensorEntity):
    _attr_translation_key = "battery_current"
    _attr_device_class = SensorDeviceClass.CURRENT
    _attr_native_unit_of_measurement = UnitOfElectricCurrent.MILLIAMPERE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    @property
    def native_value(self) -> int | None:
        return self.coordinator.data.battery_current


class BusyBarUsbVoltageSensor(BusyBarEntity, SensorEntity):
    _attr_translation_key = "usb_voltage"
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_suggested_display_precision = 3

    @property
    def native_value(self) -> float | None:
        mv = self.coordinator.data.usb_voltage
        return mv / 1000 if mv is not None else None
