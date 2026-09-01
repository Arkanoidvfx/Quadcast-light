import asyncio
import datetime
import json
import os
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock
from urllib import error

from quadcastlight.integrations import twitch as twitch_monitor

TEST_CHANNELS = ("alpha", "beta", "gamma")


class FakeClient:
    def __init__(self, config_path, channels, on_online, on_status):
        self.config_path = config_path
        self.channels = channels
        self.on_online = on_online
        self.on_status = on_status
        self.started = False
        self.closed = False

    async def start(self, **_kwargs):
        self.started = True

    async def close(self):
        self.closed = True


class FakePublicApi:
    def __init__(self, snapshots):
        self.snapshots = iter(snapshots)

    def live_channels(self, _channels):
        return next(self.snapshots)


class TwitchMonitorTests(unittest.TestCase):
    def test_channels_from_json_normalizes_user_input(self):
        """Channels are user config now, so the parsing has to be forgiving."""
        self.assertEqual(twitch_monitor.channels_from_json(None), ())
        self.assertEqual(
            twitch_monitor.channels_from_json(["  Alpha ", "@Beta", "alpha", ""]),
            ("alpha", "beta"),
        )
        self.assertEqual(
            twitch_monitor.channels_from_json("Alpha, beta; GAMMA"),
            ("alpha", "beta", "gamma"),
        )

    def test_redirect_uri_matches_local_oauth_adapter(self):
        self.assertEqual(
            twitch_monitor.REDIRECT_URI,
            "http://localhost:4343/oauth/callback",
        )

    def test_config_secrets_are_encrypted_and_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "twitch.json")
            twitch_monitor.save_config(
                {
                    "enabled": True,
                    "client_id": "client-id",
                    "client_secret": "client-secret",
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "user_id": "123",
                },
                path,
            )

            with open(path, encoding="utf-8") as config_file:
                raw = config_file.read()
            self.assertNotIn("client-secret", raw)
            self.assertNotIn("access-token", raw)
            self.assertNotIn("refresh-token", raw)

            config = twitch_monitor.load_config(path)
            self.assertEqual(config["client_id"], "client-id")
            self.assertEqual(config["client_secret"], "client-secret")
            self.assertEqual(config["access_token"], "access-token")
            self.assertEqual(config["refresh_token"], "refresh-token")
            self.assertEqual(config["user_id"], "123")

    def test_changing_credentials_clears_oauth_tokens(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "twitch.json")
            twitch_monitor.save_config(
                {
                    "enabled": True,
                    "client_id": "old-id",
                    "client_secret": "old-secret",
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "user_id": "123",
                },
                path,
            )

            twitch_monitor.save_credentials("new-id", "new-secret", True, path)
            config = twitch_monitor.load_config(path)

            self.assertEqual(config["client_id"], "new-id")
            self.assertEqual(config["access_token"], "")
            self.assertEqual(config["refresh_token"], "")
            self.assertEqual(config["user_id"], "")

    def test_stream_online_dispatches_tracked_channel(self):
        notifications = []
        client = object.__new__(twitch_monitor.QuadcastTwitchClient)
        client.channels = TEST_CHANNELS
        client.on_online_callback = lambda channel, stream: notifications.append(
            (channel, stream)
        )
        payload = SimpleNamespace(
            broadcaster=SimpleNamespace(name="Gamma", display_name="Gamma"),
            id="stream-1",
            type="live",
            started_at=datetime.datetime(2026, 6, 11, tzinfo=datetime.UTC),
        )

        asyncio.run(client.event_stream_online(payload))

        self.assertEqual(notifications[0][0], "gamma")
        self.assertEqual(notifications[0][1]["id"], "stream-1")

    def test_monitor_passes_three_channels_to_twitchio_client(self):
        created = []

        def factory(*args):
            client = FakeClient(*args)
            created.append(client)
            return client

        monitor = twitch_monitor.TwitchMonitor(
            "client-id",
            "client-secret",
            channels=TEST_CHANNELS,
            client_factory=factory,
        )
        monitor._run()

        self.assertEqual(created[0].channels, TEST_CHANNELS)
        self.assertTrue(created[0].started)

    def test_public_fallback_notifies_only_new_online_transition(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            notifications = []
            monitor = twitch_monitor.TwitchMonitor(
                "",
                "",
                channels=TEST_CHANNELS,
                public_api=FakePublicApi(
                    [
                        {"gamma": {"id": "already-live"}},
                        {"gamma": {"id": "already-live"}},
                        {
                            "gamma": {"id": "already-live"},
                            "beta": {"id": "new-live"},
                        },
                    ]
                ),
                on_online=lambda channel, stream: notifications.append((channel, stream)),
                state_path=os.path.join(temp_dir, "state.json"),
            )

            monitor.poll_public_once()
            monitor.poll_public_once()
            monitor.poll_public_once()

            self.assertEqual(notifications[0][0], "beta")
            self.assertEqual(len(notifications), 1)

    def test_decapi_detects_live_uptime(self):
        class Response:
            def __init__(self, body):
                self.body = body
                self.headers = {"X-RateLimit-Remaining": "97"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self, _limit=None):
                return self.body

        pages = {
            "alpha": b"alpha is offline",
            "beta": b"beta is offline",
            "gamma": b"2 hours, 30 minutes, 21 seconds",
        }

        def opener(req, timeout):
            self.assertEqual(timeout, 15)
            return Response(pages[req.full_url.rsplit("/", 1)[-1]])

        api = twitch_monitor.DecApiTwitchStatus(opener)
        live = api.live_channels(
            TEST_CHANNELS
        )
        self.assertEqual(set(live), {"gamma"})
        self.assertEqual(api.rate_remaining, 97)

    def test_decapi_rejects_unknown_response(self):
        class Response:
            headers = {}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self, _limit=None):
                return b"service temporarily confused"

        with self.assertRaisesRegex(RuntimeError, "Unexpected DecAPI response"):
            twitch_monitor.DecApiTwitchStatus(lambda *_args, **_kwargs: Response()).live_channels(
                ("gamma",)
            )

    def test_rate_limit_uses_retry_after(self):
        headers = {"Retry-After": "900"}
        http_error = error.HTTPError(
            "https://decapi.me/twitch/uptime/gamma",
            429,
            "Too Many Requests",
            headers,
            None,
        )

        def opener(*_args, **_kwargs):
            raise http_error

        with self.assertRaises(twitch_monitor.RateLimitError) as raised:
            twitch_monitor.DecApiTwitchStatus(opener).live_channels(("gamma",))
        self.assertEqual(raised.exception.retry_after, 900)

    def test_retry_delay_has_backoff_cap(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            monitor = twitch_monitor.TwitchMonitor(
                "",
                "",
                state_path=os.path.join(temp_dir, "state.json"),
            )
            monitor.failure_count = 10
            with mock.patch.object(twitch_monitor.random, "uniform", return_value=0):
                self.assertEqual(
                    monitor.retry_delay(RuntimeError("down")),
                    twitch_monitor.MAX_BACKOFF,
                )
                self.assertEqual(
                    monitor.retry_delay(twitch_monitor.RateLimitError("limited", 900)),
                    900,
                )

    def test_saved_state_prevents_duplicate_after_restart(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = os.path.join(temp_dir, "state.json")
            first = twitch_monitor.TwitchMonitor(
                "",
                "",
                channels=TEST_CHANNELS,
                public_api=FakePublicApi([{"gamma": {"id": "live"}}]),
                state_path=state_path,
            )
            first.poll_public_once()

            notifications = []
            second = twitch_monitor.TwitchMonitor(
                "",
                "",
                channels=TEST_CHANNELS,
                public_api=FakePublicApi([{"gamma": {"id": "live"}}]),
                state_path=state_path,
                on_online=lambda channel, stream: notifications.append(channel),
            )
            second.poll_public_once()

            self.assertEqual(notifications, [])


if __name__ == "__main__":
    unittest.main()
