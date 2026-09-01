"""Color math and animation frame generation.

Pure functions: no device, no threads, no I/O. Everything here is safe to call
from the UI thread and easy to test.

Brightness is software scaling of RGB (0-100%), exactly how NGENUITY does it;
the protocol itself has no brightness register.
"""
import colorsys
import math

NAMED_COLORS = {
    "red": "ff0000", "green": "00ff00", "blue": "0000ff", "white": "ffffff",
    "orange": "ff5a00", "purple": "8000ff", "cyan": "00ffff", "magenta": "ff00ff",
    "yellow": "ffff00", "pink": "ff3066", "warmwhite": "ffb44c",
    "off": "000000", "black": "000000",
}

ANIMATION_PRESETS = {
    "color_shift": "selected hue with smooth companion colors",
    "aurora": "green, cyan, violet, and rose flow",
    "rainbow": "full spectrum two-zone flow",
    "breathe": "soft fade in and out of the selected color",
    "fire": "ember orange and red wave",
    "ocean": "deep blue and cyan drift",
}


def parse_color(value):
    """Parse 'ff0000', '#ff0000' or a name into an (r, g, b) tuple."""
    text = str(value).strip().lower().lstrip("#")
    text = NAMED_COLORS.get(text, text)
    if len(text) != 6 or any(char not in "0123456789abcdef" for char in text):
        raise ValueError(
            f"bad color: {value!r} (use hex RRGGBB or a name: {', '.join(NAMED_COLORS)})"
        )
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def parse_palette(value):
    if value is None:
        return None
    parts = [
        part.strip()
        for part in value.replace(";", ",").replace("|", ",").replace(" ", ",").split(",")
        if part.strip()
    ]
    if len(parts) < 2:
        raise ValueError("palette needs at least two colors")
    return [parse_color(part) for part in parts]


def scale(rgb, brightness):
    return scale_zone(rgb, brightness, 100)


def scale_zone(rgb, master, zone):
    """Apply the master level and a zone level in one step.

    Doing it as two integer divisions rounded down twice, which darkened every
    channel by about a level and cost one more off the top of the range. One
    multiply and one rounding removes that bias.

    It does not buy back much range, and it cannot: at 20% master with a zone
    at 25% the brightest a channel can be is 12 of 255, so the palette really
    is about fourteen levels deep. That is the 8-bit device and the multiply,
    not the arithmetic, and NGENUITY scales in software the same way. Coarse
    animation at a low brightness is the hardware talking.
    """
    factor = (max(0, min(100, master)) / 100.0) * (max(0, min(100, zone)) / 100.0)
    return clamp_rgb(channel * factor for channel in rgb)


def apply_factor(rgb, factor):
    """Multiply an RGB triple by a float factor and clamp to 0-255."""
    return clamp_rgb(channel * factor for channel in rgb)


def clamp_channel(value):
    return max(0, min(255, int(round(value))))


def clamp_rgb(rgb):
    return tuple(clamp_channel(channel) for channel in rgb)


def rgb_to_hex(rgb):
    rgb = clamp_rgb(rgb)
    return f"{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def format_palette(palette):
    return ",".join(rgb_to_hex(color) for color in palette)


def mix_rgb(left, right, amount):
    amount = max(0.0, min(1.0, amount))
    return clamp_rgb(left[i] + (right[i] - left[i]) * amount for i in range(3))


def smoothstep(progress):
    """Ease 0..1 with a smooth start and end; the shape every fade here uses."""
    progress = max(0.0, min(1.0, progress))
    return progress * progress * (3 - 2 * progress)


def hsv_rgb(hue, saturation=1.0, value=1.0):
    return clamp_rgb(
        channel * 255 for channel in colorsys.hsv_to_rgb(hue % 1.0, saturation, value)
    )


def palette_at(palette, position):
    if not palette:
        return (0, 0, 0)
    if len(palette) == 1:
        return palette[0]
    scaled = (position % 1.0) * len(palette)
    index = int(scaled) % len(palette)
    return mix_rgb(palette[index], palette[(index + 1) % len(palette)], scaled - int(scaled))


def related_palette(base):
    """Companion colors around a base hue, for the Color Shift preset."""
    if base == (0, 0, 0):
        base = parse_color("8000ff")
    red, green, blue = (channel / 255 for channel in base)
    hue, saturation, value = colorsys.rgb_to_hsv(red, green, blue)
    saturation = max(0.65, saturation)
    value = max(0.85, value)
    return [
        hsv_rgb(hue, saturation, value),
        hsv_rgb(hue + 0.08, min(1.0, saturation + 0.1), value),
        hsv_rgb(hue + 0.48, saturation, value),
        hsv_rgb(hue + 0.62, saturation, max(0.75, value - 0.1)),
    ]


def animation_frames(
    preset,
    base,
    brightness=100,
    frame_count=48,
    palette=None,
    upper_brightness=100,
    lower_brightness=100,
):
    """Build direct-stream frames for an animation preset.

    Returns a list of (upper_rgb, lower_rgb) tuples, already brightness-scaled.
    """
    if preset not in ANIMATION_PRESETS:
        raise ValueError(f"unknown animation preset: {preset}")
    if frame_count < 2:
        raise ValueError("frame_count must be at least 2")

    base = clamp_rgb(base)
    palette = [clamp_rgb(color) for color in palette] if palette else None
    frames = []
    if preset == "rainbow":
        for index in range(frame_count):
            position = index / frame_count
            frames.append((hsv_rgb(position), hsv_rgb(position + 0.12)))
    elif preset == "aurora":
        palette = [parse_color(color) for color in ("22c55e", "06b6d4", "8b5cf6", "f43f5e")]
        for index in range(frame_count):
            position = index / frame_count
            frames.append((palette_at(palette, position), palette_at(palette, position + 0.18)))
    elif preset == "fire":
        palette = [parse_color(color) for color in ("ff2d00", "ff7a00", "ffd166", "7f1d1d")]
        for index in range(frame_count):
            position = index / frame_count
            frames.append((palette_at(palette, position), palette_at(palette, position + 0.14)))
    elif preset == "ocean":
        palette = [parse_color(color) for color in ("0f172a", "0ea5e9", "22d3ee", "14b8a6")]
        for index in range(frame_count):
            position = index / frame_count
            frames.append((palette_at(palette, position), palette_at(palette, position + 0.2)))
    elif preset == "breathe":
        for index in range(frame_count):
            wave = (1 - math.cos((index / frame_count) * math.tau)) / 2
            intensity = 0.18 + wave * 0.82
            color = clamp_rgb(channel * intensity for channel in base)
            frames.append((color, color))
    elif preset == "color_shift":
        palette = palette or related_palette(base)
        for index in range(frame_count):
            position = index / frame_count
            frames.append((palette_at(palette, position), palette_at(palette, position + 0.16)))

    return [
        (
            scale_zone(upper, brightness, upper_brightness),
            scale_zone(lower, brightness, lower_brightness),
        )
        for upper, lower in frames
    ]
