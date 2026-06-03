"""Tests for the diagnostics dump."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.busybar.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import make_api, setup_busybar


async def test_diagnostics_redacts_sensitive_fields(hass: HomeAssistant) -> None:
    """The dump must not leak token, host, serial or MAC addresses."""
    api = make_api()
    entry = await setup_busybar(hass, api, token="super-secret")

    diag = await async_get_config_entry_diagnostics(hass, entry)

    assert diag["entry"]["unique_id"] == "**REDACTED**"
    assert diag["entry"]["data"]["host"] == "**REDACTED**"
    assert diag["entry"]["data"]["token"] == "**REDACTED**"
    assert diag["coordinator"]["data"]["serial_number"] == "**REDACTED**"
    assert diag["coordinator"]["data"]["wifi_mac"] == "**REDACTED**"
    # Non-sensitive runtime stays visible for debugging.
    assert diag["coordinator"]["data"]["firmware_version"] == "0.9.2-rc"
    assert diag["coordinator"]["last_update_success"] is True
