"""Update platform: firmware OTA."""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import UpdateEntity, UpdateEntityFeature
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
    async_add_entities([BusyBarFirmwareUpdate(coordinator)])


class BusyBarFirmwareUpdate(BusyBarEntity, UpdateEntity):
    _attr_translation_key = "firmware_update"
    _attr_supported_features = UpdateEntityFeature.INSTALL

    @property
    def installed_version(self) -> str | None:
        return self.coordinator.data.firmware_version

    @property
    def latest_version(self) -> str | None:
        # Fall back to the installed version so HA does not flag an update when
        # the device reports nothing newer.
        return self.coordinator.data.update_latest or self.coordinator.data.firmware_version

    @property
    def in_progress(self) -> bool:
        return self.coordinator.data.update_in_progress

    async def async_install(self, version: str | None, backup: bool, **kwargs: Any) -> None:
        target = version or self.coordinator.data.update_latest
        if not target:
            raise HomeAssistantError("No firmware version available to install")
        try:
            await self.coordinator.api.install_update(target)
        except BusyBarApiError as err:
            raise HomeAssistantError(str(err)) from err
        await self.coordinator.async_request_refresh()
