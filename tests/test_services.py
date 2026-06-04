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


async def test_notify_plain(hass: HomeAssistant) -> None:
    """A bare notify draws a single centered text element."""
    api = make_api()
    await setup_busybar(hass, api)
    await hass.services.async_call(
        DOMAIN, "notify", {"message": "Hello"}, blocking=True
    )
    payload = api.draw.call_args.args[0]
    assert payload["application_name"]
    texts = [e for e in payload["elements"] if e["type"] == "text"]
    assert texts and texts[-1]["text"] == "Hello"
    assert texts[-1]["align"] == "center"


async def test_notify_with_icon_sound_and_scroll(hass: HomeAssistant) -> None:
    """Icon + sound + forced scroll add an image element and play audio."""
    api = make_api()
    await setup_busybar(hass, api)
    await hass.services.async_call(
        DOMAIN,
        "notify",
        {
            "message": "Laundry is done and ready",
            "title": "Washer",
            "icon": "check",
            "sound": "event",
            "scroll": "fast",
            "display": "both",
        },
        blocking=True,
    )
    payload = api.draw.call_args.args[0]
    assert any(e["type"] == "image" for e in payload["elements"])
    scrolled = [e for e in payload["elements"] if e.get("scroll_rate")]
    assert scrolled and scrolled[0]["scroll_rate"] > 0
    api.play_audio.assert_awaited()


async def test_notify_non_ascii_is_sanitized(hass: HomeAssistant) -> None:
    """Cyrillic/emoji are replaced so the device font schema accepts the text."""
    api = make_api()
    await setup_busybar(hass, api)
    await hass.services.async_call(
        DOMAIN, "notify", {"message": "Привет"}, blocking=True
    )
    payload = api.draw.call_args.args[0]
    text = [e for e in payload["elements"] if e["type"] == "text"][-1]["text"]
    assert all(0x20 <= ord(c) <= 0x7E for c in text)


async def test_display_text_interrupt_priority(hass: HomeAssistant) -> None:
    """interrupt=True raises the draw priority above the default."""
    from custom_components.busybar.const import PRIORITY_DEFAULT, PRIORITY_INTERRUPT

    api = make_api()
    await setup_busybar(hass, api)
    await hass.services.async_call(
        DOMAIN, "display_text", {"text": "Hi", "interrupt": True}, blocking=True
    )
    assert api.draw.call_args.args[0]["priority"] == PRIORITY_INTERRUPT
    await hass.services.async_call(
        DOMAIN, "display_text", {"text": "Hi"}, blocking=True
    )
    assert api.draw.call_args.args[0]["priority"] == PRIORITY_DEFAULT


async def test_display_image_stock_vs_app_path(hass: HomeAssistant) -> None:
    """'shared/...' maps to stock_path, anything else to path."""
    api = make_api()
    await setup_busybar(hass, api)
    await hass.services.async_call(
        DOMAIN, "display_image", {"image": "shared/images/foo.image"}, blocking=True
    )
    assert "stock_path" in api.draw.call_args.args[0]["elements"][0]

    await hass.services.async_call(
        DOMAIN, "display_image", {"image": "my-app/logo.png"}, blocking=True
    )
    assert "path" in api.draw.call_args.args[0]["elements"][0]


async def test_display_animation(hass: HomeAssistant) -> None:
    api = make_api()
    await setup_busybar(hass, api)
    await hass.services.async_call(
        DOMAIN,
        "display_animation",
        {"animation": "shared/anim/spin.anim", "loop": False},
        blocking=True,
    )
    el = api.draw.call_args.args[0]["elements"][0]
    assert el["type"] == "animation" and el["loop"] is False


async def test_display_countdown(hass: HomeAssistant) -> None:
    api = make_api()
    await setup_busybar(hass, api)
    await hass.services.async_call(
        DOMAIN,
        "display_countdown",
        {"until": "2099-01-01T00:00:00+00:00"},
        blocking=True,
    )
    el = api.draw.call_args.args[0]["elements"][0]
    assert el["type"] == "countdown" and el["timestamp"].isdigit()


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
        "notify",
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
            "notify",
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
            DOMAIN, "notify", {"message": "Hi"}, blocking=True
        )


async def test_notify_icon_without_scroll(hass: HomeAssistant) -> None:
    """Icon + no scroll left-anchors the text beside the icon (no scroll_rate)."""
    api = make_api()
    await setup_busybar(hass, api)
    # Short message + auto scroll → no marquee; the icon still left-anchors text.
    await hass.services.async_call(
        DOMAIN,
        "notify",
        {"message": "Hi", "icon": "check"},
        blocking=True,
    )
    payload = api.draw.call_args.args[0]
    msg = [e for e in payload["elements"] if e["type"] == "text"][-1]
    assert msg["align"] == "mid_left" and "scroll_rate" not in msg


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
        DOMAIN, "notify", {"message": "Hi", "area_id": [area.id]}, blocking=True
    )
    api.draw.assert_awaited()


async def test_target_by_entity_id(hass: HomeAssistant) -> None:
    """Targeting one of the bar's entities resolves its coordinator."""
    from homeassistant.helpers import entity_registry as er

    api = make_api()
    await setup_busybar(hass, api)
    eid = er.async_get(hass).async_get_entity_id("number", DOMAIN, f"{SERIAL}_brightness")
    await hass.services.async_call(
        DOMAIN, "notify", {"message": "Hi", "entity_id": [eid]}, blocking=True
    )
    api.draw.assert_awaited()


async def test_api_error_becomes_homeassistant_error(hass: HomeAssistant) -> None:
    """A device/API failure inside a service surfaces as HomeAssistantError."""
    api = make_api()
    api.draw.side_effect = BusyBarApiError("boom")
    await setup_busybar(hass, api)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "display_text", {"text": "Hi"}, blocking=True
        )
