import json
import os
import tempfile
import unittest

from quadcastlight import settings


class SettingsTests(unittest.TestCase):
    def temp_path(self, stack):
        temp_dir = stack.enter_context(tempfile.TemporaryDirectory())
        return os.path.join(temp_dir, "gui.json")

    def test_round_trip_preserves_every_field(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "gui.json")
            original = dict(settings.DEFAULTS)
            original.update(
                {
                    "color": (10, 20, 30),
                    "brightness": 42,
                    "animation": "color_shift",
                    "speed": 77,
                    "flow_palette": [(1, 2, 3), (4, 5, 6), (7, 8, 9)],
                    "upper_brightness": 15,
                    "lower_brightness": 85,
                    "notification_color": (0, 128, 255),
                    "notification_times": 12,
                    "notification_on_seconds": 0.25,
                    "notification_off_seconds": 0.35,
                    "startup_light": "save",
                }
            )
            settings.save(original, path)
            loaded = settings.load(path)

            self.assertEqual(loaded["color"], (10, 20, 30))
            self.assertEqual(loaded["brightness"], 42)
            self.assertEqual(loaded["animation"], "color_shift")
            self.assertEqual(loaded["speed"], 77)
            self.assertEqual(loaded["flow_palette"], [(1, 2, 3), (4, 5, 6), (7, 8, 9)])
            self.assertEqual(loaded["upper_brightness"], 15)
            self.assertEqual(loaded["lower_brightness"], 85)
            self.assertEqual(loaded["notification_color"], (0, 128, 255))
            self.assertEqual(loaded["notification_times"], 12)
            self.assertAlmostEqual(loaded["notification_on_seconds"], 0.25)
            self.assertEqual(loaded["startup_light"], "save")

    def test_missing_file_returns_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            loaded = settings.load(os.path.join(temp_dir, "absent.json"))
            self.assertEqual(loaded["animation"], settings.DEFAULTS["animation"])
            self.assertEqual(loaded["flow_palette"], list(settings.DEFAULT_FLOW_PALETTE))

    def test_garbage_is_clamped_rather_than_fatal(self):
        """A resident starting at logon must survive a hand-edited config."""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "gui.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "color": "not a color",
                        "brightness": 5000,
                        "animation": "does-not-exist",
                        "speed": -12,
                        "flow_palette": ["nope", [1, 2, 3]],
                        "upper_brightness": None,
                        "notification_times": 0,
                        "notification_on_seconds": "soon",
                        "startup_light": "explode",
                    },
                    handle,
                )
            loaded = settings.load(path)

            self.assertEqual(loaded["color"], settings.DEFAULT_COLOR)
            self.assertEqual(loaded["brightness"], 100)
            self.assertEqual(loaded["animation"], "solid")
            self.assertEqual(loaded["speed"], 1)
            # One usable color is not enough for a flow, so the default is kept.
            self.assertEqual(loaded["flow_palette"], list(settings.DEFAULT_FLOW_PALETTE))
            self.assertEqual(loaded["upper_brightness"], settings.DEFAULTS["upper_brightness"])
            self.assertEqual(loaded["notification_times"], 1)
            self.assertEqual(loaded["startup_light"], "set")

    def test_truncated_file_returns_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "gui.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('{"color": [1, 2')
            self.assertEqual(settings.load(path)["color"], settings.DEFAULT_COLOR)

    def test_save_is_atomic(self):
        """A kill mid-write must not leave a half-written config behind."""
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "gui.json")
            settings.save(settings.DEFAULTS, path)
            self.assertTrue(os.path.exists(path))
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_mic_flip_is_remembered_and_defaults_to_upright(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "gui.json")
            self.assertFalse(settings.load(path)["mic_flipped"])

            flipped = dict(settings.DEFAULTS, mic_flipped=True)
            settings.save(flipped, path)
            self.assertTrue(settings.load(path)["mic_flipped"])

            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"mic_flipped": "sideways"}, handle)
            self.assertFalse(
                settings.load(path)["mic_flipped"], "garbage must fall back to upright"
            )

    def test_channel_notifications_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "gui.json")
            values = dict(
                settings.DEFAULTS,
                notification_per_channel=True,
                channel_notifications={
                    "alpha": {"color": (255, 0, 0), "times": 3},
                    "beta": {"on_seconds": 0.4},
                },
            )
            settings.save(values, path)
            loaded = settings.load(path)

            self.assertTrue(loaded["notification_per_channel"])
            self.assertEqual(loaded["channel_notifications"]["alpha"]["color"], (255, 0, 0))
            self.assertEqual(loaded["channel_notifications"]["alpha"]["times"], 3)
            self.assertAlmostEqual(loaded["channel_notifications"]["beta"]["on_seconds"], 0.4)
            # A partial override stays partial, so it keeps inheriting.
            self.assertNotIn("color", loaded["channel_notifications"]["beta"])

    def test_channel_notifications_survive_a_mangled_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "gui.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "notification_per_channel": "yes",
                        "channel_notifications": {
                            "  ALPHA ": {"color": [300, -5, 20], "times": 900},
                            "beta": "not a dict",
                            "": {"times": 3},
                            "gamma": {"unknown_field": 1},
                        },
                    },
                    handle,
                )
            loaded = settings.load(path)

            self.assertFalse(loaded["notification_per_channel"], "only a real bool enables it")
            overrides = loaded["channel_notifications"]
            self.assertEqual(set(overrides), {"alpha"}, "junk entries are dropped")
            self.assertEqual(overrides["alpha"]["color"], (255, 0, 20))
            self.assertEqual(overrides["alpha"]["times"], 30)

    def test_animation_delay_shrinks_as_speed_rises(self):
        self.assertGreater(settings.animation_delay(1), settings.animation_delay(100))
        self.assertGreater(settings.animation_delay(100), 0)

    def test_effect_keys_and_labels_stay_in_step(self):
        self.assertEqual(len(settings.EFFECT_KEYS), len(settings.EFFECT_LABELS))
        self.assertIn("solid", settings.EFFECT_KEYS)
        for key in settings.EFFECT_KEYS:
            self.assertTrue(settings.EFFECT_LABELS[key])


if __name__ == "__main__":
    unittest.main()
