"""User settings: %APPDATA%\\QuadcastLight\\gui.json.

Every value is validated and clamped on load, so a hand-edited or truncated
file degrades to defaults instead of crashing a resident that starts at logon.
No secrets live here; credentials go through DPAPI in their own files.
"""
import json
import os

SETTINGS_PATH = os.path.join(
    os.environ.get("APPDATA", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "QuadcastLight",
    "gui.json",
)

DEFAULT_COLOR = (128, 0, 255)
DEFAULT_NOTIFICATION_COLOR = (0, 255, 0)
DEFAULT_FLOW_PALETTE = [
    (139, 92, 246),
    (34, 211, 238),
    (16, 185, 129),
    (244, 63, 94),
]

# Preset key -> label shown in the UI. The key is what gets stored.
EFFECTS = (
    ("solid", "Solid"),
    ("color_shift", "Color Shift"),
    ("aurora", "Aurora Flow"),
    ("rainbow", "Spectrum Flow"),
    ("breathe", "Breathing"),
    ("fire", "Ember Wave"),
    ("ocean", "Ocean Drift"),
)
EFFECT_KEYS = tuple(key for key, _label in EFFECTS)
EFFECT_LABELS = dict(EFFECTS)

# What the last explicit user action was, so a resident can restore it at logon.
# What the last explicit action was: restore the effect at logon, or leave it
# to the flash. Brightness zero is how the light gets turned off, so there is
# no third mode to remember.
STARTUP_LIGHT_MODES = ("set", "save")

DEFAULTS = {
    "color": DEFAULT_COLOR,
    "brightness": 25,
    "animation": "solid",
    "speed": 55,
    "flow_palette": list(DEFAULT_FLOW_PALETTE),
    "upper_brightness": 100,
    "lower_brightness": 100,
    "notification_color": DEFAULT_NOTIFICATION_COLOR,
    "notification_times": 8,
    "notification_on_seconds": 1.5,
    "notification_off_seconds": 1.5,
    # Off: every channel flashes the same way. On: a channel may carry its own
    # notification, and anything it does not override falls back to the shared
    # values above.
    "notification_per_channel": False,
    "channel_notifications": {},
    "startup_light": "set",
    # Purely how the mic is drawn: people who hang a QuadCast under a boom arm
    # want the render to match what is in front of them.
    "mic_flipped": False,
}


def clamp_int(value, default, minimum=0, maximum=100):
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


def clamp_float(value, default, minimum, maximum):
    try:
        return max(minimum, min(maximum, float(value)))
    except (TypeError, ValueError):
        return default


def rgb_from_json(value, default):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return default
    try:
        return tuple(max(0, min(255, int(channel))) for channel in value)
    except (TypeError, ValueError):
        return default


def palette_from_json(value):
    if not isinstance(value, list):
        return list(DEFAULT_FLOW_PALETTE)
    palette = [rgb_from_json(color, None) for color in value]
    palette = [color for color in palette if color is not None]
    return palette if len(palette) >= 2 else list(DEFAULT_FLOW_PALETTE)


def channel_notifications_from_json(value):
    """Per-channel notification overrides, keyed by lowercased channel name.

    Every field is optional: an override holds only what differs from the
    shared notification, so adding a field later cannot invalidate a stored
    one, and a half-written entry still resolves.
    """
    if not isinstance(value, dict):
        return {}
    cleaned = {}
    for channel, override in value.items():
        if not isinstance(override, dict):
            continue
        name = str(channel).strip().lower()
        if not name:
            continue
        entry = {}
        color = rgb_from_json(override.get("color"), None)
        if color is not None:
            entry["color"] = color
        if "times" in override:
            entry["times"] = clamp_int(override.get("times"), 8, 1, 30)
        if "on_seconds" in override:
            entry["on_seconds"] = clamp_float(override.get("on_seconds"), 1.5, 0.05, 10.0)
        if "off_seconds" in override:
            entry["off_seconds"] = clamp_float(override.get("off_seconds"), 1.5, 0.05, 10.0)
        if entry:
            cleaned[name] = entry
    return cleaned


def load(path=SETTINGS_PATH):
    settings = dict(DEFAULTS)
    settings["flow_palette"] = list(DEFAULT_FLOW_PALETTE)
    try:
        with open(path, encoding="utf-8") as settings_file:
            data = json.load(settings_file)
    except (OSError, json.JSONDecodeError):
        return settings
    if not isinstance(data, dict):
        return settings

    palette = palette_from_json(data.get("flow_palette"))
    animation = data.get("animation", settings["animation"])
    if animation not in EFFECT_LABELS:
        animation = settings["animation"]
    startup_light = data.get("startup_light", settings["startup_light"])
    if startup_light not in STARTUP_LIGHT_MODES:
        startup_light = settings["startup_light"]

    settings.update(
        {
            "color": rgb_from_json(data.get("color"), settings["color"]),
            "brightness": clamp_int(data.get("brightness"), settings["brightness"]),
            "animation": animation,
            "speed": clamp_int(data.get("speed"), settings["speed"], 1, 100),
            "flow_palette": palette,
            "upper_brightness": clamp_int(
                data.get("upper_brightness"), settings["upper_brightness"]
            ),
            "lower_brightness": clamp_int(
                data.get("lower_brightness"), settings["lower_brightness"]
            ),
            "notification_color": rgb_from_json(
                data.get("notification_color"), settings["notification_color"]
            ),
            "notification_times": clamp_int(
                data.get("notification_times"), settings["notification_times"], 1, 30
            ),
            "notification_on_seconds": clamp_float(
                data.get("notification_on_seconds"),
                settings["notification_on_seconds"],
                0.05,
                10.0,
            ),
            "notification_off_seconds": clamp_float(
                data.get("notification_off_seconds"),
                settings["notification_off_seconds"],
                0.05,
                10.0,
            ),
            "startup_light": startup_light,
            "notification_per_channel": data.get("notification_per_channel") is True,
            "channel_notifications": channel_notifications_from_json(
                data.get("channel_notifications")
            ),
            # Strict: anything that is not a real boolean means upright.
            "mic_flipped": data.get("mic_flipped") is True,
        }
    )
    return settings


def save(settings, path=SETTINGS_PATH):
    """Write atomically: a resident killed mid-write must not lose its config."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        key: list(value) if isinstance(value, tuple) else value
        for key, value in settings.items()
    }
    payload["flow_palette"] = [list(color) for color in settings.get("flow_palette", [])]
    payload["channel_notifications"] = {
        channel: {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in override.items()
        }
        for channel, override in settings.get("channel_notifications", {}).items()
    }
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as settings_file:
        json.dump(payload, settings_file, indent=2)
    os.replace(temp_path, path)


def animation_delay(speed):
    """Seconds per animation frame for a 1-100 speed slider."""
    return 0.16 - (max(1, min(100, speed)) * 0.0013)
