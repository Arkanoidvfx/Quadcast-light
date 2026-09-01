"""The single writer that owns the LEDs.

One thread holds the HID handle open and renders whatever program is current,
at a fixed cadence. Everything else - the UI, the Discord monitor, notification
blinks - just hands it a program.

This replaces an older design where every color change killed a detached
process and spawned a new one. That cost 200-400 ms per change, raced two
writers against the same device, and let a dead writer go unnoticed, which is
what made Discord mute silently stop working.

Two entry points, and the priority between them is the whole state machine:

    set_program(program)      the standing program (user effect, Discord state)
    flash(program, seconds)   a temporary override that reverts on its own

Because flash() reverts to whatever set_program() holds *at that moment*, a
state change during a notification is simply remembered, not queued: the newest
request wins with no deferral bookkeeping.
"""
from dataclasses import dataclass, field
import math
import threading
import time

from . import device as device_module
from . import effects

FRAME_DELAY = device_module.FRAME_DELAY
CROSSFADE_SECONDS = 0.5
PULSE_PERIOD = 4.0
PULSE_DEPTH = 0.15
RECONNECT_INTERVAL = 2.0

BLACK = ((0, 0, 0), (0, 0, 0))


@dataclass(frozen=True)
class Program:
    """What the LEDs should show: frames, timing, and an optional breath."""

    frames: tuple = field(default=(BLACK,))
    frame_delay: float = FRAME_DELAY
    pulse_period: float = 0.0
    pulse_depth: float = 0.0
    label: str = ""
    # Animations are read as a continuous path through their frames. A
    # notification is not: its flashes have to stay crisp.
    smooth: bool = True

    @classmethod
    def solid(cls, upper, lower, pulse=True, label="Solid"):
        """A held color. It breathes by dimming only, so the chosen color is the peak."""
        return cls(
            frames=((effects.clamp_rgb(upper), effects.clamp_rgb(lower)),),
            pulse_period=PULSE_PERIOD if pulse else 0.0,
            pulse_depth=PULSE_DEPTH if pulse else 0.0,
            label=label,
        )

    @classmethod
    def animation(cls, frames, frame_delay=0.06, label="Animation"):
        frames = tuple(
            (effects.clamp_rgb(upper), effects.clamp_rgb(lower)) for upper, lower in frames
        )
        if not frames:
            raise ValueError("animation requires at least one frame")
        return cls(frames=frames, frame_delay=max(0.02, float(frame_delay)), label=label)

    @classmethod
    def blink(cls, color, on_seconds=0.35, off_seconds=0.25, label="Notification"):
        """On/off cycle rendered as frames, so blinking needs no special path."""
        color = effects.clamp_rgb(color)
        on_frames = max(1, round(on_seconds / FRAME_DELAY))
        off_frames = max(1, round(off_seconds / FRAME_DELAY))
        frames = [(color, color)] * on_frames + [BLACK] * off_frames
        return cls(
            frames=tuple(frames), frame_delay=FRAME_DELAY, label=label, smooth=False
        )

    @classmethod
    def off(cls):
        return cls(frames=(BLACK,), label="Off")

    def frame_at(self, elapsed):
        """The frame this program shows `elapsed` seconds in."""
        if len(self.frames) == 1:
            upper, lower = self.frames[0]
            if self.pulse_period > 0 and self.pulse_depth > 0:
                phase = (elapsed / self.pulse_period) * math.tau
                factor = 1.0 - self.pulse_depth * (1 - math.cos(phase)) / 2
                return effects.apply_factor(upper, factor), effects.apply_factor(lower, factor)
            return upper, lower
        position = elapsed / self.frame_delay
        index = int(position) % len(self.frames)
        if not self.smooth:
            return self.frames[index]
        # Blend into the next frame rather than stepping onto it. The device is
        # refreshed on its own cadence, which does not divide into the frame
        # period, so stepping showed each frame for two ticks or three at
        # random. Wrapping blends the last frame into the first, which is what
        # makes the loop seamless rather than merely gapless.
        following = self.frames[(index + 1) % len(self.frames)]
        current = self.frames[index]
        blend = position - int(position)
        return (
            effects.mix_rgb(current[0], following[0], blend),
            effects.mix_rgb(current[1], following[1], blend),
        )

    def representative_frame(self):
        """A frame that stands for this program, for previews and fade sources."""
        return self.frames[len(self.frames) // 2]


class LightEngine:
    """Owns the device. Start it once, then only hand it programs."""

    def __init__(self, on_status=None, open_device=None, crossfade=CROSSFADE_SECONDS):
        self.on_status = on_status or (lambda connected, detail: None)
        self._open_device = open_device or device_module.open_dev
        self.crossfade = crossfade

        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None

        self._program = Program.off()
        # One clock for the standing program. Editing a colour or a brightness
        # rebuilds the program several times a second while a slider moves, and
        # timestamping each one restarted the animation every time.
        self._program_started = time.monotonic()
        self._flash = None
        self._flash_until = 0.0
        self._flash_started = 0.0
        self._fade_from = None
        self._fade_started = 0.0
        self._rendered = BLACK
        self._connected = False

    # -- public API ---------------------------------------------------------

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="LightEngine", daemon=True)
        self._thread.start()

    def stop(self, blank=False):
        """Stop rendering. blank=True leaves the LEDs dark rather than held."""
        if blank:
            self.set_program(Program.off())
            time.sleep(FRAME_DELAY * 2)
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def set_program(self, program):
        """Set the standing program. Takes effect now unless a flash is running."""
        with self._lock:
            if program == self._program:
                return
            self._program = program
            if self._flash is None:
                self._begin_fade()
        self._wake.set()

    def flash(self, program, seconds):
        """Override for `seconds`, then fall back to the standing program."""
        with self._lock:
            self._flash = program
            self._flash_until = time.monotonic() + max(0.0, seconds)
            self._flash_started = time.monotonic()
            self._begin_fade()
        self._wake.set()

    def cancel_flash(self):
        with self._lock:
            if self._flash is None:
                return
            self._flash = None
            self._begin_fade()
        self._wake.set()

    @property
    def connected(self):
        return self._connected

    @property
    def flashing(self):
        return self._flash is not None

    def current_frame(self):
        """The (upper, lower) pair last written to the device."""
        return self._rendered

    def current_label(self):
        with self._lock:
            program = self._flash or self._program
            return program.label

    # -- internals ----------------------------------------------------------

    def _begin_fade(self):
        """Crossfade from what is on the LEDs now. Caller holds the lock."""
        self._fade_from = self._rendered
        self._fade_started = time.monotonic()

    def _active(self, now):
        """(program, elapsed) for this instant, expiring a finished flash."""
        with self._lock:
            if self._flash is not None and now >= self._flash_until:
                self._flash = None
                self._begin_fade()
            if self._flash is not None:
                return self._flash, now - self._flash_started
            return self._program, now - self._program_started

    def _frame_now(self, now):
        program, elapsed = self._active(now)
        upper, lower = program.frame_at(max(0.0, elapsed))
        fade_from, fade_started = self._fade_from, self._fade_started
        if fade_from is not None and self.crossfade > 0:
            progress = (now - fade_started) / self.crossfade
            if progress >= 1.0:
                self._fade_from = None
            else:
                eased = effects.smoothstep(progress)
                upper = effects.mix_rgb(fade_from[0], upper, eased)
                lower = effects.mix_rgb(fade_from[1], lower, eased)
        return (upper, lower), program.frame_delay

    def _run(self):
        device = None
        while not self._stop.is_set():
            if device is None:
                try:
                    device = self._open_device()
                except Exception as exc:
                    self._set_connected(False, str(exc))
                    self._wake.wait(RECONNECT_INTERVAL)
                    self._wake.clear()
                    continue
                self._set_connected(True, "connected")
                # A reconnect must not inherit a stale fade source.
                with self._lock:
                    self._fade_from = None

            now = time.monotonic()
            frame, delay = self._frame_now(now)
            try:
                device_module.send(device, device_module.apply_packet())
                device_module.send(device, device_module.color_packet(*frame))
            except Exception as exc:
                # The mic was unplugged or re-enumerated. Drop the handle and
                # let the reconnect loop bring the current program back.
                try:
                    device.close()
                except Exception:
                    pass
                device = None
                self._set_connected(False, str(exc))
                continue
            self._rendered = frame
            # Animations pace themselves by frame_delay; a held color still has
            # to be refreshed often or the mic reverts to its flash color.
            self._wake.wait(min(delay, FRAME_DELAY))
            self._wake.clear()

        if device is not None:
            try:
                device.close()
            except Exception:
                pass
        self._set_connected(False, "stopped")

    def _set_connected(self, connected, detail):
        if connected != self._connected:
            self._connected = connected
            self.on_status(connected, detail)
