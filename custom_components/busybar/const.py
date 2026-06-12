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

# Auto-scroll speed (scroll_rate, pixels per MINUTE per the device spec) applied
# to a notification line only when it is long enough to overflow the 72px panel.
SCROLL_RATE_NORMAL = 1200

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

# Draw Tool icon set — 66 full-color icons added to the device firmware in FW-984
# (shipped r835+), the same artwork offered in the BUSY web Draw Tool. They live on
# the device as shared/images/dt_<name>.image. Verified live: every icon is exactly
# 16x16 (full panel height), so the notify text offset (icon width + gap) is uniform.
# Exposed under their bare <name> — the "dt_" prefix is a firmware-internal grouping,
# not user-facing — and merged into STOCK_ICONS so the service schemas, the picker
# options and the layout (which keys off the stored width) all pick them up. The
# stock-mono icons above are kept for backward compatibility. The few odd spellings
# (coctail / laught / tounge / sparkls) mirror the device filenames verbatim.
_DT_ICON_NAMES = (
    "apple_green", "apple_red", "apple_yellow",
    "available", "unavailable",
    "basketball", "football", "tennis",
    "book", "study", "work", "home", "leaf",
    "burger", "chicken", "pizza", "pizza_margarita", "pizza_peperoni",
    "pie", "toast", "tomato",
    "coffee", "tea", "coctail", "drink_1", "drink_2",
    "dialog", "dialog_yes", "dialog_no", "yes", "no",
    "crescent_moon_1", "crescent_moon_2", "moon_1", "moon_2",
    "sparkls_1", "sparkls_2",
    "heart_red", "heart_pink", "heart_orange", "heart_yellow",
    "heart_green", "heart_blue", "heart_light_blue", "heart_violet",
    "emoji_happy", "emoji_grinning", "emoji_laught", "emoji_heart_eyes",
    "emoji_relief", "emoji_glasses", "emoji_tounge", "emoji_sweat_smile",
    "emoji_awkward", "emoji_expressionless", "emoji_eyes", "emoji_surprised",
    "emoji_sad", "emoji_cry", "emoji_fatigue", "emoji_sleep", "emoji_melted",
    "emoji_angry", "emoji_evil", "emoji_panic", "emoji_dead",
)

STOCK_ICONS.update(
    {name: (f"shared/images/dt_{name}.image", 16) for name in _DT_ICON_NAMES}
)

# Stock notification sounds, verified present in the device asset Manifest under
# shared/sounds/. The previous mapping (shared/positive.snd, …) pointed at files
# that do not exist on the device, so playback silently no-op'd (play returns 200
# regardless of whether the asset exists).
STOCK_SOUNDS = {
    "event": "shared/sounds/calendar_event_starts.snd",
    "reminder": "shared/sounds/calendar_reminder_ends.snd",
    "volume": "shared/sounds/volume_change.snd",
}
