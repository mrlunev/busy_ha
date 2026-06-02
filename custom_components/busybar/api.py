"""HTTP client for BUSY Bar local API."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

class BusyBarApiError(Exception):
    """API request failed."""


class BusyBarAuthError(BusyBarApiError):
    """Authentication with the device failed (bad/expired token)."""


class BusyBarApi:
    """Thin wrapper over busybar-openapi endpoints."""

    def __init__(self, host: str, token: str, session: aiohttp.ClientSession) -> None:
        host = host.rstrip("/")
        if not host.startswith("http"):
            host = f"http://{host}"
        self._base = host
        self._token = token
        self._session = session

    def _headers(self) -> dict[str, str]:
        # Auth is optional on the device: only sent when the user enabled
        # "Password protection" and provided that password as the token.
        if self._token:
            return {"X-API-Token": self._token}
        return {}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
    ) -> Any:
        url = f"{self._base}{path}"
        async with self._session.request(
            method,
            url,
            headers=self._headers(),
            params=params,
            json=json,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            body = await resp.text()
            if resp.status in (401, 403):
                raise BusyBarAuthError(f"{method} {path} -> {resp.status}: {body[:200]}")
            if resp.status >= 400:
                raise BusyBarApiError(f"{method} {path} -> {resp.status}: {body[:200]}")
            if not body:
                return {}
            return await resp.json()

    async def get_name(self) -> dict:
        return await self._request("GET", "/api/name")

    async def get_status(self) -> dict:
        return await self._request("GET", "/api/status")

    async def get_wifi_status(self) -> dict:
        return await self._request("GET", "/api/wifi/status")

    async def get_snapshot(self) -> dict:
        return await self._request("GET", "/api/busy/snapshot")

    async def put_snapshot(self, snapshot: dict) -> dict:
        return await self._request("PUT", "/api/busy/snapshot", json=snapshot)

    async def get_brightness(self) -> dict:
        return await self._request("GET", "/api/display/brightness")

    async def set_brightness(self, value: int | str) -> dict:
        return await self._request("POST", "/api/display/brightness", params={"value": str(value)})

    async def get_volume(self) -> dict:
        return await self._request("GET", "/api/audio/volume")

    async def set_volume(self, volume: int, *, silent: bool = True) -> dict:
        return await self._request(
            "POST",
            "/api/audio/volume",
            params={"volume": volume, "silent": 1 if silent else 0},
        )

    async def get_screen_b64(self, display: int = 0) -> str:
        """Return the current display frame as a base64 string.

        ``/api/screen`` responds with ``Content-Type: image/bmp`` but the body
        is base64-encoded raw pixels (not a BMP file and not JSON), so this
        bypasses ``_request``'s JSON parsing.
        """
        url = f"{self._base}/api/screen"
        async with self._session.request(
            "GET",
            url,
            headers=self._headers(),
            params={"display": display},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            body = await resp.text()
            if resp.status in (401, 403):
                raise BusyBarAuthError(f"GET /api/screen -> {resp.status}")
            if resp.status >= 400:
                raise BusyBarApiError(f"GET /api/screen -> {resp.status}: {body[:200]}")
            return body.strip()

    async def get_pairing(self) -> dict:
        return await self._request("GET", "/api/smart_home/pairing")

    async def get_update_status(self) -> dict:
        return await self._request("GET", "/api/update/status")

    async def check_update(self) -> dict:
        return await self._request("POST", "/api/update/check")

    async def install_update(self, version: str) -> dict:
        return await self._request("POST", "/api/update/install", params={"version": version})

    async def get_smart_home_switch(self) -> dict:
        return await self._request("GET", "/api/smart_home/switch")

    async def set_smart_home_switch(self, state: bool) -> dict:
        return await self._request(
            "POST",
            "/api/smart_home/switch",
            json={"state": state},
        )

    async def draw(self, payload: dict) -> dict:
        return await self._request("POST", "/api/display/draw", json=payload)

    async def clear_display(self, application_name: str | None = None) -> dict:
        params = {}
        if application_name:
            params["application_name"] = application_name
        return await self._request("DELETE", "/api/display/draw", params=params or None)

    async def play_audio(self, payload: dict) -> dict:
        return await self._request("POST", "/api/audio/play", json=payload)

    async def send_key(self, key: str) -> dict:
        return await self._request("POST", "/api/input", params={"key": key})

    async def stop_busy(self) -> dict:
        return await self.put_snapshot(_not_started_snapshot())

    async def start_infinite(self, theme: str, *, trigger_smart_home: bool = True) -> dict:
        snap = {
            "snapshot": {
                "type": "INFINITE",
                "card_id": str(uuid.uuid4()),
                "is_paused": False,
                "busy_bar_settings": _busy_settings(theme, trigger_smart_home),
            },
            "snapshot_timestamp_ms": _now_ms(),
        }
        return await self.put_snapshot(snap)

    async def start_simple(
        self,
        theme: str,
        duration_minutes: int,
        *,
        trigger_smart_home: bool = True,
    ) -> dict:
        snap = {
            "snapshot": {
                "type": "SIMPLE",
                "card_id": str(uuid.uuid4()),
                "time_left_ms": duration_minutes * 60 * 1000,
                "is_paused": False,
                "busy_bar_settings": _busy_settings(theme, trigger_smart_home),
            },
            "snapshot_timestamp_ms": _now_ms(),
        }
        return await self.put_snapshot(snap)

    async def start_pomodoro(
        self,
        theme: str,
        work_minutes: int,
        break_minutes: int,
        cycles: int,
        *,
        trigger_smart_home: bool = True,
    ) -> dict:
        snap = {
            "snapshot": {
                "type": "INTERVAL",
                "card_id": str(uuid.uuid4()),
                "current_interval": 1,
                "current_interval_time_total_ms": work_minutes * 60 * 1000,
                "current_interval_time_left_ms": work_minutes * 60 * 1000,
                "is_paused": False,
                "interval_settings": {
                    "type": "INTERVAL",
                    "interval_work_ms": work_minutes * 60 * 1000,
                    "interval_rest_ms": break_minutes * 60 * 1000,
                    "interval_work_cycles_count": cycles,
                    "is_autostart_enabled": True,
                },
                "busy_bar_settings": _busy_settings(theme, trigger_smart_home),
            },
            "snapshot_timestamp_ms": _now_ms(),
        }
        return await self.put_snapshot(snap)

    async def set_theme(self, theme: str) -> dict:
        data = await self.get_snapshot()
        snap = data.get("snapshot") or {}
        if snap.get("type") == "NOT_STARTED":
            raise BusyBarApiError("No active session to change theme")
        settings = snap.setdefault("busy_bar_settings", _busy_settings(theme, True))
        settings["theme"] = theme
        data["snapshot_timestamp_ms"] = _now_ms()
        return await self.put_snapshot(data)

    async def pause_busy(self) -> dict:
        data = await self.get_snapshot()
        snap = data.get("snapshot") or {}
        if snap.get("type") == "NOT_STARTED":
            return data
        snap["is_paused"] = True
        data["snapshot_timestamp_ms"] = _now_ms()
        return await self.put_snapshot(data)

    async def resume_busy(self) -> dict:
        data = await self.get_snapshot()
        snap = data.get("snapshot") or {}
        if snap.get("type") == "NOT_STARTED":
            return data
        snap["is_paused"] = False
        data["snapshot_timestamp_ms"] = _now_ms()
        return await self.put_snapshot(data)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _busy_settings(theme: str, trigger_smart_home: bool) -> dict:
    return {
        "theme": theme,
        "show_work_phase_only": False,
        "trigger_smart_home": trigger_smart_home,
    }


def _not_started_snapshot() -> dict:
    return {
        "snapshot": {
            "type": "NOT_STARTED",
            "busy_bar_settings": _busy_settings("busy", False),
        },
        "snapshot_timestamp_ms": _now_ms(),
    }
