"""Tests for entity write paths (number/select/switch/update/button) and image."""

from __future__ import annotations

import base64

import pytest
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.busybar.api import BusyBarApiError
from custom_components.busybar.const import DOMAIN
from custom_components.busybar.image import _PX, BusyBarScreenImage

from .conftest import SERIAL, SNAPSHOT_ACTIVE, make_api, setup_busybar


def _eid(hass: HomeAssistant, platform: str, key: str) -> str:
    eid = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{SERIAL}_{key}")
    assert eid is not None, f"missing {platform} {key}"
    return eid


async def test_number_set_brightness_and_volume(hass: HomeAssistant) -> None:
    api = make_api()
    await setup_busybar(hass, api)
    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: _eid(hass, "number", "brightness"), "value": 75},
        blocking=True,
    )
    api.set_brightness.assert_awaited_with(75)
    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: _eid(hass, "number", "volume"), "value": 40},
        blocking=True,
    )
    api.set_volume.assert_awaited_with(40)


async def test_select_rotary_sends_key(hass: HomeAssistant) -> None:
    api = make_api()
    await setup_busybar(hass, api)
    eid = _eid(hass, "select", "selector")
    await hass.services.async_call(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: eid, "option": "off"},
        blocking=True,
    )
    api.send_key.assert_awaited_with("off")
    assert hass.states.get(eid).state == "off"


async def test_theme_select_starts_session_when_idle(hass: HomeAssistant) -> None:
    api = make_api()
    await setup_busybar(hass, api)
    await hass.services.async_call(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: _eid(hass, "select", "theme_select"), "option": "meeting"},
        blocking=True,
    )
    api.start_infinite.assert_awaited_with("meeting")


async def test_theme_select_updates_active_session(hass: HomeAssistant) -> None:
    api = make_api(get_snapshot=SNAPSHOT_ACTIVE)
    entry = await setup_busybar(hass, api)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    await hass.services.async_call(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: _eid(hass, "select", "theme_select"), "option": "flow"},
        blocking=True,
    )
    api.set_theme.assert_awaited_with("flow")


async def test_switch_turn_on_off(hass: HomeAssistant) -> None:
    api = make_api()
    await setup_busybar(hass, api)
    eid = _eid(hass, "switch", "smart_home")
    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: eid}, blocking=True
    )
    api.set_smart_home_switch.assert_awaited_with(True)
    await hass.services.async_call(
        "switch", "turn_off", {ATTR_ENTITY_ID: eid}, blocking=True
    )
    api.set_smart_home_switch.assert_awaited_with(False)


async def test_switch_unavailable_without_fabric(hass: HomeAssistant) -> None:
    """No Matter fabric → the smart-home switch is unavailable."""
    api = make_api(get_pairing={"fabric_count": 0})
    await setup_busybar(hass, api)
    assert hass.states.get(_eid(hass, "switch", "smart_home")).state == "unavailable"


async def test_update_install(hass: HomeAssistant) -> None:
    api = make_api(
        get_update_status={
            "check": {"status": "available", "available_version": "1.0.0"}
        }
    )
    await setup_busybar(hass, api)
    await hass.services.async_call(
        "update",
        "install",
        {ATTR_ENTITY_ID: _eid(hass, "update", "firmware_update")},
        blocking=True,
    )
    api.install_update.assert_awaited_with("1.0.0")


async def test_update_install_without_target_raises(hass: HomeAssistant) -> None:
    api = make_api()  # no newer version available
    await setup_busybar(hass, api)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "update",
            "install",
            {ATTR_ENTITY_ID: _eid(hass, "update", "firmware_update")},
            blocking=True,
        )


async def test_buttons_press(hass: HomeAssistant) -> None:
    api = make_api(get_snapshot=SNAPSHOT_ACTIVE)
    entry = await setup_busybar(hass, api)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    for key, attr in (
        ("ok", "send_key"),
        ("back", "send_key"),
        ("stop_busy", "stop_busy"),
        ("pause_busy", "pause_busy"),
    ):
        await hass.services.async_call(
            "button", "press", {ATTR_ENTITY_ID: _eid(hass, "button", key)}, blocking=True
        )
    api.stop_busy.assert_awaited()
    api.pause_busy.assert_awaited()
    assert api.send_key.await_count >= 2


async def test_button_api_error_raises(hass: HomeAssistant) -> None:
    api = make_api()
    api.send_key.side_effect = BusyBarApiError("offline")
    await setup_busybar(hass, api)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button", "press", {ATTR_ENTITY_ID: _eid(hass, "button", "ok")}, blocking=True
        )


async def test_number_brightness_auto_is_unavailable(hass: HomeAssistant) -> None:
    """An 'auto' brightness has no numeric value → entity unavailable."""
    api = make_api(get_brightness={"value": "auto"})
    await setup_busybar(hass, api)
    assert hass.states.get(_eid(hass, "number", "brightness")).state == "unavailable"


async def test_number_brightness_non_numeric(hass: HomeAssistant) -> None:
    """A non-numeric brightness is treated as no value (no crash)."""
    api = make_api(get_brightness={"value": "bogus"})
    await setup_busybar(hass, api)
    assert hass.states.get(_eid(hass, "number", "brightness")).state == "unavailable"


async def test_number_set_value_api_error(hass: HomeAssistant) -> None:
    api = make_api()
    api.set_volume.side_effect = BusyBarApiError("offline")
    await setup_busybar(hass, api)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "number",
            "set_value",
            {ATTR_ENTITY_ID: _eid(hass, "number", "volume"), "value": 10},
            blocking=True,
        )


async def test_select_api_error(hass: HomeAssistant) -> None:
    api = make_api()
    api.send_key.side_effect = BusyBarApiError("offline")
    await setup_busybar(hass, api)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "select",
            "select_option",
            {ATTR_ENTITY_ID: _eid(hass, "select", "selector"), "option": "busy"},
            blocking=True,
        )


async def test_theme_select_api_error(hass: HomeAssistant) -> None:
    api = make_api()
    api.start_infinite.side_effect = BusyBarApiError("offline")
    await setup_busybar(hass, api)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "select",
            "select_option",
            {ATTR_ENTITY_ID: _eid(hass, "select", "theme_select"), "option": "flow"},
            blocking=True,
        )


async def test_switch_api_error(hass: HomeAssistant) -> None:
    api = make_api()
    api.set_smart_home_switch.side_effect = BusyBarApiError("503")
    await setup_busybar(hass, api)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "switch",
            "turn_on",
            {ATTR_ENTITY_ID: _eid(hass, "switch", "smart_home")},
            blocking=True,
        )


async def test_update_install_api_error(hass: HomeAssistant) -> None:
    api = make_api(
        get_update_status={"check": {"status": "available", "available_version": "1.0.0"}}
    )
    api.install_update.side_effect = BusyBarApiError("offline")
    await setup_busybar(hass, api)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "update",
            "install",
            {ATTR_ENTITY_ID: _eid(hass, "update", "firmware_update")},
            blocking=True,
        )


async def test_resume_button_when_paused(hass: HomeAssistant) -> None:
    api = make_api(
        get_snapshot={
            "snapshot": {"type": "SIMPLE", "time_left_ms": 600000, "is_paused": True}
        }
    )
    entry = await setup_busybar(hass, api)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    await hass.services.async_call(
        "button", "press", {ATTR_ENTITY_ID: _eid(hass, "button", "resume_busy")}, blocking=True
    )
    api.resume_busy.assert_awaited()


async def test_stop_button_api_error(hass: HomeAssistant) -> None:
    api = make_api()
    api.stop_busy.side_effect = BusyBarApiError("offline")
    await setup_busybar(hass, api)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button", "press", {ATTR_ENTITY_ID: _eid(hass, "button", "stop_busy")}, blocking=True
        )


async def test_image_returns_bmp(hass: HomeAssistant) -> None:
    api = make_api()
    api.get_screen_b64.return_value = base64.b64encode(bytes([5, 6, 7]) * _PX).decode()
    entry = await setup_busybar(hass, api)
    image_entity = BusyBarScreenImage(entry.runtime_data, hass)
    img = await image_entity.async_image()
    assert img is not None and img[:2] == b"BM"


async def test_image_handles_api_error_and_bad_b64(hass: HomeAssistant) -> None:
    api = make_api()
    entry = await setup_busybar(hass, api)
    image_entity = BusyBarScreenImage(entry.runtime_data, hass)

    api.get_screen_b64.side_effect = BusyBarApiError("offline")
    assert await image_entity.async_image() is None

    api.get_screen_b64.side_effect = None
    api.get_screen_b64.return_value = "!!!not-base64!!!"
    assert await image_entity.async_image() is None
