import dataclasses
import unittest

from retrovault.core import config
from retrovault.input import Action, ActionEvent, Backend, BackendState, NullBackend


class ActionEnumTests(unittest.TestCase):
    def test_action_has_exactly_expected_members_and_values(self):
        expected = {
            "UP": "up",
            "DOWN": "down",
            "LEFT": "left",
            "RIGHT": "right",
            "ACCEPT": "accept",
            "BACK": "back",
            "MENU": "menu",
            "OPTIONS": "options",
            "PREV_SYSTEM": "previous_system",
            "NEXT_SYSTEM": "next_system",
        }
        actual = {member.name: member.value for member in Action}
        self.assertEqual(actual, expected)
        self.assertEqual(len(list(Action)), 10)

    def test_action_event_is_frozen_and_defaults_repeat_false(self):
        event = ActionEvent(Action.UP)
        self.assertFalse(event.repeat)
        self.assertEqual(event, ActionEvent(Action.UP, repeat=False))
        self.assertNotEqual(event, ActionEvent(Action.UP, repeat=True))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            event.repeat = True  # type: ignore[misc]


class BackendProtocolTests(unittest.TestCase):
    def test_null_backend_satisfies_protocol(self):
        self.assertIsInstance(NullBackend(), Backend)

    def test_null_backend_reports_not_connected(self):
        self.assertFalse(NullBackend().is_connected())

    def test_null_backend_poll_returns_neutral_state(self):
        state = NullBackend().poll()
        self.assertEqual(state.buttons, frozenset())
        self.assertEqual(state.axes, (0.0, 0.0))

    def test_null_backend_lifecycle_hooks_are_noops(self):
        backend = NullBackend()
        self.assertIsNone(backend.start())
        self.assertIsNone(backend.stop())

    def test_backend_state_is_frozen(self):
        state = BackendState()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            state.axes = (1.0, 1.0)  # type: ignore[misc]

    def test_backend_state_equality(self):
        a = BackendState(buttons=frozenset({"dpad_up"}), axes=(0.5, -0.5))
        b = BackendState(buttons=frozenset({"dpad_up"}), axes=(0.5, -0.5))
        c = BackendState(buttons=frozenset({"dpad_down"}), axes=(0.5, -0.5))
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)


class ControllerConfigMigrationTests(unittest.TestCase):
    def test_missing_controller_section_gets_full_defaults(self):
        migrated = config.migrate_config({})
        self.assertEqual(migrated["controller"], config.DEFAULT_CONFIG["controller"])
        self.assertTrue(migrated["controller"]["enabled"])
        self.assertEqual(migrated["controller"]["dead_zone"], 0.35)
        self.assertEqual(migrated["controller"]["repeat_delay_ms"], 400)
        self.assertEqual(migrated["controller"]["repeat_rate_ms"], 120)
        self.assertEqual(migrated["controller"]["accept_button"], "south")

    def test_partial_controller_section_keeps_override_and_fills_rest(self):
        migrated = config.migrate_config({"controller": {"dead_zone": 0.1}})
        self.assertEqual(migrated["controller"]["dead_zone"], 0.1)
        self.assertTrue(migrated["controller"]["enabled"])
        self.assertEqual(migrated["controller"]["repeat_delay_ms"], 400)
        self.assertEqual(migrated["controller"]["repeat_rate_ms"], 120)
        self.assertEqual(migrated["controller"]["accept_button"], "south")

    def test_enabled_and_accept_button_round_trip(self):
        migrated = config.migrate_config(
            {"controller": {"enabled": False, "accept_button": "east"}}
        )
        self.assertFalse(migrated["controller"]["enabled"])
        self.assertEqual(migrated["controller"]["accept_button"], "east")


if __name__ == "__main__":
    unittest.main()
