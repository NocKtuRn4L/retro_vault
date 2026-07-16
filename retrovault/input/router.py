"""Focus router: turn normalized backend state into semantic action events.

Two layers live here, deliberately kept apart so the interesting logic can be
tested without a Qt event loop or any real controller:

* :class:`InputStateMachine` — a pure, clock-free state machine. Feed it a
  :class:`~retrovault.input.backend.BackendState` snapshot plus a monotonic
  millisecond timestamp and it returns the discrete
  :class:`~retrovault.input.actions.ActionEvent` list to fire this tick. It owns
  dead-zone/hysteresis handling, held-direction auto-repeat, and button edge
  detection. No wall-clock calls happen inside it; all timing is injected via the
  ``now_ms`` parameter.
* :class:`ControllerRouter` — a thin ``QObject`` driver that polls a
  :class:`~retrovault.input.backend.Backend` on a ``QTimer``, runs the state
  machine with ``time.monotonic()``-derived time, and re-emits each event on its
  ``action`` signal. It can be paused/resumed so a launch session may suspend
  polling while an emulator is running.

Axis convention: the left stick is ``(x, y)`` with ``x`` positive = right and
``y`` positive = down (SDL convention). The D-pad button constants provide the
same directions discretely; the two sources are combined.
"""

import time

from .actions import Action, ActionEvent
from .backend import (
    BTN_BACK,
    BTN_DPAD_DOWN,
    BTN_DPAD_LEFT,
    BTN_DPAD_RIGHT,
    BTN_DPAD_UP,
    BTN_FACE_EAST,
    BTN_FACE_SOUTH,
    BTN_SHOULDER_L,
    BTN_SHOULDER_R,
    BTN_START,
    Backend,
    BackendState,
)

# The four directional actions, in a stable emission order.
_DIRECTION_ACTIONS = (Action.LEFT, Action.RIGHT, Action.UP, Action.DOWN)


class InputStateMachine:
    """Pure state machine mapping backend snapshots to :class:`ActionEvent`s.

    Timing is fully injectable: every method that cares about time takes an
    explicit monotonic ``now_ms`` so tests can drive a fake clock. The machine
    keeps no wall-clock state of its own.
    """

    def __init__(
        self,
        *,
        dead_zone: float = 0.35,
        repeat_delay_ms: float = 400,
        repeat_rate_ms: float = 120,
        accept_button: str = "south",
        enabled: bool = True,
    ) -> None:
        self._dead_zone = float(dead_zone)
        # Hysteresis: once engaged, a stick direction only releases after the
        # axis falls back below this lower threshold, preventing drift/chatter.
        self._release_threshold = self._dead_zone * 0.7
        self._repeat_delay_ms = float(repeat_delay_ms)
        self._repeat_rate_ms = float(repeat_rate_ms)
        self._enabled = bool(enabled)

        accept = str(accept_button).lower()
        if accept == "east":
            accept_face, back_face = BTN_FACE_EAST, BTN_FACE_SOUTH
        else:  # default / "south"
            accept_face, back_face = BTN_FACE_SOUTH, BTN_FACE_EAST
        self._accept_button = "east" if accept == "east" else "south"

        # (Action, predicate(buttons) -> bool). Buttons never auto-repeat; each
        # entry fires once per not-pressed -> pressed transition.
        self._button_map = [
            (Action.ACCEPT, lambda b, x=accept_face: x in b),
            (Action.BACK, lambda b, f=back_face: f in b or BTN_BACK in b),
            (Action.MENU, lambda b: BTN_START in b),
            (Action.PREV_SYSTEM, lambda b: BTN_SHOULDER_L in b),
            (Action.NEXT_SYSTEM, lambda b: BTN_SHOULDER_R in b),
        ]

        self.reset()

    # ── Introspection ────────────────────────────────────────────────────────
    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def accept_button(self) -> str:
        return self._accept_button

    @classmethod
    def from_config(cls, controller_cfg: dict) -> "InputStateMachine":
        """Build a machine from a config ``controller`` section (see config.py)."""
        cfg = controller_cfg or {}
        return cls(
            dead_zone=cfg.get("dead_zone", 0.35),
            repeat_delay_ms=cfg.get("repeat_delay_ms", 400),
            repeat_rate_ms=cfg.get("repeat_rate_ms", 120),
            accept_button=cfg.get("accept_button", "south"),
            enabled=cfg.get("enabled", True),
        )

    def reset(self) -> None:
        """Clear all latched/held state (e.g. after resuming from a pause)."""
        # Latched stick direction per axis, each in {-1, 0, 1}.
        self._stick_h = 0
        self._stick_v = 0
        # Directions currently held, and when each next auto-repeat is due.
        self._dir_held: set[Action] = set()
        self._dir_next_repeat: dict[Action, float] = {}
        # Previous pressed state of each mapped button action, for edge detection.
        self._btn_prev: dict[Action, bool] = {}

    # ── Main entry point ─────────────────────────────────────────────────────
    def update(self, state: BackendState, now_ms: float) -> list[ActionEvent]:
        """Return the events to fire for ``state`` at monotonic ``now_ms``."""
        if not self._enabled:
            return []

        events: list[ActionEvent] = []
        h, v = self._resolve_directions(state)
        active = {
            Action.LEFT: h == -1,
            Action.RIGHT: h == 1,
            Action.UP: v == -1,
            Action.DOWN: v == 1,
        }
        for action in _DIRECTION_ACTIONS:
            events.extend(self._process_direction(action, active[action], now_ms))
        events.extend(self._process_buttons(state.buttons))
        return events

    # ── Direction handling ───────────────────────────────────────────────────
    def _resolve_directions(self, state: BackendState) -> tuple[int, int]:
        """Combine D-pad and (hysteresis-latched) stick into (h, v) in {-1,0,1}."""
        buttons = state.buttons
        ax, ay = state.axes
        self._stick_h = self._latch(self._stick_h, ax)
        self._stick_v = self._latch(self._stick_v, ay)

        dpad_h = (BTN_DPAD_RIGHT in buttons) - (BTN_DPAD_LEFT in buttons)
        dpad_v = (BTN_DPAD_DOWN in buttons) - (BTN_DPAD_UP in buttons)

        # D-pad is explicit; when it names a direction it wins, otherwise the
        # stick's latched direction applies. A single scalar per axis guarantees
        # LEFT/RIGHT (and UP/DOWN) can never fire simultaneously — dominant wins.
        h = dpad_h if dpad_h != 0 else self._stick_h
        v = dpad_v if dpad_v != 0 else self._stick_v
        return h, v

    def _latch(self, current: int, value: float) -> int:
        """Apply dead zone + hysteresis to one axis, returning {-1, 0, 1}."""
        if current == 1:
            if value > self._release_threshold:
                return 1
            if value < -self._dead_zone:
                return -1
            return 0
        if current == -1:
            if value < -self._release_threshold:
                return -1
            if value > self._dead_zone:
                return 1
            return 0
        # Neutral: require crossing the full dead zone to engage.
        if value > self._dead_zone:
            return 1
        if value < -self._dead_zone:
            return -1
        return 0

    def _process_direction(self, action: Action, active: bool, now_ms: float) -> list[ActionEvent]:
        events: list[ActionEvent] = []
        if active:
            if action not in self._dir_held:
                # Initial press.
                self._dir_held.add(action)
                self._dir_next_repeat[action] = now_ms + self._repeat_delay_ms
                events.append(ActionEvent(action, repeat=False))
            elif self._repeat_rate_ms > 0:
                # Fire every repeat_rate_ms once the delay has elapsed. The loop
                # covers fake-clock jumps that span several intervals.
                while now_ms >= self._dir_next_repeat[action]:
                    events.append(ActionEvent(action, repeat=True))
                    self._dir_next_repeat[action] += self._repeat_rate_ms
            elif now_ms >= self._dir_next_repeat[action]:
                # Degenerate rate <= 0: fire at most once per delay window.
                events.append(ActionEvent(action, repeat=True))
                self._dir_next_repeat[action] = now_ms + self._repeat_delay_ms
        else:
            self._dir_held.discard(action)
            self._dir_next_repeat.pop(action, None)
        return events

    # ── Button handling ──────────────────────────────────────────────────────
    def _process_buttons(self, buttons: frozenset) -> list[ActionEvent]:
        events: list[ActionEvent] = []
        for action, predicate in self._button_map:
            pressed = bool(predicate(buttons))
            if pressed and not self._btn_prev.get(action, False):
                events.append(ActionEvent(action, repeat=False))
            self._btn_prev[action] = pressed
        return events


# ── Qt driver ─────────────────────────────────────────────────────────────────
try:
    from PySide6.QtCore import QObject, Qt, QTimer, Signal
    from PySide6.QtWidgets import QApplication

    _QT_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without PySide6
    _QT_AVAILABLE = False


if _QT_AVAILABLE:

    class ControllerRouter(QObject):
        """Poll a backend on a timer and re-emit action events for the UI.

        The ``action`` signal carries an :class:`ActionEvent` (payload type
        ``object`` so PySide6 does not try to marshal the dataclass). Windows and
        dialogs connect to it in later PRs; this class does not perform per-widget
        navigation itself.
        """

        # Emitted for every event the state machine produces. Payload: ActionEvent.
        action = Signal(object)

        def __init__(
            self,
            backend: Backend,
            machine: InputStateMachine,
            *,
            interval_ms: int = 12,
            parent: "QObject | None" = None,
        ) -> None:
            super().__init__(parent)
            self._backend = backend
            self._machine = machine
            self._interval_ms = int(interval_ms)
            self._target = None
            self._last_target = None
            self._running = False
            self._paused = False

            self._timer = QTimer(self)
            self._timer.setInterval(self._interval_ms)
            self._timer.setTimerType(Qt.TimerType.PreciseTimer)
            self._timer.timeout.connect(self._tick)

        # ── Lifecycle ────────────────────────────────────────────────────────
        def start(self) -> None:
            """Start the backend and begin polling."""
            if self._running:
                return
            self._backend.start()
            self._running = True
            self._paused = False
            self._machine.reset()
            self._timer.start(self._interval_ms)

        def stop(self) -> None:
            """Stop polling and release the backend."""
            self._timer.stop()
            self._running = False
            self._paused = False
            self._backend.stop()

        def pause(self) -> None:
            """Suspend polling without releasing the backend (e.g. during a launch)."""
            if not self._running or self._paused:
                return
            self._paused = True
            self._timer.stop()

        def resume(self) -> None:
            """Resume polling after :meth:`pause`."""
            if not self._running or not self._paused:
                return
            self._paused = False
            # Drop any state latched before the pause so a stick still held does
            # not immediately auto-repeat on resume.
            self._machine.reset()
            self._timer.start(self._interval_ms)

        @property
        def running(self) -> bool:
            return self._running

        @property
        def paused(self) -> bool:
            return self._paused

        # ── Routing ──────────────────────────────────────────────────────────
        def set_target(self, widget) -> None:
            """Set an explicit routing target, overriding the active-window lookup."""
            self._target = widget

        def _resolve_target(self):
            if self._target is not None:
                return self._target
            app = QApplication.instance()
            if app is None:
                return None
            return (
                QApplication.activeModalWidget()
                or QApplication.activePopupWidget()
                or QApplication.activeWindow()
            )

        def route_action(self, event: ActionEvent):
            """Emit ``event`` and record the surface it is destined for."""
            self.action.emit(event)
            self._last_target = self._resolve_target()
            return self._last_target

        # ── Timer tick ───────────────────────────────────────────────────────
        @staticmethod
        def _now_ms() -> float:
            return time.monotonic() * 1000.0

        def _tick(self) -> None:
            if self._paused or not self._running:
                return
            state = self._backend.poll()
            for event in self._machine.update(state, self._now_ms()):
                self.route_action(event)

else:  # pragma: no cover - stub used only when PySide6 is unavailable

    class ControllerRouter:  # type: ignore[no-redef]
        """Placeholder raised when PySide6 is not installed."""

        def __init__(self, *args, **kwargs) -> None:
            raise RuntimeError("ControllerRouter requires PySide6, which is not installed")
