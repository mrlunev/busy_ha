"""Select platform: rotary selector and presence theme."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import BusyBarApiError
from .const import SELECTOR_POSITIONS, THEMES
from .coordinator import BusyBarCoordinator
from .entity import BusyBarEntity, device_error


PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BusyBarCoordinator = entry.runtime_data
    async_add_entities(
        [
            BusyBarSelectorSelect(coordinator),
            BusyBarThemeSelect(coordinator),
        ]
    )


class BusyBarSelectorSelect(BusyBarEntity, SelectEntity):
    """Physical rotary selector (BUSY / CUSTOM / OFF / APPS / SETTINGS).

    The device exposes no read-back for the selector position, so this entity
    is optimistic: it remembers the last position we sent. A physical turn on
    the device is not reflected here until we set it again.
    """

    _attr_translation_key = "selector"
    _attr_options = SELECTOR_POSITIONS

    def __init__(self, coordinator: BusyBarCoordinator) -> None:
        super().__init__(coordinator, key="selector")
        self._attr_current_option: str | None = None

    async def async_select_option(self, option: str) -> None:
        try:
            await self.coordinator.api.send_key(option)
        except BusyBarApiError as err:
            raise device_error(err) from err
        self._attr_current_option = option
        self.async_write_ha_state()


class BusyBarThemeSelect(BusyBarEntity, SelectEntity):
    """Presence theme of the current session.

    Changing it while a session is active updates that session's theme. When no
    session is running, picking a theme starts an open-ended (INFINITE) presence
    session with it — one tap to "show you're busy". Use Stop to clear.
    """

    _attr_translation_key = "theme_select"
    _attr_options = THEMES

    @property
    def current_option(self) -> str | None:
        return self.coordinator.data.theme

    async def async_select_option(self, option: str) -> None:
        try:
            if self.coordinator.data.active:
                await self.coordinator.api.set_theme(option)
            else:
                await self.coordinator.api.start_infinite(option)
        except BusyBarApiError as err:
            raise device_error(err) from err
        await self.coordinator.async_request_refresh_full()
