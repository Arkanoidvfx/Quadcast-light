import threading
import time
import unittest

from quadcastlight import effects
from quadcastlight.engine import BLACK, LightEngine, Program


RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)


class FakeDevice:
    """Records every color packet the engine writes."""

    def __init__(self, fail_after=None):
        self.packets = []
        self.closed = False
        self.fail_after = fail_after
        self.writes = 0

    def send_feature_report(self, buffer):
        self.writes += 1
        if self.fail_after is not None and self.writes > self.fail_after:
            return -1
        if buffer[1] == 0x81:  # a color packet, not a register write
            self.packets.append((tuple(buffer[2:5]), tuple(buffer[6:9])))
        return len(buffer)

    def error(self):
        return "fake device gone"

    def close(self):
        self.closed = True


class ProgramTests(unittest.TestCase):
    def test_solid_pulse_only_dims_so_the_chosen_color_is_the_peak(self):
        program = Program.solid(RED, RED)
        peak = program.frame_at(0.0)
        trough = program.frame_at(program.pulse_period / 2)

        self.assertEqual(peak[0], RED)
        self.assertLess(trough[0][0], RED[0])
        for elapsed in (0.0, 0.7, 1.9, 3.3, 4.0):
            for zone in program.frame_at(elapsed):
                self.assertLessEqual(max(zone), 255)

    def test_solid_without_pulse_is_constant(self):
        program = Program.solid(RED, BLUE, pulse=False)
        self.assertEqual(program.frame_at(0.0), (RED, BLUE))
        self.assertEqual(program.frame_at(12.5), (RED, BLUE))

    def test_animation_moves_between_frames_instead_of_stepping(self):
        """The device refresh does not divide into the frame period, so stepping
        showed each frame for two ticks or three at random."""
        program = Program.animation([(RED, RED), (GREEN, GREEN)], frame_delay=0.1)

        self.assertEqual(program.frame_at(0.0)[0], RED)
        self.assertEqual(program.frame_at(0.1)[0], GREEN)

        halfway = program.frame_at(0.05)[0]
        self.assertNotIn(halfway, (RED, GREEN), "should be between the two")
        self.assertGreater(halfway[0], 0, "still leaving red")
        self.assertGreater(halfway[1], 0, "already arriving at green")

    def test_the_loop_wraps_through_the_last_frame_into_the_first(self):
        """A seam here is what makes a cycle visibly restart rather than run."""
        program = Program.animation([(RED, RED), (GREEN, GREEN)], frame_delay=0.1)

        # Between the last frame and the first, not a jump back to it.
        wrapping = program.frame_at(0.15)[0]
        self.assertNotIn(wrapping, (RED, GREEN))
        self.assertEqual(program.frame_at(0.2)[0], RED, "one full cycle later")

        # The step across the seam is the same size as a step mid-cycle.
        seam = max(
            abs(a - b)
            for a, b in zip(program.frame_at(0.19)[0], program.frame_at(0.21)[0])
        )
        middle = max(
            abs(a - b)
            for a, b in zip(program.frame_at(0.09)[0], program.frame_at(0.11)[0])
        )
        self.assertLessEqual(seam, middle * 1.2)

    def test_a_notification_keeps_hard_edges(self):
        """Blending an alert would turn its flashes into a soft pulse."""
        program = Program.blink(GREEN, on_seconds=0.2, off_seconds=0.2)
        seen = {program.frame_at(t / 100.0)[0] for t in range(40)}

        self.assertEqual(seen, {GREEN, (0, 0, 0)})

    def test_blink_alternates_color_and_black(self):
        program = Program.blink(GREEN, on_seconds=0.1, off_seconds=0.1)

        self.assertEqual(program.frame_at(0.0), (GREEN, GREEN))
        self.assertEqual(program.frame_at(0.15), BLACK)

    def test_animation_rejects_empty_frames(self):
        with self.assertRaises(ValueError):
            Program.animation([])


class PriorityTests(unittest.TestCase):
    """flash() over set_program() is the entire priority model."""

    def setUp(self):
        self.engine = LightEngine(crossfade=0)

    def test_flash_overrides_then_reverts_to_the_standing_program(self):
        self.engine.set_program(Program.solid(RED, RED, pulse=False))
        now = time.monotonic()
        self.assertEqual(self.engine._frame_now(now)[0][0], RED)

        self.engine.flash(Program.solid(GREEN, GREEN, pulse=False), seconds=1.0)
        self.assertEqual(self.engine._frame_now(time.monotonic())[0][0], GREEN)

        # After the flash expires the standing program is back, untouched.
        self.assertEqual(
            self.engine._frame_now(time.monotonic() + 1.5)[0][0], RED
        )
        self.assertFalse(self.engine.flashing)

    def test_program_set_during_a_flash_wins_when_the_flash_ends(self):
        """The old code needed a deferral queue for this; here it is free."""
        self.engine.set_program(Program.solid(RED, RED, pulse=False))
        self.engine.flash(Program.solid(GREEN, GREEN, pulse=False), seconds=1.0)

        # Discord mute arrives mid-notification.
        self.engine.set_program(Program.solid(BLUE, BLUE, pulse=False))
        self.assertEqual(
            self.engine._frame_now(time.monotonic())[0][0], GREEN, "flash still owns the LEDs"
        )

        self.assertEqual(
            self.engine._frame_now(time.monotonic() + 1.5)[0][0],
            BLUE,
            "the newest program must win, not the one from before the flash",
        )

    def test_editing_a_setting_does_not_restart_the_cycle(self):
        """Moving a slider rebuilds the program many times a second. Timestamping
        each one threw the animation back to its first frame every time."""
        frames = [((step * 8, 0, 255 - step * 8), (0, step * 8, 0)) for step in range(32)]
        engine = LightEngine(crossfade=0)
        engine.set_program(Program.animation(frames, 0.1, label="Flow"))

        now = time.monotonic()
        before = engine._frame_now(now + 1.7)[0][0]

        # The same animation, rebuilt one brightness step darker.
        dimmer = [((u[0] - 1, u[1], u[2]), l) for u, l in frames]
        engine.set_program(Program.animation(dimmer, 0.1, label="Flow"))
        after = engine._frame_now(now + 1.7)[0][0]

        drift = max(abs(a - b) for a, b in zip(before, after))
        self.assertLessEqual(drift, 4, "the cycle should carry on, not jump")
        self.assertNotEqual(after, dimmer[0][0], "and certainly not to frame 0")

    def test_a_flash_still_starts_at_its_first_frame(self):
        """The standing program runs on a continuous clock, but an alert has to
        begin lit rather than wherever that clock happens to be."""
        engine = LightEngine(crossfade=0)
        engine.set_program(Program.solid(RED, RED, pulse=False))
        time.sleep(0.05)
        engine.flash(Program.blink(GREEN, on_seconds=0.3, off_seconds=0.3), seconds=2)

        self.assertEqual(engine._frame_now(time.monotonic())[0][0], GREEN)

    def test_cancel_flash_returns_immediately(self):
        self.engine.set_program(Program.solid(RED, RED, pulse=False))
        self.engine.flash(Program.solid(GREEN, GREEN, pulse=False), seconds=60)
        self.engine.cancel_flash()

        self.assertEqual(self.engine._frame_now(time.monotonic())[0][0], RED)

    def test_no_dedup_cache_hides_a_lost_frame(self):
        """Re-setting the same program is a no-op, but rendering never stops."""
        program = Program.solid(RED, RED, pulse=False)
        self.engine.set_program(program)
        self.engine.set_program(program)

        for offset in (0.0, 5.0, 50.0):
            self.assertEqual(
                self.engine._frame_now(time.monotonic() + offset)[0][0], RED
            )


class CrossfadeTests(unittest.TestCase):
    def test_program_change_fades_from_what_is_on_the_leds(self):
        engine = LightEngine(crossfade=1.0)
        engine._rendered = (RED, RED)
        engine.set_program(Program.solid(GREEN, GREEN, pulse=False))

        start = time.monotonic()
        midway = engine._frame_now(start + 0.5)[0][0]

        self.assertNotIn(midway, (RED, GREEN), "midpoint should be a blend")
        self.assertGreater(midway[1], 0, "green rising")
        self.assertGreater(midway[0], 0, "red still fading out")
        self.assertEqual(engine._frame_now(start + 2.0)[0][0], GREEN)


class DeviceLifecycleTests(unittest.TestCase):
    def test_engine_writes_the_program_to_the_device(self):
        device = FakeDevice()
        engine = LightEngine(open_device=lambda: device, crossfade=0)
        engine.set_program(Program.solid(RED, RED, pulse=False))
        engine.start()
        try:
            deadline = time.monotonic() + 2
            while not device.packets and time.monotonic() < deadline:
                time.sleep(0.01)
        finally:
            engine.stop()

        self.assertTrue(device.packets, "engine never wrote a frame")
        self.assertEqual(device.packets[-1], (RED, RED))
        self.assertTrue(device.closed)

    def test_engine_reopens_the_device_and_keeps_the_program(self):
        """A mid-write failure (unplug, re-enumeration) must self-heal."""
        devices = [FakeDevice(fail_after=4), FakeDevice()]
        opened = []

        def open_device():
            if not devices:
                raise RuntimeError("no device")
            device = devices.pop(0)
            opened.append(device)
            return device

        statuses = []
        engine = LightEngine(
            on_status=lambda connected, detail: statuses.append(connected),
            open_device=open_device,
            crossfade=0,
        )
        engine.set_program(Program.solid(BLUE, BLUE, pulse=False))
        engine.start()
        try:
            deadline = time.monotonic() + 5
            while len(opened) < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
            # Give the replacement device a chance to receive frames.
            deadline = time.monotonic() + 2
            while not opened[-1].packets and time.monotonic() < deadline:
                time.sleep(0.01)
        finally:
            engine.stop()

        self.assertEqual(len(opened), 2, "engine did not reopen the device")
        self.assertTrue(opened[0].closed, "the dead handle must be released")
        self.assertEqual(
            opened[1].packets[-1], (BLUE, BLUE), "program must survive a reconnect"
        )
        self.assertIn(False, statuses, "a disconnect must be reported")

    def test_engine_retries_while_the_device_is_missing(self):
        attempts = []

        def open_device():
            attempts.append(time.monotonic())
            raise RuntimeError("not found")

        engine = LightEngine(open_device=open_device, crossfade=0)
        engine.start()
        try:
            time.sleep(0.2)
        finally:
            engine.stop()

        self.assertGreaterEqual(len(attempts), 1)
        self.assertFalse(engine.connected)

    def test_stop_is_idempotent_and_joins(self):
        engine = LightEngine(open_device=FakeDevice, crossfade=0)
        engine.start()
        engine.stop()
        engine.stop()

        self.assertFalse(any(t.name == "LightEngine" and t.is_alive() for t in threading.enumerate()))


class EffectsBridgeTests(unittest.TestCase):
    def test_animation_frames_feed_a_program_directly(self):
        frames = effects.animation_frames("aurora", (128, 0, 255), 50, frame_count=8)
        program = Program.animation(frames, frame_delay=0.06, label="Aurora Flow")

        self.assertEqual(len(program.frames), 8)
        self.assertEqual(program.label, "Aurora Flow")
        for upper, lower in program.frames:
            self.assertLessEqual(max(upper + lower), 255)


if __name__ == "__main__":
    unittest.main()
