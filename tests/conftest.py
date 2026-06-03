"""Fixtures for BUSY Bar tests."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_socket

from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.busybar.const import CONF_TOKEN, DOMAIN

pytest_plugins = ["pytest_homeassistant_custom_component"]

# The HA test plugin disables socket creation for every test. On Windows that
# breaks asyncio's event-loop self-pipe (socket.socketpair), erroring at setup.
# All device network access is mocked here, so neutralise the block by making
# disable_socket a no-op before the plugin's pytest_runtest_setup hook runs.
pytest_socket.disable_socket = lambda *args, **kwargs: None  # type: ignore[assignment]

SERIAL = "203638485431500400123456"

# A healthy /api/status payload for a charging, online bar on firmware 0.9.2.
STATUS = {
    "device": {"serial_number": SERIAL, "wifi_mac": "0c:fa:22:21:2a:31"},
    "power": {"state": "charging", "battery_charge": 80, "battery_voltage": 4100},
    "system": {"api_semver": "23.0.0", "uptime": "00d 01h", "boot_time": 1767225600},
    "firmware": {"version": "0.9.2-rc"},
}
SNAPSHOT_IDLE = {"snapshot": {"type": "NOT_STARTED", "busy_bar_settings": {"theme": "red"}}}
SNAPSHOT_ACTIVE = {
    "snapshot": {
        "type": "SIMPLE",
        "time_left_ms": 600000,
        "is_paused": False,
        "busy_bar_settings": {"theme": "meeting"},
    }
}


def make_api(**overrides: Any) -> AsyncMock:
    """Build a fully-mocked BusyBarApi with healthy defaults."""
    api = AsyncMock()
    api.get_name.return_value = {"name": "Office Bar"}
    api.get_status.return_value = STATUS
    api.get_snapshot.return_value = SNAPSHOT_IDLE
    api.get_brightness.return_value = {"value": "50"}
    api.get_volume.return_value = {"volume": 30}
    api.get_wifi_status.return_value = {"rssi": -50}
    api.get_smart_home_switch.return_value = {"state": False}
    api.get_pairing.return_value = {"fabric_count": 1}
    api.get_update_status.return_value = {}
    for key, value in overrides.items():
        getattr(api, key).return_value = value
    return api


async def setup_busybar(
    hass: HomeAssistant, api: AsyncMock, token: str = ""
) -> MockConfigEntry:
    """Add a config entry and run a full setup with the given mocked API."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SERIAL,
        data={CONF_HOST: "1.2.3.4", CONF_TOKEN: token},
    )
    entry.add_to_hass(hass)
    with patch("custom_components.busybar.BusyBarApi", return_value=api):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations, socket_enabled):
    """Enable loading of the custom component in every test.

    ``socket_enabled`` re-enables sockets that pytest-socket blocks by default;
    on Windows asyncio's event-loop self-pipe needs them or every test errors.
    """
    yield


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Avoid real setup during config-flow tests."""
    with patch(
        "custom_components.busybar.async_setup_entry", return_value=True
    ) as mock:
        yield mock


@pytest.fixture
def mock_api() -> Generator[AsyncMock]:
    """Mock the device API used by the config flow."""
    with patch(
        "custom_components.busybar.config_flow.BusyBarApi", autospec=True
    ) as api_cls:
        api = api_cls.return_value
        api.get_status = AsyncMock(
            return_value={"device": {"serial_number": SERIAL}}
        )
        api.get_name = AsyncMock(return_value={"name": "Office Bar"})
        yield api


USER_INPUT = {CONF_HOST: "192.168.1.50", CONF_TOKEN: "tok-123"}
