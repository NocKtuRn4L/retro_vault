"""Tests for the input state machine and (lightly) the Qt controller router.

The state-machine tests are pure: they drive :class:`InputStateMachine` with a
hand-built sequence of :class:`BackendState`s and an explicit fake clock, so they
need neither Qt nor a real controller. A single optional test exercises
:class:`ControllerRouter` and is skipped when PySide6 is unavailable.
"""

import os
import unittest

from retrovault.input import Action, ActionEvent, BackendState
from retrovault.input.backend import (
    BTN_BACK,
    BTN_DPAD_LEFT,
    BTN_DPAD_RIGHT,
    BTN_DPAD_UP,
    BTN_FACE_EAST,
    BTN_FACE_SOUTH,
    BTN_FACE_WEST,
    BTN_SHOULDER_L,
    BTN_SHOULDER_R,
    BTN_START,
)
from retrovault.input.router import InputStateMachine


def _state(buttons=(), axes=(0.0, 0.0)):
    return BackendState(buttons=frozenset(buttons), axes=axes)


def _actions(events):
    return [e.action for e in events]


class DirectionRepeatTests(unittest.TestCase):
    def _machine(self, **kw):
        defaults = dict(dead_zone=0.35, repeat_delay_ms=400, repeat_rate_ms=120, accept_button="south")
        defaults.update(kw)
        return InputStateMachine(**defaults)

    def test_initial_dpad_press_emits_single_non_repeat(self):
        m = self._machine()
        events = m.update(_state(buttons={BTN_DPAD_RIGHT}), now_ms=0)
        self.assertEqual(events, [ActionEvent(Action.RIGHT, repeat=False)])

    def test_holding_without_delay_emits_nothing_until_delay(self):
        m = self._machine()
        m.update(_state(buttons={BTN_DPAD_RIGHT}), now_ms=0)
        # Still within the 400ms delay window: no further events.
        self.assertEqual(m.update(_state(buttons={BTN_DPAD_RIGHT}), now_ms=200), [])
        self.assertEqual(m.update(_state(buttons={BTN_DPAD_RIGHT}), now_ms=399), [])

    def test_repeat_fires_after_delay_then_at_rate(self):
        m = self._machine()
        m.update(_state(buttons={BTN_DPAD_RIGHT}), now_ms=0)
        # First repeat exactly at the delay boundary.
        self.assertEqual(
            m.update(_state(buttons={BTN_DPAD_RIGHT}), now_ms=400),
            [ActionEvent(Action.RIGHT, repeat=True)],
        )
        # Nothing until the next rate interval elapses.
        self.assertEqual(m.update(_state(buttons={BTN_DPAD_RIGHT}), now_ms=500), [])
        # Second repeat at delay + rate = 520.
        self.assertEqual(
            m.update(_state(buttons={BTN_DPAD_RIGHT}), now_ms=520),
            [ActionEvent(Action.RIGHT, repeat=True)],
        )

    def test_large_time_jump_emits_multiple_repeats(self):
        m = self._machine()
        m.update(_state(buttons={BTN_DPAD_RIGHT}), now_ms=0)
        # Jump well past delay + several rate intervals: 400, 520, 640 all due.
        events = m.update(_state(buttons={BTN_DPAD_RIGHT}), now_ms=700)
        self.assertEqual(events, [ActionEvent(Action.RIGHT, repeat=True)] * 3)

    def test_release_stops_repeats_and_next_press_starts_fresh(self):
        m = self._machine()
        m.update(_state(buttons={BTN_DPAD_RIGHT}), now_ms=0)
        m.update(_state(buttons={BTN_DPAD_RIGHT}), now_ms=400)  # a repeat
        # Release.
        self.assertEqual(m.update(_state(), now_ms=450), [])
        # Held-neutral emits nothing even past old repeat schedule.
        self.assertEqual(m.update(_state(), now_ms=1000), [])
        # Press again: fresh non-repeat, and delay counts from the new press.
        self.assertEqual(
            m.update(_state(buttons={BTN_DPAD_RIGHT}), now_ms=1000),
            [ActionEvent(Action.RIGHT, repeat=False)],
        )
        self.assertEqual(m.update(_state(buttons={BTN_DPAD_RIGHT}), now_ms=1200), [])
        self.assertEqual(
            m.update(_state(buttons={BTN_DPAD_RIGHT}), now_ms=1400),
            [ActionEvent(Action.RIGHT, repeat=True)],
        )


class DeadZoneHysteresisTests(unittest.TestCase):
    def _machine(self):
        return InputStateMachine(dead_zone=0.35, repeat_delay_ms=400, repeat_rate_ms=120)

    def test_axis_below_dead_zone_emits_nothing(self):
        m = self._machine()
        self.assertEqual(m.update(_state(axes=(0.2, 0.0)), now_ms=0), [])
        self.assertEqual(m.update(_state(axes=(0.34, 0.0)), now_ms=10), [])

    def test_axis_above_dead_zone_emits_direction_once(self):
        m = self._machine()
        events = m.update(_state(axes=(0.5, 0.0)), now_ms=0)
        self.assertEqual(events, [ActionEvent(Action.RIGHT, repeat=False)])
        # Held above dead zone within delay: no re-fire.
        self.assertEqual(m.update(_state(axes=(0.5, 0.0)), now_ms=100), [])

    def test_negative_axis_maps_up(self):
        m = self._machine()
        # y negative == up (SDL convention).
        self.assertEqual(
            m.update(_state(axes=(0.0, -0.6)), now_ms=0),
            [ActionEvent(Action.UP, repeat=False)],
        )

    def test_hysteresis_small_dip_keeps_direction_held(self):
        m = self._machine()  # release threshold = 0.35 * 0.7 = 0.245
        self.assertEqual(
            m.update(_state(axes=(0.5, 0.0)), now_ms=0),
            [ActionEvent(Action.RIGHT, repeat=False)],
        )
        # Dip below dead_zone (0.35) but above release threshold (0.245):
        # still engaged, so no new press event.
        self.assertEqual(m.update(_state(axes=(0.30, 0.0)), now_ms=50), [])
        self.assertEqual(m.update(_state(axes=(0.26, 0.0)), now_ms=60), [])
        # Rising back up: still no re-fire (never released).
        self.assertEqual(m.update(_state(axes=(0.5, 0.0)), now_ms=70), [])

    def test_hysteresis_release_below_lower_threshold_then_refire(self):
        m = self._machine()
        m.update(_state(axes=(0.5, 0.0)), now_ms=0)
        # Drop below the release threshold -> released, no event.
        self.assertEqual(m.update(_state(axes=(0.2, 0.0)), now_ms=50), [])
        # Cross the dead zone again -> a fresh press.
        self.assertEqual(
            m.update(_state(axes=(0.5, 0.0)), now_ms=60),
            [ActionEvent(Action.RIGHT, repeat=False)],
        )


class DirectionCombinationTests(unittest.TestCase):
    def test_dpad_and_stick_do_not_double_fire(self):
        m = InputStateMachine(dead_zone=0.35)
        # Both dpad-right and stick-right: a single RIGHT press.
        events = m.update(_state(buttons={BTN_DPAD_RIGHT}, axes=(0.9, 0.0)), now_ms=0)
        self.assertEqual(events, [ActionEvent(Action.RIGHT, repeat=False)])

    def test_never_left_and_right_together_dpad_dominates(self):
        m = InputStateMachine(dead_zone=0.35)
        # dpad-left with stick pushed right: dpad wins, only LEFT.
        events = m.update(_state(buttons={BTN_DPAD_LEFT}, axes=(0.9, 0.0)), now_ms=0)
        self.assertEqual(_actions(events), [Action.LEFT])

    def test_horizontal_and_vertical_are_independent(self):
        m = InputStateMachine(dead_zone=0.35)
        events = m.update(_state(axes=(0.8, -0.8)), now_ms=0)
        self.assertEqual(set(_actions(events)), {Action.RIGHT, Action.UP})


class ButtonEdgeTests(unittest.TestCase):
    def test_held_face_button_emits_accept_once(self):
        m = InputStateMachine(accept_button="south")
        self.assertEqual(
            m.update(_state(buttons={BTN_FACE_SOUTH}), now_ms=0),
            [ActionEvent(Action.ACCEPT, repeat=False)],
        )
        # Held across ticks: no repeat for buttons.
        self.assertEqual(m.update(_state(buttons={BTN_FACE_SOUTH}), now_ms=100), [])
        self.assertEqual(m.update(_state(buttons={BTN_FACE_SOUTH}), now_ms=1000), [])

    def test_release_then_press_emits_again(self):
        m = InputStateMachine(accept_button="south")
        m.update(_state(buttons={BTN_FACE_SOUTH}), now_ms=0)
        self.assertEqual(m.update(_state(), now_ms=10), [])
        self.assertEqual(
            m.update(_state(buttons={BTN_FACE_SOUTH}), now_ms=20),
            [ActionEvent(Action.ACCEPT, repeat=False)],
        )

    def test_accept_button_south_mapping(self):
        m = InputStateMachine(accept_button="south")
        self.assertEqual(_actions(m.update(_state(buttons={BTN_FACE_SOUTH}), 0)), [Action.ACCEPT])
        self.assertEqual(_actions(m.update(_state(), 1)), [])
        self.assertEqual(_actions(m.update(_state(buttons={BTN_FACE_EAST}), 2)), [Action.BACK])

    def test_accept_button_east_mapping_swaps(self):
        m = InputStateMachine(accept_button="east")
        self.assertEqual(_actions(m.update(_state(buttons={BTN_FACE_EAST}), 0)), [Action.ACCEPT])
        self.assertEqual(_actions(m.update(_state(), 1)), [])
        self.assertEqual(_actions(m.update(_state(buttons={BTN_FACE_SOUTH}), 2)), [Action.BACK])

    def test_select_button_also_backs(self):
        m = InputStateMachine(accept_button="south")
        self.assertEqual(_actions(m.update(_state(buttons={BTN_BACK}), 0)), [Action.BACK])

    def test_shoulders_and_start_map_once_per_press(self):
        m = InputStateMachine()
        self.assertEqual(_actions(m.update(_state(buttons={BTN_SHOULDER_L}), 0)), [Action.PREV_SYSTEM])
        self.assertEqual(_actions(m.update(_state(buttons={BTN_SHOULDER_L}), 1)), [])
        self.assertEqual(_actions(m.update(_state(buttons={BTN_SHOULDER_R}), 2)), [Action.NEXT_SYSTEM])
        self.assertEqual(_actions(m.update(_state(buttons={BTN_SHOULDER_R}), 3)), [])
        self.assertEqual(_actions(m.update(_state(buttons={BTN_START}), 4)), [Action.MENU])
        self.assertEqual(_actions(m.update(_state(buttons={BTN_START}), 5)), [])

    def test_west_face_button_maps_to_options(self):
        m = InputStateMachine(accept_button="south")
        self.assertEqual(_actions(m.update(_state(buttons={BTN_FACE_WEST}), 0)), [Action.OPTIONS])
        # Buttons don't repeat while held.
        self.assertEqual(_actions(m.update(_state(buttons={BTN_FACE_WEST}), 1)), [])

    def test_options_button_independent_of_accept_swap(self):
        # OPTIONS stays on the west button regardless of the south/east accept swap.
        m = InputStateMachine(accept_button="east")
        self.assertEqual(_actions(m.update(_state(buttons={BTN_FACE_WEST}), 0)), [Action.OPTIONS])

    def test_directions_never_repeat_only_directions_do(self):
        # Sanity: a held shoulder past the repeat delay still never repeats.
        m = InputStateMachine(repeat_delay_ms=100, repeat_rate_ms=50)
        m.update(_state(buttons={BTN_SHOULDER_R}), now_ms=0)
        self.assertEqual(m.update(_state(buttons={BTN_SHOULDER_R}), now_ms=1000), [])


class DisabledTests(unittest.TestCase):
    def test_disabled_yields_no_events(self):
        m = InputStateMachine(enabled=False)
        self.assertEqual(m.update(_state(buttons={BTN_FACE_SOUTH}), 0), [])
        self.assertEqual(m.update(_state(buttons={BTN_DPAD_UP}, axes=(0.9, 0.0)), 500), [])


class FromConfigTests(unittest.TestCase):
    def test_from_config_reads_controller_section(self):
        m = InputStateMachine.from_config(
            {"enabled": True, "dead_zone": 0.5, "repeat_delay_ms": 300,
             "repeat_rate_ms": 80, "accept_button": "east"}
        )
        self.assertTrue(m.enabled)
        self.assertEqual(m.accept_button, "east")
        # dead_zone honored: 0.4 is below 0.5 so nothing fires.
        self.assertEqual(m.update(_state(axes=(0.4, 0.0)), 0), [])
        self.assertEqual(_actions(m.update(_state(axes=(0.6, 0.0)), 1)), [Action.RIGHT])


# ── Optional Qt driver smoke test ─────────────────────────────────────────────
try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from retrovault.input.router import ControllerRouter

    _QT_AVAILABLE = True
except ImportError:
    _QT_AVAILABLE = False


class _QueueBackend:
    """Fake backend returning queued states, then neutral once drained."""

    def __init__(self, states):
        self._states = list(states)
        self.started = False
        self.stopped = False

    def poll(self):
        if self._states:
            return self._states.pop(0)
        return BackendState()

    def is_connected(self):
        return True

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


@unittest.skipUnless(_QT_AVAILABLE, "PySide6 is not installed")
class ControllerRouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_tick_emits_action_signal(self):
        backend = _QueueBackend([_state(buttons={BTN_FACE_SOUTH})])
        machine = InputStateMachine(accept_button="south")
        router = ControllerRouter(backend, machine, interval_ms=10)

        received = []
        router.action.connect(received.append)

        router.start()
        self.assertTrue(backend.started)
        router._tick()  # drive one tick manually rather than spinning the loop
        self.assertEqual(received, [ActionEvent(Action.ACCEPT, repeat=False)])

        router.stop()
        self.assertTrue(backend.stopped)

    def test_pause_blocks_polling(self):
        backend = _QueueBackend([_state(buttons={BTN_FACE_SOUTH})])
        router = ControllerRouter(backend, InputStateMachine(), interval_ms=10)
        received = []
        router.action.connect(received.append)

        router.start()
        router.pause()
        self.assertTrue(router.paused)
        router._tick()  # should be a no-op while paused
        self.assertEqual(received, [])

        router.resume()
        self.assertFalse(router.paused)
        router._tick()
        self.assertEqual(received, [ActionEvent(Action.ACCEPT, repeat=False)])
        router.stop()


class _ConnBackend:
    """Fake backend whose connection state can be toggled between polls."""

    def __init__(self, connected=True):
        self.connected = connected

    def poll(self):
        return BackendState()

    def is_connected(self):
        return self.connected

    def start(self):
        pass

    def stop(self):
        pass


@unittest.skipUnless(_QT_AVAILABLE, "PySide6 is not installed")
class ControllerConnectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_start_reports_initial_connection(self):
        backend = _ConnBackend(connected=True)
        router = ControllerRouter(backend, InputStateMachine(), interval_ms=10)
        seen = []
        router.connection_changed.connect(seen.append)
        router.start()
        self.assertEqual(seen, [True])
        self.assertTrue(router.connected)
        router.stop()

    def test_change_emits_once_on_cadence(self):
        backend = _ConnBackend(connected=True)
        router = ControllerRouter(backend, InputStateMachine(), interval_ms=10)
        seen = []
        router.connection_changed.connect(seen.append)
        router.start()  # -> [True]

        # Disconnect, then tick past the cadence threshold; exactly one False.
        backend.connected = False
        for _ in range(router._CONN_CHECK_EVERY):
            router._tick()
        self.assertEqual(seen, [True, False])
        self.assertFalse(router.connected)

        # No further churn while state is stable.
        for _ in range(router._CONN_CHECK_EVERY):
            router._tick()
        self.assertEqual(seen, [True, False])
        router.stop()


if __name__ == "__main__":
    unittest.main()
