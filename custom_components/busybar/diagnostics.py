"""Diagnostics support for BUSY Bar."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .const import CONF_TOKEN
from .coordinator import BusyBarConfigEntry

# Identifiers that pin the bar to a person/network are redacted: the API token,
# the host/IP, the hardware serial (== unique_id) and the MAC addresses.
TO_REDACT = {
    CONF_TOKEN,
    CONF_HOST,
    "serial_number",
    "wifi_mac",
    "usb_mac",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BusyBarConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "entry": {
            "title": entry.title,
            "source": entry.source,
            "unique_id": "**REDACTED**" if entry.unique_id else None,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval": str(coordinator.update_interval),
            "data": async_redact_data(asdict(coordinator.data), TO_REDACT),
        },
    }
