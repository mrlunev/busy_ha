"""Fixtures for BUSY Bar tests."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.const import CONF_HOST

from custom_components.busybar.const import CONF_TOKEN, DOMAIN

pytest_plugins = ["pytest_homeassistant_custom_component"]

SERIAL = "203638485431500400123456"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading of the custom component in every test."""
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
