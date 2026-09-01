"""Discord local RPC monitoring for voice state events."""
import base64
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import io
import json
import msvcrt
import os
import struct
import threading
import time
import uuid
from urllib import error, parse, request

from .. import logging_setup

log = logging_setup.get("discord")


CONFIG_PATH = os.path.join(
    os.environ.get("APPDATA", os.path.dirname(os.path.abspath(__file__))),
    "QuadcastLight",
    "discord.json",
)
REDIRECT_URI = "http://localhost"
USER_AGENT = "DiscordBot (https://github.com/local/QuadcastLight, 1.0)"
POLL_INTERVAL = 0.5
RPC_VERSION = 1
# Refresh this long before the access token actually expires, so a token never
# dies mid-session (Discord issues 7-day tokens).
TOKEN_REFRESH_SKEW = 6 * 3600

# Every pipe read has a deadline. Without one, a Discord client that accepts the
# connection and then goes quiet freezes the monitor thread forever, and nothing
# restarts it. The handshake budget is deliberately generous: a live client was
# measured answering READY in 20-59 s, so a tight timeout would reject healthy
# connections.
PIPE_POLL_INTERVAL = 0.01
HANDSHAKE_TIMEOUT = 90.0
COMMAND_TIMEOUT = 20.0
# How long the event loop waits for a pushed voice update before looping round
# to run its keepalive. Not an error, just a tick.
EVENT_IDLE_TIMEOUT = 5.0
# Re-poll state this often even with subscriptions live, to catch a missed event
# or a half-dead connection.
KEEPALIVE_INTERVAL = 15.0
RECONNECT_BACKOFF_START = 10.0
RECONNECT_BACKOFF_MAX = 60.0
# Discord RPC error codes meaning "this access token is no good": INVALID_TOKEN
# and INVALID_PERMISSIONS. Both are answered by refreshing, then re-authorizing.
TOKEN_REJECTED_CODES = (4006, 4009)

OP_HANDSHAKE = 0
OP_FRAME = 1
OP_CLOSE = 2
OP_PING = 3
OP_PONG = 4

EVENT_CONNECTED = "voice_connected"
EVENT_MUTED = "muted"
EVENT_DEAFENED = "deafened"
DEFAULT_MUTE_COLOR = (255, 90, 0)
DEFAULT_DEAFEN_COLOR = (255, 0, 0)


def redact(text, *secrets):
    """Replace known secret values in text headed for a log, the UI, or stdout.

    Discord echoes the rejected credential back inside its own error message
    ("Invalid access token: MTUx..."), so logging an RPC error verbatim would
    write access tokens to disk. Exact replacement of the values we hold, so
    there is nothing to guess and nothing to miss.
    """
    text = str(text)
    for secret in secrets:
        if secret and len(secret) >= 8:
            text = text.replace(secret, "<redacted>")
    return text


def rgb_from_json(value, default):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return default
    try:
        return tuple(max(0, min(255, int(channel))) for channel in value)
    except (TypeError, ValueError):
        return default


def optional_brightness_from_json(value):
    if value is None:
        return None
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return None


class DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _blob(data):
    buffer = ctypes.create_string_buffer(data)
    return DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def protect_secret(secret):
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


def load_config(path=CONFIG_PATH):
    defaults = {
        "enabled": False,
        "client_id": "",
        "client_secret": "",
        "access_token": "",
        "refresh_token": "",
        "expires_at": 0.0,
        "mute_color": DEFAULT_MUTE_COLOR,
        "deafen_color": DEFAULT_DEAFEN_COLOR,
        "brightness": None,
        "restore_default": True,
    }
    try:
        with open(path, encoding="utf-8") as config_file:
            data = json.load(config_file)
        defaults.update(
            {
                "enabled": bool(data.get("enabled", False)),
                "client_id": data.get("client_id", ""),
                "client_secret": unprotect_secret(data.get("client_secret", "")),
                "access_token": unprotect_secret(data.get("access_token", "")),
                "refresh_token": unprotect_secret(data.get("refresh_token", "")),
                "expires_at": float(data.get("expires_at") or 0.0),
                "mute_color": rgb_from_json(
                    data.get("mute_color"),
                    defaults["mute_color"],
                ),
                "deafen_color": rgb_from_json(
                    data.get("deafen_color"),
                    defaults["deafen_color"],
                ),
                "brightness": optional_brightness_from_json(data.get("brightness")),
                "restore_default": bool(data.get("restore_default", True)),
            }
        )
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        pass
    return defaults


def save_config(config, path=CONFIG_PATH):
    data = {
        "enabled": bool(config.get("enabled", False)),
        "client_id": config.get("client_id", "").strip(),
        "client_secret": protect_secret(config.get("client_secret", "").strip()),
        "access_token": protect_secret(config.get("access_token", "").strip()),
        "refresh_token": protect_secret(config.get("refresh_token", "").strip()),
        "expires_at": float(config.get("expires_at") or 0.0),
        "mute_color": list(rgb_from_json(config.get("mute_color"), DEFAULT_MUTE_COLOR)),
        "deafen_color": list(rgb_from_json(config.get("deafen_color"), DEFAULT_DEAFEN_COLOR)),
        "brightness": optional_brightness_from_json(config.get("brightness")),
        "restore_default": bool(config.get("restore_default", True)),
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as config_file:
        json.dump(data, config_file, indent=2)


def save_credentials(client_id, client_secret, enabled=True, path=CONFIG_PATH):
    config = load_config(path)
    changed = (
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
    if changed:
        config.update({"access_token": "", "refresh_token": "", "expires_at": 0.0})
    save_config(config, path)


def _token_request(client_id, client_secret, form, opener=None, what="token exchange"):
    opener = opener or request.urlopen
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    req = request.Request(
        "https://discord.com/api/v10/oauth2/token",
        data=parse.urlencode(form).encode("ascii"),
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with opener(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Discord {what} failed: HTTP {exc.code} "
            f"{redact(details, client_secret, *form.values())}"
        ) from exc


def exchange_code(client_id, client_secret, code, opener=None):
    return _token_request(
        client_id,
        client_secret,
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
        },
        opener=opener,
    )


def refresh_access_token(client_id, client_secret, refresh_token, opener=None):
    """Trade a refresh token for a fresh access token.

    Discord access tokens live 7 days. Without this the integration silently
    dies a week after every authorization and only a manual re-authorize
    revives it.
    """
    if not refresh_token:
        raise RuntimeError("No Discord refresh token stored; authorize again.")
    return _token_request(
        client_id,
        client_secret,
        {"grant_type": "refresh_token", "refresh_token": refresh_token},
        opener=opener,
        what="token refresh",
    )


def store_token(config, token):
    """Copy a token response into config, including when it goes stale."""
    expires_in = token.get("expires_in")
    config.update(
        {
            "access_token": token.get("access_token", ""),
            # Discord rotates the refresh token on every refresh; keep the old
            # one only if the response omits it.
            "refresh_token": token.get("refresh_token") or config.get("refresh_token", ""),
            "expires_at": time.time() + float(expires_in) if expires_in else 0.0,
        }
    )
    return config


def token_expired(config, skew=TOKEN_REFRESH_SKEW):
    """True when the stored token is past (or nearly past) its lifetime.

    An unknown expiry (legacy config written before expires_at existed) counts
    as expired: refreshing costs one request, guessing wrong costs the feature.
    """
    if not config.get("access_token"):
        return True
    return time.time() + skew >= (config.get("expires_at") or 0.0)


def ensure_access_token(config, path=CONFIG_PATH, opener=None):
    """Return a usable access token, refreshing and persisting it if needed.

    Returns (token, refreshed). Raises RuntimeError when only a new manual
    authorization can help, so the caller can surface that state instead of
    retrying forever.
    """
    if not token_expired(config):
        return config["access_token"], False
    if not config.get("refresh_token"):
        raise NeedsAuthorization("no stored Discord authorization")
    try:
        token = refresh_access_token(
            config["client_id"], config["client_secret"], config["refresh_token"], opener=opener
        )
    except RuntimeError as exc:
        # Discord rejected the refresh grant (revoked, rotated away, secret
        # changed). Retrying will not help; the user must authorize again.
        raise NeedsAuthorization(str(exc)) from exc
    store_token(config, token)
    save_config(config, path)
    return config["access_token"], True


def encode_frame(opcode, payload):
    data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return struct.pack("<II", opcode, len(data)) + data


def decode_header(header):
    return struct.unpack("<II", header)


def wait_readable(stream, deadline):
    """Block until the pipe has bytes, the peer closes, or the deadline passes.

    Python file objects have no read timeout, so this peeks instead of reading.
    Streams that are not real pipes (test fakes) fall through to a plain
    blocking read.
    """
    try:
        handle = msvcrt.get_osfhandle(stream.fileno())
    except (AttributeError, ValueError, OSError, io.UnsupportedOperation):
        return
    available = wintypes.DWORD()
    while True:
        ok = ctypes.windll.kernel32.PeekNamedPipe(
            handle, None, 0, None, ctypes.byref(available), None
        )
        if not ok:
            raise ConnectionError("Discord IPC closed")
        if available.value:
            return
        if time.monotonic() >= deadline:
            raise TimeoutError("Discord IPC timed out")
        time.sleep(PIPE_POLL_INTERVAL)


def read_exact(stream, size, deadline=None):
    chunks = []
    remaining = size
    while remaining:
        if deadline is not None:
            wait_readable(stream, deadline)
        chunk = stream.read(remaining)
        if not chunk:
            raise ConnectionError("Discord IPC closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


@dataclass(frozen=True)
class DiscordVoiceState:
    connected: bool = False
    muted: bool = False
    deafened: bool = False
    channel_name: str = ""


class DiscordRpcError(RuntimeError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class NeedsAuthorization(RuntimeError):
    """Only a new manual authorization can fix this; retrying cannot."""


class DiscordIpc:
    def __init__(self, client_id, pipe_factory=None):
        self.client_id = client_id
        self.pipe_factory = pipe_factory or open
        self.stream = None
        self.pending_events = []

    def connect(self, timeout=HANDSHAKE_TIMEOUT):
        for index in range(10):
            path = f"\\\\?\\pipe\\discord-ipc-{index}"
            try:
                self.stream = self.pipe_factory(path, "r+b", buffering=0)
            except OSError:
                self.close()
                continue  # that pipe index is not there; try the next one
            try:
                self._send(OP_HANDSHAKE, {"v": RPC_VERSION, "client_id": self.client_id})
                payload = self._recv_payload(deadline=time.monotonic() + timeout)
                if payload.get("evt") != "READY":
                    raise ConnectionError(f"Unexpected Discord RPC hello: {payload!r}")
                return
            except (OSError, TimeoutError, ConnectionError):
                # The pipe existed but the handshake did not complete. Do not
                # fall through to other indices with a half-open stream.
                self.close()
                raise
        raise ConnectionError("Discord IPC pipe not found") from None

    def close(self):
        self.pending_events = []
        if self.stream:
            try:
                self.stream.close()
            except OSError:
                pass
            finally:
                self.stream = None

    def _send(self, opcode, payload):
        self.stream.write(encode_frame(opcode, payload))

    def _recv_payload(self, deadline=None):
        while True:
            opcode, length = decode_header(read_exact(self.stream, 8, deadline))
            payload = json.loads(read_exact(self.stream, length, deadline).decode("utf-8"))
            if opcode == OP_PING:
                self._send(OP_PONG, payload)
                continue
            if opcode == OP_CLOSE:
                raise ConnectionError(payload.get("message", "Discord RPC closed"))
            if opcode == OP_FRAME:
                return payload

    def command(self, cmd, args=None, evt=None, timeout=COMMAND_TIMEOUT):
        nonce = uuid.uuid4().hex
        payload = {"cmd": cmd, "args": args or {}, "nonce": nonce}
        if evt:
            payload["evt"] = evt
        self._send(OP_FRAME, payload)
        deadline = time.monotonic() + timeout
        while True:
            response = self._recv_payload(deadline)
            if response.get("nonce") != nonce:
                # An unsolicited event arrived while we waited for our reply.
                # Keep it so the event loop can act on it instead of dropping it.
                self.pending_events.append(response)
                continue
            if response.get("cmd") == "ERROR" or response.get("evt") == "ERROR":
                data = response.get("data") or {}
                raise DiscordRpcError(
                    data.get("message", "Discord RPC error"),
                    data.get("code"),
                )
            return response.get("data")

    def subscribe(self, event):
        return self.command("SUBSCRIBE", {}, evt=event)

    def next_event(self, timeout=EVENT_IDLE_TIMEOUT):
        """Return the next pushed event, or None if none arrived in time.

        None is an ordinary idle tick, not an error.
        """
        if self.pending_events:
            return self.pending_events.pop(0)
        try:
            return self._recv_payload(time.monotonic() + timeout)
        except TimeoutError:
            return None

    def authenticate(self, access_token):
        return self.command("AUTHENTICATE", {"access_token": access_token})

    def authorize(self):
        return self.command(
            "AUTHORIZE",
            {"client_id": self.client_id, "scopes": ["rpc", "identify"]},
        )

    def selected_voice_channel(self):
        return self.command("GET_SELECTED_VOICE_CHANNEL")

    def voice_settings(self):
        return self.command("GET_VOICE_SETTINGS")


def build_voice_state(channel_data, settings_data):
    settings = settings_data or {}
    return DiscordVoiceState(
        connected=bool(channel_data),
        muted=bool(settings.get("mute")),
        deafened=bool(settings.get("deaf")),
        channel_name=(channel_data or {}).get("name", ""),
    )


class DiscordMonitor:
    def __init__(
        self,
        client_id,
        access_token="",
        on_event=None,
        on_state=None,
        on_status=None,
        poll_interval=POLL_INTERVAL,
        ipc_factory=DiscordIpc,
        config_loader=load_config,
    ):
        self.client_id = client_id
        self.access_token = access_token
        self.config_loader = config_loader
        self.on_event = on_event or (lambda event, state: None)
        self.on_state = on_state or (lambda state: None)
        self._on_status = on_status or (lambda status: None)
        self.poll_interval = poll_interval
        self.ipc_factory = ipc_factory
        self.stop_event = threading.Event()
        self.thread = None
        self.previous_state = DiscordVoiceState()
        self.ipc = None
        self._last_status = None

    def on_status(self, status):
        """Report status to the UI and to the log, so a hidden resident is diagnosable."""
        if status != self._last_status:
            self._last_status = status
            log.info("status: %s", status)
        self._on_status(status)

    def poll_once(self):
        channel = self.ipc.selected_voice_channel()
        settings = self.ipc.voice_settings()
        state = build_voice_state(channel, settings)
        self.handle_state(state)
        return state

    def handle_state(self, state):
        previous = self.previous_state
        if state != previous:
            self.on_state(state)
        if state.connected and not previous.connected:
            self.on_event(EVENT_CONNECTED, state)
        if state.connected and state.muted and not previous.muted:
            self.on_event(EVENT_MUTED, state)
        if state.connected and state.deafened and not previous.deafened:
            self.on_event(EVENT_DEAFENED, state)
        self.previous_state = state

        if not state.connected:
            self.on_status("not in voice")
        elif state.deafened:
            self.on_status(f"deafened in {state.channel_name or 'voice'}")
        elif state.muted:
            self.on_status(f"muted in {state.channel_name or 'voice'}")
        else:
            self.on_status(f"connected to {state.channel_name or 'voice'}")

    def _authenticated_token(self):
        """Token to authenticate with, refreshed from disk if it went stale.

        Read fresh from the config on every attempt: a token refreshed here or
        by a re-authorization must take effect without restarting the app.
        """
        config = self.config_loader()
        self.client_id = config.get("client_id") or self.client_id
        token, refreshed = ensure_access_token(config)
        if refreshed:
            self.on_status("token refreshed")
        self.access_token = token
        return token

    def _authenticate(self):
        """Authenticate, refreshing once if Discord rejects the token.

        Covers the case where the stored expiry is wrong or the token was
        revoked early: the expiry check alone would not catch it.
        """
        try:
            self.ipc.authenticate(self.access_token)
        except DiscordRpcError as exc:
            if exc.code not in TOKEN_REJECTED_CODES:
                raise
            config = self.config_loader()
            if not config.get("refresh_token"):
                raise NeedsAuthorization("Discord rejected the stored token") from exc
            try:
                token = refresh_access_token(
                    config["client_id"], config["client_secret"], config["refresh_token"]
                )
            except RuntimeError as refresh_error:
                raise NeedsAuthorization(str(refresh_error)) from refresh_error
            store_token(config, token)
            save_config(config)
            self.access_token = config["access_token"]
            self.on_status("token refreshed")
            self.ipc.authenticate(self.access_token)

    def _session(self):
        """One connected session: subscribe, then react to pushed updates.

        Falls back to plain polling when the client will not accept
        subscriptions, so an older or restricted client still works.
        """
        self.previous_state = DiscordVoiceState()  # re-apply state after a reconnect
        subscribed = True
        for event in ("VOICE_SETTINGS_UPDATE", "VOICE_CHANNEL_SELECT"):
            try:
                self.ipc.subscribe(event)
            except DiscordRpcError:
                subscribed = False
        self.on_status("connected")
        self.poll_once()
        last_keepalive = time.monotonic()
        while not self.stop_event.is_set():
            pushed = False
            if subscribed:
                # None means "nothing pushed in the idle window" - an ordinary
                # tick that lets us run the keepalive and re-check stop_event.
                pushed = self.ipc.next_event(EVENT_IDLE_TIMEOUT) is not None
            else:
                self.stop_event.wait(self.poll_interval)
            due = time.monotonic() - last_keepalive >= KEEPALIVE_INTERVAL
            # A pushed update must be read back immediately; waiting for the
            # keepalive would make mute react slower than the old polling did.
            if pushed or not subscribed or due:
                self.poll_once()
                last_keepalive = time.monotonic()

    def _run(self):
        backoff = RECONNECT_BACKOFF_START
        while not self.stop_event.is_set():
            try:
                if not self.client_id:
                    self.on_status("configure Discord client id")
                    self.stop_event.wait(RECONNECT_BACKOFF_MAX)
                    self.client_id = self.config_loader().get("client_id", "")
                    continue
                token = self._authenticated_token()
                self.ipc = self.ipc_factory(self.client_id)
                self.ipc.connect()
                if token:
                    self._authenticate()
                backoff = RECONNECT_BACKOFF_START
                self._session()
            except NeedsAuthorization as exc:
                # Hammering the pipe cannot fix this, and each attempt occupies
                # a pipe instance for up to a minute. Wait long, keep the thread.
                self.on_status(f"authorization required: {exc}")
                self._wait_backoff(RECONNECT_BACKOFF_MAX)
                continue
            except DiscordRpcError as exc:
                self.on_status(f"RPC error [{exc.code}]: {self._safe(exc)}")
            except TimeoutError:
                self.on_status("Discord not responding; retrying")
            except Exception as exc:
                self.on_status(f"offline: {self._safe(exc)}")
            finally:
                if self.ipc:
                    self.ipc.close()
                    self.ipc = None
            self._wait_backoff(backoff)
            backoff = min(backoff * 2, RECONNECT_BACKOFF_MAX)

    def _safe(self, exc):
        return redact(exc, self.access_token)

    def _wait_backoff(self, seconds):
        self.stop_event.wait(seconds)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._run, name="DiscordMonitor", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.ipc:
            self.ipc.close()
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)


def authorize_and_save(config_path=CONFIG_PATH, ipc_factory=DiscordIpc, token_opener=None):
    config = load_config(config_path)
    if not config["client_id"] or not config["client_secret"]:
        raise RuntimeError("Enter Discord Client ID and Client Secret first.")
    ipc = ipc_factory(config["client_id"])
    try:
        ipc.connect()
        auth = ipc.authorize()
    finally:
        ipc.close()
    token = exchange_code(
        config["client_id"],
        config["client_secret"],
        auth["code"],
        opener=token_opener,
    )
    config["enabled"] = True
    store_token(config, token)
    save_config(config, config_path)
    return token
