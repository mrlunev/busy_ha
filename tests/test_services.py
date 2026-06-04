"""Tests for the BUSY Bar service actions registered in __init__."""

from __future__ import annotations

import pytest
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr

from custom_components.busybar.api import BusyBarApiError
from custom_components.busybar.const import DOMAIN

from .conftest import SERIAL, SNAPSHOT_ACTIVE, make_api, setup_busybar


def _device_id(hass: HomeAssistant) -> str:
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, SERIAL)})
    assert device is not None
    return device.id


async def test_notify_one_line_plain(hass: HomeAssistant) -> None:
    """One-line notify with no icon draws a single left-anchored text element."""
    api = make_api()
    await setup_busybar(hass, api)
    await hass.services.async_call(
        DOMAIN, "notify_one_line", {"message": "Hello"}, blocking=True
    )
    payload = api.draw.call_args.args[0]
    assert payload["application_name"]
    elements = payload["elements"]
    assert not any(e["type"] == "image" for e in elements)
    text = [e for e in elements if e["type"] == "text"][-1]
    assert text["text"] == "Hello"
    assert text["align"] == "mid_left" and text["x"] == 2


async def test_notify_one_line_icon_shifts_text(hass: HomeAssistant) -> None:
    """An icon adds an image element and shifts the text right by the icon width."""
    api = make_api()
    await setup_busybar(hass, api)
    # 'check' is an 8px icon → text x = 8 + ICON_TEXT_GAP(2) = 10.
    await hass.services.async_call(
        DOMAIN,
        "notify_one_line",
        {"message": "Hi", "icon": "check", "sound": "event"},
        blocking=True,
    )
    payload = api.draw.call_args.args[0]
    assert any(e["type"] == "image" for e in payload["elements"])
    text = [e for e in payload["elements"] if e["type"] == "text"][-1]
    assert text["align"] == "mid_left" and text["x"] == 10
    assert "scroll_rate" not in text  # short text → no marquee
    api.play_audio.assert_awaited()


async def test_notify_one_line_long_text_scrolls(hass: HomeAssistant) -> None:
    """A line too long to fit gets a marquee (scroll_rate) clipped to a width."""
    api = make_api()
    await setup_busybar(hass, api)
    await hass.services.async_call(
        DOMAIN,
        "notify_one_line",
        {"message": "This is a very long message that overflows"},
        blocking=True,
    )
    text = [e for e in api.draw.call_args.args[0]["elements"] if e["type"] == "text"][-1]
    assert text.get("scroll_rate", 0) > 0 and "width" in text


async def test_notify_one_line_non_ascii_is_sanitized(hass: HomeAssistant) -> None:
    """Cyrillic/emoji are replaced so the device font schema accepts the text."""
    api = make_api()
    await setup_busybar(hass, api)
    await hass.services.async_call(
        DOMAIN, "notify_one_line", {"message": "Привет"}, blocking=True
    )
    payload = api.draw.call_args.args[0]
    text = [e for e in payload["elements"] if e["type"] == "text"][-1]["text"]
    assert all(0x20 <= ord(c) <= 0x7E for c in text)


async def test_notify_one_line_interrupt_priority(hass: HomeAssistant) -> None:
    """interrupt=True raises the draw priority above the default."""
    from custom_components.busybar.const import PRIORITY_DEFAULT, PRIORITY_INTERRUPT

    api = make_api()
    await setup_busybar(hass, api)
    await hass.services.async_call(
        DOMAIN, "notify_one_line", {"message": "Hi", "interrupt": True}, blocking=True
    )
    assert api.draw.call_args.args[0]["priority"] == PRIORITY_INTERRUPT
    await hass.services.async_call(
        DOMAIN, "notify_one_line", {"message": "Hi"}, blocking=True
    )
    assert api.draw.call_args.args[0]["priority"] == PRIORITY_DEFAULT


async def test_notify_two_lines(hass: HomeAssistant) -> None:
    """Two lines are stacked at y=1 and y=8 and never overlap."""
    api = make_api()
    await setup_busybar(hass, api)
    await hass.services.async_call(
        DOMAIN,
        "notify_small_two_lines",
        {"line_1": "Error occured", "line_2": "Try again"},
        blocking=True,
    )
    texts = [e for e in api.draw.call_args.args[0]["elements"] if e["type"] == "text"]
    assert len(texts) == 2
    assert texts[0]["text"] == "Error occured" and texts[0]["y"] == 1
    assert texts[1]["text"] == "Try again" and texts[1]["y"] == 8
    assert all(t["x"] == 2 for t in texts)  # no icon → left margin


async def test_notify_two_lines_icon_shifts_text(hass: HomeAssistant) -> None:
    """With an icon, both lines shift right by the icon width."""
    api = make_api()
    await setup_busybar(hass, api)
    # 'start' is an 11px icon → text x = 11 + 2 = 13.
    await hass.services.async_call(
        DOMAIN,
        "notify_small_two_lines",
        {"line_1": "A", "line_2": "B", "icon": "start"},
        blocking=True,
    )
    elements = api.draw.call_args.args[0]["elements"]
    assert any(e["type"] == "image" for e in elements)
    texts = [e for e in elements if e["type"] == "text"]
    assert all(t["x"] == 13 for t in texts)


async def test_notify_picture_centers_icon(hass: HomeAssistant) -> None:
    """A picture is a stock icon shown centered, with optional sound."""
    api = make_api()
    await setup_busybar(hass, api)
    await hass.services.async_call(
        DOMAIN, "notify_picture", {"picture": "info", "sound": "reminder"}, blocking=True
    )
    el = api.draw.call_args.args[0]["elements"][0]
    assert el["type"] == "image" and el["align"] == "center"
    assert el["stock_path"].endswith(".image")
    api.play_audio.assert_awaited()


async def test_simple_timer_draws_countdown(hass: HomeAssistant) -> None:
    """simple_timer draws a countdown to now+total with a timeout that clears it."""
    api = make_api()
    await setup_busybar(hass, api)
    await hass.services.async_call(
        DOMAIN,
        "simple_timer",
        {"hours": 0, "minutes": 1, "seconds": 30, "sound": "none"},
        blocking=True,
    )
    el = api.draw.call_args.args[0]["elements"][0]
    assert el["type"] == "countdown" and el["timestamp"].isdigit()
    assert el["timeout"] == 90 and el["show_hours"] == "always"


async def test_simple_timer_zero_raises(hass: HomeAssistant) -> None:
    """A zero-length timer is rejected."""
    api = make_api()
    await setup_busybar(hass, api)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "simple_timer",
            {"hours": 0, "minutes": 0, "seconds": 0},
            blocking=True,
        )


async def test_simple_timer_schedules_end_sound(hass: HomeAssistant) -> None:
    """The end-of-timer sound is scheduled for the full duration and plays on fire."""
    from unittest.mock import patch

    from homeassistant.util import dt as dt_util

    captured: dict = {}

    def _fake_call_later(_hass, delay, action):
        captured["delay"] = delay
        captured["action"] = action
        return lambda: None

    api = make_api()
    await setup_busybar(hass, api)
    with patch(
        "custom_components.busybar.async_call_later", side_effect=_fake_call_later
    ):
        await hass.services.async_call(
            DOMAIN,
            "simple_timer",
            {"minutes": 2, "seconds": 30, "sound": "event"},
            blocking=True,
        )
    assert captured["delay"] == 150  # 2m30s, fired when the countdown ends
    api.play_audio.assert_not_awaited()  # nothing plays at start
    await captured["action"](dt_util.utcnow())  # simulate the deadline
    api.play_audio.assert_awaited()


async def test_simple_timer_no_sound_schedules_nothing(hass: HomeAssistant) -> None:
    """sound='none' draws the countdown without scheduling any end sound."""
    from unittest.mock import patch

    api = make_api()
    await setup_busybar(hass, api)
    with patch(
        "custom_components.busybar.async_call_later"
    ) as call_later:
        await hass.services.async_call(
            DOMAIN, "simple_timer", {"seconds": 30, "sound": "none"}, blocking=True
        )
    call_later.assert_not_called()
    api.draw.assert_awaited()


async def test_start_timer_countdown_and_infinite(hass: HomeAssistant) -> None:
    api = make_api()
    await setup_busybar(hass, api)
    await hass.services.async_call(
        DOMAIN,
        "start_timer",
        {"mode": "countdown", "theme": "meeting", "duration": 30},
        blocking=True,
    )
    api.start_simple.assert_awaited_with("meeting", 30)

    await hass.services.async_call(
        DOMAIN, "start_timer", {"theme": "meeting"}, blocking=True
    )
    api.start_infinite.assert_awaited_with("meeting")


async def test_start_timer_countdown_requires_duration(hass: HomeAssistant) -> None:
    """countdown mode without a duration raises a validation error."""
    api = make_api()
    await setup_busybar(hass, api)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "start_timer", {"mode": "countdown"}, blocking=True
        )


async def test_start_timer_pomodoro(hass: HomeAssistant) -> None:
    api = make_api()
    await setup_busybar(hass, api)
    await hass.services.async_call(
        DOMAIN,
        "start_timer",
        {"mode": "pomodoro", "work_minutes": 50, "break_minutes": 10, "cycles": 2, "theme": "flow"},
        blocking=True,
    )
    api.start_pomodoro.assert_awaited_with("flow", 50, 10, 2)


async def test_start_profile(hass: HomeAssistant) -> None:
    """start_profile launches the requested preset slot."""
    api = make_api()
    await setup_busybar(hass, api)
    await hass.services.async_call(
        DOMAIN, "start_profile", {"slot": "custom"}, blocking=True
    )
    api.start_profile.assert_awaited_with("custom")


async def test_set_theme_requires_active_session(hass: HomeAssistant) -> None:
    """Setting a theme with no running session raises a validation error."""
    api = make_api()
    await setup_busybar(hass, api)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "set_theme", {"theme": "meeting"}, blocking=True
        )


async def test_set_theme_when_active(hass: HomeAssistant) -> None:
    api = make_api(get_snapshot=SNAPSHOT_ACTIVE)
    entry = await setup_busybar(hass, api)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    await hass.services.async_call(
        DOMAIN, "set_theme", {"theme": "meeting"}, blocking=True
    )
    api.set_theme.assert_awaited_with("meeting")


async def test_play_sound_and_clear(hass: HomeAssistant) -> None:
    api = make_api()
    await setup_busybar(hass, api)
    await hass.services.async_call(
        DOMAIN, "play_sound", {"sound": "event"}, blocking=True
    )
    api.play_audio.assert_awaited()
    await hass.services.async_call(DOMAIN, "clear", {}, blocking=True)
    api.clear_display.assert_awaited()


async def test_timer_control_services(hass: HomeAssistant) -> None:
    api = make_api()
    await setup_busybar(hass, api)
    await hass.services.async_call(DOMAIN, "stop_timer", {}, blocking=True)
    await hass.services.async_call(DOMAIN, "pause_timer", {}, blocking=True)
    await hass.services.async_call(DOMAIN, "resume_timer", {}, blocking=True)
    api.stop_busy.assert_awaited()
    api.pause_busy.assert_awaited()
    api.resume_busy.assert_awaited()


async def test_target_by_device_id(hass: HomeAssistant) -> None:
    """An explicit device target resolves to that bar's coordinator."""
    api = make_api()
    await setup_busybar(hass, api)
    await hass.services.async_call(
        DOMAIN,
        "notify_one_line",
        {"message": "Hi", ATTR_DEVICE_ID: [_device_id(hass)]},
        blocking=True,
    )
    api.draw.assert_awaited()


async def test_target_unknown_device_raises(hass: HomeAssistant) -> None:
    api = make_api()
    await setup_busybar(hass, api)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "notify_one_line",
            {"message": "Hi", ATTR_DEVICE_ID: ["does-not-exist"]},
            blocking=True,
        )


async def test_no_loaded_entry_raises(hass: HomeAssistant) -> None:
    """With every entry unloaded the service reports no target."""
    api = make_api()
    entry = await setup_busybar(hass, api)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "notify_one_line", {"message": "Hi"}, blocking=True
        )


async def test_target_by_area(hass: HomeAssistant) -> None:
    """Targeting an area resolves the bars assigned to it."""
    from homeassistant.helpers import area_registry as ar

    api = make_api()
    await setup_busybar(hass, api)
    area = ar.async_get(hass).async_create("Office")
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, SERIAL)})
    dev_reg.async_update_device(device.id, area_id=area.id)
    await hass.services.async_call(
        DOMAIN, "notify_one_line", {"message": "Hi", "area_id": [area.id]}, blocking=True
    )
    api.draw.assert_awaited()


async def test_target_by_entity_id(hass: HomeAssistant) -> None:
    """Targeting one of the bar's entities resolves its coordinator."""
    from homeassistant.helpers import entity_registry as er

    api = make_api()
    await setup_busybar(hass, api)
    eid = er.async_get(hass).async_get_entity_id("number", DOMAIN, f"{SERIAL}_brightness")
    await hass.services.async_call(
        DOMAIN, "notify_one_line", {"message": "Hi", "entity_id": [eid]}, blocking=True
    )
    api.draw.assert_awaited()


async def test_api_error_becomes_homeassistant_error(hass: HomeAssistant) -> None:
    """A device/API failure inside a service surfaces as HomeAssistantError."""
    api = make_api()
    api.draw.side_effect = BusyBarApiError("boom")
    await setup_busybar(hass, api)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "notify_one_line", {"message": "Hi"}, blocking=True
        )
