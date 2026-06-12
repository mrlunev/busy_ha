"""WebSocket state-stream client for the BUSY Bar (`/api/status/ws`).

The device pushes a protobuf stream (schema `BSB_State.State`) over WebSocket:
real-time status deltas plus physical input events (buttons, rotary selector,
encoder). This wraps :meth:`busylib.AsyncBusyBar.stream_status_ws` (which does
the protobuf decoding) with reconnect/backoff, drops the high-volume screen
``frame`` updates, and hands decoded updates to callbacks.

The coordinator merges status updates into its data for push refreshes (with
REST polling kept as the fallback), and forwards input events onto the HA event
bus for automations / device triggers.

Design notes:
- ``busylib`` is imported lazily so the integration keeps working on REST
  polling alone if a ``busylib`` build without the status-stream client is
  installed (the WS feature simply stays dormant).
- proto3 omits zero-valued fields, so a missing ``button``/``action``/
  ``position``/``delta`` key means the enum/number default — the parsers below
  fill those defaults in explicitly.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

_LOGGER = logging.getLogger(__name__)

# StateUpdate oneof field names (proto field names, preserved by busylib's
# MessageToDict(preserving_proto_field_name=True)).
_FRAME_KEY = "frame"
_INPUT_KEY = "input"

# Input oneof + enum defaults (see module docstring on omitted proto3 zeros).
_DEFAULT_BUTTON = "OK"
_DEFAULT_ACTION = "PRESS"
_DEFAULT_POSITION = "BUSY"

# Reconnect backoff (seconds): grows geometrically, capped, reset on healthy data.
_BACKOFF_START = 1.0
_BACKOFF_MAX = 60.0


@dataclass(frozen=True)
class InputEvent:
    """A decoded physical input event from the bar.

    ``kind`` is one of ``"button"``, ``"selector"`` or ``"encoder"``; only the
    fields relevant to that kind are populated.
    """

    kind: str
    button: str | None = None  # OK / BACK / START
    action: str | None = None  # PRESS / RELEASE
    position: str | None = None  # BUSY / CUSTOM / OFF / APPS / SETTINGS
    delta: int | None = None


def parse_input_event(event: dict[str, Any]) -> InputEvent | None:
    """Decode one ``InputEvent`` dict into an :class:`InputEvent`, or None."""
    if "button_event" in event:
        body = event.get("button_event") or {}
        return InputEvent(
            "button",
            button=body.get("button", _DEFAULT_BUTTON),
            action=body.get("action", _DEFAULT_ACTION),
        )
    if "switch_event" in event:
        body = event.get("switch_event") or {}
        return InputEvent("selector", position=body.get("position", _DEFAULT_POSITION))
    if "encoder_event" in event:
        body = event.get("encoder_event") or {}
        try:
            delta = int(body.get("delta", 0))
        except (TypeError, ValueError):
            delta = 0
        return InputEvent("encoder", delta=delta)
    return None


def decode_timer_snapshot(timer_update: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the JSON timer snapshot carried inside a ``timer`` update.

    The firmware packs the same JSON as ``/api/busy/snapshot`` into a protobuf
    ``bytes`` field, which ``MessageToDict`` base64-encodes as ``json.data``.
    """
    data = (timer_update.get("json") or {}).get("data")
    if not data:
        return None
    try:
        decoded = base64.b64decode(data)
        result = json.loads(decoded)
    except (binascii.Error, ValueError, TypeError):
        return None
    return result if isinstance(result, dict) else None


def split_message(
    message: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[InputEvent]]:
    """Split a decoded ``State`` message into (status updates, input events).

    Screen ``frame`` updates are dropped (high-volume, not used for status).
    """
    status: list[dict[str, Any]] = []
    inputs: list[InputEvent] = []
    for update in message.get("updates") or []:
        if not isinstance(update, dict):
            continue
        if _FRAME_KEY in update:
            continue
        if _INPUT_KEY in update:
            if (event := parse_input_event(update[_INPUT_KEY] or {})) is not None:
                inputs.append(event)
            continue
        status.append(update)
    return status, inputs


class BusyBarWsClient:
    """Manage a resilient WebSocket subscription to one bar's status stream.

    Lifecycle: :meth:`start` spawns a background task that connects, streams,
    and reconnects with backoff until :meth:`stop`. Decoded updates are routed
    to the supplied callbacks. The client never raises into the caller — failures
    are logged and retried, so the integration degrades to polling-only.
    """

    def __init__(
        self,
        host: str,
        token: str,
        *,
        on_status: Callable[[list[dict[str, Any]]], Awaitable[None]],
        on_input: Callable[[InputEvent], Awaitable[None]],
        on_connection_change: Callable[[bool], None] | None = None,
    ) -> None:
        self._host = host
        self._token = token
        self._on_status = on_status
        self._on_input = on_input
        self._on_connection_change = on_connection_change
        self._task: asyncio.Task[None] | None = None
        self._stopped = False
        self._connected = False

    @property
    def connected(self) -> bool:
        """Whether the WebSocket is currently streaming."""
        return self._connected

    def start(self) -> None:
        """Start the background streaming task (idempotent)."""
        if self._task is None or self._task.done():
            self._stopped = False
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Stop streaming and wait for the background task to finish."""
        self._stopped = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._set_connected(False)

    def _set_connected(self, value: bool) -> None:
        if value != self._connected:
            self._connected = value
            if self._on_connection_change is not None:
                self._on_connection_change(value)

    async def _run(self) -> None:
        try:
            from busylib import AsyncBusyBar  # noqa: PLC0415  (lazy: optional WS)
        except ImportError:
            _LOGGER.debug(
                "busylib status-stream client unavailable; "
                "BUSY Bar WS disabled, using REST polling only"
            )
            return

        loop = asyncio.get_running_loop()
        backoff = _BACKOFF_START
        while not self._stopped:
            try:
                # Constructing the client builds an httpx client whose default
                # SSL context loads CA certificates from disk synchronously;
                # keep that blocking I/O off the event loop.
                bar = await loop.run_in_executor(
                    None, partial(AsyncBusyBar, self._host, token=self._token or None)
                )
                async with bar:
                    async for message in bar.stream_status_ws():
                        if self._stopped:
                            break
                        self._set_connected(True)
                        backoff = _BACKOFF_START
                        if isinstance(message, dict):
                            await self._dispatch(message)
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE0001  (any failure → retry)
                _LOGGER.debug("BUSY Bar WS stream error (will retry): %s", err)
            finally:
                self._set_connected(False)

            if self._stopped:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)

    async def _dispatch(self, message: dict[str, Any]) -> None:
        status, inputs = split_message(message)
        if status:
            await self._on_status(status)
        for event in inputs:
            await self._on_input(event)
