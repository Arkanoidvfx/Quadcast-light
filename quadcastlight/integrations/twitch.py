"""TwitchIO EventSub monitoring for Twitch stream-online events."""
import asyncio
import base64
import ctypes
from ctypes import wintypes
import json
import os
import random
import re
import threading
import time
from urllib import error, parse, request

import twitchio
from twitchio import eventsub, web


# Channels come from the user's config; nothing is watched until they add one.
DEFAULT_CHANNELS = ()
POLL_INTERVAL = 330
MAX_BACKOFF = 3600
STATE_MAX_AGE = 12 * 60 * 60
OAUTH_PORT = 4343
REDIRECT_URI = f"http://localhost:{OAUTH_PORT}/oauth/callback"
AUTHORIZE_URL = f"http://localhost:{OAUTH_PORT}/oauth?scopes=user%3Aread%3Aemotes"
CONFIG_PATH = os.path.join(
    os.environ.get("APPDATA", os.path.dirname(os.path.abspath(__file__))),
    "QuadcastLight",
    "twitch.json",
)
STATE_PATH = os.path.join(os.path.dirname(CONFIG_PATH), "twitch-state.json")


class DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _blob(data):
    buffer = ctypes.create_string_buffer(data)
    return DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def protect_secret(secret):
    """Encrypt text for the current Windows user with DPAPI."""
    if not secret:
        return ""
    input_blob, input_buffer = _blob(secret.encode("utf-8"))
    output_blob = DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(input_blob), None, None, None, None, 0x01, ctypes.byref(output_blob)
    ):
        raise ctypes.WinError()
    try:
        encrypted = ctypes.string_at(output_blob.pbData, output_blob.cbData)
        return base64.b64encode(encrypted).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)
        del input_buffer


def unprotect_secret(value):
    if not value:
        return ""
    encrypted = base64.b64decode(value)
    input_blob, input_buffer = _blob(encrypted)
    output_blob = DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(input_blob), None, None, None, None, 0x01, ctypes.byref(output_blob)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree(output_blob.pbData)
        del input_buffer


def channels_from_json(value):
    """Normalize a channel list: lowercase, de-duplicated, no blanks."""
    if isinstance(value, str):
        value = value.replace(";", ",").split(",")
    if not isinstance(value, (list, tuple)):
        return tuple(DEFAULT_CHANNELS)
    seen = []
    for entry in value:
        name = str(entry).strip().lower().lstrip("@")
        if name and name not in seen:
            seen.append(name)
    return tuple(seen)


def load_config(path=CONFIG_PATH):
    defaults = {
        "enabled": True,
        "client_id": "",
        "client_secret": "",
        "access_token": "",
        "refresh_token": "",
        "user_id": "",
        "channels": list(DEFAULT_CHANNELS),
    }
    try:
        with open(path, encoding="utf-8") as config_file:
            data = json.load(config_file)
        defaults.update(
            {
                "enabled": bool(data.get("enabled", True)),
                "client_id": data.get("client_id", ""),
                "client_secret": unprotect_secret(data.get("client_secret", "")),
                "access_token": unprotect_secret(data.get("access_token", "")),
                "refresh_token": unprotect_secret(data.get("refresh_token", "")),
                "user_id": data.get("user_id", ""),
                "channels": channels_from_json(data.get("channels")),
            }
        )
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        pass
    return defaults


def save_config(config, path=CONFIG_PATH):
    data = {
        "enabled": bool(config.get("enabled", True)),
        "client_id": config.get("client_id", "").strip(),
        "client_secret": protect_secret(config.get("client_secret", "").strip()),
        "access_token": protect_secret(config.get("access_token", "").strip()),
        "refresh_token": protect_secret(config.get("refresh_token", "").strip()),
        "user_id": config.get("user_id", "").strip(),
        "channels": list(channels_from_json(config.get("channels"))),
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as config_file:
        json.dump(data, config_file, indent=2)


def save_credentials(client_id, client_secret, enabled=True, path=CONFIG_PATH):
    config = load_config(path)
    credentials_changed = (
        config["client_id"] != client_id.strip()
        or config["client_secret"] != client_secret.strip()
    )
    config.update(
        {
            "enabled": bool(enabled),
            "client_id": client_id.strip(),
            "client_secret": client_secret.strip(),
        }
    )
    if credentials_changed:
        config.update({"access_token": "", "refresh_token": "", "user_id": ""})
    save_config(config, path)


class QuadcastTwitchClient(twitchio.Client):
    def __init__(self, config_path, channels, on_online, on_status):
        self.config_path = config_path
        self.channels = tuple(channel.lower() for channel in channels)
        self.on_online_callback = on_online
        self.on_status_callback = on_status
        self.authorized_user_id = ""
        config = load_config(config_path)
        adapter = web.AiohttpAdapter(host="localhost", port=OAUTH_PORT)
        super().__init__(
            client_id=config["client_id"],
            client_secret=config["client_secret"],
            adapter=adapter,
            redirect_uri=REDIRECT_URI,
            scopes=twitchio.Scopes(user_read_emotes=True),
            fetch_client_user=False,
        )

    def status(self, message):
        self.on_status_callback(message)

    def _save_managed_token(self, user_id):
        token_data = self._http._tokens.get(user_id)
        if not token_data:
            return
        config = load_config(self.config_path)
        config.update(
            {
                "access_token": token_data["token"],
                "refresh_token": token_data["refresh"],
                "user_id": user_id,
            }
        )
        save_config(config, self.config_path)

    async def add_token(self, token, refresh):
        validated = await super().add_token(token, refresh)
        if validated.user_id:
            self.authorized_user_id = validated.user_id
            self._save_managed_token(validated.user_id)
        return validated

    async def load_tokens(self, _path=None):
        config = load_config(self.config_path)
        if config["access_token"] and config["refresh_token"]:
            try:
                await self.add_token(config["access_token"], config["refresh_token"])
            except Exception:
                config.update({"access_token": "", "refresh_token": "", "user_id": ""})
                save_config(config, self.config_path)
                self.status("authorization expired; sign in again")
        self._http._has_loaded = True

    async def save_tokens(self, _path=None):
        if self.authorized_user_id:
            self._save_managed_token(self.authorized_user_id)

    async def setup_hook(self):
        if self.authorized_user_id:
            await self.subscribe_channels()
        else:
            self.status("waiting for Twitch authorization")

    async def subscribe_channels(self):
        users = await self.fetch_users(logins=list(self.channels))
        by_name = {user.name.lower(): user for user in users if user.name}
        missing = [channel for channel in self.channels if channel not in by_name]
        if missing:
            raise RuntimeError(f"Twitch channel not found: {', '.join(missing)}")
        for channel in self.channels:
            payload = eventsub.StreamOnlineSubscription(
                broadcaster_user_id=by_name[channel].id
            )
            await self.subscribe_websocket(
                payload,
                token_for=self.authorized_user_id,
            )
        self.status(f"EventSub connected; tracking {', '.join(self.channels)}")

    async def event_oauth_authorized(self, payload):
        validated = await self.add_token(payload.access_token, payload.refresh_token)
        self.authorized_user_id = validated.user_id
        await self.subscribe_channels()

    async def event_token_refreshed(self, payload):
        self.authorized_user_id = payload.user_id
        self._save_managed_token(payload.user_id)
        self.status("Twitch token refreshed; EventSub connected")

    async def event_stream_online(self, payload):
        channel = (payload.broadcaster.name or payload.broadcaster.display_name).lower()
        if channel in self.channels:
            self.on_online_callback(
                channel,
                {
                    "id": payload.id,
                    "type": payload.type,
                    "started_at": payload.started_at.isoformat(),
                },
            )

    async def event_ready(self):
        if not self.authorized_user_id:
            self.status("OAuth server ready; click Authorize Twitch")


class RateLimitError(RuntimeError):
    def __init__(self, message, retry_after):
        super().__init__(message)
        self.retry_after = retry_after


class DecApiTwitchStatus:
    """Read cached Twitch status from DecAPI without contacting Twitch directly."""

    UPTIME_PATTERN = re.compile(
        r"\b\d+\s+(?:second|minute|hour|day|week)s?\b",
        re.IGNORECASE,
    )

    def __init__(self, opener=None):
        self.opener = opener or request.urlopen
        self.rate_remaining = None

    def live_channels(self, channels):
        live = {}
        for channel in channels:
            req = request.Request(
                f"https://decapi.me/twitch/uptime/{parse.quote(channel)}",
                headers={
                    "User-Agent": "QuadcastLight/1.0 (local desktop notifier)",
                    "Accept": "text/plain",
                },
            )
            try:
                with self.opener(req, timeout=15) as response:
                    body = response.read(4096).decode("utf-8", errors="replace").strip()
                    remaining = response.headers.get("X-RateLimit-Remaining")
                    if remaining and remaining.isdigit():
                        self.rate_remaining = int(remaining)
            except error.HTTPError as exc:
                if exc.code == 429:
                    retry = exc.headers.get("Retry-After", "600")
                    retry_after = int(retry) if retry.isdigit() else 600
                    raise RateLimitError("DecAPI rate limit reached", retry_after) from exc
                raise RuntimeError(f"Twitch channel {channel}: HTTP {exc.code}") from exc
            except (error.URLError, TimeoutError) as exc:
                raise RuntimeError(f"DecAPI connection failed: {exc}") from exc

            lower = body.lower()
            if lower.endswith(" is offline"):
                continue
            if self.UPTIME_PATTERN.search(lower):
                live[channel] = {"user_login": channel, "type": "live", "uptime": body}
                continue
            raise RuntimeError(f"Unexpected DecAPI response for {channel}: {body!r}")
        return live


class TwitchMonitor:
    def __init__(
        self,
        client_id,
        client_secret,
        channels=DEFAULT_CHANNELS,
        on_online=None,
        on_status=None,
        config_path=CONFIG_PATH,
        client_factory=QuadcastTwitchClient,
        public_api=None,
        poll_interval=POLL_INTERVAL,
        state_path=STATE_PATH,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.channels = tuple(channel.lower() for channel in channels)
        self.on_online = on_online or (lambda channel, stream: None)
        self.on_status = on_status or (lambda status: None)
        self.config_path = config_path
        self.client_factory = client_factory
        self.public_api = public_api or DecApiTwitchStatus()
        self.poll_interval = poll_interval
        self.state_path = state_path
        self.client = None
        self.loop = None
        self.thread = None
        self.stop_event = threading.Event()
        self.previous_live = self._load_previous_live()
        self.failure_count = 0

    def _run_twitchio(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.client = self.client_factory(
                self.config_path,
                self.channels,
                self.on_online,
                self.on_status,
            )
            self.loop.run_until_complete(
                self.client.start(with_adapter=True, load_tokens=True, save_tokens=True)
            )
        except Exception as exc:
            self.on_status(f"error: {exc}")
        finally:
            self.loop.close()

    def _load_previous_live(self):
        try:
            with open(self.state_path, encoding="utf-8") as state_file:
                state = json.load(state_file)
            checked_at = float(state["checked_at"])
            if time.time() - checked_at > STATE_MAX_AGE:
                return None
            return {
                channel
                for channel, is_live in state.get("channels", {}).items()
                if channel in self.channels and is_live
            }
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    def _save_previous_live(self, live_names):
        state = {
            "checked_at": time.time(),
            "channels": {channel: channel in live_names for channel in self.channels},
        }
        directory = os.path.dirname(self.state_path)
        os.makedirs(directory, exist_ok=True)
        temp_path = self.state_path + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as state_file:
            json.dump(state, state_file, indent=2)
        os.replace(temp_path, self.state_path)

    def poll_public_once(self):
        live = self.public_api.live_channels(self.channels)
        live_names = set(live)
        if self.previous_live is not None:
            for channel in sorted(live_names - self.previous_live):
                self.on_online(channel, live[channel])
        self.previous_live = live_names
        self._save_previous_live(live_names)
        summary = ", ".join(sorted(live_names)) if live_names else "all offline"
        remaining = getattr(self.public_api, "rate_remaining", None)
        rate = f"; quota {remaining}/100" if remaining is not None else ""
        self.on_status(f"DecAPI fallback; {summary}{rate}")
        return live

    def retry_delay(self, error=None):
        jitter = random.uniform(0, 60)
        if isinstance(error, RateLimitError):
            return max(self.poll_interval, error.retry_after) + jitter
        if error is None:
            return self.poll_interval + jitter
        exponent = min(self.failure_count, 4)
        return min(MAX_BACKOFF, self.poll_interval * (2 ** exponent)) + jitter

    def _run_public(self):
        while not self.stop_event.is_set():
            try:
                self.poll_public_once()
                self.failure_count = 0
                delay = self.retry_delay()
            except Exception as exc:
                self.failure_count += 1
                delay = self.retry_delay(exc)
                self.on_status(
                    f"DecAPI fallback error: {exc}; retry in {int(delay // 60)} min"
                )
            self.stop_event.wait(delay)

    def _run(self):
        if self.client_id and self.client_secret:
            self._run_twitchio()
        else:
            self._run_public()

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        mode = "TwitchIO" if self.client_id and self.client_secret else "TwitchPublic"
        self.thread = threading.Thread(target=self._run, name=mode, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.client and self.loop and self.loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self.client.close(), self.loop)
            try:
                future.result(timeout=5)
            except Exception:
                pass
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
