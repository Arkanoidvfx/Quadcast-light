import unittest

from quadcastlight.integrations.discord import DiscordVoiceState
from quadcastlight import policy, settings


def base_settings(**changes):
    values = dict(settings.DEFAULTS)
    values["flow_palette"] = list(settings.DEFAULT_FLOW_PALETTE)
    values.update(changes)
    return values


DISCORD = {
    "mute_color": (255, 90, 0),
    "deafen_color": (255, 0, 0),
    "brightness": None,
    "restore_default": True,
}


class ZoneTests(unittest.TestCase):
    def test_zone_levels_apply_after_the_master_brightness(self):
        upper, lower = policy.zone_colors((200, 100, 50), 50, 100, 0)
        self.assertEqual(upper, (100, 50, 25))
        self.assertEqual(lower, (0, 0, 0))

    def test_full_brightness_is_the_untouched_color(self):
        self.assertEqual(
            policy.zone_colors((10, 20, 30), 100, 100, 100), ((10, 20, 30), (10, 20, 30))
        )


class AlertTests(unittest.TestCase):
    def test_alert_palette_stays_near_the_chosen_hue(self):
        palette = policy.alert_palette((255, 0, 0))
        self.assertEqual(palette[0], (255, 0, 0))
        for color in palette:
            self.assertGreater(color[0], color[1], "red must stay dominant")
            self.assertGreater(color[0], color[2])

    def test_alert_ignores_dimmed_zones(self):
        """An alert that respects a zone dimmed to zero would be invisible."""
        program = policy.alert_program((255, 0, 0), 100)
        brightest = max(max(upper) for upper, _lower in program.frames)
        self.assertEqual(brightest, 255)
        for upper, lower in program.frames:
            self.assertEqual(max(upper) > 0, True)
            self.assertEqual(max(lower) > 0, True)

    def test_alert_brightness_is_honored(self):
        dim = policy.alert_program((255, 0, 0), 40)
        bright = policy.alert_program((255, 0, 0), 100)
        self.assertLess(
            max(max(u) for u, _ in dim.frames), max(max(u) for u, _ in bright.frames)
        )


class DecideTests(unittest.TestCase):
    def test_deafened_wins_over_muted(self):
        state = DiscordVoiceState(connected=True, muted=True, deafened=True)
        program = policy.decide(state, base_settings(), DISCORD)
        self.assertEqual(program.label, "Discord deafened")

    def test_muted_uses_the_mute_color(self):
        state = DiscordVoiceState(connected=True, muted=True)
        program = policy.decide(state, base_settings(), DISCORD)
        self.assertEqual(program.label, "Discord muted")
        self.assertEqual(program.frames[0][0], (255, 90, 0))

    def test_clear_state_returns_the_selected_effect(self):
        state = DiscordVoiceState(connected=True)
        program = policy.decide(state, base_settings(animation="aurora"), DISCORD)
        self.assertEqual(program.label, "Aurora Flow")

    def test_restore_disabled_leaves_the_light_alone(self):
        state = DiscordVoiceState(connected=True)
        config = dict(DISCORD, restore_default=False)
        self.assertIsNone(policy.decide(state, base_settings(), config))

    def test_no_voice_state_still_gives_the_selected_effect(self):
        program = policy.decide(None, base_settings(animation="solid"), DISCORD)
        self.assertEqual(program.label, "Solid")


class EffectProgramTests(unittest.TestCase):
    def test_solid_effect_respects_both_zone_levels(self):
        program = policy.effect_program(
            base_settings(
                animation="solid",
                color=(200, 0, 0),
                brightness=100,
                upper_brightness=0,
                lower_brightness=100,
            )
        )
        upper, lower = program.frames[0]
        self.assertEqual(upper, (0, 0, 0))
        self.assertEqual(lower, (200, 0, 0))

    def test_color_shift_uses_the_custom_palette(self):
        palette = [(255, 0, 0), (0, 255, 0)]
        program = policy.effect_program(
            base_settings(animation="color_shift", flow_palette=palette, brightness=100)
        )
        seen = {frame[0] for frame in program.frames}
        self.assertGreater(len(seen), 2, "a flow must actually move between colors")

    def test_speed_changes_the_frame_delay(self):
        slow = policy.effect_program(base_settings(animation="aurora", speed=1))
        fast = policy.effect_program(base_settings(animation="aurora", speed=100))
        self.assertGreater(slow.frame_delay, fast.frame_delay)


class NotificationTests(unittest.TestCase):
    def test_notification_blinks_the_raw_color_in_both_zones(self):
        program = policy.notification_program((0, 255, 0), 0.2, 0.2)
        lit = [frame for frame in program.frames if max(frame[0]) > 0]
        self.assertTrue(lit)
        for upper, lower in lit:
            self.assertEqual(upper, (0, 255, 0))
            self.assertEqual(lower, (0, 255, 0), "both zones, unscaled")

    def test_duration_covers_every_repeat(self):
        self.assertAlmostEqual(policy.notification_duration(5, 0.2, 0.3), 2.5)


class PerChannelNotificationTests(unittest.TestCase):
    def shared(self, **changes):
        return base_settings(
            notification_color=(0, 255, 0),
            notification_times=8,
            notification_on_seconds=1.5,
            notification_off_seconds=1.5,
            **changes,
        )

    def test_without_per_channel_every_channel_gets_the_shared_notification(self):
        values = self.shared(
            channel_notifications={"alpha": {"color": (255, 0, 0), "times": 2}}
        )
        self.assertEqual(
            policy.notification_for(values, "alpha"), ((0, 255, 0), 8, 1.5, 1.5)
        )

    def test_an_override_only_replaces_the_fields_it_sets(self):
        values = self.shared(
            notification_per_channel=True,
            channel_notifications={"alpha": {"color": (255, 0, 0)}},
        )
        color, times, on_seconds, off_seconds = policy.notification_for(values, "alpha")
        self.assertEqual(color, (255, 0, 0))
        self.assertEqual(times, 8, "shared repeats survive a colour-only override")
        self.assertEqual((on_seconds, off_seconds), (1.5, 1.5))

    def test_channel_lookup_ignores_case(self):
        values = self.shared(
            notification_per_channel=True,
            channel_notifications={"alpha": {"times": 3}},
        )
        self.assertEqual(policy.notification_for(values, "ALPHA")[1], 3)

    def test_channels_without_an_override_still_get_the_shared_one(self):
        values = self.shared(
            notification_per_channel=True,
            channel_notifications={"alpha": {"times": 3}},
        )
        self.assertEqual(policy.notification_for(values, "beta"), ((0, 255, 0), 8, 1.5, 1.5))

    def test_turning_per_channel_off_restores_shared_without_losing_overrides(self):
        overrides = {"alpha": {"color": (255, 0, 0)}}
        on = self.shared(notification_per_channel=True, channel_notifications=overrides)
        off = self.shared(notification_per_channel=False, channel_notifications=overrides)

        self.assertEqual(policy.notification_for(on, "alpha")[0], (255, 0, 0))
        self.assertEqual(policy.notification_for(off, "alpha")[0], (0, 255, 0))
        self.assertEqual(off["channel_notifications"], overrides, "overrides are kept")

    def test_no_channel_means_the_shared_notification(self):
        values = self.shared(
            notification_per_channel=True,
            channel_notifications={"alpha": {"color": (255, 0, 0)}},
        )
        self.assertEqual(policy.notification_for(values), ((0, 255, 0), 8, 1.5, 1.5))
        self.assertEqual(policy.notification_for(values, ""), ((0, 255, 0), 8, 1.5, 1.5))


if __name__ == "__main__":
    unittest.main()
