"""Setup/unload tests — exercise coordinator, platforms and entities end to end."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.busybar.api import BusyBarApiError, BusyBarAuthError
from custom_components.busybar.const import CONF_TOKEN, DOMAIN

from .conftest import SERIAL

STATUS = {
    "device": {"serial_number": SERIAL, "wifi_mac": "0c:fa:22:21:2a:31"},
    "power": {"state": "charging", "battery_charge": 80},
    "system": {"api_semver": "23.0.0", "uptime": "00d 01h", "boot_time": 1767225600},
    "firmware": {"version": "0.9.2-rc"},
}
SNAPSHOT = {"snapshot": {"type": "NOT_STARTED", "busy_bar_settings": {"theme": "red"}}}


def _mock_api() -> AsyncMock:
    api = AsyncMock()
    api.get_name.return_value = {"name": "Office Bar"}
    api.get_status.return_value = STATUS
    api.get_snapshot.return_value = SNAPSHOT
    api.get_brightness.return_value = {"value": "50"}
    api.get_volume.return_value = {"volume": 30}
    api.get_wifi_status.return_value = {"rssi": -50}
    api.get_smart_home_switch.return_value = {"state": False}
    api.get_pairing.return_value = {"fabric_count": 0}
    api.get_update_status.return_value = {}
    return api


def _entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SERIAL,
        data={CONF_HOST: "1.2.3.4", CONF_TOKEN: ""},
    )
    entry.add_to_hass(hass)
    return entry


async def test_setup_and_unload(hass: HomeAssistant) -> None:
    """A healthy device loads entities + services and unloads cleanly."""
    entry = _entry(hass)
    with patch("custom_components.busybar.BusyBarApi", return_value=_mock_api()):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert len(hass.states.async_all()) > 10
    assert hass.services.has_service(DOMAIN, "notify")

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_connectivity_reports_offline_but_stays_available(
    hass: HomeAssistant,
) -> None:
    """The connectivity sensor flips to 'off' (not 'unavailable') when unreachable."""
    api = _mock_api()
    entry = _entry(hass)
    with patch("custom_components.busybar.BusyBarApi", return_value=api):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        conn_id = "binary_sensor.office_bar_connectivity"
        assert hass.states.get(conn_id).state == "on"

        api.get_status.side_effect = BusyBarApiError("device offline")
        await entry.runtime_data.async_refresh()
        await hass.async_block_till_done()

    # Other entities go unavailable; connectivity stays available and reports off.
    assert hass.states.get("sensor.office_bar_battery").state == "unavailable"
    assert hass.states.get(conn_id).state == "off"


async def test_setup_serial_mismatch_is_not_ready(hass: HomeAssistant) -> None:
    """Host pointing at a DIFFERENT bar (serial mismatch) must not load that data."""
    api = _mock_api()
    api.get_status.return_value = {
        **STATUS,
        "device": {"serial_number": "203638485431500400999999"},
    }
    entry = _entry(hass)
    with patch("custom_components.busybar.BusyBarApi", return_value=api):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_auth_failure_triggers_reauth(hass: HomeAssistant) -> None:
    """A 401/403 during the first refresh fails setup into reauth."""
    api = _mock_api()
    api.get_status.side_effect = BusyBarAuthError("401")
    entry = _entry(hass)
    with patch("custom_components.busybar.BusyBarApi", return_value=api):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"].get("source") == "reauth" for f in flows)
