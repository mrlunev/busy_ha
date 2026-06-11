"""Button platform."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    async_add_entities(
        [
            BusyBarKeyButton(coordinator, "ok", "ok"),
            BusyBarKeyButton(coordinator, "back", "back"),
            BusyBarStartButton(coordinator),
            BusyBarStopButton(coordinator),
            BusyBarPauseButton(coordinator),
            BusyBarResumeButton(coordinator),
        ]
    )


class BusyBarKeyButton(BusyBarEntity, ButtonEntity):
    def __init__(self, coordinator: BusyBarCoordinator, key: str, translation_key: str) -> None:
        super().__init__(coordinator, key=translation_key)
        self._key = key
        self._attr_translation_key = translation_key

    async def async_press(self) -> None:
        try:
            await self.coordinator.api.send_key(self._key)
        except BusyBarApiError as err:
            raise device_error(err) from err
        await self.coordinator.async_request_refresh_full()


class BusyBarStartButton(BusyBarEntity, ButtonEntity):
    """One-tap start of an open-ended BUSY session.

    Mirrors the Stop/Pause/Resume controls so the dashboard has a "go busy now"
    button without opening the Start timer action. Starts an INFINITE session
    (the core "I'm busy" mode); Simple/Pomodoro need parameters and stay on the
    `start_timer` action. Reuses the current theme when one is known, else the
    same "meeting" default as the action. Hidden while a session is already
    running (use Stop first), like the other session buttons.
    """

    _attr_translation_key = "start_timer"

    @property
    def available(self) -> bool:
        return super().available and not self.coordinator.data.active

    async def async_press(self) -> None:
        try:
            await self.coordinator.api.start_infinite(self.coordinator.data.theme or "meeting")
        except BusyBarApiError as err:
            raise device_error(err) from err
        await self.coordinator.async_request_refresh_full()


class BusyBarStopButton(BusyBarEntity, ButtonEntity):
    _attr_translation_key = "stop_timer"

    async def async_press(self) -> None:
        try:
            await self.coordinator.api.stop_busy()
        except BusyBarApiError as err:
            raise device_error(err) from err
        await self.coordinator.async_request_refresh_full()


class BusyBarPauseButton(BusyBarEntity, ButtonEntity):
    _attr_translation_key = "pause_timer"

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.active and not self.coordinator.data.paused

    async def async_press(self) -> None:
        try:
            await self.coordinator.api.pause_busy()
        except BusyBarApiError as err:
            raise device_error(err) from err
        await self.coordinator.async_request_refresh_full()


class BusyBarResumeButton(BusyBarEntity, ButtonEntity):
    _attr_translation_key = "resume_timer"

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.active and self.coordinator.data.paused

    async def async_press(self) -> None:
        try:
            await self.coordinator.api.resume_busy()
        except BusyBarApiError as err:
            raise device_error(err) from err
        await self.coordinator.async_request_refresh_full()
