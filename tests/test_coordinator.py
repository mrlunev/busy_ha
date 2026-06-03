"""Coordinator parsing and resiliency tests."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.busybar.api import BusyBarApiError
from custom_components.busybar.const import DOMAIN

from .conftest import SERIAL, make_api, setup_busybar


async def test_interval_break_phase(hass: HomeAssistant) -> None:
    api = make_api(
        get_snapshot={
            "snapshot": {
                "type": "INTERVAL",
                "current_interval": 2,
                "current_interval_time_left_ms": 120000,
                "busy_bar_settings": {"theme": "flow"},
            }
        }
    )
    entry = await setup_busybar(hass, api)
    data = entry.runtime_data.data
    assert data.snapshot_type == "INTERVAL"
    assert data.current_interval == 2
    assert data.phase == "break"
    assert data.time_remaining_sec == 120


async def test_interval_work_phase(hass: HomeAssistant) -> None:
    api = make_api(
        get_snapshot={
            "snapshot": {
                "type": "INTERVAL",
                "current_interval": 1,
                "current_interval_time_left_ms": 60000,
            }
        }
    )
    entry = await setup_busybar(hass, api)
    assert entry.runtime_data.data.phase == "work"


async def test_optional_endpoint_failures_tolerated(hass: HomeAssistant) -> None:
    """smart_home/pairing/update endpoints failing must not break the update."""
    api = make_api()
    api.get_smart_home_switch.side_effect = BusyBarApiError("503")
    api.get_pairing.side_effect = BusyBarApiError("503")
    api.get_update_status.side_effect = BusyBarApiError("503")
    entry = await setup_busybar(hass, api)
    data = entry.runtime_data.data
    assert data.smart_home is None
    assert data.smart_home_available is False
    assert data.update_latest is None


async def test_device_name_is_synced_on_rename(hass: HomeAssistant) -> None:
    """A rename on the bar's web UI propagates into the HA device registry."""
    api = make_api()
    entry = await setup_busybar(hass, api)
    api.get_name.return_value = {"name": "Kitchen Bar"}
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, SERIAL)})
    assert device is not None and device.name == "Kitchen Bar"
