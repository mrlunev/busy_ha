"""Unit tests for the BUSY Bar HTTP API client."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from custom_components.busybar.api import (
    BusyBarApi,
    BusyBarApiError,
    BusyBarAuthError,
)


class _FakeResponse:
    """Minimal async-context-manager stand-in for an aiohttp response."""

    def __init__(self, status: int, body: str = "") -> None:
        self.status = status
        self._body = body

    async def text(self) -> str:
        return self._body

    async def json(self):
        return json.loads(self._body or "{}")

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


def _session(resp: _FakeResponse) -> MagicMock:
    session = MagicMock()
    session.request = MagicMock(return_value=resp)
    return session


@pytest.mark.parametrize("status", [401, 403])
async def test_auth_status_raises_auth_error(status: int) -> None:
    """401/403 must map to BusyBarAuthError so reauth/invalid_auth can trigger."""
    api = BusyBarApi("1.2.3.4", "tok", _session(_FakeResponse(status, "nope")))
    with pytest.raises(BusyBarAuthError):
        await api.get_status()


@pytest.mark.parametrize("status", [400, 500, 503])
async def test_other_errors_raise_generic(status: int) -> None:
    """Non-auth 4xx/5xx stay BusyBarApiError (not auth)."""
    api = BusyBarApi("1.2.3.4", "tok", _session(_FakeResponse(status, "boom")))
    with pytest.raises(BusyBarApiError) as err:
        await api.get_status()
    assert not isinstance(err.value, BusyBarAuthError)


async def test_empty_token_omits_header() -> None:
    """Local-only use needs no token → X-API-Token header must be absent."""
    session = _session(_FakeResponse(200, "{}"))
    api = BusyBarApi("1.2.3.4", "", session)
    await api.get_status()
    assert "X-API-Token" not in session.request.call_args.kwargs["headers"]


async def test_token_sets_header() -> None:
    """When a token is configured it is sent as X-API-Token."""
    session = _session(_FakeResponse(200, "{}"))
    api = BusyBarApi("1.2.3.4", "secret", session)
    await api.get_status()
    assert session.request.call_args.kwargs["headers"]["X-API-Token"] == "secret"
