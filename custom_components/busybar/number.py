"""Number platform."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import BusyBarApiError
from .coordinator import BusyBarCoordinator
from .entity import BusyBarEntity


PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BusyBarCoordinator = entry.runtime_data
    async_add_entities(
        [
            BusyBarBrightnessNumber(coordinator),
            BusyBarVolumeNumber(coordinator),
        ]
    )


class BusyBarBrightnessNumber(BusyBarEntity, NumberEntity):
    _attr_translation_key = "brightness"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = "slider"

    @property
    def native_value(self) -> float | None:
        val = self.coordinator.data.brightness
        if val is None or val == "auto":
            return None
        try:
            return float(val)
        except ValueError:
            return None

    @property
    def available(self) -> bool:
        return super().available and self.native_value is not None

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.coordinator.api.set_brightness(int(value))
        except BusyBarApiError as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_request_refresh()


class BusyBarVolumeNumber(BusyBarEntity, NumberEntity):
    _attr_translation_key = "volume"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = "slider"

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.volume

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self.coordinator.api.set_volume(int(value))
        except BusyBarApiError as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_request_refresh()
