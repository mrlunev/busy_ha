"""BUSY Bar integration for Home Assistant."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_AREA_ID, ATTR_DEVICE_ID, ATTR_ENTITY_ID, CONF_HOST
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .api import BusyBarApi, BusyBarApiError
from .const import (
    APPLICATION_NAME,
    CONF_TOKEN,
    DOMAIN,
    PRIORITY_DEFAULT,
    PRIORITY_INTERRUPT,
    STOCK_SOUNDS,
    THEMES,
)
from .coordinator import BusyBarConfigEntry, BusyBarCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    "binary_sensor",
    "button",
    "image",
    "number",
    "select",
    "sensor",
    "switch",
    "update",
]

SERVICE_NOTIFY = "notify"
SERVICE_DISPLAY_TEXT = "display_text"
SERVICE_DISPLAY_IMAGE = "display_image"
SERVICE_DISPLAY_ANIMATION = "display_animation"
SERVICE_DISPLAY_COUNTDOWN = "display_countdown"
SERVICE_START_BUSY = "start_busy"
SERVICE_START_POMODORO = "start_pomodoro"
SERVICE_STOP_BUSY = "stop_busy"
SERVICE_PAUSE_BUSY = "pause_busy"
SERVICE_RESUME_BUSY = "resume_busy"
SERVICE_SET_THEME = "set_theme"
SERVICE_PLAY_SOUND = "play_sound"
SERVICE_CLEAR = "clear"


def _rgb_to_hexaa(rgb: list[int]) -> str:
    r, g, b = (int(rgb[0]), int(rgb[1]), int(rgb[2])) if len(rgb) >= 3 else (255, 255, 255)
    return f"#{r:02X}{g:02X}{b:02X}FF"


def _ascii(text: str) -> str:
    """Device fonts render printable ASCII only; replace anything else.

    The TextElement schema enforces ``^[\\x20-\\x7E]+$`` (min length 1), so
    non-ASCII input (Cyrillic, emoji, …) would be rejected with HTTP 400.
    """
    cleaned = "".join(ch if 0x20 <= ord(ch) <= 0x7E else "?" for ch in text)
    return cleaned or " "


def _displays(display: str) -> list[str]:
    if display == "both":
        return ["front", "back"]
    return [display]


def _asset_ref(value: str) -> dict:
    """Map an asset string to {stock_path} or {path}.

    Stock assets shipped in firmware live under "shared/" (e.g.
    "shared/laundry.png"); anything else is treated as an app asset path.
    """
    if value.startswith("shared/"):
        return {"stock_path": value}
    return {"path": value}


# Optional target keys. Unlike cv.make_entity_service_schema, these do NOT
# require a target: with a single bar HA addresses it implicitly (the spec
# promise "target можно опустить"). When a target is given it flows into
# call.data and is resolved by _coordinators().
_TARGET_FIELDS = {
    vol.Optional(ATTR_ENTITY_ID): cv.entity_ids,
    vol.Optional(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(ATTR_AREA_ID): vol.All(cv.ensure_list, [cv.string]),
}


def _schema(fields: dict) -> vol.Schema:
    return vol.Schema({**fields, **_TARGET_FIELDS})


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register integration-wide service actions (available without a loaded entry)."""
    _register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: BusyBarConfigEntry) -> bool:
    """Set up BUSY Bar from config entry."""
    session = async_get_clientsession(hass)
    api = BusyBarApi(entry.data[CONF_HOST], entry.data[CONF_TOKEN], session)
    coordinator = BusyBarCoordinator(hass, api, entry)

    # Raises ConfigEntryNotReady (transient) or ConfigEntryAuthFailed (bad token,
    # triggers reauth) on failure — see coordinator._async_update_data.
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BusyBarConfigEntry) -> bool:
    """Unload entry. Services stay registered (registered in async_setup)."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_NOTIFY):
        return

    def _coordinators(call: ServiceCall) -> list[BusyBarCoordinator]:
        # Key by the device-identifier value (hardware serial, == entry.unique_id),
        # matching DeviceInfo.identifiers so target-by-device resolution works.
        loaded: dict[str, BusyBarCoordinator] = {
            (entry.unique_id or entry.entry_id): entry.runtime_data
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.state is ConfigEntryState.LOADED and entry.runtime_data is not None
        }
        if not loaded:
            raise ServiceValidationError("No loaded BUSY Bar config entry")

        dev_reg = dr.async_get(hass)
        ent_reg = er.async_get(hass)

        device_ids: set[str] = set(call.data.get(ATTR_DEVICE_ID, []) or [])
        for area_id in call.data.get(ATTR_AREA_ID, []) or []:
            for device in dr.async_entries_for_area(dev_reg, area_id):
                device_ids.add(device.id)
        for entity_id in call.data.get(ATTR_ENTITY_ID, []) or []:
            ent = ent_reg.async_get(entity_id)
            if ent and ent.device_id:
                device_ids.add(ent.device_id)

        # No explicit target: address all loaded bars (single-bar setups address implicitly).
        if not device_ids:
            return list(loaded.values())

        out: list[BusyBarCoordinator] = []
        for device_id in device_ids:
            device = dev_reg.async_get(device_id)
            if not device:
                continue
            for ident in device.identifiers:
                if ident[0] == DOMAIN and (coord := loaded.get(ident[1])) and coord not in out:
                    out.append(coord)
        if not out:
            raise ServiceValidationError("Target is not a BUSY Bar device")
        return out

    def _register(name: str, handler, schema: vol.Schema) -> None:
        """Register a service, surfacing device/API errors as HomeAssistantError."""

        async def wrapped(call: ServiceCall) -> None:
            try:
                await handler(call)
            except BusyBarApiError as err:
                raise HomeAssistantError(str(err)) from err

        hass.services.async_register(DOMAIN, name, wrapped, schema=schema)

    async def _notify(call: ServiceCall) -> None:
        message = call.data["message"]
        title = call.data.get("title")
        color = call.data.get("color", [255, 255, 255])
        sound = call.data.get("sound", "none")
        display = call.data.get("display", "front")
        duration = int(call.data.get("duration", 10))
        interrupt = call.data.get("interrupt", False)
        priority = PRIORITY_INTERRUPT if interrupt else PRIORITY_DEFAULT
        hex_color = _rgb_to_hexaa(color)

        for coord in _coordinators(call):
            elements = []
            eid = 0
            for disp in _displays(display):
                if title:
                    elements.append(
                        {
                            "id": str(eid),
                            "type": "text",
                            "text": _ascii(title[:40]),
                            "font": "bold",
                            "color": hex_color,
                            "display": disp,
                            "align": "top_mid",
                            "timeout": duration,
                        }
                    )
                    eid += 1
                elements.append(
                    {
                        "id": str(eid),
                        "type": "text",
                        "text": _ascii(message[:80]),
                        "font": "normal",
                        "color": hex_color,
                        "display": disp,
                        "align": "center",
                        "timeout": duration,
                        "scroll_rate": 1200 if len(message) > 12 else 0,
                    }
                )
                eid += 1
            await coord.api.draw(
                {
                    "application_name": APPLICATION_NAME,
                    "priority": priority,
                    "elements": elements,
                }
            )
            if sound and sound != "none" and sound in STOCK_SOUNDS:
                await coord.api.play_audio(
                    {
                        "application_name": APPLICATION_NAME,
                        "stock_path": STOCK_SOUNDS[sound],
                    }
                )
            await coord.async_request_refresh()

    async def _display_text(call: ServiceCall) -> None:
        text = call.data["text"]
        color = call.data.get("color", [255, 255, 255])
        display = call.data.get("display", "front")
        duration = int(call.data.get("duration", 0))
        interrupt = call.data.get("interrupt", False)
        priority = PRIORITY_INTERRUPT if interrupt else PRIORITY_DEFAULT
        hex_color = _rgb_to_hexaa(color)
        for coord in _coordinators(call):
            elements = []
            for i, disp in enumerate(_displays(display)):
                elements.append(
                    {
                        "id": str(i),
                        "type": "text",
                        "text": _ascii(text[:80]),
                        "font": "normal",
                        "color": hex_color,
                        "display": disp,
                        "align": "center",
                        "timeout": duration,
                    }
                )
            await coord.api.draw(
                {
                    "application_name": APPLICATION_NAME,
                    "priority": priority,
                    "elements": elements,
                }
            )
            await coord.async_request_refresh()

    async def _display_image(call: ServiceCall) -> None:
        ref = _asset_ref(call.data["image"])
        display = call.data.get("display", "front")
        duration = int(call.data.get("duration", 0))
        interrupt = call.data.get("interrupt", False)
        priority = PRIORITY_INTERRUPT if interrupt else PRIORITY_DEFAULT
        for coord in _coordinators(call):
            elements = [
                {"id": str(i), "type": "image", "display": disp, "timeout": duration, **ref}
                for i, disp in enumerate(_displays(display))
            ]
            await coord.api.draw(
                {"application_name": APPLICATION_NAME, "priority": priority, "elements": elements}
            )
            await coord.async_request_refresh()

    async def _display_animation(call: ServiceCall) -> None:
        ref = _asset_ref(call.data["animation"])
        display = call.data.get("display", "front")
        loop = call.data.get("loop", True)
        duration = int(call.data.get("duration", 0))
        interrupt = call.data.get("interrupt", False)
        priority = PRIORITY_INTERRUPT if interrupt else PRIORITY_DEFAULT
        for coord in _coordinators(call):
            elements = [
                {"id": str(i), "type": "animation", "display": disp, "timeout": duration, "loop": loop, **ref}
                for i, disp in enumerate(_displays(display))
            ]
            await coord.api.draw(
                {"application_name": APPLICATION_NAME, "priority": priority, "elements": elements}
            )
            await coord.async_request_refresh()

    async def _display_countdown(call: ServiceCall) -> None:
        until = call.data["until"]
        timestamp = str(int(dt_util.as_timestamp(until)))
        display = call.data.get("display", "front")
        color = _rgb_to_hexaa(call.data.get("color", [255, 255, 255]))
        interrupt = call.data.get("interrupt", False)
        priority = PRIORITY_INTERRUPT if interrupt else PRIORITY_DEFAULT
        for coord in _coordinators(call):
            elements = [
                {
                    "id": str(i),
                    "type": "countdown",
                    "display": disp,
                    "align": "center",
                    "timestamp": timestamp,
                    "direction": "time_left",
                    "show_hours": "when_non_zero",
                    "color": color,
                }
                for i, disp in enumerate(_displays(display))
            ]
            await coord.api.draw(
                {"application_name": APPLICATION_NAME, "priority": priority, "elements": elements}
            )
            await coord.async_request_refresh()

    async def _start_busy(call: ServiceCall) -> None:
        theme = call.data.get("theme", "meeting")
        duration = call.data.get("duration")
        for coord in _coordinators(call):
            if duration:
                await coord.api.start_simple(theme, int(duration))
            else:
                await coord.api.start_infinite(theme)
            await coord.async_request_refresh()

    async def _start_pomodoro(call: ServiceCall) -> None:
        for coord in _coordinators(call):
            await coord.api.start_pomodoro(
                call.data.get("theme", "flow"),
                int(call.data.get("work_minutes", 25)),
                int(call.data.get("break_minutes", 5)),
                int(call.data.get("cycles", 4)),
            )
            await coord.async_request_refresh()

    async def _simple_api(call: ServiceCall, method: str) -> None:
        for coord in _coordinators(call):
            fn = getattr(coord.api, method)
            await fn()
            await coord.async_request_refresh()

    async def _set_theme(call: ServiceCall) -> None:
        theme = call.data["theme"]
        for coord in _coordinators(call):
            if not coord.data.active:
                raise ServiceValidationError(
                    "Start a BUSY session before changing the theme "
                    "(use the Theme select or busybar.start_busy)"
                )
            await coord.api.set_theme(theme)
            await coord.async_request_refresh()

    async def _play_sound(call: ServiceCall) -> None:
        sound = call.data["sound"]
        for coord in _coordinators(call):
            await coord.api.play_audio(
                {"application_name": APPLICATION_NAME, "stock_path": STOCK_SOUNDS[sound]}
            )

    async def _clear(call: ServiceCall) -> None:
        for coord in _coordinators(call):
            await coord.api.clear_display(APPLICATION_NAME)

    _register(
        SERVICE_NOTIFY,
        _notify,
        _schema(
            {
                vol.Required("message"): cv.string,
                vol.Optional("title"): cv.string,
                vol.Optional("color"): vol.All(cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(0, 255))]),
                vol.Optional("sound"): vol.In(list(STOCK_SOUNDS.keys()) + ["none"]),
                vol.Optional("display", default="front"): vol.In(["front", "back", "both"]),
                vol.Optional("duration", default=10): vol.All(vol.Coerce(int), vol.Range(0, 3600)),
                vol.Optional("interrupt", default=False): cv.boolean,
            }
        ),
    )
    _register(
        SERVICE_DISPLAY_TEXT,
        _display_text,
        _schema(
            {
                vol.Required("text"): cv.string,
                vol.Optional("color"): vol.All(cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(0, 255))]),
                vol.Optional("display", default="front"): vol.In(["front", "back", "both"]),
                vol.Optional("duration", default=0): vol.All(vol.Coerce(int), vol.Range(0, 86400)),
                vol.Optional("interrupt", default=False): cv.boolean,
            }
        ),
    )
    _register(
        SERVICE_DISPLAY_IMAGE,
        _display_image,
        _schema(
            {
                vol.Required("image"): cv.string,
                vol.Optional("display", default="front"): vol.In(["front", "back", "both"]),
                vol.Optional("duration", default=0): vol.All(vol.Coerce(int), vol.Range(0, 86400)),
                vol.Optional("interrupt", default=False): cv.boolean,
            }
        ),
    )
    _register(
        SERVICE_DISPLAY_ANIMATION,
        _display_animation,
        _schema(
            {
                vol.Required("animation"): cv.string,
                vol.Optional("loop", default=True): cv.boolean,
                vol.Optional("display", default="front"): vol.In(["front", "back", "both"]),
                vol.Optional("duration", default=0): vol.All(vol.Coerce(int), vol.Range(0, 86400)),
                vol.Optional("interrupt", default=False): cv.boolean,
            }
        ),
    )
    _register(
        SERVICE_DISPLAY_COUNTDOWN,
        _display_countdown,
        _schema(
            {
                vol.Required("until"): cv.datetime,
                vol.Optional("color"): vol.All(cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(0, 255))]),
                vol.Optional("display", default="front"): vol.In(["front", "back", "both"]),
                vol.Optional("interrupt", default=False): cv.boolean,
            }
        ),
    )
    for name, schema, handler in (
        (SERVICE_START_BUSY, {vol.Optional("theme", default="meeting"): vol.In(THEMES), vol.Optional("duration"): vol.All(vol.Coerce(int), vol.Range(1, 1440))}, _start_busy),
        (SERVICE_START_POMODORO, {
            vol.Optional("work_minutes", default=25): vol.All(vol.Coerce(int), vol.Range(1, 180)),
            vol.Optional("break_minutes", default=5): vol.All(vol.Coerce(int), vol.Range(1, 60)),
            vol.Optional("cycles", default=4): vol.All(vol.Coerce(int), vol.Range(1, 20)),
            vol.Optional("theme", default="flow"): vol.In(THEMES),
        }, _start_pomodoro),
        (SERVICE_SET_THEME, {vol.Required("theme"): vol.In(THEMES)}, _set_theme),
        (SERVICE_PLAY_SOUND, {vol.Required("sound"): vol.In(list(STOCK_SOUNDS.keys()))}, _play_sound),
    ):
        _register(name, handler, _schema(schema))

    async def _stop(call: ServiceCall) -> None:
        await _simple_api(call, "stop_busy")

    async def _pause(call: ServiceCall) -> None:
        await _simple_api(call, "pause_busy")

    async def _resume(call: ServiceCall) -> None:
        await _simple_api(call, "resume_busy")

    _register(SERVICE_CLEAR, _clear, _schema({}))
    _register(SERVICE_STOP_BUSY, _stop, _schema({}))
    _register(SERVICE_PAUSE_BUSY, _pause, _schema({}))
    _register(SERVICE_RESUME_BUSY, _resume, _schema({}))
