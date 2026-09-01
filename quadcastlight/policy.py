"""What should be on the LEDs right now.

Pure decisions, no device and no threads: given the settings and the current
Discord voice state, return the Program the engine should hold. Keeping this
separate from the UI is what lets the same rules be tested without a window and
reused by the CLI.
"""
from . import effects
from . import settings as settings_module
from .engine import Program

# Discord alerts run at full zone brightness: an alert that respects a dimmed
# upper zone can end up invisible, which defeats the point of an alert.
ALERT_BRIGHTNESS = 100
ALERT_ZONE_BRIGHTNESS = 100
ALERT_FRAME_DELAY = 0.08
ALERT_FRAME_COUNT = 24


def zone_colors(rgb, brightness, upper_brightness, lower_brightness):
    """Apply the master brightness and each zone's own level, in one step."""
    return (
        effects.scale_zone(rgb, brightness, upper_brightness),
        effects.scale_zone(rgb, brightness, lower_brightness),
    )


def alert_palette(color):
    """Companion shades close to the alert color, so the flow reads as one hue."""
    red, green, blue = effects.clamp_rgb(color)
    return [
        (red, green, blue),
        (min(255, red + 14), max(0, int(green * 0.78)), max(0, int(blue * 0.72))),
        (
            max(0, int(red * 0.88)),
            min(120, int(green * 1.08) + 8),
            min(80, int(blue * 1.05) + 4),
        ),
        (min(255, red + 6), max(0, int(green * 0.48)), max(0, int(blue * 0.50))),
    ]


def effect_program(settings):
    """The user's selected color and effect, as a Program."""
    preset = settings["animation"]
    label = settings_module.EFFECT_LABELS.get(preset, preset)
    upper, lower = zone_colors(
        settings["color"],
        settings["brightness"],
        settings["upper_brightness"],
        settings["lower_brightness"],
    )
    if preset == "solid":
        return Program.solid(upper, lower, label=label)
    palette = settings["flow_palette"] if preset == "color_shift" else None
    frames = effects.animation_frames(
        preset,
        settings["color"],
        settings["brightness"],
        palette=palette,
        upper_brightness=settings["upper_brightness"],
        lower_brightness=settings["lower_brightness"],
    )
    return Program.animation(
        frames, settings_module.animation_delay(settings["speed"]), label=label
    )


def alert_program(color, brightness=ALERT_BRIGHTNESS, label="Discord alert"):
    """The flowing alert used for Discord mute and deafen."""
    frames = effects.animation_frames(
        "color_shift",
        color,
        brightness,
        frame_count=ALERT_FRAME_COUNT,
        palette=alert_palette(color),
        upper_brightness=ALERT_ZONE_BRIGHTNESS,
        lower_brightness=ALERT_ZONE_BRIGHTNESS,
    )
    return Program.animation(frames, ALERT_FRAME_DELAY, label=label)


def notification_for(settings, channel=None):
    """The notification a channel should get: (color, times, on, off).

    Falls back field by field, so a channel that only overrides its color keeps
    the shared timing, and turning per-channel off restores the shared
    notification everywhere without discarding what was set.
    """
    shared = (
        settings["notification_color"],
        settings["notification_times"],
        settings["notification_on_seconds"],
        settings["notification_off_seconds"],
    )
    if not settings.get("notification_per_channel") or not channel:
        return shared
    override = settings.get("channel_notifications", {}).get(str(channel).lower())
    if not override:
        return shared
    color, times, on_seconds, off_seconds = shared
    return (
        override.get("color", color),
        override.get("times", times),
        override.get("on_seconds", on_seconds),
        override.get("off_seconds", off_seconds),
    )


def notification_program(color, on_seconds, off_seconds):
    return Program.blink(color, on_seconds, off_seconds, label="Notification")


def notification_duration(times, on_seconds, off_seconds):
    return times * (on_seconds + off_seconds)


def decide(voice_state, settings, discord_config):
    """The standing Program for a voice state, or None to leave the light alone.

    None means "the user turned restore off, so keep showing whatever is on" -
    distinct from "show the selected effect".
    """
    brightness = discord_config.get("brightness")
    brightness = ALERT_BRIGHTNESS if brightness is None else max(0, min(100, int(brightness)))

    if voice_state is not None and voice_state.deafened:
        return alert_program(discord_config["deafen_color"], brightness, "Discord deafened")
    if voice_state is not None and voice_state.muted:
        return alert_program(discord_config["mute_color"], brightness, "Discord muted")
    if voice_state is not None and not discord_config.get("restore_default", True):
        return None
    return effect_program(settings)
