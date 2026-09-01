"""Entry-point behaviour the Arkanoid supervisor depends on.

These do not open a window: they cover the process-level contract, which is the
part that breaks silently when the resident is refactored.
"""
import os
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

from quadcastlight import autostart, singleinstance


class ShowWindowTests(unittest.TestCase):
    def unique_name(self, tag):
        return "Local" + chr(92) + f"QuadcastLight.{tag}.Test{os.getpid()}"

    def test_request_show_signals_a_listening_resident(self):
        import ctypes

        kernel32 = ctypes.windll.kernel32
        name = self.unique_name("ShowWindow")
        handle = kernel32.CreateEventW(None, False, False, name)
        self.assertTrue(handle)
        try:
            with mock.patch.object(singleinstance, "SHOW_EVENT_NAME", name):
                self.assertTrue(singleinstance.request_show(timeout_seconds=1.0))
            # The auto-reset event is now signaled, so a zero wait consumes it.
            self.assertEqual(kernel32.WaitForSingleObject(handle, 0), 0)
        finally:
            kernel32.CloseHandle(handle)

    def test_request_show_times_out_when_nobody_listens(self):
        name = self.unique_name("NoListener")
        with mock.patch.object(singleinstance, "SHOW_EVENT_NAME", name):
            self.assertFalse(
                singleinstance.request_show(timeout_seconds=0.2, poll_interval=0.05)
            )

    def test_listener_runs_the_callback_when_signalled(self):
        name = self.unique_name("Roundtrip")
        fired = threading.Event()
        with mock.patch.object(singleinstance, "SHOW_EVENT_NAME", name):
            handle = singleinstance.listen_for_show(fired.set)
            self.assertTrue(handle)
            self.assertTrue(singleinstance.request_show(timeout_seconds=2.0))
            self.assertTrue(fired.wait(2.0), "listener never ran the callback")

    def test_second_instance_does_not_acquire_the_mutex(self):
        """Two residents fighting over one HID device is the failure this prevents."""
        code = (
            "import sys; sys.path.insert(0, %r);"
            "from quadcastlight import singleinstance;"
            "print(singleinstance.acquire())" % os.path.dirname(os.path.abspath(__file__))
        )
        first = subprocess.Popen(
            [sys.executable, "-c", code + "; import time; time.sleep(3)"],
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            time.sleep(1.0)  # let the first process take the mutex
            second = subprocess.run(
                [sys.executable, "-c", code], capture_output=True, text=True, timeout=20
            )
            self.assertEqual(second.stdout.strip(), "False")
        finally:
            first.kill()
            first.wait(timeout=5)
            if first.stdout:
                first.stdout.close()


class CredentialExposureTests(unittest.TestCase):
    def test_the_window_can_ask_whether_a_secret_is_stored_but_never_read_it(self):
        """Client secrets are write-only from the UI's side.

        The window is open while people stream, and QML bindings end up in
        screenshots and screen shares, so the bridge must only ever answer
        "is one stored", never hand the value back.
        """
        import re

        qml_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "quadcastlight", "ui", "qml"
        )
        allowed = {"discordHasSecret", "twitchHasSecret"}
        for name in os.listdir(qml_dir):
            if not name.endswith(".qml"):
                continue
            with open(os.path.join(qml_dir, name), encoding="utf-8") as handle:
                source = handle.read()
            for used in re.findall(r"bridge\.(\w*[Ss]ecret\w*)", source):
                self.assertIn(used, allowed, f"{name} reads a secret from the bridge")

    def test_bridge_exposes_no_getter_that_returns_a_stored_secret(self):
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "quadcastlight", "ui", "bridge.py",
        )
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn('return self._discord_config()["client_secret"]', source)
        self.assertNotIn('return self._twitch_config()["client_secret"]', source)


class StatusHealthTests(unittest.TestCase):
    """The header chips were amber whenever the user muted, and amber for the
    public-API mode, which is a supported configuration. These pin the mapping
    so prose changes in the monitors cannot quietly break it again."""

    def health(self, status, table):
        from quadcastlight.ui.bridge import classify

        return classify(status, table)[0]

    def test_every_discord_status_the_monitor_emits_is_classified(self):
        from quadcastlight.ui.bridge import DISCORD_HEALTH as table

        expected = {
            "disabled": "off",
            "connecting": "busy",
            "connected": "ok",
            "connected to General": "ok",
            "muted in General": "ok",
            "deafened in General": "ok",
            "not in voice": "ok",
            "token refreshed": "ok",
            "authorization required: no stored Discord authorization": "attention",
            "configure Discord client id": "attention",
            "Discord not responding; retrying": "busy",
            "offline: pipe closed": "busy",
            "RPC error [4009]: <redacted>": "busy",
        }
        for status, want in expected.items():
            self.assertEqual(self.health(status, table), want, status)

    def test_every_twitch_status_the_monitor_emits_is_classified(self):
        from quadcastlight.ui.bridge import TWITCH_HEALTH as table

        expected = {
            "disabled": "off",
            "connecting": "busy",
            "EventSub connected; tracking alpha, beta": "ok",
            "Twitch token refreshed; EventSub connected": "ok",
            # Polling the public API is what you get without credentials.
            "DecAPI fallback; 2 live, 1 offline": "ok",
            "authorization expired; sign in again": "attention",
            "waiting for Twitch authorization": "attention",
            "OAuth server ready; click Authorize Twitch": "attention",
            "error: connection reset": "busy",
        }
        for status, want in expected.items():
            self.assertEqual(self.health(status, table), want, status)

    def test_unknown_wording_asks_for_attention_rather_than_passing(self):
        from quadcastlight.ui.bridge import DISCORD_HEALTH, classify

        health, summary = classify("some new failure nobody mapped", DISCORD_HEALTH)
        self.assertEqual(health, "attention")
        self.assertTrue(summary)

    def test_the_status_strings_in_the_monitors_are_all_covered(self):
        """Reads the literals out of the monitors, so a new one shows up here."""
        import ast
        import os

        for module, table_name in (("discord.py", "DISCORD_HEALTH"), ("twitch.py", "TWITCH_HEALTH")):
            path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "quadcastlight", "integrations", module,
            )
            with open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            from quadcastlight.ui import bridge as bridge_module

            table = getattr(bridge_module, table_name)
            markers = [marker for marker, _health, _summary in table]
            for node in ast.walk(tree):
                # on_status("...") and self.status(f"...") calls
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "attr", "")
                if name not in ("on_status", "status") or not node.args:
                    continue
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    text = arg.value
                elif isinstance(arg, ast.JoinedStr) and arg.values:
                    first = arg.values[0]
                    text = first.value if isinstance(first, ast.Constant) else ""
                else:
                    continue
                if not text:
                    continue
                self.assertTrue(
                    any(text.startswith(m) for m in markers),
                    f"{module} can emit {text!r}, which {table_name} does not classify",
                )


class LauncherTests(unittest.TestCase):
    def test_gui_launcher_forwards_command_line_arguments(self):
        """--show and --no-tray have to survive the .cmd wrapper."""
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "miclight-gui.cmd")
        with open(script, encoding="utf-8") as handle:
            body = handle.read()
        self.assertIn("%*", body)

    def test_autostart_launcher_points_at_the_entry_script(self):
        self.assertEqual(autostart.ENTRY_SCRIPT, "miclight_gui.pyw")
        self.assertTrue(
            os.path.isfile(os.path.join(autostart.project_dir(), autostart.ENTRY_SCRIPT)),
            "the Startup launcher would point at a missing file",
        )

    def test_autostart_writes_and_removes_its_launcher(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "QuadcastLight.cmd")
            with mock.patch.object(autostart, "launcher_path", return_value=path):
                self.assertFalse(autostart.enabled())
                autostart.set_enabled(True)
                self.assertTrue(autostart.enabled())
                with open(path, encoding="utf-8") as handle:
                    self.assertIn(autostart.ENTRY_SCRIPT, handle.read())
                autostart.set_enabled(False)
                self.assertFalse(autostart.enabled())

    def test_frozen_build_launches_the_exe_itself(self):
        """A packaged build has no interpreter and no .pyw beside it."""
        with mock.patch.object(sys, "frozen", True, create=True):
            with mock.patch.object(sys, "executable", r"C:\Apps\QuadcastLight.exe"):
                self.assertEqual(
                    autostart.launch_command(), [r"C:\Apps\QuadcastLight.exe"]
                )

    def test_source_build_launches_the_entry_script(self):
        command = autostart.launch_command()
        self.assertEqual(len(command), 2)
        self.assertTrue(command[0].lower().endswith(("pythonw.exe", "python.exe")))
        self.assertTrue(command[1].endswith(autostart.ENTRY_SCRIPT))

    def test_startup_launcher_quotes_a_path_with_spaces(self):
        """Program Files is the normal install location for a packaged build."""
        import tempfile

        exe = r"C:\Program Files\QuadcastLight\QuadcastLight.exe"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "QuadcastLight.cmd")
            with mock.patch.object(autostart, "launcher_path", return_value=path):
                with mock.patch.object(autostart, "launch_command", return_value=[exe]):
                    autostart.set_enabled(True)
                with open(path, encoding="utf-8") as handle:
                    self.assertIn(f'"{exe}"', handle.read())


if __name__ == "__main__":
    unittest.main()
