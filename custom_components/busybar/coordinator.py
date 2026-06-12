"""Data update coordinator."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import BusyBarApi, BusyBarApiError, BusyBarAuthError
from .const import (
    CONF_TOKEN,
    DOMAIN,
    MEDIUM_POLL_FACTOR,
    SCAN_INTERVAL,
    SLOW_POLL_FACTOR,
)
from .ws import BusyBarWsClient, InputEvent, decode_timer_snapshot

_LOGGER = logging.getLogger(__name__)

type BusyBarConfigEntry = ConfigEntry[BusyBarCoordinator]

# HA event fired for each physical input on the bar (button / rotary selector /
# encoder), so automations and device triggers can react to it.
EVENT_INPUT = f"{DOMAIN}_event"


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
    finishes_at: datetime | None
    current_interval: int | None
    battery: int | None
    charging: bool
    rssi: int | None
    brightness: str | None
    volume: float | None
    smart_home: bool | None
    smart_home_available: bool
    bluetooth: str | None
    update_latest: str | None
    update_in_progress: bool
    wifi_mac: str | None
    usb_mac: str | None
    boot_time: int | None
    battery_voltage: int | None
    battery_current: int | None
    usb_voltage: int | None


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
        # Tiered polling bookkeeping. Fast endpoints are fetched every cycle;
        # medium/slow ones every Nth cycle, reusing the last payload in between.
        self._cycle = 0
        self._force_full = False
        self._cache: dict[str, dict] = {}
        self._ws: BusyBarWsClient | None = None

    def start_ws(self) -> None:
        """Start the WebSocket push stream (best-effort; polling stays the base).

        The stream pushes timer/session changes (applied instantly) and physical
        input events (re-emitted as HA events); any other status change just
        nudges a REST refresh so the canonical value flows through the normal
        parse path. Failures degrade silently to polling-only.
        """
        if self._ws is None:
            self._ws = BusyBarWsClient(
                self.config_entry.data[CONF_HOST],
                self.config_entry.data.get(CONF_TOKEN, ""),
                on_status=self._on_ws_status,
                on_input=self._on_ws_input,
                on_connection_change=self._on_ws_connection,
            )
        self._ws.start()

    async def stop_ws(self) -> None:
        """Stop the WebSocket push stream."""
        if self._ws is not None:
            await self._ws.stop()

    async def _on_ws_status(self, updates: list[dict[str, Any]]) -> None:
        """Merge pushed status updates: timer/name applied live, rest → refresh."""
        if self.data is None:
            return
        data = self.data
        need_refresh = False
        for update in updates:
            if "timer" in update:
                if (snap := decode_timer_snapshot(update["timer"])) is not None:
                    data = replace(data, **_parse_snapshot(snap))
            elif "device_name" in update:
                if name := (update["device_name"] or {}).get("name"):
                    self._sync_device_name(name)
                    data = replace(data, device_name=name)
            else:
                # Other fields use a different (protobuf) shape than REST; rather
                # than re-parse them here, pull the canonical value via REST.
                need_refresh = True
        if data is not self.data:
            self.async_set_updated_data(data)
        if need_refresh:
            await self.async_request_refresh()

    async def _on_ws_input(self, event: InputEvent) -> None:
        """Re-emit a physical input event onto the HA event bus."""
        payload: dict[str, Any] = {"type": event.kind}
        if event.kind == "button":
            payload["button"] = (event.button or "").lower()
            payload["action"] = (event.action or "").lower()
        elif event.kind == "selector":
            payload["position"] = (event.position or "").lower()
        elif event.kind == "encoder":
            payload["delta"] = event.delta
        serial = self.config_entry.unique_id
        payload["serial_number"] = serial
        if serial:
            device = dr.async_get(self.hass).async_get_device(
                identifiers={(DOMAIN, serial)}
            )
            if device is not None:
                payload["device_id"] = device.id
        self.hass.bus.async_fire(EVENT_INPUT, payload)

    def _on_ws_connection(self, connected: bool) -> None:
        """On (re)connect, pull a fresh full snapshot so push starts from truth."""
        if connected:
            self.config_entry.async_create_task(
                self.hass, self.async_request_refresh()
            )

    async def async_request_refresh_full(self) -> None:
        """Request a refresh that includes the medium and slow tiers.

        Used after a user-initiated write (set brightness, toggle switch, …) so
        the affected entity reflects the new value immediately instead of waiting
        for its slow tier to come round.
        """
        self._force_full = True
        await self.async_request_refresh()

    async def _async_update_data(self) -> BusyBarRuntime:
        cycle = self._cycle
        force = self._force_full
        self._force_full = False
        self._cycle = cycle + 1
        do_medium = force or cycle % MEDIUM_POLL_FACTOR == 0
        do_slow = force or cycle % SLOW_POLL_FACTOR == 0

        try:
            # Fast tier (every cycle): live session state, power/battery (and the
            # serial guard), plus the cheap device name so renames stay responsive.
            status = await self.api.get_status()
            snapshot_data = await self.api.get_snapshot()
            name = await self.api.get_name()

            if do_medium:
                self._cache["brightness"] = await self.api.get_brightness()
                self._cache["volume"] = await self.api.get_volume()
                self._cache["wifi"] = await self.api.get_wifi_status()
                try:
                    self._cache["sh"] = await self.api.get_smart_home_switch()
                except BusyBarApiError:
                    self._cache["sh"] = {}
            if do_slow:
                try:
                    self._cache["pairing"] = await self.api.get_pairing()
                except BusyBarApiError:
                    self._cache["pairing"] = {}
                try:
                    self._cache["update"] = await self.api.get_update_status()
                except BusyBarApiError:
                    self._cache["update"] = {}
                try:
                    self._cache["ble"] = await self.api.get_ble_status()
                except BusyBarApiError:
                    self._cache["ble"] = {}
        except BusyBarAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except BusyBarApiError as err:
            raise UpdateFailed(str(err)) from err

        brightness = self._cache.get("brightness") or {}
        volume = self._cache.get("volume") or {}
        wifi = self._cache.get("wifi") or {}
        sh = self._cache.get("sh") or {}
        pairing = self._cache.get("pairing") or {}
        update = self._cache.get("update") or {}
        ble = self._cache.get("ble") or {}

        session = _parse_snapshot(snapshot_data)
        stype = session["snapshot_type"]
        theme = session["theme"]
        active = session["active"]
        paused = session["paused"]
        phase = session["phase"]
        time_left = session["time_remaining_sec"]
        finishes_at = session["finishes_at"]
        interval_no = session["current_interval"]

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
        system = (status.get("system") or {}) if status else {}
        # "charged" = full but still on USB; only "charging" means actively charging.
        charging = power.get("state") == "charging"

        fabric_count = pairing.get("fabric_count", 0) or 0

        update_check = (update.get("check") or {}) if update else {}
        update_install = (update.get("install") or {}) if update else {}
        latest = update_check.get("available_version") or None
        if update_check.get("status") != "available":
            latest = None
        in_progress = update_install.get("event") not in (None, "none") and update_install.get(
            "action"
        ) not in (None, "none")

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
            finishes_at=finishes_at,
            current_interval=interval_no,
            battery=power.get("battery_charge"),
            charging=charging,
            rssi=wifi.get("rssi") if isinstance(wifi.get("rssi"), int) else None,
            brightness=str(brightness.get("value")) if brightness.get("value") is not None else None,
            volume=float(volume.get("volume")) if volume.get("volume") is not None else None,
            smart_home=sh.get("state") if "state" in sh else None,
            smart_home_available=fabric_count > 0,
            bluetooth=ble.get("status") if ble.get("status") else None,
            update_latest=latest,
            update_in_progress=in_progress,
            wifi_mac=device.get("wifi_mac"),
            usb_mac=device.get("usb_mac"),
            boot_time=system.get("boot_time") if isinstance(system.get("boot_time"), int) else None,
            battery_voltage=power.get("battery_voltage") if isinstance(power.get("battery_voltage"), int) else None,
            battery_current=power.get("battery_current") if isinstance(power.get("battery_current"), int) else None,
            usb_voltage=power.get("usb_voltage") if isinstance(power.get("usb_voltage"), int) else None,
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


def _parse_snapshot(snapshot_data: dict[str, Any]) -> dict[str, Any]:
    """Derive the session fields from a ``/api/busy/snapshot`` payload.

    Shared by the REST poll and the WebSocket ``timer`` update (whose JSON
    snapshot is byte-identical to this endpoint), so the live timer/phase stays
    consistent across both paths.
    """
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

    # Expose the countdown as an absolute finish time: the frontend renders a
    # live "in N min" that ticks down between polls, so we don't need a fast
    # poll just to move a number. Frozen (None) while paused / not running.
    finishes_at: datetime | None = None
    if active and not paused and time_left is not None:
        finishes_at = dt_util.utcnow() + timedelta(seconds=time_left)

    return {
        "snapshot_type": stype,
        "theme": theme,
        "active": active,
        "paused": paused,
        "phase": phase,
        "time_remaining_sec": time_left,
        "finishes_at": finishes_at,
        "current_interval": interval_no,
    }


def _phase_from_snapshot(stype: str, paused: bool, interval_no: int | None) -> str:
    if stype == "NOT_STARTED":
        return "idle"
    if paused:
        return "paused"
    if stype == "INTERVAL" and interval_no is not None:
        # current_interval is the firmware's 0-based interval index; its parity is
        # the phase: even (incl. the initial 0) = Work, odd = Rest. Mirrors
        # busy_timer.c `is_rest = state->index % 2`.
        return "work" if interval_no % 2 == 0 else "break"
    return "work"
