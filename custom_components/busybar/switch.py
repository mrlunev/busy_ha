"""Switch platform."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import BusyBarApiError
from .coordinator import BusyBarCoordinator
from .entity import BusyBarEntity, device_error


PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BusyBarCoordinator = entry.runtime_data
    async_add_entities([BusyBarSmartHomeSwitch(coordinator)])


class BusyBarSmartHomeSwitch(BusyBarEntity, SwitchEntity):
    _attr_translation_key = "smart_home"

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.smart_home

    @property
    def available(self) -> bool:
        # The emulated Matter switch only works once the bar is commissioned
        # into a Matter fabric; otherwise the device returns 503 on write.
        return (
            super().available
            and self.coordinator.data.smart_home is not None
            and self.coordinator.data.smart_home_available
        )

    async def async_turn_on(self, **kwargs) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set(False)

    async def _set(self, state: bool) -> None:
        try:
            await self.coordinator.api.set_smart_home_switch(state)
        except BusyBarApiError as err:
            raise device_error(err) from err
        await self.coordinator.async_request_refresh_full()
