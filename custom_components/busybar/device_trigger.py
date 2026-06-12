"""Device triggers for the BUSY Bar (physical input as automation triggers).

The bar streams physical input over WebSocket (see ``ws.py`` / ``coordinator``),
which the coordinator re-emits as ``busybar_event`` events. This module exposes
those as UI-selectable device triggers ("When the Start button is pressed",
"When the selector is turned to BUSY", …) so users can build automations without
hand-writing event filters — the bar becomes a physical controller for HA.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_DOMAIN,
    CONF_PLATFORM,
    CONF_TYPE,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers.trigger import TriggerActionType, TriggerInfo
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import EVENT_INPUT

# Each trigger type maps to the ``busybar_event`` data that identifies it (the
# device_id is added at attach time). Buttons trigger on press (the natural
# moment for an automation); the selector on each rotary position; the encoder
# on any rotation (the turn direction is in the event's ``delta``).
TRIGGER_TYPES: dict[str, dict[str, Any]] = {
    "ok_pressed": {"type": "button", "button": "ok", "action": "press"},
    "back_pressed": {"type": "button", "button": "back", "action": "press"},
    "start_pressed": {"type": "button", "button": "start", "action": "press"},
    "selector_busy": {"type": "selector", "position": "busy"},
    "selector_custom": {"type": "selector", "position": "custom"},
    "selector_off": {"type": "selector", "position": "off"},
    "selector_apps": {"type": "selector", "position": "apps"},
    "selector_settings": {"type": "selector", "position": "settings"},
    "encoder_rotated": {"type": "encoder"},
}

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {vol.Required(CONF_TYPE): vol.In(TRIGGER_TYPES)}
)


async def async_get_triggers(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, Any]]:
    """List the device triggers a BUSY Bar offers."""
    return [
        {
            CONF_PLATFORM: "device",
            CONF_DOMAIN: DOMAIN,
            CONF_DEVICE_ID: device_id,
            CONF_TYPE: trigger_type,
        }
        for trigger_type in TRIGGER_TYPES
    ]


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: TriggerActionType,
    trigger_info: TriggerInfo,
) -> CALLBACK_TYPE:
    """Attach a device trigger by filtering the integration's input events."""
    event_data = {
        "device_id": config[CONF_DEVICE_ID],
        **TRIGGER_TYPES[config[CONF_TYPE]],
    }
    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: EVENT_INPUT,
            event_trigger.CONF_EVENT_DATA: event_data,
        }
    )
    return await event_trigger.async_attach_trigger(
        hass, event_config, action, trigger_info, platform_type="device"
    )
