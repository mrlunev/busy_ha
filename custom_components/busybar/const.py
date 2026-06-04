"""Constants for the BUSY Bar integration."""

DOMAIN = "busybar"
MANUFACTURER = "BUSY Bar"

CONF_TOKEN = "token"

# Base (fast) poll interval. The Pomodoro/timer countdown is exposed as a
# timestamp sensor that the frontend ticks down locally, so the coordinator no
# longer has to poll every few seconds just to move a number. Rarely-changing
# endpoints are fetched on slower multiples of this interval (see below) to keep
# the sustained request rate low (appropriate-polling).
SCAN_INTERVAL = 30
# Fetch the "medium" tier (display brightness, audio volume, Wi-Fi signal,
# smart-home switch) every Nth fast cycle, and the "slow" tier (Matter pairing,
# firmware update check) every Mth cycle. A user-initiated write forces a full
# refresh of all tiers regardless (see BusyBarCoordinator.async_request_refresh_full).
MEDIUM_POLL_FACTOR = 2  # ~60 s
SLOW_POLL_FACTOR = 10  # ~5 min

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

# Draw text fonts (TextElement.font enum from the device draw API; distinct from
# the internal *.font asset files). Verified live on firmware v23 by rendering
# and measuring glyph height: tiny~5px, small~6px (busy 5px), normal/condensed/
# bold~9px, large~11px, extra_large~10px. "global" is an internal fallback.
TEXT_FONTS = [
    "tiny",
    "small",
    "normal",
    "condensed",
    "bold",
    "large",
    "extra_large",
]

# Default font for notification text. "small" is the device's "busy 5px"
# (busy_regular_5); good legibility while leaving room for two lines on 72x16.
DEFAULT_TEXT_FONT = "small"

# Fonts offered for the two-line notify. Positioning anchors line 1 to the top
# and line 2 to the bottom of the 72x16 panel, so any font fits regardless of its
# exact glyph height — except the two tallest, where two lines simply don't fit
# 16px, so they're excluded here (they remain available for the one-line notify).
TWO_LINE_FONTS = ["tiny", "small", "normal", "condensed", "bold"]

# Per-font vertical tuning, calibrated live on the 72x16 panel (api 23). The draw
# fonts have slightly different glyph metrics/baselines, so the same anchor sits a
# pixel off for some of them. Values below are the element `y` after calibration.
#
# one_line uses a `mid_left` anchor (vertical center). Base center is y=8; most
# fonts read better one pixel higher, while tiny/extra_large are already centered.
NOTIFY_ONE_LINE_Y = {
    "tiny": 8,
    "small": 7,
    "normal": 7,
    "condensed": 7,
    "bold": 7,
    "large": 7,
    "extra_large": 8,
}

# two_lines anchors line 1 to the top (`top_left`) and line 2 to the bottom
# (`bottom_left`). Each entry is (top_y, bottom_y). small sits at the raw anchors;
# tiny pulls the lines together, the 9px fonts push them apart so they don't kiss.
NOTIFY_TWO_LINE_Y = {
    "tiny": (1, 15),
    "small": (0, 16),
    "normal": (-1, 17),
    "condensed": (-1, 17),
    "bold": (-1, 17),
}

# Gap (px) between a left-aligned icon and the text that follows it.
ICON_TEXT_GAP = 2

# Named scroll speeds → scroll_rate (pixels per MINUTE, per the device spec).
# "auto" is resolved at call time: scroll only when the text overflows.
SCROLL_RATES = {
    "off": 0,
    "slow": 600,
    "normal": 1200,
    "fast": 2400,
}

# Curated front-display stock icons, verified against the device asset Manifest
# (/api/storage/read?path=/ext/Manifest). They are small enough to sit next to
# text on the 72x16 panel.
#
# stock_path is the Manifest path without the "apps_assets/" prefix and is only
# resolved under the "shared/" root — it REQUIRES the sub-folder and the file
# extension (verified live: a path without extension, or under another root such
# as "busy/", does not render even though draw returns 200 OK). The flat
# `shared/<name>` pattern in the OpenAPI spec is outdated.
#
# Each value is (stock_path, width_px). The width drives the text offset in the
# notify layouts: text is shifted right by the icon width (+ICON_TEXT_GAP) so the
# icon and text never overlap, regardless of the icon size. The shipped icons are
# 5/8/11px wide today; the layout adapts to whatever width an icon declares.
STOCK_ICONS = {
    "check": ("shared/images/checkmark_front_8x8.image", 8),
    "error": ("shared/images/error_front_8x8.image", 8),
    "info": ("shared/images/info_front_8x8.image", 8),
    "low_battery": ("shared/images/low_battery_front_8x8.image", 8),
    "clock": ("shared/images/clock_5x5.image", 5),
    "hourglass": ("shared/images/hourglass_5x5.image", 5),
    "start": ("shared/images/start_11x11.image", 11),
    "setup": ("shared/images/setup_11x11.image", 11),
}

# Stock notification sounds, verified present in the device asset Manifest under
# shared/sounds/. The previous mapping (shared/positive.snd, …) pointed at files
# that do not exist on the device, so playback silently no-op'd (play returns 200
# regardless of whether the asset exists).
STOCK_SOUNDS = {
    "event": "shared/sounds/calendar_event_starts.snd",
    "reminder": "shared/sounds/calendar_reminder_ends.snd",
    "volume": "shared/sounds/volume_change.snd",
}
