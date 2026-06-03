"""Config-flow tests for BUSY Bar."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from homeassistant.config_entries import SOURCE_DHCP, SOURCE_REAUTH, SOURCE_USER
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.busybar.api import BusyBarApiError, BusyBarAuthError
from custom_components.busybar.const import CONF_TOKEN, DOMAIN

from .conftest import SERIAL, USER_INPUT


async def test_user_flow_success(
    hass: HomeAssistant, mock_api: AsyncMock, mock_setup_entry: AsyncMock
) -> None:
    """A valid host/token creates an entry keyed by the device serial."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Office Bar"
    assert result["result"].unique_id == SERIAL
    assert result["data"] == USER_INPUT


async def test_user_flow_without_token(
    hass: HomeAssistant, mock_api: AsyncMock, mock_setup_entry: AsyncMock
) -> None:
    """A device without Password protection is added with an empty token."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.50"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_HOST: "192.168.1.50", CONF_TOKEN: ""}


async def test_user_flow_unsupported_version(
    hass: HomeAssistant, mock_api: AsyncMock
) -> None:
    """Firmware below the supported API major is rejected with a clear error."""
    mock_api.get_status.return_value = {
        "device": {"serial_number": SERIAL},
        "system": {"api_semver": "22.9.9"},
    }
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unsupported_version"}


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (BusyBarAuthError("bad"), "invalid_auth"),
        (BusyBarApiError("down"), "cannot_connect"),
    ],
)
async def test_user_flow_errors(
    hass: HomeAssistant, mock_api: AsyncMock, error: Exception, reason: str
) -> None:
    """Auth/connection failures surface as recoverable form errors."""
    mock_api.get_status.side_effect = error
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": reason}

    # Recovery: clearing the error lets the flow complete.
    mock_api.get_status.side_effect = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_already_configured(
    hass: HomeAssistant, mock_api: AsyncMock, mock_setup_entry: AsyncMock
) -> None:
    """A second entry with the same serial aborts and updates the host."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SERIAL, data=USER_INPUT)
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.99", CONF_TOKEN: "tok-123"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == "192.168.1.99"


DHCP_INFO = DhcpServiceInfo(
    ip="192.168.1.77", hostname="mlunev_green", macaddress="8c8b48bc27b8"
)


async def test_dhcp_discovery_success(
    hass: HomeAssistant, mock_api: AsyncMock, mock_setup_entry: AsyncMock
) -> None:
    """A bar found via DHCP confirms and is added (empty token, serial unique_id)."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP_INFO
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "discovery_confirm"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == SERIAL
    assert result["data"] == {CONF_HOST: "http://192.168.1.77", CONF_TOKEN: ""}


async def test_dhcp_discovery_self_heals_host(
    hass: HomeAssistant, mock_api: AsyncMock, mock_setup_entry: AsyncMock
) -> None:
    """A DHCP hit for an already-configured bar silently updates its host (new IP)."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SERIAL, data=USER_INPUT)
    entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP_INFO
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_HOST] == "http://192.168.1.77"


async def test_dhcp_discovery_cannot_connect(
    hass: HomeAssistant, mock_api: AsyncMock
) -> None:
    """If the discovered host is unreachable the flow aborts cleanly."""
    mock_api.get_status.side_effect = BusyBarApiError("down")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=DHCP_INFO
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_reauth_success(
    hass: HomeAssistant, mock_api: AsyncMock, mock_setup_entry: AsyncMock
) -> None:
    """Re-auth updates the token on the existing entry."""
    entry = MockConfigEntry(domain=DOMAIN, unique_id=SERIAL, data=USER_INPUT)
    entry.add_to_hass(hass)

    result = await entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_TOKEN: "new-token"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_TOKEN] == "new-token"
