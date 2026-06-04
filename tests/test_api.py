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


class _RecordingResponse:
    def __init__(self, status: int = 200, body: str = "{}") -> None:
        self.status = status
        self._body = body

    async def text(self) -> str:
        return self._body

    async def json(self):
        return json.loads(self._body or "{}")

    async def __aenter__(self) -> "_RecordingResponse":
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


class _RecordingSession:
    """Captures every request so we can assert method/path/params/json."""

    def __init__(self, body: str = "{}", status: int = 200) -> None:
        self.body = body
        self.status = status
        self.calls: list[tuple] = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, kwargs))
        return _RecordingResponse(self.status, self.body)

    @property
    def last(self) -> tuple:
        return self.calls[-1]


def _api(body: str = "{}", status: int = 200) -> tuple[BusyBarApi, _RecordingSession]:
    session = _RecordingSession(body, status)
    return BusyBarApi("1.2.3.4", "", session), session


def test_host_normalisation() -> None:
    api, session = _api()
    assert api._base == "http://1.2.3.4"
    api2 = BusyBarApi("http://10.0.0.5/", "", session)
    assert api2._base == "http://10.0.0.5"


async def test_get_endpoints_use_expected_paths() -> None:
    api, session = _api(body='{"ok": true}')
    expected = {
        api.get_name: "/api/name",
        api.get_status: "/api/status",
        api.get_snapshot: "/api/busy/snapshot",
        api.get_brightness: "/api/display/brightness",
        api.get_volume: "/api/audio/volume",
        api.get_wifi_status: "/api/wifi/status",
        api.get_pairing: "/api/smart_home/pairing",
        api.get_update_status: "/api/update/status",
        api.get_smart_home_switch: "/api/smart_home/switch",
        api.get_ble_status: "/api/ble/status",
    }
    for fn, path in expected.items():
        await fn()
        method, url, _ = session.last
        assert method == "GET"
        assert url == f"http://1.2.3.4{path}"


async def test_setters_send_params_and_bodies() -> None:
    api, session = _api()
    await api.set_brightness(50)
    assert session.last[2]["params"] == {"value": "50"}

    await api.set_volume(30)
    assert session.last[2]["params"] == {"volume": 30, "silent": 1}

    await api.send_key("ok")
    assert session.last[:2] == ("POST", "http://1.2.3.4/api/input")
    assert session.last[2]["params"] == {"key": "ok"}

    await api.install_update("1.2.3")
    assert session.last[2]["params"] == {"version": "1.2.3"}

    await api.set_smart_home_switch(True)
    assert session.last[2]["json"] == {"state": True}

    await api.draw({"foo": "bar"})
    assert session.last[:2] == ("POST", "http://1.2.3.4/api/display/draw")

    await api.play_audio({"a": 1})
    assert session.last[:2] == ("POST", "http://1.2.3.4/api/audio/play")


async def test_clear_display_params() -> None:
    api, session = _api()
    await api.clear_display("busybar")
    assert session.last[0] == "DELETE"
    assert session.last[2]["params"] == {"application_name": "busybar"}
    await api.clear_display()
    assert session.last[2]["params"] is None


async def test_get_screen_b64_paths() -> None:
    api, _ = _api(body="QUJD\n")
    assert await api.get_screen_b64() == "QUJD"

    api401, _ = _api(status=401)
    with pytest.raises(BusyBarAuthError):
        await api401.get_screen_b64()

    api500, _ = _api(status=500)
    with pytest.raises(BusyBarApiError):
        await api500.get_screen_b64()


async def test_start_helpers_build_snapshots() -> None:
    api, session = _api()
    await api.start_infinite("flow")
    assert session.last[:2] == ("PUT", "http://1.2.3.4/api/busy/snapshot")
    assert session.last[2]["json"]["snapshot"]["type"] == "INFINITE"

    await api.start_simple("flow", 10)
    snap = session.last[2]["json"]["snapshot"]
    assert snap["type"] == "SIMPLE" and snap["time_left_ms"] == 600000

    await api.start_pomodoro("flow", 25, 5, 4)
    snap = session.last[2]["json"]["snapshot"]
    assert snap["type"] == "INTERVAL"
    assert snap["interval_settings"]["interval_work_cycles_count"] == 4

    await api.stop_busy()
    assert session.last[2]["json"]["snapshot"]["type"] == "NOT_STARTED"


async def test_start_profile_builds_snapshot_from_preset() -> None:
    """start_profile reads the slot preset and PUTs a matching snapshot."""
    profile = json.dumps(
        {
            "title": "study",
            "timer_settings": {
                "type": "INTERVAL",
                "interval_work_ms": 1500000,
                "interval_rest_ms": 300000,
                "interval_work_cycles_count": 4,
                "is_autostart_enabled": True,
            },
            "busy_bar_settings": {"theme": "flow"},
        }
    )
    api, session = _api(body=profile)
    await api.start_profile("custom")
    # First call reads the preset slot, last call writes the running snapshot.
    assert session.calls[0][:2] == ("GET", "http://1.2.3.4/api/busy/profiles/custom")
    assert session.last[:2] == ("PUT", "http://1.2.3.4/api/busy/snapshot")
    snap = session.last[2]["json"]["snapshot"]
    assert snap["type"] == "INTERVAL"
    assert snap["current_interval_time_total_ms"] == 1500000
    assert snap["interval_settings"]["interval_rest_ms"] == 300000
    assert snap["busy_bar_settings"]["theme"] == "flow"


async def test_set_theme_requires_session() -> None:
    active, session = _api(body='{"snapshot": {"type": "SIMPLE", "busy_bar_settings": {}}}')
    await active.set_theme("flow")
    assert any(c[0] == "PUT" for c in session.calls)
    assert session.last[2]["json"]["snapshot"]["busy_bar_settings"]["theme"] == "flow"

    idle, _ = _api(body='{"snapshot": {"type": "NOT_STARTED"}}')
    with pytest.raises(BusyBarApiError):
        await idle.set_theme("flow")


async def test_pause_resume_toggle_is_paused() -> None:
    paused, session = _api(body='{"snapshot": {"type": "SIMPLE"}}')
    await paused.pause_busy()
    assert session.last[0] == "PUT"
    assert session.last[2]["json"]["snapshot"]["is_paused"] is True

    resumed, session2 = _api(body='{"snapshot": {"type": "SIMPLE", "is_paused": true}}')
    await resumed.resume_busy()
    assert session2.last[2]["json"]["snapshot"]["is_paused"] is False

    idle, idle_session = _api(body='{"snapshot": {"type": "NOT_STARTED"}}')
    await idle.pause_busy()
    # No write when there is nothing running.
    assert all(c[0] != "PUT" for c in idle_session.calls)
