import json
import time
import unittest

from quadcastlight.integrations import discord as discord_monitor


class DiscordMonitorTests(unittest.TestCase):
    def test_config_round_trip_preserves_discord_effect_settings(self):
        original_protect = discord_monitor.protect_secret
        original_unprotect = discord_monitor.unprotect_secret
        discord_monitor.protect_secret = lambda value: value
        discord_monitor.unprotect_secret = lambda value: value
        try:
            with self.subTest("round trip"):
                import os
                import tempfile

                with tempfile.TemporaryDirectory() as temp_dir:
                    path = os.path.join(temp_dir, "discord.json")
                    discord_monitor.save_config(
                        {
                            "enabled": True,
                            "client_id": "id",
                            "client_secret": "secret",
                            "access_token": "token",
                            "refresh_token": "refresh",
                            "mute_color": [1, 2, 3],
                            "deafen_color": [4, 5, 6],
                            "brightness": 77,
                            "restore_default": False,
                        },
                        path,
                    )

                    loaded = discord_monitor.load_config(path)

            self.assertTrue(loaded["enabled"])
            self.assertEqual(loaded["client_id"], "id")
            self.assertEqual(loaded["client_secret"], "secret")
            self.assertEqual(loaded["access_token"], "token")
            self.assertEqual(loaded["refresh_token"], "refresh")
            self.assertEqual(loaded["mute_color"], (1, 2, 3))
            self.assertEqual(loaded["deafen_color"], (4, 5, 6))
            self.assertEqual(loaded["brightness"], 77)
            self.assertFalse(loaded["restore_default"])
        finally:
            discord_monitor.protect_secret = original_protect
            discord_monitor.unprotect_secret = original_unprotect

    def test_frame_round_trip_header(self):
        payload = {"cmd": "GET_VOICE_SETTINGS", "nonce": "abc"}
        frame = discord_monitor.encode_frame(discord_monitor.OP_FRAME, payload)
        opcode, length = discord_monitor.decode_header(frame[:8])

        self.assertEqual(opcode, discord_monitor.OP_FRAME)
        self.assertEqual(json.loads(frame[8:8 + length].decode("utf-8")), payload)

    def test_build_voice_state_uses_channel_and_settings(self):
        state = discord_monitor.build_voice_state(
            {"name": "General"},
            {"mute": True, "deaf": False},
        )

        self.assertTrue(state.connected)
        self.assertTrue(state.muted)
        self.assertFalse(state.deafened)
        self.assertEqual(state.channel_name, "General")

    def test_state_transitions_emit_only_entering_events(self):
        events = []
        states = []
        statuses = []
        monitor = discord_monitor.DiscordMonitor(
            "client-id",
            on_event=lambda event, state: events.append((event, state.channel_name)),
            on_state=lambda state: states.append(state),
            on_status=statuses.append,
        )

        monitor.handle_state(discord_monitor.DiscordVoiceState())
        monitor.handle_state(discord_monitor.DiscordVoiceState(True, False, False, "Voice"))
        monitor.handle_state(discord_monitor.DiscordVoiceState(True, True, False, "Voice"))
        monitor.handle_state(discord_monitor.DiscordVoiceState(True, True, True, "Voice"))
        monitor.handle_state(discord_monitor.DiscordVoiceState(True, True, True, "Voice"))

        self.assertEqual(
            events,
            [
                (discord_monitor.EVENT_CONNECTED, "Voice"),
                (discord_monitor.EVENT_MUTED, "Voice"),
                (discord_monitor.EVENT_DEAFENED, "Voice"),
            ],
        )
        self.assertEqual(len(states), 3)
        self.assertEqual(statuses[-1], "deafened in Voice")

    def test_same_state_does_not_emit_state_callback(self):
        states = []
        monitor = discord_monitor.DiscordMonitor(
            "client-id",
            on_state=lambda state: states.append(state),
        )
        state = discord_monitor.DiscordVoiceState(True, False, False, "Voice")

        monitor.handle_state(state)
        monitor.handle_state(state)

        self.assertEqual(states, [state])

    def test_poll_once_reads_rpc_state(self):
        class FakeIpc:
            def selected_voice_channel(self):
                return {"name": "Squad"}

            def voice_settings(self):
                return {"mute": False, "deaf": True}

        events = []
        monitor = discord_monitor.DiscordMonitor(
            "client-id",
            on_event=lambda event, state: events.append(event),
        )
        monitor.ipc = FakeIpc()

        state = monitor.poll_once()

        self.assertTrue(state.connected)
        self.assertTrue(state.deafened)
        self.assertEqual(
            events,
            [discord_monitor.EVENT_CONNECTED, discord_monitor.EVENT_DEAFENED],
        )

    def test_exchange_code_posts_oauth_form(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self):
                return b'{"access_token":"token","refresh_token":"refresh"}'

        captured = {}

        def opener(req, timeout):
            captured["url"] = req.full_url
            captured["timeout"] = timeout
            captured["data"] = req.data.decode("ascii")
            captured["user_agent"] = req.headers.get("User-agent")
            return Response()

        token = discord_monitor.exchange_code("id", "secret", "code", opener=opener)

        self.assertEqual(token["access_token"], "token")
        self.assertEqual(captured["url"], "https://discord.com/api/v10/oauth2/token")
        self.assertEqual(captured["timeout"], 20)
        self.assertEqual(captured["user_agent"], discord_monitor.USER_AGENT)
        self.assertIn("grant_type=authorization_code", captured["data"])
        self.assertIn("redirect_uri=http%3A%2F%2Flocalhost", captured["data"])


class TokenLifecycleTests(unittest.TestCase):
    def test_redact_removes_known_secrets_only(self):
        token = "EXAMPLE-TOKEN-VALUE-not-a-real-credential"
        message = f"Invalid access token: {token}"
        cleaned = discord_monitor.redact(message, token)

        self.assertNotIn(token, cleaned)
        self.assertIn("Invalid access token", cleaned)
        self.assertEqual(discord_monitor.redact("plain text", ""), "plain text")

    def test_store_token_sets_expiry_and_keeps_old_refresh_when_absent(self):
        config = {"refresh_token": "old"}
        discord_monitor.store_token(config, {"access_token": "a", "expires_in": 604800})

        self.assertEqual(config["access_token"], "a")
        self.assertEqual(config["refresh_token"], "old")
        self.assertAlmostEqual(config["expires_at"], time.time() + 604800, delta=5)

        discord_monitor.store_token(config, {"access_token": "b", "refresh_token": "new"})
        self.assertEqual(config["refresh_token"], "new")

    def test_token_expired_treats_unknown_expiry_as_expired(self):
        self.assertTrue(discord_monitor.token_expired({"access_token": "a", "expires_at": 0.0}))
        self.assertTrue(discord_monitor.token_expired({"access_token": "", "expires_at": 1e12}))
        self.assertFalse(
            discord_monitor.token_expired({"access_token": "a", "expires_at": time.time() + 1e6})
        )
        # Inside the refresh skew it counts as expired, so a token never dies mid-session.
        self.assertTrue(
            discord_monitor.token_expired(
                {"access_token": "a", "expires_at": time.time() + 60},
            )
        )

    def test_ensure_access_token_refreshes_and_persists(self):
        import os
        import tempfile

        original = discord_monitor.protect_secret, discord_monitor.unprotect_secret
        discord_monitor.protect_secret = lambda value: value
        discord_monitor.unprotect_secret = lambda value: value
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                path = os.path.join(temp_dir, "discord.json")
                config = discord_monitor.load_config(path)
                config.update(
                    {
                        "client_id": "id",
                        "client_secret": "secret",
                        "access_token": "stale",
                        "refresh_token": "refresh",
                        "expires_at": 0.0,
                    }
                )

                class Response:
                    def __enter__(self):
                        return self

                    def __exit__(self, *_args):
                        return None

                    def read(self):
                        return (
                            b'{"access_token":"fresh","refresh_token":"rotated",'
                            b'"expires_in":604800}'
                        )

                token, refreshed = discord_monitor.ensure_access_token(
                    config, path, opener=lambda req, timeout: Response()
                )

                self.assertEqual(token, "fresh")
                self.assertTrue(refreshed)
                saved = discord_monitor.load_config(path)
                self.assertEqual(saved["access_token"], "fresh")
                self.assertEqual(saved["refresh_token"], "rotated")
                self.assertGreater(saved["expires_at"], time.time())
                # A live token is returned untouched, without a second request.
                self.assertEqual(
                    discord_monitor.ensure_access_token(saved, path, opener=None),
                    ("fresh", False),
                )
        finally:
            discord_monitor.protect_secret, discord_monitor.unprotect_secret = original

    def test_ensure_access_token_without_refresh_token_needs_authorization(self):
        with self.assertRaises(discord_monitor.NeedsAuthorization):
            discord_monitor.ensure_access_token(
                {"access_token": "stale", "refresh_token": "", "expires_at": 0.0}
            )


class MonitorResilienceTests(unittest.TestCase):
    def test_authenticate_refreshes_once_when_discord_rejects_the_token(self):
        attempts = []

        class FakeIpc:
            def authenticate(self, token):
                attempts.append(token)
                if len(attempts) == 1:
                    raise discord_monitor.DiscordRpcError("Invalid access token", 4009)
                return {"user": {"id": "1"}}

        monitor = discord_monitor.DiscordMonitor(
            "id",
            "stale",
            config_loader=lambda: {
                "client_id": "id",
                "client_secret": "secret",
                "refresh_token": "refresh",
            },
        )
        monitor.ipc = FakeIpc()

        original_refresh = discord_monitor.refresh_access_token
        original_save = discord_monitor.save_config
        discord_monitor.refresh_access_token = lambda *a, **k: {
            "access_token": "fresh",
            "expires_in": 604800,
        }
        discord_monitor.save_config = lambda *a, **k: None
        try:
            monitor._authenticate()
        finally:
            discord_monitor.refresh_access_token = original_refresh
            discord_monitor.save_config = original_save

        self.assertEqual(attempts, ["stale", "fresh"])
        self.assertEqual(monitor.access_token, "fresh")

    def test_authenticate_without_refresh_token_needs_authorization(self):
        class FakeIpc:
            def authenticate(self, _token):
                raise discord_monitor.DiscordRpcError("Invalid access token", 4009)

        monitor = discord_monitor.DiscordMonitor(
            "id", "stale", config_loader=lambda: {"refresh_token": ""}
        )
        monitor.ipc = FakeIpc()

        with self.assertRaises(discord_monitor.NeedsAuthorization):
            monitor._authenticate()

    def test_command_keeps_unsolicited_events_instead_of_dropping_them(self):
        pushed = {"cmd": "DISPATCH", "evt": "VOICE_SETTINGS_UPDATE", "data": {"mute": True}}
        ipc = discord_monitor.DiscordIpc("id")
        sent = []
        ipc._send = lambda opcode, payload: sent.append(payload)
        replies = [pushed]

        def fake_recv(_deadline=None):
            if replies:
                return replies.pop(0)
            return {"nonce": sent[0]["nonce"], "data": {"mute": False}}

        ipc._recv_payload = fake_recv

        data = ipc.command("GET_VOICE_SETTINGS")

        self.assertEqual(data, {"mute": False})
        self.assertEqual(ipc.pending_events, [pushed])
        self.assertEqual(ipc.next_event(), pushed)

    def test_session_reapplies_state_after_a_reconnect(self):
        """previous_state must reset, or the light stays wrong after Discord restarts."""
        states = []

        class FakeIpc:
            def __init__(self):
                self.subscribed = []

            def subscribe(self, event):
                self.subscribed.append(event)

            def selected_voice_channel(self):
                return {"name": "Voice"}

            def voice_settings(self):
                return {"mute": True, "deaf": False}

            def next_event(self, _timeout=None):
                monitor.stop_event.set()
                return None

        monitor = discord_monitor.DiscordMonitor("id", on_state=states.append)
        monitor.ipc = FakeIpc()
        # Monitor believes the user is already muted, as it would after a drop.
        monitor.previous_state = discord_monitor.DiscordVoiceState(True, True, False, "Voice")

        monitor._session()

        self.assertEqual(
            monitor.ipc.subscribed, ["VOICE_SETTINGS_UPDATE", "VOICE_CHANNEL_SELECT"]
        )
        self.assertEqual(len(states), 1, "state must be re-emitted after reconnect")
        self.assertTrue(states[0].muted)

    def test_pushed_event_triggers_an_immediate_re_poll(self):
        """A push must be read back at once, not deferred to the keepalive tick."""
        polls = []

        class FakeIpc:
            def __init__(self):
                self.events = [{"evt": "VOICE_SETTINGS_UPDATE"}, None]

            def subscribe(self, _event):
                return None

            def selected_voice_channel(self):
                return {"name": "Voice"}

            def voice_settings(self):
                polls.append(time.monotonic())
                return {"mute": len(polls) > 1, "deaf": False}

            def next_event(self, _timeout=None):
                if not self.events:
                    monitor.stop_event.set()
                    return None
                event = self.events.pop(0)
                if event is None:
                    monitor.stop_event.set()
                return event

        monitor = discord_monitor.DiscordMonitor("id")
        monitor.ipc = FakeIpc()
        monitor._session()

        # One poll on entry, one more forced by the pushed event, with no
        # KEEPALIVE_INTERVAL wait in between.
        self.assertEqual(len(polls), 2)

    def test_read_exact_with_deadline_works_on_non_pipe_streams(self):
        import io as _io

        stream = _io.BytesIO(b"12345678")
        self.assertEqual(discord_monitor.read_exact(stream, 8, time.monotonic() + 1), b"12345678")


if __name__ == "__main__":
    unittest.main()
