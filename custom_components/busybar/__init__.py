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
    NOTIFY_ONE_LINE_Y,
    NOTIFY_TWO_LINE_Y,
    PRIORITY_DEFAULT,
    PRIORITY_INTERRUPT,
    SCROLL_RATES,
    STOCK_ICONS,
    STOCK_SOUNDS,
    TEXT_FONTS,
    THEMES,
    TWO_LINE_FONTS,
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
SERVICE_STOP_TIMER = "stop_timer"
SERVICE_PAUSE_TIMER = "pause_timer"
SERVICE_RESUME_TIMER = "resume_timer"
SERVICE_SET_THEME = "set_theme"
SERVICE_PLAY_SOUND = "play_sound"
SERVICE_CLEAR = "clear"

TIMER_MODES = ["infinite", "simple", "pomodoro"]


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


# The draw API has no fill/rect primitive (firmware request tracked as BUSY-38),
# so a "background color" is emulated by tiling a dense glyph across the panel:
# four offset copies of a "[" run in `extra_large` cover the inter-glyph and
# inter-row gaps, reading as a near-solid wash of the chosen color. The element
# id doubles as the z-order on the device (higher == on top), so the fill uses
# ids 0..3 and foreground content starts at FG_ID_BASE to stay above it.
_BG_FILL_TEXT = "[" * 19
_BG_FILL_OFFSETS = ((0, -2), (2, -2), (2, 4), (0, 4))
FG_ID_BASE = 10


def _background_elements(color: str, duration: int) -> list[dict]:
    """Build the tiled-glyph fill elements that emulate a solid background."""
    return [
        {
            "id": str(i),
            "type": "text",
            "text": _BG_FILL_TEXT,
            "font": "extra_large",
            "color": color,
            "width": 72,
            "display": "front",
            "x": x,
            "y": y,
            "timeout": duration,
        }
        for i, (x, y) in enumerate(_BG_FILL_OFFSETS)
    ]


def _bg_start(call: ServiceCall, duration: int) -> tuple[list[dict], int]:
    """Return (initial elements, first foreground id) given an optional background.

    When a background_color is set, the fill elements (ids 0..3) are placed first
    and foreground ids start at FG_ID_BASE so content renders above the fill.
    """
    bg = call.data.get("background_color")
    if not bg:
        return [], 0
    return _background_elements(_rgb_to_hexaa(bg), duration), FG_ID_BASE


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
        message_raw = (call.data.get("message") or "")[:80]
        icon = _icon(call.data.get("icon"))
        color = _rgb_to_hexaa(call.data.get("color", [255, 255, 255]))
        font = call.data.get("font", DEFAULT_TEXT_FONT)
        sound = call.data.get("sound", "none")
        duration = int(call.data.get("duration", 10))
        priority = PRIORITY_INTERRUPT if call.data.get("interrupt") else PRIORITY_DEFAULT

        text_x = _text_x(icon)
        elements, eid = _bg_start(call, duration)
        if icon:
            elements.append(_icon_element(eid, icon, duration))
            eid += 1
        # Everything is optional: skip the text element entirely when no message
        # was given (otherwise _ascii would render a lone space).
        if message_raw.strip():
            message = _ascii(message_raw)
            # mid_left anchors the line to the vertical center, so any font height
            # stays within the 16px panel; the exact center is tuned per font
            # (NOTIFY_ONE_LINE_Y). A width box keeps wide text in the panel
            # (clipped, or scrolled when long) instead of being dropped.
            msg: dict[str, Any] = {
                "id": str(eid),
                "type": "text",
                "text": message,
                "font": font,
                "color": color,
                "display": "front",
                "align": "mid_left",
                "x": text_x,
                "y": NOTIFY_ONE_LINE_Y.get(font, 8),
                "width": 72 - text_x,
                "timeout": duration,
            }
            if rate := _scroll_rate("auto", message):
                msg["scroll_rate"] = rate
            elements.append(msg)
            eid += 1
        await _draw_and_sound(call, elements, priority, sound)

    async def _notify_two_lines(call: ServiceCall) -> None:
        line_1_raw = (call.data.get("line_1") or "")[:80]
        line_2_raw = (call.data.get("line_2") or "")[:80]
        icon = _icon(call.data.get("icon"))
        color_1 = _rgb_to_hexaa(call.data.get("line_1_color", [255, 255, 255]))
        color_2 = _rgb_to_hexaa(call.data.get("line_2_color", [255, 255, 255]))
        font = call.data.get("font", DEFAULT_TEXT_FONT)
        sound = call.data.get("sound", "none")
        duration = int(call.data.get("duration", 10))
        priority = PRIORITY_INTERRUPT if call.data.get("interrupt") else PRIORITY_DEFAULT

        text_x = _text_x(icon)
        elements, eid = _bg_start(call, duration)
        if icon:
            elements.append(_icon_element(eid, icon, duration))
            eid += 1
        # Line 1 is anchored to the top of the panel, line 2 to the bottom, so any
        # font fits regardless of its exact glyph height. The exact top/bottom Y is
        # tuned per font (NOTIFY_TWO_LINE_Y) so the lines neither clip nor kiss.
        # Both lines are optional: an empty one is simply skipped.
        top_y, bottom_y = NOTIFY_TWO_LINE_Y.get(font, (0, 16))
        lines = (
            (line_1_raw, "top_left", top_y, color_1),
            (line_2_raw, "bottom_left", bottom_y, color_2),
        )
        for raw, align, y, line_color in lines:
            if not raw.strip():
                continue
            elements.append(
                {
                    "id": str(eid),
                    "type": "text",
                    "text": _ascii(raw),
                    "font": font,
                    "color": line_color,
                    "display": "front",
                    "align": align,
                    "x": text_x,
                    "y": y,
                    "width": 72 - text_x,
                    "timeout": duration,
                }
            )
            eid += 1
        await _draw_and_sound(call, elements, priority, sound)

    async def _notify_picture(call: ServiceCall) -> None:
        # Stock catalog has no full-panel pictures yet, so a "picture" is one of
        # the stock icons shown centered on the panel.
        picture = call.data.get("picture")
        sound = call.data.get("sound", "none")
        duration = int(call.data.get("duration", 10))
        priority = PRIORITY_INTERRUPT if call.data.get("interrupt") else PRIORITY_DEFAULT
        elements, eid = _bg_start(call, duration)
        # The picture is optional: without one only the background (if any) shows.
        if picture:
            elements.append(
                {
                    "id": str(eid),
                    "type": "image",
                    "stock_path": STOCK_ICONS[picture][0],
                    "display": "front",
                    "align": "center",
                    "x": 36,
                    "y": 8,
                    "timeout": duration,
                }
            )
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
        work = call.data.get("work")
        rest = call.data.get("rest")
        cycles = call.data.get("cycles")

        # HA service forms can't disable fields per mode, so validate here:
        # Pomodoro takes Rest and Cycles together (one without the other is rejected);
        # Simple needs a Work duration. Infinite ignores all time fields.
        if mode == "pomodoro" and (rest is None) != (cycles is None):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="pomodoro_pair_required"
            )
        if mode == "simple" and not work:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="work_required"
            )

        for coord in _coordinators(call):
            if mode == "pomodoro":
                await coord.api.start_pomodoro(
                    theme,
                    int(work) if work else 25,
                    int(rest) if rest is not None else 5,
                    int(cycles) if cycles is not None else 4,
                )
            elif mode == "simple":
                await coord.api.start_simple(theme, int(work))
            else:
                await coord.api.start_infinite(theme)
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
                vol.Optional("message", default=""): cv.string,
                vol.Optional("icon", default="none"): _icon_field,
                vol.Optional("font", default=DEFAULT_TEXT_FONT): vol.In(TEXT_FONTS),
                vol.Optional("color"): _color_field,
                vol.Optional("background_color"): _color_field,
                vol.Optional("sound", default="none"): _sound_field,
                vol.Optional("duration", default=10): vol.All(vol.Coerce(int), vol.Range(0, 120)),
                vol.Optional("interrupt", default=False): cv.boolean,
            }
        ),
    )
    _register(
        SERVICE_NOTIFY_TWO_LINES,
        _notify_two_lines,
        _schema(
            {
                vol.Optional("line_1", default=""): cv.string,
                vol.Optional("line_2", default=""): cv.string,
                vol.Optional("icon", default="none"): _icon_field,
                vol.Optional("font", default=DEFAULT_TEXT_FONT): vol.In(TWO_LINE_FONTS),
                vol.Optional("line_1_color"): _color_field,
                vol.Optional("line_2_color"): _color_field,
                vol.Optional("background_color"): _color_field,
                vol.Optional("sound", default="none"): _sound_field,
                vol.Optional("duration", default=10): vol.All(vol.Coerce(int), vol.Range(0, 120)),
                vol.Optional("interrupt", default=False): cv.boolean,
            }
        ),
    )
    _register(
        SERVICE_NOTIFY_PICTURE,
        _notify_picture,
        _schema(
            {
                vol.Optional("picture"): vol.In(list(STOCK_ICONS.keys())),
                vol.Optional("background_color"): _color_field,
                vol.Optional("sound", default="none"): _sound_field,
                vol.Optional("duration", default=10): vol.All(vol.Coerce(int), vol.Range(0, 120)),
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
            vol.Optional("work"): vol.All(vol.Coerce(int), vol.Range(1, 1440)),
            vol.Optional("rest"): vol.All(vol.Coerce(int), vol.Range(1, 60)),
            vol.Optional("cycles"): vol.All(vol.Coerce(int), vol.Range(1, 20)),
        }, _start_timer),
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
