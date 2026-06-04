"""BUSY Bar integration for Home Assistant."""

from __future__ import annotations

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
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .api import BusyBarApi, BusyBarApiError
from .const import (
    APPLICATION_NAME,
    CONF_TOKEN,
    DEFAULT_TEXT_FONT,
    DOMAIN,
    ICON_TEXT_GAP,
    PRIORITY_DEFAULT,
    PRIORITY_INTERRUPT,
    SCROLL_RATES,
    STOCK_ICONS,
    STOCK_SOUNDS,
    THEMES,
)
from .coordinator import BusyBarConfigEntry, BusyBarCoordinator

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

# Notification design templates. Each is a separate action with its own fields
# (HA forms are static — it cannot swap fields based on a "template" dropdown),
# so "pick a template" == "pick the action". The layout (text coordinates) is
# computed in code from the chosen icon's width.
SERVICE_NOTIFY_ONE_LINE = "notify_one_line"
SERVICE_NOTIFY_TWO_LINES = "notify_small_two_lines"
SERVICE_NOTIFY_PICTURE = "notify_picture"
SERVICE_SIMPLE_TIMER = "simple_timer"
# A running timer always has one of three types (open-ended / countdown /
# pomodoro); "busy" and "custom" are just two preset slots of the same app, not
# different functions. So the actions are named by timer behaviour, plus one
# action to launch a preconfigured slot as-is.
SERVICE_START_TIMER = "start_timer"
SERVICE_START_PROFILE = "start_profile"
SERVICE_STOP_TIMER = "stop_timer"
SERVICE_PAUSE_TIMER = "pause_timer"
SERVICE_RESUME_TIMER = "resume_timer"
SERVICE_SET_THEME = "set_theme"
SERVICE_PLAY_SOUND = "play_sound"
SERVICE_CLEAR = "clear"

TIMER_MODES = ["infinite", "countdown", "pomodoro"]
PROFILE_SLOTS = ["busy", "custom"]


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


def _scroll_rate(scroll: str, text: str) -> int:
    """Resolve a named scroll speed to a scroll_rate (pixels/minute).

    "auto" scrolls only when the text is long enough to overflow the panel.
    """
    if scroll == "auto":
        return SCROLL_RATES["normal"] if len(text) > 12 else 0
    return SCROLL_RATES.get(scroll, 0)


def _icon(name: str | None) -> tuple[str, int] | None:
    """Resolve an icon name to (stock_path, width_px), or None for no icon."""
    if not name or name == "none":
        return None
    return STOCK_ICONS.get(name)


def _icon_element(eid: int, icon: tuple[str, int], duration: int) -> dict:
    """A left-anchored, vertically centered icon element."""
    return {
        "id": str(eid),
        "type": "image",
        "stock_path": icon[0],
        "display": "front",
        "align": "mid_left",
        "x": 0,
        "y": 8,
        "timeout": duration,
    }


def _text_x(icon: tuple[str, int] | None) -> int:
    """Left X for text: just past the icon (icon width + gap), else a small margin."""
    return icon[1] + ICON_TEXT_GAP if icon else 2


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
    if hass.services.has_service(DOMAIN, SERVICE_NOTIFY_ONE_LINE):
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
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_loaded_entry"
            )

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
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="invalid_target"
            )
        return out

    def _register(name: str, handler, schema: vol.Schema) -> None:
        """Register a service, surfacing device/API errors as HomeAssistantError."""

        async def wrapped(call: ServiceCall) -> None:
            try:
                await handler(call)
            except BusyBarApiError as err:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="device_error",
                    translation_placeholders={"error": str(err)},
                ) from err

        hass.services.async_register(DOMAIN, name, wrapped, schema=schema)

    async def _play_stock_sound(coord: BusyBarCoordinator, sound: str | None) -> None:
        """Play a stock sound if one was chosen (ignores 'none'/unknown)."""
        if sound and sound != "none" and sound in STOCK_SOUNDS:
            await coord.api.play_audio(
                {"application_name": APPLICATION_NAME, "stock_path": STOCK_SOUNDS[sound]}
            )

    async def _draw_and_sound(
        call: ServiceCall, elements: list[dict], priority: int, sound: str | None
    ) -> None:
        """Send one front-panel draw to every targeted bar, then play the sound."""
        for coord in _coordinators(call):
            await coord.api.draw(
                {
                    "application_name": APPLICATION_NAME,
                    "priority": priority,
                    "elements": elements,
                }
            )
            # Sound is fired right after the draw so it lands with the visual.
            await _play_stock_sound(coord, sound)
            await coord.async_request_refresh_full()

    async def _notify_one_line(call: ServiceCall) -> None:
        message = _ascii(call.data["message"][:80])
        icon = _icon(call.data.get("icon"))
        color = _rgb_to_hexaa(call.data.get("color", [255, 255, 255]))
        sound = call.data.get("sound", "none")
        duration = int(call.data.get("duration", 10))
        priority = PRIORITY_INTERRUPT if call.data.get("interrupt") else PRIORITY_DEFAULT

        text_x = _text_x(icon)
        elements: list[dict] = []
        eid = 0
        if icon:
            elements.append(_icon_element(eid, icon, duration))
            eid += 1
        msg: dict[str, Any] = {
            "id": str(eid),
            "type": "text",
            "text": message,
            "font": DEFAULT_TEXT_FONT,
            "color": color,
            "display": "front",
            "align": "mid_left",
            "x": text_x,
            "y": 8,
            "timeout": duration,
        }
        # Marquee a single line only when it is too long to fit the panel.
        if rate := _scroll_rate("auto", message):
            msg["scroll_rate"] = rate
            msg["width"] = 72 - text_x
        elements.append(msg)
        await _draw_and_sound(call, elements, priority, sound)

    async def _notify_two_lines(call: ServiceCall) -> None:
        line_1 = _ascii(call.data["line_1"][:80])
        line_2 = _ascii(call.data["line_2"][:80])
        icon = _icon(call.data.get("icon"))
        color = _rgb_to_hexaa(call.data.get("color", [255, 255, 255]))
        sound = call.data.get("sound", "none")
        duration = int(call.data.get("duration", 10))
        priority = PRIORITY_INTERRUPT if call.data.get("interrupt") else PRIORITY_DEFAULT

        text_x = _text_x(icon)
        elements: list[dict] = []
        eid = 0
        if icon:
            elements.append(_icon_element(eid, icon, duration))
            eid += 1
        # Two stacked lines, top-anchored at y=1 and y=8 so they never overlap.
        for line, y in ((line_1, 1), (line_2, 8)):
            elements.append(
                {
                    "id": str(eid),
                    "type": "text",
                    "text": line,
                    "font": DEFAULT_TEXT_FONT,
                    "color": color,
                    "display": "front",
                    "align": "top_left",
                    "x": text_x,
                    "y": y,
                    "timeout": duration,
                }
            )
            eid += 1
        await _draw_and_sound(call, elements, priority, sound)

    async def _notify_picture(call: ServiceCall) -> None:
        # Stock catalog has no full-panel pictures yet, so a "picture" is one of
        # the stock icons shown centered on the panel.
        icon = STOCK_ICONS[call.data["picture"]]
        sound = call.data.get("sound", "none")
        duration = int(call.data.get("duration", 10))
        priority = PRIORITY_INTERRUPT if call.data.get("interrupt") else PRIORITY_DEFAULT
        elements = [
            {
                "id": "0",
                "type": "image",
                "stock_path": icon[0],
                "display": "front",
                "align": "center",
                "x": 36,
                "y": 8,
                "timeout": duration,
            }
        ]
        await _draw_and_sound(call, elements, priority, sound)

    async def _simple_timer(call: ServiceCall) -> None:
        total = (
            int(call.data.get("hours", 0)) * 3600
            + int(call.data.get("minutes", 0)) * 60
            + int(call.data.get("seconds", 0))
        )
        if total <= 0:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="time_required"
            )
        color = _rgb_to_hexaa(call.data.get("color", [255, 255, 255]))
        sound = call.data.get("sound", "event")
        priority = PRIORITY_INTERRUPT if call.data.get("interrupt") else PRIORITY_DEFAULT
        timestamp = str(int(dt_util.utcnow().timestamp()) + total)
        # The firmware renders the countdown digits in a fixed small font (the
        # `font` field is ignored for countdown elements), so we don't expose one.
        elements = [
            {
                "id": "0",
                "type": "countdown",
                "display": "front",
                "align": "center",
                "x": 36,
                "y": 8,
                "timestamp": timestamp,
                "direction": "time_left",
                "show_hours": "always",
                "color": color,
                "timeout": total,
            }
        ]
        coords = _coordinators(call)
        for coord in coords:
            await coord.api.draw(
                {
                    "application_name": APPLICATION_NAME,
                    "priority": priority,
                    "elements": elements,
                }
            )
            await coord.async_request_refresh_full()

        # The draw countdown has no completion sound, so schedule it HA-side.
        # Best-effort (a HA restart before the deadline cancels it) — fine for a
        # transient on-screen timer.
        if sound and sound != "none" and sound in STOCK_SOUNDS:

            async def _fire_end_sound(_now, _coords=coords, _sound=sound) -> None:
                for coord in _coords:
                    try:
                        await _play_stock_sound(coord, _sound)
                    except BusyBarApiError:
                        pass

            async_call_later(hass, total, _fire_end_sound)

    async def _start_timer(call: ServiceCall) -> None:
        mode = call.data.get("mode", "infinite")
        theme = call.data.get("theme", "meeting")
        for coord in _coordinators(call):
            if mode == "pomodoro":
                await coord.api.start_pomodoro(
                    theme,
                    int(call.data.get("work_minutes", 25)),
                    int(call.data.get("break_minutes", 5)),
                    int(call.data.get("cycles", 4)),
                )
            elif mode == "countdown":
                duration = call.data.get("duration")
                if not duration:
                    raise ServiceValidationError(
                        translation_domain=DOMAIN,
                        translation_key="duration_required",
                    )
                await coord.api.start_simple(theme, int(duration))
            else:
                await coord.api.start_infinite(theme)
            await coord.async_request_refresh_full()

    async def _start_profile(call: ServiceCall) -> None:
        slot = call.data["slot"]
        for coord in _coordinators(call):
            await coord.api.start_profile(slot)
            await coord.async_request_refresh_full()

    async def _simple_api(call: ServiceCall, method: str) -> None:
        for coord in _coordinators(call):
            fn = getattr(coord.api, method)
            await fn()
            await coord.async_request_refresh_full()

    async def _set_theme(call: ServiceCall) -> None:
        theme = call.data["theme"]
        for coord in _coordinators(call):
            if not coord.data.active:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="theme_requires_session",
                )
            await coord.api.set_theme(theme)
            await coord.async_request_refresh_full()

    async def _play_sound(call: ServiceCall) -> None:
        sound = call.data["sound"]
        for coord in _coordinators(call):
            await coord.api.play_audio(
                {"application_name": APPLICATION_NAME, "stock_path": STOCK_SOUNDS[sound]}
            )

    async def _clear(call: ServiceCall) -> None:
        for coord in _coordinators(call):
            await coord.api.clear_display(APPLICATION_NAME)

    _color_field = vol.All(cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(0, 255))])
    _icon_field = vol.In(list(STOCK_ICONS.keys()) + ["none"])
    _sound_field = vol.In(list(STOCK_SOUNDS.keys()) + ["none"])

    _register(
        SERVICE_NOTIFY_ONE_LINE,
        _notify_one_line,
        _schema(
            {
                vol.Required("message"): cv.string,
                vol.Optional("icon", default="none"): _icon_field,
                vol.Optional("color"): _color_field,
                vol.Optional("sound", default="none"): _sound_field,
                vol.Optional("duration", default=10): vol.All(vol.Coerce(int), vol.Range(0, 3600)),
                vol.Optional("interrupt", default=False): cv.boolean,
            }
        ),
    )
    _register(
        SERVICE_NOTIFY_TWO_LINES,
        _notify_two_lines,
        _schema(
            {
                vol.Required("line_1"): cv.string,
                vol.Required("line_2"): cv.string,
                vol.Optional("icon", default="none"): _icon_field,
                vol.Optional("color"): _color_field,
                vol.Optional("sound", default="none"): _sound_field,
                vol.Optional("duration", default=10): vol.All(vol.Coerce(int), vol.Range(0, 3600)),
                vol.Optional("interrupt", default=False): cv.boolean,
            }
        ),
    )
    _register(
        SERVICE_NOTIFY_PICTURE,
        _notify_picture,
        _schema(
            {
                vol.Required("picture"): vol.In(list(STOCK_ICONS.keys())),
                vol.Optional("sound", default="none"): _sound_field,
                vol.Optional("duration", default=10): vol.All(vol.Coerce(int), vol.Range(0, 3600)),
                vol.Optional("interrupt", default=False): cv.boolean,
            }
        ),
    )
    _register(
        SERVICE_SIMPLE_TIMER,
        _simple_timer,
        _schema(
            {
                vol.Optional("hours", default=0): vol.All(vol.Coerce(int), vol.Range(0, 23)),
                vol.Optional("minutes", default=5): vol.All(vol.Coerce(int), vol.Range(0, 59)),
                vol.Optional("seconds", default=0): vol.All(vol.Coerce(int), vol.Range(0, 59)),
                vol.Optional("color"): _color_field,
                vol.Optional("sound", default="event"): _sound_field,
                vol.Optional("interrupt", default=False): cv.boolean,
            }
        ),
    )
    for name, schema, handler in (
        (SERVICE_START_TIMER, {
            vol.Optional("mode", default="infinite"): vol.In(TIMER_MODES),
            vol.Optional("theme", default="meeting"): vol.In(THEMES),
            vol.Optional("duration"): vol.All(vol.Coerce(int), vol.Range(1, 1440)),
            vol.Optional("work_minutes", default=25): vol.All(vol.Coerce(int), vol.Range(1, 180)),
            vol.Optional("break_minutes", default=5): vol.All(vol.Coerce(int), vol.Range(1, 60)),
            vol.Optional("cycles", default=4): vol.All(vol.Coerce(int), vol.Range(1, 20)),
        }, _start_timer),
        (SERVICE_START_PROFILE, {vol.Required("slot"): vol.In(PROFILE_SLOTS)}, _start_profile),
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
    _register(SERVICE_STOP_TIMER, _stop, _schema({}))
    _register(SERVICE_PAUSE_TIMER, _pause, _schema({}))
    _register(SERVICE_RESUME_TIMER, _resume, _schema({}))
