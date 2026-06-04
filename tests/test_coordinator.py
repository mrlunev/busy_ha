"""Coordinator parsing and resiliency tests."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from custom_components.busybar.api import BusyBarApiError
from custom_components.busybar.const import DOMAIN

from .conftest import SERIAL, SNAPSHOT_ACTIVE, make_api, setup_busybar


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


async def test_finishes_at_set_while_running(hass: HomeAssistant) -> None:
    """A running timer exposes an absolute finish time; idle exposes none."""
    api = make_api(get_snapshot=SNAPSHOT_ACTIVE)
    entry = await setup_busybar(hass, api)
    data = entry.runtime_data.data
    assert data.time_remaining_sec == 600
    assert data.finishes_at is not None
    # ~10 min out (600 s), allow generous slack for test execution time.
    delta = (data.finishes_at - dt_util.utcnow()).total_seconds()
    assert 540 < delta <= 600


async def test_finishes_at_none_when_idle(hass: HomeAssistant) -> None:
    """No countdown timestamp when the bar is not running a session."""
    entry = await setup_busybar(hass, make_api())
    assert entry.runtime_data.data.finishes_at is None


async def test_finishes_at_none_when_paused(hass: HomeAssistant) -> None:
    """A paused timer freezes the countdown (no live finish timestamp)."""
    api = make_api(
        get_snapshot={
            "snapshot": {
                "type": "SIMPLE",
                "time_left_ms": 300000,
                "is_paused": True,
            }
        }
    )
    entry = await setup_busybar(hass, api)
    assert entry.runtime_data.data.finishes_at is None


async def test_tiered_polling_skips_slow_endpoints(hass: HomeAssistant) -> None:
    """Rare endpoints are not re-fetched on an in-between fast cycle."""
    api = make_api()
    entry = await setup_busybar(hass, api)
    coordinator = entry.runtime_data
    # First refresh (cycle 0) fetched everything.
    assert api.get_pairing.call_count == 1
    assert api.get_brightness.call_count == 1
    assert api.get_status.call_count == 1

    # Cycle 1 is fast-only: status/snapshot/name re-fetched, the rest cached.
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert api.get_status.call_count == 2
    assert api.get_name.call_count == 2
    assert api.get_brightness.call_count == 1  # medium tier skipped
    assert api.get_pairing.call_count == 1  # slow tier skipped
    # Cached values are still surfaced.
    assert coordinator.data.brightness == "50"
    assert coordinator.data.smart_home_available is True


async def test_full_refresh_fetches_all_tiers(hass: HomeAssistant) -> None:
    """A user-initiated full refresh re-fetches the medium and slow tiers."""
    api = make_api()
    entry = await setup_busybar(hass, api)
    coordinator = entry.runtime_data
    assert api.get_brightness.call_count == 1
    assert api.get_pairing.call_count == 1

    await coordinator.async_request_refresh_full()
    await hass.async_block_till_done()
    assert api.get_brightness.call_count == 2
    assert api.get_pairing.call_count == 2


async def test_device_name_is_synced_on_rename(hass: HomeAssistant) -> None:
    """A rename on the bar's web UI propagates into the HA device registry."""
    api = make_api()
    entry = await setup_busybar(hass, api)
    api.get_name.return_value = {"name": "Kitchen Bar"}
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, SERIAL)})
    assert device is not None and device.name == "Kitchen Bar"
