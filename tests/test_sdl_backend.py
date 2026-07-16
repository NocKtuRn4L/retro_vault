"""Tests for the SDL/pygame-ce controller backend.

The pure ``normalize_state`` mapping is exercised with plain Python values and
needs no pygame. The ``SdlBackend`` lifecycle tests must pass whether or not
pygame-ce is installed, and never require a physical controller.
"""

import unittest

from retrovault.input.backend import (
    BTN_BACK,
    BTN_DPAD_DOWN,
    BTN_DPAD_LEFT,
    BTN_DPAD_RIGHT,
    BTN_DPAD_UP,
    BTN_FACE_EAST,
    BTN_FACE_NORTH,
    BTN_FACE_SOUTH,
    BTN_FACE_WEST,
    BTN_SHOULDER_L,
    BTN_SHOULDER_R,
    BTN_START,
    NEUTRAL_STATE,
    Backend,
    BackendState,
)
from retrovault.input.sdl_backend import SdlBackend, _controller_button_map, normalize_state

try:
    import pygame  # noqa: F401

    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False


class _FakePygameConstants:
    """Minimal stand-in exposing the SDL CONTROLLER_BUTTON_* constants."""

    CONTROLLER_BUTTON_A = 0
    CONTROLLER_BUTTON_B = 1
    CONTROLLER_BUTTON_X = 2
    CONTROLLER_BUTTON_Y = 3
    CONTROLLER_BUTTON_BACK = 4
    CONTROLLER_BUTTON_START = 6
    CONTROLLER_BUTTON_LEFTSHOULDER = 9
    CONTROLLER_BUTTON_RIGHTSHOULDER = 10
    CONTROLLER_BUTTON_DPAD_UP = 11
    CONTROLLER_BUTTON_DPAD_DOWN = 12
    CONTROLLER_BUTTON_DPAD_LEFT = 13
    CONTROLLER_BUTTON_DPAD_RIGHT = 14


class ControllerButtonMapTests(unittest.TestCase):
    """The GameController button-constant -> semantic mapping; no pygame needed."""

    def test_map_covers_face_dpad_shoulders_and_menu_buttons(self):
        mapping = _controller_button_map(_FakePygameConstants())
        self.assertEqual(mapping[0], BTN_FACE_SOUTH)  # A is always the south face button
        self.assertEqual(mapping[1], BTN_FACE_EAST)
        self.assertEqual(mapping[2], BTN_FACE_WEST)
        self.assertEqual(mapping[3], BTN_FACE_NORTH)
        self.assertEqual(mapping[9], BTN_SHOULDER_L)
        self.assertEqual(mapping[10], BTN_SHOULDER_R)
        self.assertEqual(mapping[4], BTN_BACK)
        self.assertEqual(mapping[6], BTN_START)
        # The D-pad is delivered as buttons (a Switch Pro Controller has no hat).
        self.assertEqual(mapping[11], BTN_DPAD_UP)
        self.assertEqual(mapping[12], BTN_DPAD_DOWN)
        self.assertEqual(mapping[13], BTN_DPAD_LEFT)
        self.assertEqual(mapping[14], BTN_DPAD_RIGHT)

    def test_map_has_all_four_dpad_directions(self):
        values = set(_controller_button_map(_FakePygameConstants()).values())
        self.assertTrue({BTN_DPAD_UP, BTN_DPAD_DOWN, BTN_DPAD_LEFT, BTN_DPAD_RIGHT} <= values)


@unittest.skipUnless(PYGAME_AVAILABLE, "pygame-ce is not installed")
class HeadlessHintTests(unittest.TestCase):
    """start() must configure SDL for windowless input or the pad reads dead."""

    def test_start_sets_headless_video_and_background_event_hints(self):
        import os

        backend = SdlBackend()
        try:
            backend.start()
            # Both are required: the dummy driver lets the event queue pump, and
            # the background-events hint stops SDL dropping input with no window.
            self.assertIsNotNone(os.environ.get("SDL_VIDEODRIVER"))
            self.assertEqual(os.environ.get("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS"), "1")
        finally:
            backend.stop()


class NormalizeStateTests(unittest.TestCase):
    """The pure raw->semantic mapping; no pygame required."""

    def test_hat_left(self):
        state = normalize_state((-1, 0), [], set())
        self.assertEqual(state.buttons, frozenset({BTN_DPAD_LEFT}))

    def test_hat_right(self):
        state = normalize_state((1, 0), [], set())
        self.assertEqual(state.buttons, frozenset({BTN_DPAD_RIGHT}))

    def test_hat_up_uses_positive_y(self):
        # SDL hat convention: y = +1 means UP (screen-inverted vs. analog stick).
        state = normalize_state((0, 1), [], set())
        self.assertEqual(state.buttons, frozenset({BTN_DPAD_UP}))

    def test_hat_down_uses_negative_y(self):
        # SDL hat convention: y = -1 means DOWN.
        state = normalize_state((0, -1), [], set())
        self.assertEqual(state.buttons, frozenset({BTN_DPAD_DOWN}))

    def test_hat_diagonal(self):
        state = normalize_state((-1, 1), [], set())
        self.assertEqual(state.buttons, frozenset({BTN_DPAD_LEFT, BTN_DPAD_UP}))

    def test_hat_neutral(self):
        state = normalize_state((0, 0), [], set())
        self.assertEqual(state.buttons, frozenset())

    def test_face_button_indices(self):
        self.assertEqual(normalize_state((0, 0), [], {0}).buttons, frozenset({BTN_FACE_SOUTH}))
        self.assertEqual(normalize_state((0, 0), [], {1}).buttons, frozenset({BTN_FACE_EAST}))
        self.assertEqual(normalize_state((0, 0), [], {2}).buttons, frozenset({BTN_FACE_WEST}))
        self.assertEqual(normalize_state((0, 0), [], {3}).buttons, frozenset({BTN_FACE_NORTH}))

    def test_shoulder_and_menu_buttons(self):
        self.assertEqual(normalize_state((0, 0), [], {4}).buttons, frozenset({BTN_SHOULDER_L}))
        self.assertEqual(normalize_state((0, 0), [], {5}).buttons, frozenset({BTN_SHOULDER_R}))
        self.assertEqual(normalize_state((0, 0), [], {6}).buttons, frozenset({BTN_BACK}))
        self.assertEqual(normalize_state((0, 0), [], {7}).buttons, frozenset({BTN_START}))

    def test_multiple_buttons(self):
        state = normalize_state((0, 0), [], {0, 7})
        self.assertEqual(state.buttons, frozenset({BTN_FACE_SOUTH, BTN_START}))

    def test_unknown_button_index_ignored(self):
        state = normalize_state((0, 0), [], {0, 99})
        self.assertEqual(state.buttons, frozenset({BTN_FACE_SOUTH}))

    def test_axes_passthrough(self):
        state = normalize_state((0, 0), [0.5, -0.25], set())
        self.assertEqual(state.axes, (0.5, -0.25))

    def test_axes_clamped(self):
        state = normalize_state((0, 0), [2.0, -3.0], set())
        self.assertEqual(state.axes, (1.0, -1.0))

    def test_axes_missing_default_to_zero(self):
        self.assertEqual(normalize_state((0, 0), [], set()).axes, (0.0, 0.0))
        self.assertEqual(normalize_state((0, 0), [0.3], set()).axes, (0.3, 0.0))

    def test_returns_backend_state(self):
        self.assertIsInstance(normalize_state((0, 0), [], set()), BackendState)


class SdlBackendLifecycleTests(unittest.TestCase):
    """Lifecycle behavior that must hold regardless of pygame presence."""

    def test_constructs(self):
        backend = SdlBackend()
        self.assertIsInstance(backend, Backend)

    def test_poll_before_start_is_neutral(self):
        backend = SdlBackend()
        self.assertEqual(backend.poll(), NEUTRAL_STATE)
        self.assertFalse(backend.is_connected())

    def test_start_is_safe_without_a_controller(self):
        # start()/poll() must never raise, whether or not a controller (or
        # pygame) is present. We do not require a physical controller: when
        # none is connected the backend stays disconnected and reports neutral;
        # if a device happens to be present, poll() still returns a valid state.
        backend = SdlBackend()
        try:
            backend.start()
            if backend.is_connected():
                self.assertIsInstance(backend.poll(), BackendState)
            else:
                self.assertEqual(backend.poll(), NEUTRAL_STATE)
        finally:
            backend.stop()

    def test_stop_is_idempotent(self):
        backend = SdlBackend()
        backend.start()
        backend.stop()
        backend.stop()  # second stop must not raise
        self.assertFalse(backend.is_connected())

    def test_rescan_without_pygame_is_noop(self):
        backend = SdlBackend()
        # No start() -> no pygame reference; rescan must be safe.
        backend.rescan()
        self.assertFalse(backend.is_connected())


if __name__ == "__main__":
    unittest.main()
