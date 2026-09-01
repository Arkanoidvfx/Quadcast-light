"""The object QML talks to.

Holds no rendering logic and no protocol knowledge: it turns user intent into
engine programs, mirrors engine and monitor state back out as properties, and
persists settings. Monitor callbacks arrive on their own threads and are
marshalled here through Qt signals, which is what makes the UI thread safe.
"""
import threading

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot
from PySide6.QtGui import QColor

from ..integrations import discord as discord_monitor
from ..integrations import twitch as twitch_monitor
from .. import autostart, device, logging_setup, policy
from .. import settings as settings_module
from ..engine import LightEngine, Program

log = logging_setup.get("ui")

# The mirror only has to keep up with the eye, not with the 20 Hz device feed.
MIRROR_INTERVAL_MS = 33
SETTINGS_DEBOUNCE_MS = 700


def hex_of(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(c))) for c in rgb)


def rgb_of(text):
    color = QColor(text)
    return (color.red(), color.green(), color.blue()) if color.isValid() else (0, 0, 0)


# A status indicator that is green whatever happens is decoration, and one that
# turns amber when you mute is worse than none. The monitors report prose, so
# the mapping from prose to health lives here, next to a test that pins every
# string they can emit.
#
# ok        working
# busy      connecting or reconnecting; nothing for anyone to do
# attention the user has to act
# off       switched off

DISCORD_HEALTH = (
    ("disabled", "off", "Discord off"),
    ("connecting", "busy", "Discord connecting"),
    ("token refreshed", "ok", "Discord connected"),
    ("connected to ", "ok", "Discord connected"),
    ("connected", "ok", "Discord connected"),
    ("muted in ", "ok", "Discord muted"),
    ("deafened in ", "ok", "Discord deafened"),
    ("not in voice", "ok", "Discord idle"),
    ("authorization required", "attention", "Discord sign-in needed"),
    ("configure Discord client id", "attention", "Discord not set up"),
    ("Discord not responding", "busy", "Discord reconnecting"),
    ("offline", "busy", "Discord reconnecting"),
    ("RPC error", "busy", "Discord reconnecting"),
)

TWITCH_HEALTH = (
    ("disabled", "off", "Twitch off"),
    ("connecting", "busy", "Twitch connecting"),
    # Polling the public API is a supported mode, not a fault: it is what you
    # get without credentials, and it was being flagged as a problem.
    ("DecAPI fallback", "ok", "Twitch watching"),
    ("EventSub connected", "ok", "Twitch watching"),
    ("Twitch token refreshed", "ok", "Twitch watching"),
    ("authorization expired", "attention", "Twitch sign-in needed"),
    ("waiting for Twitch authorization", "attention", "Twitch sign-in needed"),
    ("OAuth server ready", "attention", "Twitch sign-in needed"),
    ("error", "busy", "Twitch retrying"),
)


def classify(status, table):
    """(health, short label) for a status string.

    Unknown wording counts as needing attention: a new failure message should
    show up rather than pass for healthy.
    """
    text = (status or "").strip()
    for marker, health, summary in table:
        if text.startswith(marker):
            return health, summary
    return "attention", text.split(";")[0][:28] or "unknown"


class Bridge(QObject):
    # Property notifications
    lightChanged = Signal()
    settingsChanged = Signal()
    statusChanged = Signal()
    paletteChanged = Signal()
    integrationsChanged = Signal()
    channelNotificationsChanged = Signal()

    # Cross-thread hops from monitor callbacks.
    _discordState = Signal(object)
    _discordStatus = Signal(str)
    _twitchStatus = Signal(str)
    _twitchLive = Signal(str)

    def __init__(self, parent=None, engine=None, with_monitors=True):
        """engine/with_monitors are seams: a preview harness can supply a fake
        device and skip the network monitors. Production passes neither."""
        super().__init__(parent)
        self._settings = settings_module.load()
        self._status_message = ""
        self._device_connected = False
        self._device_detail = "looking for the microphone"
        self._discord_status = "disabled"
        self._twitch_status = "disabled"
        self._voice_state = None
        self._upper = "#000000"
        self._lower = "#000000"
        self._label = ""
        self._mirror_enabled = True
        # Discord and Twitch config is read from disk once and written through,
        # so the UI never blocks on a file read per property access.
        self._discord_config_cache = None
        self._twitch_config_cache = None

        self.engine = engine or LightEngine(on_status=self._on_device_status)
        self.engine.on_status = self._on_device_status
        self.engine.start()

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SETTINGS_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self._flush_settings)

        self._mirror = QTimer(self)
        self._mirror.setInterval(MIRROR_INTERVAL_MS)
        self._mirror.timeout.connect(self._pump_mirror)
        self._mirror.start()

        self._discordState.connect(self._apply_voice_state)
        self._discordStatus.connect(self._set_discord_status)
        self._twitchStatus.connect(self._set_twitch_status)
        self._twitchLive.connect(self._on_twitch_live)

        self.discord = None
        self.twitch = None
        if with_monitors:
            self.start_monitors()

        self._supervisor = QTimer(self)
        self._supervisor.setInterval(30_000)
        self._supervisor.timeout.connect(self._supervise)
        self._supervisor.start()

        if self._settings["startup_light"] == "set":
            self.apply_effect(remember=False)

    # -- lifecycle ----------------------------------------------------------

    def shutdown(self):
        self._flush_settings()
        for monitor in (self.discord, self.twitch):
            if monitor:
                monitor.stop()
        self.engine.stop()

    def set_mirror_enabled(self, enabled):
        """Stop mirroring while the window is hidden; nothing is watching it."""
        self._mirror_enabled = enabled
        if enabled and not self._mirror.isActive():
            self._mirror.start()
        elif not enabled and self._mirror.isActive():
            self._mirror.stop()

    # -- live mirror --------------------------------------------------------

    def _pump_mirror(self):
        upper, lower = self.engine.current_frame()
        upper_hex, lower_hex = hex_of(upper), hex_of(lower)
        label = self.engine.current_label()
        if (upper_hex, lower_hex, label) != (self._upper, self._lower, self._label):
            self._upper, self._lower, self._label = upper_hex, lower_hex, label
            self.lightChanged.emit()

    def _on_device_status(self, connected, detail):
        self._device_connected = connected
        self._device_detail = detail
        log.info("device %s: %s", "connected" if connected else "lost", detail)
        self.statusChanged.emit()

    # -- programs -----------------------------------------------------------

    def _live_apply(self):
        """Push the edited settings to the LEDs immediately.

        There is nothing to commit: the engine swaps programs in place, so an
        apply button only made sense when a colour change meant killing one
        process and spawning another. Goes through the standing program, so a
        Discord alert still wins and the edit shows once it clears.
        """
        self.engine.start()  # no-op unless Off or Stop released the device
        program = self._standing_program()
        if program is not None:
            self.engine.set_program(program)
        # Clear whatever the last message was: acting on the light makes an
        # older error or progress line stale.
        self._status_message = ""
        self._settings["startup_light"] = "set"
        self._queue_save()
        self.statusChanged.emit()

    def _standing_program(self):
        """What should be showing, given settings and the current voice state."""
        return policy.decide(self._voice_state, self._settings, self._discord_config())

    # -- monitors -----------------------------------------------------------

    def start_monitors(self):
        self.start_discord_monitor()
        self.start_twitch_monitor()

    def start_discord_monitor(self):
        if self.discord:
            self.discord.stop()
            self.discord = None
        self._discord_config_cache = discord_monitor.load_config()
        config = self._discord_config_cache
        if not config["enabled"]:
            self._set_discord_status("disabled")
            return
        self._set_discord_status("connecting")
        self.discord = discord_monitor.DiscordMonitor(
            config["client_id"],
            config["access_token"],
            on_state=self._discordState.emit,
            on_status=self._safe_emit(self._discordStatus.emit),
        )
        self.discord.start()

    def start_twitch_monitor(self):
        if self.twitch:
            self.twitch.stop()
            self.twitch = None
        self._twitch_config_cache = twitch_monitor.load_config()
        config = self._twitch_config_cache
        if not config["enabled"]:
            self._set_twitch_status("disabled")
            return
        self._set_twitch_status("connecting")
        self.twitch = twitch_monitor.TwitchMonitor(
            config["client_id"],
            config["client_secret"],
            channels=config["channels"],
            on_online=lambda channel, _stream: self._twitchLive.emit(channel),
            on_status=self._safe_emit(self._twitchStatus.emit),
        )
        self.twitch.start()

    @staticmethod
    def _safe_emit(emit):
        """Monitors call back from their own threads; never let one die on us."""

        def handler(value):
            try:
                emit(str(value))
            except RuntimeError:
                pass

        return handler

    def _supervise(self):
        for monitor, restart in (
            (self.discord, self.start_discord_monitor),
            (self.twitch, self.start_twitch_monitor),
        ):
            thread = getattr(monitor, "thread", None) if monitor else None
            if monitor and (not thread or not thread.is_alive()):
                log.warning("monitor thread died; restarting")
                restart()

    def _apply_voice_state(self, state):
        self._voice_state = state
        program = self._standing_program()
        if program is None:
            self._status_message = "Discord restore is off; light left as is."
        else:
            self.engine.set_program(program)
            self._status_message = ""
            log.info("voice state -> %s", program.label)
        self.statusChanged.emit()

    def _set_discord_status(self, status):
        if status != self._discord_status:
            self._discord_status = status
            self.statusChanged.emit()

    def _set_twitch_status(self, status):
        if status != self._twitch_status:
            self._twitch_status = status
            self.statusChanged.emit()

    def _on_twitch_live(self, channel):
        self._flash_notification(f"{channel} is live", channel=channel)

    def _flash_notification(self, message, channel=None):
        """Flash the notification this channel earns, shared or its own."""
        color, times, on_seconds, off_seconds = policy.notification_for(
            self._settings, channel
        )
        self.engine.flash(
            policy.notification_program(color, on_seconds, off_seconds),
            policy.notification_duration(times, on_seconds, off_seconds),
        )
        self._status_message = message
        self.statusChanged.emit()
        log.info("notification for %s: %s", channel or "shared", hex_of(color))

    # -- properties ---------------------------------------------------------

    @Property(str, notify=lightChanged)
    def upperHex(self):
        return self._upper

    @Property(str, notify=lightChanged)
    def lowerHex(self):
        return self._lower

    @Property(str, notify=lightChanged)
    def lightLabel(self):
        return self._label

    @Property(bool, notify=statusChanged)
    def deviceConnected(self):
        return self._device_connected

    @Property(str, constant=True)
    def logPath(self):
        return logging_setup.LOG_PATH

    @Property(str, notify=statusChanged)
    def statusMessage(self):
        return self._status_message

    @Property(str, notify=statusChanged)
    def discordStatus(self):
        return self._discord_status

    @Property(str, notify=statusChanged)
    def twitchStatus(self):
        return self._twitch_status

    @Property(bool, notify=statusChanged)
    def discordNeedsAuth(self):
        return classify(self._discord_status, DISCORD_HEALTH)[0] == "attention"

    @Property(str, notify=statusChanged)
    def discordHealth(self):
        return classify(self._discord_status, DISCORD_HEALTH)[0]

    @Property(str, notify=statusChanged)
    def discordSummary(self):
        return classify(self._discord_status, DISCORD_HEALTH)[1]

    @Property(str, notify=statusChanged)
    def twitchHealth(self):
        return classify(self._twitch_status, TWITCH_HEALTH)[0]

    @Property(str, notify=statusChanged)
    def twitchSummary(self):
        return classify(self._twitch_status, TWITCH_HEALTH)[1]

    def _get_color(self):
        return hex_of(self._settings["color"])

    def _set_color(self, value):
        rgb = rgb_of(value)
        if rgb != self._settings["color"]:
            self._settings["color"] = rgb
            self._queue_save()
            self.settingsChanged.emit()
            self._live_apply()

    colorHex = Property(str, _get_color, _set_color, notify=settingsChanged)

    def _get_brightness(self):
        return self._settings["brightness"]

    def _set_brightness(self, value):
        self._settings["brightness"] = max(0, min(100, int(value)))
        self._queue_save()
        self.settingsChanged.emit()
        self._live_apply()

    brightness = Property(int, _get_brightness, _set_brightness, notify=settingsChanged)

    def _get_effect(self):
        return self._settings["animation"]

    def _set_effect(self, value):
        if value in settings_module.EFFECT_LABELS:
            self._settings["animation"] = value
            self._queue_save()
            self.settingsChanged.emit()
            self._live_apply()

    effect = Property(str, _get_effect, _set_effect, notify=settingsChanged)

    @Property(list, constant=True)
    def effectKeys(self):
        return list(settings_module.EFFECT_KEYS)

    @Property(list, constant=True)
    def effectLabels(self):
        return [settings_module.EFFECT_LABELS[key] for key in settings_module.EFFECT_KEYS]

    def _get_speed(self):
        return self._settings["speed"]

    def _set_speed(self, value):
        self._settings["speed"] = max(1, min(100, int(value)))
        self._queue_save()
        self.settingsChanged.emit()
        self._live_apply()

    speed = Property(int, _get_speed, _set_speed, notify=settingsChanged)

    def _get_upper(self):
        return self._settings["upper_brightness"]

    def _set_upper(self, value):
        self._settings["upper_brightness"] = max(0, min(100, int(value)))
        self._queue_save()
        self.settingsChanged.emit()
        self._live_apply()

    upperBrightness = Property(int, _get_upper, _set_upper, notify=settingsChanged)

    def _get_lower(self):
        return self._settings["lower_brightness"]

    def _set_lower(self, value):
        self._settings["lower_brightness"] = max(0, min(100, int(value)))
        self._queue_save()
        self.settingsChanged.emit()
        self._live_apply()

    lowerBrightness = Property(int, _get_lower, _set_lower, notify=settingsChanged)

    def _get_mic_flipped(self):
        return bool(self._settings["mic_flipped"])

    def _set_mic_flipped(self, value):
        value = bool(value)
        if value != self._settings["mic_flipped"]:
            self._settings["mic_flipped"] = value
            self._queue_save()
            self.settingsChanged.emit()

    micFlipped = Property(bool, _get_mic_flipped, _set_mic_flipped, notify=settingsChanged)

    @Property(list, notify=paletteChanged)
    def flowPalette(self):
        return [hex_of(color) for color in self._settings["flow_palette"]]

    @Property(bool, notify=settingsChanged)
    def paletteRelevant(self):
        return self._settings["animation"] == "color_shift"

    def _get_startup(self):
        return autostart.enabled()

    def _set_startup(self, value):
        try:
            autostart.set_enabled(bool(value))
        except OSError as exc:
            self._status_message = f"Autostart change failed: {exc}"
        self.settingsChanged.emit()

    startWithWindows = Property(bool, _get_startup, _set_startup, notify=settingsChanged)

    def _get_notification_color(self):
        return hex_of(self._settings["notification_color"])

    def _set_notification_color(self, value):
        self._settings["notification_color"] = rgb_of(value)
        self._queue_save()
        self.settingsChanged.emit()
        self.channelNotificationsChanged.emit()

    notificationColor = Property(
        str, _get_notification_color, _set_notification_color, notify=settingsChanged
    )

    def _get_notification_times(self):
        return self._settings["notification_times"]

    def _set_notification_times(self, value):
        self._settings["notification_times"] = max(1, min(30, int(value)))
        self._queue_save()
        self.settingsChanged.emit()
        self.channelNotificationsChanged.emit()

    notificationTimes = Property(
        int, _get_notification_times, _set_notification_times, notify=settingsChanged
    )

    # -- integration settings ------------------------------------------------
    #
    # Discord and Twitch keep their own config files (secrets go through DPAPI),
    # so these read and write there rather than through gui.json.

    def _discord_config(self):
        if self._discord_config_cache is None:
            self._discord_config_cache = discord_monitor.load_config()
        return self._discord_config_cache

    def _update_discord(self, **changes):
        config = self._discord_config()
        config.update(changes)
        discord_monitor.save_config(config)
        self.integrationsChanged.emit()
        # Colors and the restore toggle change what should be showing right now.
        self._apply_voice_state(self._voice_state)

    def _get_discord_enabled(self):
        return bool(self._discord_config()["enabled"])

    def _set_discord_enabled(self, value):
        self._update_discord(enabled=bool(value))
        self.start_discord_monitor()

    discordEnabled = Property(
        bool, _get_discord_enabled, _set_discord_enabled, notify=integrationsChanged
    )

    def _get_mute_color(self):
        return hex_of(self._discord_config()["mute_color"])

    def _set_mute_color(self, value):
        self._update_discord(mute_color=rgb_of(value))

    discordMuteColor = Property(
        str, _get_mute_color, _set_mute_color, notify=integrationsChanged
    )

    def _get_deafen_color(self):
        return hex_of(self._discord_config()["deafen_color"])

    def _set_deafen_color(self, value):
        self._update_discord(deafen_color=rgb_of(value))

    discordDeafenColor = Property(
        str, _get_deafen_color, _set_deafen_color, notify=integrationsChanged
    )

    def _get_discord_brightness(self):
        value = self._discord_config()["brightness"]
        return policy.ALERT_BRIGHTNESS if value is None else int(value)

    def _set_discord_brightness(self, value):
        self._update_discord(brightness=max(0, min(100, int(value))))

    discordBrightness = Property(
        int, _get_discord_brightness, _set_discord_brightness, notify=integrationsChanged
    )

    def _get_restore_default(self):
        return bool(self._discord_config()["restore_default"])

    def _set_restore_default(self, value):
        self._update_discord(restore_default=bool(value))

    discordRestoreDefault = Property(
        bool, _get_restore_default, _set_restore_default, notify=integrationsChanged
    )

    def _twitch_config(self):
        if self._twitch_config_cache is None:
            self._twitch_config_cache = twitch_monitor.load_config()
        return self._twitch_config_cache

    def _get_twitch_enabled(self):
        return bool(self._twitch_config()["enabled"])

    def _set_twitch_enabled(self, value):
        config = self._twitch_config()
        config["enabled"] = bool(value)
        twitch_monitor.save_config(config)
        self.integrationsChanged.emit()
        self.start_twitch_monitor()

    twitchEnabled = Property(
        bool, _get_twitch_enabled, _set_twitch_enabled, notify=integrationsChanged
    )

    def _get_per_channel(self):
        return bool(self._settings["notification_per_channel"])

    def _set_per_channel(self, value):
        value = bool(value)
        if value != self._settings["notification_per_channel"]:
            self._settings["notification_per_channel"] = value
            self._queue_save()
            self.settingsChanged.emit()
            self.channelNotificationsChanged.emit()

    notificationPerChannel = Property(
        bool, _get_per_channel, _set_per_channel, notify=settingsChanged
    )

    @Property(list, notify=channelNotificationsChanged)
    def channelNotifications(self):
        """One row per watched channel, with its resolved notification.

        Driven by the configured channel list, so the UI grows and shrinks with
        it, and a stored override for a channel that was removed stays on disk
        without cluttering the window.
        """
        overrides = self._settings.get("channel_notifications", {})
        rows = []
        for channel in self._twitch_config()["channels"]:
            color, times, on_seconds, off_seconds = policy.notification_for(
                self._settings, channel
            )
            rows.append(
                {
                    "name": channel,
                    "color": hex_of(color),
                    "times": times,
                    "onSeconds": on_seconds,
                    "offSeconds": off_seconds,
                    "custom": bool(overrides.get(channel)),
                }
            )
        return rows

    def _get_twitch_channels(self):
        return ", ".join(self._twitch_config()["channels"])

    def _set_twitch_channels(self, value):
        config = self._twitch_config()
        channels = twitch_monitor.channels_from_json(value)
        if channels == tuple(config["channels"]):
            return
        config["channels"] = list(channels)
        twitch_monitor.save_config(config)
        self.integrationsChanged.emit()
        self.channelNotificationsChanged.emit()
        self.start_twitch_monitor()

    twitchChannels = Property(
        str, _get_twitch_channels, _set_twitch_channels, notify=integrationsChanged
    )

    # Client IDs are not secret and come back to the UI. Secrets never do: the
    # UI only learns whether one is stored, and sends a new one to replace it.

    def _get_discord_client_id(self):
        return self._discord_config()["client_id"]

    discordClientId = Property(str, _get_discord_client_id, notify=integrationsChanged)

    @Property(bool, notify=integrationsChanged)
    def discordHasSecret(self):
        return bool(self._discord_config()["client_secret"])

    def _get_twitch_client_id(self):
        return self._twitch_config()["client_id"]

    twitchClientId = Property(str, _get_twitch_client_id, notify=integrationsChanged)

    @Property(bool, notify=integrationsChanged)
    def twitchHasSecret(self):
        return bool(self._twitch_config()["client_secret"])

    def _get_notification_on(self):
        return self._settings["notification_on_seconds"]

    def _set_notification_on(self, value):
        self._settings["notification_on_seconds"] = max(0.05, min(10.0, float(value)))
        self._queue_save()
        self.settingsChanged.emit()
        self.channelNotificationsChanged.emit()

    notificationOnSeconds = Property(
        float, _get_notification_on, _set_notification_on, notify=settingsChanged
    )

    def _get_notification_off(self):
        return self._settings["notification_off_seconds"]

    def _set_notification_off(self, value):
        self._settings["notification_off_seconds"] = max(0.05, min(10.0, float(value)))
        self._queue_save()
        self.settingsChanged.emit()
        self.channelNotificationsChanged.emit()

    notificationOffSeconds = Property(
        float, _get_notification_off, _set_notification_off, notify=settingsChanged
    )

    # -- slots --------------------------------------------------------------

    def _edit_channel(self, channel, **changes):
        """Write one field of a channel override, creating it on first edit."""
        channel = str(channel).strip().lower()
        if not channel:
            return
        overrides = dict(self._settings.get("channel_notifications", {}))
        entry = dict(overrides.get(channel, {}))
        entry.update(changes)
        overrides[channel] = entry
        self._settings["channel_notifications"] = overrides
        self._queue_save()
        self.channelNotificationsChanged.emit()

    @Slot(str, str)
    def setChannelColor(self, channel, value):
        self._edit_channel(channel, color=rgb_of(value))

    @Slot(str, int)
    def setChannelTimes(self, channel, value):
        self._edit_channel(channel, times=max(1, min(30, int(value))))

    @Slot(str, float)
    def setChannelOnSeconds(self, channel, value):
        self._edit_channel(channel, on_seconds=max(0.05, min(10.0, float(value))))

    @Slot(str, float)
    def setChannelOffSeconds(self, channel, value):
        self._edit_channel(channel, off_seconds=max(0.05, min(10.0, float(value))))

    @Slot(str)
    def resetChannelNotification(self, channel):
        """Drop the override so the channel follows the shared notification."""
        overrides = dict(self._settings.get("channel_notifications", {}))
        if overrides.pop(str(channel).strip().lower(), None) is None:
            return
        self._settings["channel_notifications"] = overrides
        self._queue_save()
        self.channelNotificationsChanged.emit()

    @Slot(str)
    def testChannelNotification(self, channel):
        self._flash_notification(f"Testing {channel}.", channel=channel)

    @Slot(str, str)
    def saveDiscordCredentials(self, client_id, secret):
        """Store the app credentials. An empty secret keeps the stored one."""
        config = self._discord_config()
        secret = secret.strip() or config["client_secret"]
        try:
            discord_monitor.save_credentials(
                client_id.strip(), secret, enabled=config["enabled"]
            )
        except OSError as exc:
            self._status_message = f"Could not save Discord credentials: {exc}"
            self.statusChanged.emit()
            return
        self._discord_config_cache = None
        self._status_message = "Discord credentials saved. Authorize next."
        self.integrationsChanged.emit()
        self.statusChanged.emit()
        self.start_discord_monitor()

    @Slot(str, str)
    def saveTwitchCredentials(self, client_id, secret):
        config = self._twitch_config()
        secret = secret.strip() or config["client_secret"]
        try:
            twitch_monitor.save_credentials(
                client_id.strip(), secret, enabled=config["enabled"]
            )
        except OSError as exc:
            self._status_message = f"Could not save Twitch credentials: {exc}"
            self.statusChanged.emit()
            return
        self._twitch_config_cache = None
        self._status_message = "Twitch credentials saved. Authorize next."
        self.integrationsChanged.emit()
        self.statusChanged.emit()
        self.start_twitch_monitor()


    def apply_effect(self, remember=True):
        try:
            program = policy.effect_program(self._settings)
        except ValueError as exc:
            self._status_message = str(exc)
            self.statusChanged.emit()
            return
        self.engine.start()  # no-op unless Stop released the device
        self.engine.set_program(program)
        if remember:
            self._settings["startup_light"] = "set"
            self._queue_save()
        self._status_message = ""
        self.statusChanged.emit()

    @Slot()
    def saveToMic(self):
        """Write the colour that is showing into mic flash.

        The flash holds one colour, not an effect: an animation is saved as the
        frame it happens to be on, and that is what the microphone shows with
        nothing running. The status line says so, because the button's name
        invites the other assumption.
        """
        upper, lower = self.engine.current_frame()
        self._settings["startup_light"] = "save"
        self._queue_save()
        self._status_message = "Saving to the microphone..."
        self.statusChanged.emit()
        self._run_off_thread(lambda: self._save_to_flash(upper, lower))

    def _save_to_flash(self, upper, lower):
        # The engine owns the handle, so pause it for the write sequence.
        self.engine.stop()
        error = None
        try:
            device.save_to_device(upper, lower)
        except Exception as exc:
            error = exc
        finally:
            # Put the light back: the flash is the fallback for when nothing is
            # running, not a reason to stop what is playing now.
            self.engine.start()
            program = self._standing_program()
            if program is not None:
                self.engine.set_program(program)
        if error is None:
            self._status_message = (
                "Saved. The mic holds this one colour while the app is closed; "
                "it cannot play an effect on its own."
            )
            log.info("saved %s to flash", hex_of(upper))
        else:
            self._status_message = f"Save failed: {error}"
            log.warning("flash save failed: %s", error)
        self.statusChanged.emit()

    @Slot()
    def testNotification(self):
        self._flash_notification("Testing notification.")

    @Slot(str)
    def setColorHex(self, value):
        self._set_color(value)

    @Slot(int, str)
    def setPaletteColor(self, index, value):
        palette = list(self._settings["flow_palette"])
        if 0 <= index < len(palette):
            palette[index] = rgb_of(value)
            self._settings["flow_palette"] = palette
            self._queue_save()
            self.paletteChanged.emit()
            self._live_apply()

    @Slot(str)
    def addPaletteColor(self, value):
        palette = list(self._settings["flow_palette"])
        palette.append(rgb_of(value))
        self._settings["flow_palette"] = palette
        self._queue_save()
        self.paletteChanged.emit()
        self._live_apply()

    @Slot(int)
    def removePaletteColor(self, index):
        palette = list(self._settings["flow_palette"])
        if len(palette) <= 2:
            self._status_message = "Color Shift needs at least two colors."
            self.statusChanged.emit()
            return
        if 0 <= index < len(palette):
            del palette[index]
            self._settings["flow_palette"] = palette
            self._queue_save()
            self.paletteChanged.emit()
            self._live_apply()

    @Slot()
    def resetPalette(self):
        self._settings["flow_palette"] = list(settings_module.DEFAULT_FLOW_PALETTE)
        self._queue_save()
        self.paletteChanged.emit()
        self._live_apply()

    @Slot()
    def authorizeDiscord(self):
        self._status_message = "Authorizing Discord..."
        self.statusChanged.emit()

        def worker():
            try:
                discord_monitor.authorize_and_save()
            except Exception as exc:
                self._status_message = f"Discord authorization failed: {exc}"
            else:
                self._status_message = "Discord authorized."
                self._discord_config_cache = None
                self.integrationsChanged.emit()
                self.start_discord_monitor()
            self.statusChanged.emit()

        self._run_off_thread(worker)

    @Slot()
    def authorizeTwitch(self):
        """Open the local OAuth adapter; TwitchIO refreshes its own token after."""
        import webbrowser

        config = self._twitch_config()
        if not config["client_id"] or not config["client_secret"]:
            self._status_message = "Enter a Twitch Client ID and Secret first."
            self.statusChanged.emit()
            return
        if not self.twitch or not getattr(self.twitch, "thread", None):
            self.start_twitch_monitor()
        webbrowser.open(twitch_monitor.AUTHORIZE_URL)
        self._status_message = "Finish the Twitch sign-in in your browser."
        self.statusChanged.emit()

    @staticmethod
    def _run_off_thread(worker):
        threading.Thread(target=worker, daemon=True).start()

    # -- persistence --------------------------------------------------------

    def _queue_save(self):
        self._save_timer.start()

    def _flush_settings(self):
        try:
            settings_module.save(self._settings)
        except OSError as exc:
            log.warning("could not save settings: %s", exc)
