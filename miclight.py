"""miclight - control HyperX QuadCast S lighting (color + brightness) without NGENUITY.

The mic exposes a separate USB lighting controller (03F0:028C) with a vendor HID
collection (usage page 0xFF90). Lighting is set with 64-byte HID feature reports:
classic QuadCast S protocol (same as NGENUITY / OpenRGB / quadcastrgb).

Brightness is software scaling of the RGB values (0-100%), exactly like NGENUITY does.

Commands:
  miclight set  <color> [--lower COLOR] [-b N]   stream color until stopped (background)
  miclight animate <preset> <color> [-b N]        stream an animation preset until stopped
                 [--palette COLORS] [--upper-brightness N] [--lower-brightness N]
  miclight save <color> [--lower COLOR] [-b N]   write to mic flash memory (persists,
                                                 no background process needed)
  miclight blink <color> [--times N]              finite notification effect
  miclight off                                   stop streaming and save black (LEDs off)
  miclight stop                                  stop background streamer only
  miclight status                                show device + streamer state

Color: hex RRGGBB (ff0000) or name (red, green, blue, white, orange, purple,
cyan, magenta, yellow, pink, warmwhite, off/black).
"""
import argparse
import ctypes
from ctypes import wintypes
import math
import os
import subprocess
import sys
import time

from quadcastlight import autostart, effects
from quadcastlight import device as device_module
from quadcastlight.device import (
    FRAME_DELAY,
    PID,
    REPORT_LEN,
    USAGE_PAGE,
    VID,
    color_packet,
    reg_packet,
    report,
    save_to_device,
    send,
)
from quadcastlight.effects import (
    ANIMATION_PRESETS,
    NAMED_COLORS,
    animation_frames,
    apply_factor,
    clamp_channel,
    clamp_rgb,
    format_palette,
    hsv_rgb,
    mix_rgb,
    palette_at,
    related_palette,
    rgb_to_hex,
    scale,
)

SOLID_FADE_SECONDS = 0.5  # smooth transition when a new solid color appears
PULSE_PERIOD = 4.0  # seconds per gentle breathing cycle of a held solid color
PULSE_DEPTH = 0.15  # peak dimming of the breathing pulse (fraction of the color, 0..1)

PID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tmp", "miclight.pid")
STARTUP_NAME = autostart.LAUNCHER_NAME


# The library raises ValueError so a GUI can show it; the CLI wants to exit.
def parse_color(value):
    try:
        return effects.parse_color(value)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def parse_palette(value):
    try:
        return effects.parse_palette(value)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def open_dev():
    try:
        return device_module.open_dev()
    except device_module.DeviceNotFound as exc:
        raise SystemExit(str(exc)) from exc


def stream(upper, lower):
    """Continuously send the color (NGENUITY-style direct mode). Blocks forever."""
    dev = open_dev()
    pkt = color_packet(upper, lower)
    apply_pkt = reg_packet(0xF2, 0, 1)
    while True:
        send(dev, apply_pkt)
        send(dev, pkt)
        time.sleep(FRAME_DELAY)


def stream_animation(frames, frame_delay=FRAME_DELAY, fade_from=None, fade_seconds=0.0):
    """Continuously send animation frames in direct mode. Blocks forever.

    fade_from    : ((r,g,b) upper, (r,g,b) lower) to fade in from before the
                   animation starts, or None to begin on the first frame.
    fade_seconds : duration of that smooth fade-in into the first frame.
    """
    if not frames:
        raise ValueError("animation requires at least one frame")
    frame_delay = max(0.02, float(frame_delay))
    dev = open_dev()
    apply_pkt = reg_packet(0xF2, 0, 1)
    packets = [color_packet(upper, lower) for upper, lower in frames]

    if fade_from is not None and fade_seconds > 0:
        target_upper, target_lower = clamp_rgb(frames[0][0]), clamp_rgb(frames[0][1])
        start_upper, start_lower = clamp_rgb(fade_from[0]), clamp_rgb(fade_from[1])
        fade_start = time.monotonic()
        while True:
            progress = (time.monotonic() - fade_start) / fade_seconds
            if progress >= 1.0:
                break
            eased = progress * progress * (3 - 2 * progress)  # smoothstep
            send(dev, apply_pkt)
            send(dev, color_packet(
                mix_rgb(start_upper, target_upper, eased),
                mix_rgb(start_lower, target_lower, eased),
            ))
            time.sleep(frame_delay)

    while True:
        for pkt in packets:
            send(dev, apply_pkt)
            send(dev, pkt)
            time.sleep(frame_delay)


def stream_solid(
    upper,
    lower,
    fade_from=None,
    fade_seconds=0.0,
    pulse_period=PULSE_PERIOD,
    pulse_depth=PULSE_DEPTH,
):
    """Stream a solid color with an optional fade-in and a gentle breathing pulse.

    fade_from    : ((r,g,b) upper, (r,g,b) lower) to transition from, or None to
                   appear directly at the target color.
    fade_seconds : duration of the smooth fade-in transition.
    pulse_period : seconds per breathing cycle (0 disables the pulse).
    pulse_depth  : peak dimming of the pulse as a fraction of the color (0 disables).

    The chosen color is the peak of each breath; the pulse only dims so channels
    never clip and the steady color never looks washed out. Blocks forever.
    """
    dev = open_dev()
    apply_pkt = reg_packet(0xF2, 0, 1)
    target_upper = clamp_rgb(upper)
    target_lower = clamp_rgb(lower)

    if fade_from is not None and fade_seconds > 0:
        start_upper = clamp_rgb(fade_from[0])
        start_lower = clamp_rgb(fade_from[1])
        fade_start = time.monotonic()
        while True:
            progress = (time.monotonic() - fade_start) / fade_seconds
            if progress >= 1.0:
                break
            eased = progress * progress * (3 - 2 * progress)  # smoothstep
            send(dev, apply_pkt)
            send(dev, color_packet(
                mix_rgb(start_upper, target_upper, eased),
                mix_rgb(start_lower, target_lower, eased),
            ))
            time.sleep(FRAME_DELAY)

    pulsing = pulse_period > 0 and pulse_depth > 0
    hold_start = time.monotonic()
    while True:
        if pulsing:
            phase = ((time.monotonic() - hold_start) / pulse_period) * math.tau
            factor = 1.0 - pulse_depth * (1 - math.cos(phase)) / 2
            frame_upper = apply_factor(target_upper, factor)
            frame_lower = apply_factor(target_lower, factor)
        else:
            frame_upper, frame_lower = target_upper, target_lower
        send(dev, apply_pkt)
        send(dev, color_packet(frame_upper, frame_lower))
        time.sleep(FRAME_DELAY)


def show_for(dev, upper, lower, duration):
    """Stream one frame for a finite duration."""
    pkt = color_packet(upper, lower)
    apply_pkt = reg_packet(0xF2, 0, 1)
    deadline = time.monotonic() + max(0, duration)
    while time.monotonic() < deadline:
        send(dev, apply_pkt)
        send(dev, pkt)
        time.sleep(min(FRAME_DELAY, max(0, deadline - time.monotonic())))


def blink(upper, lower=None, times=3, on_duration=0.35, off_duration=0.25):
    """Blink both LED zones, then let the mic return to its saved color."""
    if times < 1:
        raise ValueError("times must be at least 1")
    lower = upper if lower is None else lower
    dev = open_dev()
    try:
        for _ in range(times):
            show_for(dev, upper, lower, on_duration)
            show_for(dev, (0, 0, 0), (0, 0, 0), off_duration)
    finally:
        dev.close()


def read_streamer_pid():
    pid, _creation_marker = read_streamer_record()
    return pid


def read_streamer_record():
    """Return ``(pid, creation_marker)`` from the streamer pid file.

    New pid files include the Windows process creation timestamp so a recycled
    pid cannot be mistaken for our writer. A legacy one-field file returns a
    ``None`` marker and is validated conservatively from its mtime and image.
    """
    try:
        with open(PID_FILE) as f:
            fields = f.read().split()
        pid = int(fields[0])
        marker = int(fields[1]) if len(fields) >= 2 else None
        return pid, marker
    except (OSError, ValueError):
        return None, None


def clear_stale_streamer_pidfile():
    """Drop a pid file left over from a previous Windows session.

    The pid file survives reboots, and Windows recycles pids, so after a boot
    the stored pid can belong to an unrelated python process (often this very
    GUI). streamer_running() would then report a ghost streamer and
    stop_streamer() would taskkill an innocent process tree.
    """
    try:
        mtime = os.path.getmtime(PID_FILE)
    except OSError:
        return
    boot_time = time.time() - ctypes.windll.kernel32.GetTickCount64() / 1000.0
    if mtime < boot_time:
        try:
            os.remove(PID_FILE)
        except OSError:
            pass


def _process_details(pid):
    """Return ``(creation_marker, executable_path)`` for a live process."""
    if not pid:
        return None, None
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None, None
    try:
        created = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None, None
        marker = (created.dwHighDateTime << 32) | created.dwLowDateTime

        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        image = None
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            image = buffer.value
        return marker, image
    finally:
        kernel32.CloseHandle(handle)


def _streamer_executable():
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return pythonw if os.path.exists(pythonw) else sys.executable


def _write_streamer_record(pid):
    marker, _image = _process_details(pid)
    if marker is None:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        raise RuntimeError(f"Cannot verify streamer process ownership (pid {pid}).")
    os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
    temp_path = PID_FILE + ".tmp"
    with open(temp_path, "w") as f:
        f.write(f"{pid} {marker}\n")
    os.replace(temp_path, PID_FILE)


def _legacy_streamer_matches(pid, marker, image):
    """Safely recognize a pre-marker pid file during one upgrade transition."""
    if marker is None or not image:
        return False
    try:
        pidfile_mtime = os.path.getmtime(PID_FILE)
    except OSError:
        return False
    created_at = marker / 10_000_000 - 11_644_473_600
    expected_image = os.path.normcase(os.path.abspath(_streamer_executable()))
    actual_image = os.path.normcase(os.path.abspath(image))
    return actual_image == expected_image and abs(pidfile_mtime - created_at) <= 10.0


def streamer_running(pid):
    if not pid:
        return False
    record_pid, expected_marker = read_streamer_record()
    if record_pid != pid:
        return False
    actual_marker, image = _process_details(pid)
    if expected_marker is None:
        return _legacy_streamer_matches(pid, actual_marker, image)
    return actual_marker == expected_marker


def stop_streamer(quiet=False):
    pid = read_streamer_pid()
    if streamer_running(pid):
        # /T kills the whole tree: some venvs use a launcher stub whose real
        # interpreter (the actual HID writer) is a child process. Without /T the
        # child is orphaned and keeps streaming, fighting the next streamer.
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if not quiet:
            print(f"stopped streamer (pid {pid})")
    elif not quiet:
        print("no streamer running")
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)


def _silent_startupinfo():
    """STARTUPINFO that suppresses the Windows app-starting (busy) cursor.

    Launching a GUI-subsystem process (pythonw) normally makes Windows show the
    spinning "working in background" cursor until the new process goes input-idle.
    STARTF_FORCEOFFFEEDBACK turns that off, so color changes (e.g. Discord mute)
    don't flash a loading cursor.
    """
    info = subprocess.STARTUPINFO()
    info.dwFlags |= 0x80  # STARTF_FORCEOFFFEEDBACK
    return info


def start_streamer(
    upper,
    lower,
    fade_from=None,
    fade_seconds=SOLID_FADE_SECONDS,
    pulse_period=PULSE_PERIOD,
    pulse_depth=PULSE_DEPTH,
):
    """Spawn the background solid streamer (fade-in + gentle breathing pulse).

    fade_from is ((r,g,b) upper, (r,g,b) lower) to fade in from, or None to
    appear directly at the target color.
    """
    stop_streamer(quiet=True)
    exe = _streamer_executable()
    from_upper = rgb_to_hex(fade_from[0]) if fade_from else "-"
    from_lower = rgb_to_hex(fade_from[1]) if fade_from else "-"
    args = [exe, os.path.abspath(__file__), "_solid",
            rgb_to_hex(upper), rgb_to_hex(lower),
            from_upper, from_lower,
            f"{max(0.0, float(fade_seconds)):.3f}",
            f"{max(0.0, float(pulse_period)):.3f}",
            f"{max(0.0, min(1.0, float(pulse_depth))):.3f}"]
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    p = subprocess.Popen(args, creationflags=flags, close_fds=True, startupinfo=_silent_startupinfo())
    _write_streamer_record(p.pid)
    print(f"streaming started (pid {p.pid})")


def start_animation_streamer(
    preset,
    base,
    brightness=100,
    frame_delay=0.06,
    palette=None,
    upper_brightness=100,
    lower_brightness=100,
    fade_from=None,
    fade_seconds=SOLID_FADE_SECONDS,
):
    if preset not in ANIMATION_PRESETS:
        raise ValueError(f"unknown animation preset: {preset}")
    stop_streamer(quiet=True)
    exe = _streamer_executable()
    from_upper = rgb_to_hex(fade_from[0]) if fade_from else "-"
    from_lower = rgb_to_hex(fade_from[1]) if fade_from else "-"
    args = [
        exe,
        os.path.abspath(__file__),
        "_animate",
        preset,
        rgb_to_hex(base),
        str(max(0, min(100, int(brightness)))),
        f"{max(0.02, float(frame_delay)):.3f}",
        format_palette(palette) if palette else "-",
        str(max(0, min(100, int(upper_brightness)))),
        str(max(0, min(100, int(lower_brightness)))),
        # Optional fade-in source appended last so existing arg positions are stable.
        from_upper,
        from_lower,
        f"{max(0.0, float(fade_seconds)):.3f}",
    ]
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    p = subprocess.Popen(args, creationflags=flags, close_fds=True, startupinfo=_silent_startupinfo())
    _write_streamer_record(p.pid)
    print(f"animation streaming started (pid {p.pid})")


def startup_launcher_path():
    return autostart.launcher_path()


def startup_enabled():
    return autostart.enabled()


def set_startup_enabled(enabled):
    autostart.set_enabled(enabled)


def main():
    ap = argparse.ArgumentParser(prog="miclight", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("set", "save", "_stream"):
        p = sub.add_parser(name)
        p.add_argument("color")
        if name == "_stream":
            p.add_argument("lower_color")
        else:
            p.add_argument("--lower", help="separate color for the lower LED zone")
            p.add_argument("-b", "--brightness", type=int, default=100,
                           help="brightness 0-100 (default 100)")
    p = sub.add_parser("animate")
    p.add_argument("preset", choices=sorted(ANIMATION_PRESETS))
    p.add_argument("color")
    p.add_argument("-b", "--brightness", type=int, default=100,
                   help="brightness 0-100 (default 100)")
    p.add_argument("--delay", type=float, default=0.06,
                   help="seconds per animation frame (default 0.06)")
    p.add_argument("--palette", help="comma-separated colors for color_shift")
    p.add_argument("--upper-brightness", type=int, default=100,
                   help="upper LED zone brightness 0-100 (default 100)")
    p.add_argument("--lower-brightness", type=int, default=100,
                   help="lower LED zone brightness 0-100 (default 100)")
    p = sub.add_parser("_animate")
    p.add_argument("preset", choices=sorted(ANIMATION_PRESETS))
    p.add_argument("color")
    p.add_argument("brightness", type=int)
    p.add_argument("delay", type=float)
    p.add_argument("palette")
    p.add_argument("upper_brightness", type=int)
    p.add_argument("lower_brightness", type=int)
    p.add_argument("from_upper", nargs="?", default="-")
    p.add_argument("from_lower", nargs="?", default="-")
    p.add_argument("fade_seconds", nargs="?", type=float, default=0.0)
    p = sub.add_parser("_solid")
    p.add_argument("color")
    p.add_argument("lower_color")
    p.add_argument("from_upper")
    p.add_argument("from_lower")
    p.add_argument("fade_seconds", type=float)
    p.add_argument("pulse_period", type=float)
    p.add_argument("pulse_depth", type=float)
    p = sub.add_parser("blink")
    p.add_argument("color")
    p.add_argument("--lower", help="separate color for the lower LED zone")
    p.add_argument("-b", "--brightness", type=int, default=100,
                   help="brightness 0-100 (default 100)")
    p.add_argument("--times", type=int, default=3)
    p.add_argument("--on", type=float, default=0.35, dest="on_duration")
    p.add_argument("--off-time", type=float, default=0.25, dest="off_duration")
    sub.add_parser("off")
    sub.add_parser("stop")
    sub.add_parser("status")
    a = ap.parse_args()

    if a.cmd == "_stream":  # internal: background worker (legacy solid stream)
        stream(parse_color(a.color), parse_color(a.lower_color))
    elif a.cmd == "_solid":  # internal: background worker (fade-in + breathing pulse)
        fade_from = None
        if a.from_upper != "-" and a.from_lower != "-":
            fade_from = (parse_color(a.from_upper), parse_color(a.from_lower))
        stream_solid(
            parse_color(a.color),
            parse_color(a.lower_color),
            fade_from=fade_from,
            fade_seconds=a.fade_seconds,
            pulse_period=a.pulse_period,
            pulse_depth=a.pulse_depth,
        )
    elif a.cmd == "_animate":  # internal: background worker
        palette = None if a.palette == "-" else parse_palette(a.palette)
        fade_from = None
        if a.from_upper != "-" and a.from_lower != "-":
            fade_from = (parse_color(a.from_upper), parse_color(a.from_lower))
        stream_animation(
            animation_frames(
                a.preset,
                parse_color(a.color),
                a.brightness,
                palette=palette,
                upper_brightness=a.upper_brightness,
                lower_brightness=a.lower_brightness,
            ),
            a.delay,
            fade_from=fade_from,
            fade_seconds=a.fade_seconds,
        )
    elif a.cmd in ("set", "save"):
        upper = scale(parse_color(a.color), a.brightness)
        lower = scale(parse_color(a.lower), a.brightness) if a.lower else upper
        if a.cmd == "set":
            start_streamer(upper, lower)
        else:
            stop_streamer(quiet=True)
            save_to_device(upper, lower)
            print("saved to device memory")
    elif a.cmd == "animate":
        start_animation_streamer(
            a.preset,
            parse_color(a.color),
            a.brightness,
            a.delay,
            parse_palette(a.palette) if a.palette else None,
            a.upper_brightness,
            a.lower_brightness,
        )
    elif a.cmd == "blink":
        upper = scale(parse_color(a.color), a.brightness)
        lower = scale(parse_color(a.lower), a.brightness) if a.lower else upper
        stop_streamer(quiet=True)
        blink(upper, lower, a.times, a.on_duration, a.off_duration)
        print(f"blinked {a.times} time(s)")
    elif a.cmd == "off":
        stop_streamer(quiet=True)
        save_to_device((0, 0, 0), (0, 0, 0))
        print("LEDs off (saved)")
    elif a.cmd == "stop":
        stop_streamer()
    elif a.cmd == "status":
        print("device:", "connected" if device_module.available() else "NOT FOUND")
        pid = read_streamer_pid()
        print("streamer:", f"running (pid {pid})" if streamer_running(pid) else "not running")


if __name__ == "__main__":
    main()
