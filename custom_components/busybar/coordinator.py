"""Data update coordinator."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import BusyBarApi, BusyBarApiError, BusyBarAuthError
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

type BusyBarConfigEntry = ConfigEntry[BusyBarCoordinator]


@dataclass
class BusyBarRuntime:
    """Parsed state for entities."""

    device_name: str
    serial_number: str | None
    firmware_version: str
    snapshot_type: str
    theme: str | None
    active: bool
    paused: bool
    phase: str
    time_remaining_sec: int | None
    current_interval: int | None
    battery: int | None
    charging: bool
    rssi: int | None
    brightness: str | None
    volume: float | None
    smart_home: bool | None
    smart_home_available: bool
    update_latest: str | None
    update_in_progress: bool


class BusyBarCoordinator(DataUpdateCoordinator[BusyBarRuntime]):
    """Poll BUSY Bar HTTP API."""

    def __init__(self, hass: HomeAssistant, api: BusyBarApi, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )
        self.api = api
        self._synced_name: str | None = None

    async def _async_update_data(self) -> BusyBarRuntime:
        try:
            name = await self.api.get_name()
            status = await self.api.get_status()
            snapshot_data = await self.api.get_snapshot()
            brightness = await self.api.get_brightness()
            volume = await self.api.get_volume()
            wifi = await self.api.get_wifi_status()
            try:
                sh = await self.api.get_smart_home_switch()
            except BusyBarApiError:
                sh = {}
            try:
                pairing = await self.api.get_pairing()
            except BusyBarApiError:
                pairing = {}
            try:
                update = await self.api.get_update_status()
            except BusyBarApiError:
                update = {}
        except BusyBarAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except BusyBarApiError as err:
            raise UpdateFailed(str(err)) from err

        snap = snapshot_data.get("snapshot") or {}
        stype = snap.get("type", "NOT_STARTED")
        settings = snap.get("busy_bar_settings") or {}
        theme = settings.get("theme")
        paused = bool(snap.get("is_paused", False))
        active = stype != "NOT_STARTED"

        time_left: int | None = None
        interval_no: int | None = None
        if stype == "SIMPLE":
            ms = snap.get("time_left_ms")
            time_left = int(ms // 1000) if ms is not None else None
        elif stype == "INTERVAL":
            ms = snap.get("current_interval_time_left_ms")
            time_left = int(ms // 1000) if ms is not None else None
            interval_no = snap.get("current_interval")

        phase = _phase_from_snapshot(stype, paused, interval_no)

        device = (status.get("device") or {}) if status else {}
        # Guard against a DHCP IP reshuffle silently pointing our host at a
        # DIFFERENT bar: never surface another device's data under this entry.
        reported_serial = device.get("serial_number")
        expected_serial = self.config_entry.unique_id
        if expected_serial and reported_serial and reported_serial != expected_serial:
            raise UpdateFailed(
                f"Host now reports serial {reported_serial}, expected {expected_serial} — "
                "it points to a different BUSY Bar (likely a changed IP address)"
            )
        power = (status.get("power") or {}) if status else {}
        firmware = (status.get("firmware") or {}) if status else {}
        # "charged" = full but still on USB; only "charging" means actively charging.
        charging = power.get("state") == "charging"

        fabric_count = pairing.get("fabric_count", 0) or 0

        update_check = (update.get("check") or {}) if update else {}
        update_install = (update.get("install") or {}) if update else {}
        latest = update_check.get("available_version") or None
        if update_check.get("status") != "available":
            latest = None
        in_progress = update_install.get("event") not in (None, "none") and bool(
            update_install.get("action") not in (None, "none")
        )

        device_name = name.get("name") or "BUSY Bar"
        self._sync_device_name(device_name)

        return BusyBarRuntime(
            device_name=device_name,
            serial_number=device.get("serial_number"),
            firmware_version=str(firmware.get("version") or "unknown"),
            snapshot_type=stype,
            theme=theme,
            active=active,
            paused=paused,
            phase=phase,
            time_remaining_sec=time_left,
            current_interval=interval_no,
            battery=power.get("battery_charge"),
            charging=charging,
            rssi=wifi.get("rssi") if isinstance(wifi.get("rssi"), int) else None,
            brightness=str(brightness.get("value")) if brightness.get("value") is not None else None,
            volume=float(volume.get("volume")) if volume.get("volume") is not None else None,
            smart_home=sh.get("state") if "state" in sh else None,
            smart_home_available=fabric_count > 0,
            update_latest=latest,
            update_in_progress=in_progress,
        )

    def _sync_device_name(self, name: str) -> None:
        """Propagate a rename done on the bar's web UI to the HA device registry.

        The integration-provided ``name`` is updated; HA keeps any ``name_by_user``
        override on top, so a user-chosen name in HA is never overwritten. Guarded
        on change to avoid registry churn on every poll. On the first refresh the
        device does not exist yet — entities create it with the correct name.
        """
        if name == self._synced_name:
            return
        serial = self.config_entry.unique_id or self.config_entry.entry_id
        dev_reg = dr.async_get(self.hass)
        device = dev_reg.async_get_device(identifiers={(DOMAIN, serial)})
        if device is None:
            return
        self._synced_name = name
        if device.name != name:
            dev_reg.async_update_device(device.id, name=name)


def _phase_from_snapshot(stype: str, paused: bool, interval_no: int | None) -> str:
    if stype == "NOT_STARTED":
        return "idle"
    if paused:
        return "paused"
    if stype == "INTERVAL" and interval_no is not None:
        return "work" if interval_no % 2 == 1 else "break"
    return "work"
