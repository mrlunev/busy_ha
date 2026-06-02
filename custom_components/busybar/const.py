"""Constants for the BUSY Bar integration."""

DOMAIN = "busybar"
MANUFACTURER = "BUSY Bar"

CONF_HOST = "host"
CONF_TOKEN = "token"

DEFAULT_PORT = 80
SCAN_INTERVAL = 5

# Minimum device API contract we support (major of `system.api_semver`, e.g.
# "23.0.0"). Older firmware exposes a different/incompatible API surface, so we
# reject it at config time with a "please update firmware" message.
MIN_API_MAJOR = 23

APPLICATION_NAME = "home_assistant"
PRIORITY_DEFAULT = 50
PRIORITY_INTERRUPT = 91

# Physical rotary selector positions (galette switch). /api/input accepts these
# as keys; the device tolerates a mismatch between the selected section and what
# is on screen, and a physical turn updates the software position.
SELECTOR_POSITIONS = ["busy", "custom", "off", "apps", "settings"]

# BUSY timer snapshot types from /api/busy/snapshot.
SNAPSHOT_TYPES = ["NOT_STARTED", "INFINITE", "SIMPLE", "INTERVAL"]

THEMES = [
    "meeting",
    "dnd",
    "on_call",
    "on_air",
    "flow",
    "lunch",
    "back_soon",
    "booked",
    "chill_time",
    "keep_out",
    "busy",
]

STOCK_SOUNDS = {
    "positive": "shared/positive.snd",
    "negative": "shared/negative.snd",
    "alarm": "shared/alarm.snd",
    "notification": "shared/notification.snd",
}
