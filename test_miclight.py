import os
import tempfile
import unittest
from unittest import mock

import miclight


class FakeDevice:
    def __init__(self):
        self.reports = []
        self.closed = False

    def send_feature_report(self, report):
        self.reports.append(report)
        return len(report)

    def close(self):
        self.closed = True


class MicLightTests(unittest.TestCase):
    def test_color_packet_contains_both_zones(self):
        packet = miclight.color_packet((1, 2, 3), (4, 5, 6))
        self.assertEqual(packet[:9], bytes([0, 0x81, 1, 2, 3, 0x81, 4, 5, 6]))
        self.assertEqual(len(packet), miclight.REPORT_LEN)

    def test_blink_sends_on_and_off_frames(self):
        device = FakeDevice()
        with mock.patch.object(miclight, "open_dev", return_value=device):
            with mock.patch.object(miclight, "show_for") as show_for:
                miclight.blink((0, 255, 0), times=3)

        self.assertEqual(show_for.call_count, 6)
        self.assertEqual(show_for.call_args_list[0].args[1:3], ((0, 255, 0), (0, 255, 0)))
        self.assertEqual(show_for.call_args_list[1].args[1:3], ((0, 0, 0), (0, 0, 0)))
        self.assertTrue(device.closed)

    def test_save_to_device_emits_correct_eot_packet(self):
        # Mock where the writer actually resolves open_dev, or the test opens
        # the real microphone and writes to its flash.
        fake = FakeDevice()
        with mock.patch.object(miclight.device_module, "open_dev", return_value=fake):
            with mock.patch.object(miclight.device_module.time, "sleep"):
                miclight.save_to_device((1, 2, 3), (4, 5, 6))

        device = fake
        eot = device.reports[4]
        self.assertEqual(eot[1], 0x08)
        self.assertEqual(eot[0x3C], 0x28)
        self.assertEqual(eot[0x3D], 1)
        self.assertEqual(eot[0x3F], 0xAA)
        self.assertEqual(eot[0x40], 0x55)
        self.assertTrue(device.closed)

    def test_the_save_declares_one_packet_and_one_frame(self):
        """The flash holds a colour, not an effect. Writing 48 frames left the
        device on a still colour; OpenRGB, where this sequence comes from, only
        ever declares one frame too."""
        fake = FakeDevice()
        with mock.patch.object(miclight.device_module, "open_dev", return_value=fake):
            with mock.patch.object(miclight.device_module.time, "sleep"):
                miclight.save_to_device((9, 8, 7), (6, 5, 4))

        start = fake.reports[0]
        self.assertEqual(start[2], 0x53)
        self.assertEqual(start[8], 1, "one colour packet")

        colour = fake.reports[1]
        self.assertEqual(list(colour[1:9]), [0x81, 9, 8, 7, 0x81, 6, 5, 4])

        eot = next(r for r in fake.reports if r[1] == 0x08)
        self.assertEqual(eot[0x3D], 1, "one frame")

    def test_animation_frames_are_scaled_rgb_pairs(self):
        frames = miclight.animation_frames("color_shift", (128, 0, 255), brightness=25, frame_count=8)

        self.assertEqual(len(frames), 8)
        for upper, lower in frames:
            self.assertEqual(len(upper), 3)
            self.assertEqual(len(lower), 3)
            self.assertTrue(all(0 <= channel <= 64 for channel in upper))
            self.assertTrue(all(0 <= channel <= 64 for channel in lower))
        self.assertNotEqual(frames[0][0], frames[0][1])

    def test_parse_palette_accepts_common_separators(self):
        palette = miclight.parse_palette("#ff0000; 00ff00|blue")

        self.assertEqual(palette, [(255, 0, 0), (0, 255, 0), (0, 0, 255)])

    def test_animation_frames_apply_custom_palette_and_zone_brightness(self):
        frames = miclight.animation_frames(
            "color_shift",
            (128, 0, 255),
            brightness=100,
            frame_count=4,
            palette=[(255, 0, 0), (0, 0, 255)],
            upper_brightness=0,
            lower_brightness=100,
        )

        self.assertTrue(all(upper == (0, 0, 0) for upper, _lower in frames))
        self.assertTrue(any(lower != (0, 0, 0) for _upper, lower in frames))

    def test_start_animation_streamer_passes_worker_arguments(self):
        process = mock.Mock(pid=1234)
        with tempfile.TemporaryDirectory() as temp_dir:
            pid_file = os.path.join(temp_dir, "miclight.pid")
            with mock.patch.object(miclight, "PID_FILE", pid_file):
                with mock.patch.object(miclight, "stop_streamer") as stop_streamer:
                    with mock.patch.object(miclight.subprocess, "Popen", return_value=process) as popen:
                        with mock.patch.object(miclight, "_write_streamer_record") as write_record:
                            miclight.start_animation_streamer(
                                "aurora",
                                (1, 2, 3),
                                brightness=40,
                                frame_delay=0.07,
                                palette=[(255, 0, 0), (0, 0, 255)],
                                upper_brightness=25,
                                lower_brightness=75,
                            )

        stop_streamer.assert_called_once_with(quiet=True)
        write_record.assert_called_once_with(1234)
        args = popen.call_args.args[0]
        self.assertEqual(
            args[2:10],
            ["_animate", "aurora", "010203", "40", "0.070", "ff0000,0000ff", "25", "75"],
        )

    def test_start_animation_streamer_appends_fade_source(self):
        process = mock.Mock(pid=1234)
        with tempfile.TemporaryDirectory() as temp_dir:
            pid_file = os.path.join(temp_dir, "miclight.pid")
            with mock.patch.object(miclight, "PID_FILE", pid_file):
                with mock.patch.object(miclight, "stop_streamer"):
                    with mock.patch.object(miclight.subprocess, "Popen", return_value=process) as popen:
                        with mock.patch.object(miclight, "_write_streamer_record"):
                            miclight.start_animation_streamer(
                                "aurora",
                                (1, 2, 3),
                                brightness=40,
                                frame_delay=0.07,
                                fade_from=((10, 20, 30), (40, 50, 60)),
                                fade_seconds=0.5,
                            )

        args = popen.call_args.args[0]
        # Original positions stay stable; fade source is appended at the end.
        self.assertEqual(args[2:6], ["_animate", "aurora", "010203", "40"])
        self.assertEqual(args[-3:], ["0a141e", "28323c", "0.500"])

    def test_animate_parser_accepts_legacy_and_fade_forms(self):
        ap = miclight.argparse  # noqa: F841 - ensure argparse is wired in module
        with mock.patch.object(miclight, "stream_animation") as stream_animation:
            with mock.patch.object(miclight, "animation_frames", return_value=[((1, 2, 3), (4, 5, 6))]):
                with mock.patch.object(
                    miclight.sys,
                    "argv",
                    ["miclight.py", "_animate", "aurora", "010203", "40", "0.070", "-", "25", "75"],
                ):
                    miclight.main()
                self.assertIsNone(stream_animation.call_args.kwargs["fade_from"])

                with mock.patch.object(
                    miclight.sys,
                    "argv",
                    ["miclight.py", "_animate", "aurora", "010203", "40", "0.070", "-", "25", "75",
                     "0a141e", "28323c", "0.500"],
                ):
                    miclight.main()
                self.assertEqual(
                    stream_animation.call_args.kwargs["fade_from"], ((10, 20, 30), (40, 50, 60))
                )

    def test_stop_streamer_kills_process_tree(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pid_file = os.path.join(temp_dir, "miclight.pid")
            with open(pid_file, "w") as handle:
                handle.write("4321")
            with mock.patch.object(miclight, "PID_FILE", pid_file):
                with mock.patch.object(miclight, "streamer_running", return_value=True):
                    with mock.patch.object(miclight.subprocess, "run") as run:
                        miclight.stop_streamer(quiet=True)

        args = run.call_args.args[0]
        self.assertEqual(args[:2], ["taskkill", "/PID"])
        self.assertIn("/T", args)  # whole tree, so the real child writer dies too
        self.assertIn("/F", args)

    def test_cli_status_reports_device_and_streamer(self):
        """The status path is pure plumbing, which is exactly how it rotted before:
        it called a module that was no longer imported and nothing noticed."""
        import io
        from contextlib import redirect_stdout

        # Use a real pid so streamer_running() actually walks the Win32 path
        # instead of short-circuiting on None.
        with mock.patch.object(miclight.device_module, "available", return_value=True):
            with mock.patch.object(miclight, "read_streamer_pid", return_value=os.getpid()):
                with mock.patch.object(miclight.sys, "argv", ["miclight", "status"]):
                    output = io.StringIO()
                    with redirect_stdout(output):
                        miclight.main()

        self.assertIn("device: connected", output.getvalue())
        self.assertIn("streamer: not running", output.getvalue())

    def test_apply_factor_dims_and_clamps(self):
        self.assertEqual(miclight.apply_factor((200, 100, 0), 0.5), (100, 50, 0))
        self.assertEqual(miclight.apply_factor((255, 90, 0), 1.2), (255, 108, 0))

    def test_start_streamer_passes_solid_worker_arguments(self):
        process = mock.Mock(pid=99)
        with tempfile.TemporaryDirectory() as temp_dir:
            pid_file = os.path.join(temp_dir, "miclight.pid")
            with mock.patch.object(miclight, "PID_FILE", pid_file):
                with mock.patch.object(miclight, "stop_streamer"):
                    with mock.patch.object(miclight.subprocess, "Popen", return_value=process) as popen:
                        with mock.patch.object(miclight, "_write_streamer_record"):
                            miclight.start_streamer((128, 0, 255), (16, 32, 48))

        args = popen.call_args.args[0]
        self.assertEqual(args[2], "_solid")
        self.assertEqual(args[3:7], ["8000ff", "102030", "-", "-"])
        self.assertEqual(args[7], f"{miclight.SOLID_FADE_SECONDS:.3f}")

    def test_start_streamer_passes_fade_source(self):
        process = mock.Mock(pid=99)
        with tempfile.TemporaryDirectory() as temp_dir:
            pid_file = os.path.join(temp_dir, "miclight.pid")
            with mock.patch.object(miclight, "PID_FILE", pid_file):
                with mock.patch.object(miclight, "stop_streamer"):
                    with mock.patch.object(miclight.subprocess, "Popen", return_value=process) as popen:
                        with mock.patch.object(miclight, "_write_streamer_record"):
                            miclight.start_streamer(
                                (255, 0, 0),
                                (255, 0, 0),
                                fade_from=((0, 0, 0), (1, 2, 3)),
                            )

        args = popen.call_args.args[0]
        self.assertEqual(args[3:7], ["ff0000", "ff0000", "000000", "010203"])

    def test_stream_solid_fades_then_holds_with_pulse(self):
        device = FakeDevice()
        clock = {"t": 0.0}

        def fake_monotonic():
            now = clock["t"]
            clock["t"] += 0.05
            return now

        # Stop once the fade is done and a couple of pulse frames are sent.
        def fake_sleep(_seconds):
            if len(device.reports) >= 40:
                raise KeyboardInterrupt

        with mock.patch.object(miclight, "open_dev", return_value=device):
            with mock.patch.object(miclight.time, "monotonic", side_effect=fake_monotonic):
                with mock.patch.object(miclight.time, "sleep", side_effect=fake_sleep):
                    with self.assertRaises(KeyboardInterrupt):
                        miclight.stream_solid(
                            (200, 100, 0),
                            (200, 100, 0),
                            fade_from=((0, 0, 0), (0, 0, 0)),
                            fade_seconds=0.5,
                            pulse_period=4.0,
                            pulse_depth=0.15,
                        )

        # color packets carry the upper zone in bytes 2..4 (after report id + 0x81).
        first_color = next(r for r in device.reports if r[1] == 0x81)
        self.assertLess(first_color[2], 40)  # fade begins near the source (black), not the target
        last_color = [r for r in device.reports if r[1] == 0x81][-1]
        # held pulse never exceeds the chosen color and stays close to it
        self.assertLessEqual(last_color[2], 200)
        self.assertGreaterEqual(last_color[2], int(200 * (1 - 0.15)) - 1)

    def test_startup_launcher_create_and_remove(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with mock.patch.dict(os.environ, {"APPDATA": temp_dir}):
                with mock.patch.object(miclight, "__file__", os.path.join(temp_dir, "miclight.py")):
                    with mock.patch.object(miclight.sys, "executable", os.path.join(temp_dir, "python.exe")):
                        miclight.set_startup_enabled(True)
                        path = miclight.startup_launcher_path()
                        self.assertTrue(os.path.isfile(path))
                        with open(path) as launcher:
                            contents = launcher.read()
                        self.assertIn("miclight_gui.pyw", contents)
                        self.assertTrue(miclight.startup_enabled())

                        miclight.set_startup_enabled(False)
                        self.assertFalse(os.path.exists(path))

    def test_clear_stale_streamer_pidfile_drops_pre_boot_file_only(self):
        import ctypes
        import time

        boot_time = time.time() - ctypes.windll.kernel32.GetTickCount64() / 1000.0
        with tempfile.TemporaryDirectory() as temp_dir:
            pid_file = os.path.join(temp_dir, "miclight.pid")
            with mock.patch.object(miclight, "PID_FILE", pid_file):
                # No pid file at all: nothing to do, no error.
                miclight.clear_stale_streamer_pidfile()

                # Written before the current boot: a recycled pid, remove it.
                with open(pid_file, "w") as f:
                    f.write("1234")
                stale = boot_time - 3600
                os.utime(pid_file, (stale, stale))
                miclight.clear_stale_streamer_pidfile()
                self.assertFalse(os.path.exists(pid_file))

                # Written during this session: keep it.
                with open(pid_file, "w") as f:
                    f.write("1234")
                miclight.clear_stale_streamer_pidfile()
                self.assertTrue(os.path.exists(pid_file))

    def test_streamer_running_rejects_recycled_pid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pid_file = os.path.join(temp_dir, "miclight.pid")
            with open(pid_file, "w") as handle:
                handle.write("4321 111\n")
            with mock.patch.object(miclight, "PID_FILE", pid_file):
                with mock.patch.object(
                    miclight,
                    "_process_details",
                    return_value=(222, r"C:\Python312\pythonw.exe"),
                ):
                    self.assertFalse(miclight.streamer_running(4321))
                with mock.patch.object(
                    miclight,
                    "_process_details",
                    return_value=(111, r"C:\Python312\pythonw.exe"),
                ):
                    self.assertTrue(miclight.streamer_running(4321))

    def test_write_streamer_record_persists_creation_marker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pid_file = os.path.join(temp_dir, "miclight.pid")
            with mock.patch.object(miclight, "PID_FILE", pid_file):
                with mock.patch.object(
                    miclight,
                    "_process_details",
                    return_value=(987654321, r"C:\Python312\pythonw.exe"),
                ):
                    miclight._write_streamer_record(4321)
                self.assertEqual(miclight.read_streamer_record(), (4321, 987654321))


if __name__ == "__main__":
    unittest.main()
