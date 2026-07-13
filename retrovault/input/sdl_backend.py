"""SDL/pygame-ce controller backend.

Implements the :class:`~retrovault.input.backend.Backend` protocol on top of
``pygame-ce``'s joystick API. It is deliberately *passive*: it holds no thread
and does no work unless :meth:`SdlBackend.poll` is called. The owner (the input
router) MUST stop polling this backend while an emulator session is active, so
RetroVault and the launched emulator never fight over the same controller.

``pygame`` is imported lazily *inside* methods, never at module import time, so
this module imports cleanly on machines (and in CI/packaging) where pygame-ce is
not installed. When pygame is unavailable :meth:`SdlBackend.start` degrades
gracefully: it logs a warning, stays disconnected, and :meth:`poll` returns
:data:`~retrovault.input.backend.NEUTRAL_STATE`.

The raw-to-semantic mapping is factored into the pure :func:`normalize_state`
function so it can be unit-tested with plain Python values and no real hardware.

Button-index mapping targets the SDL2 default game-controller layout for a
typical Xbox-style pad:

    0 -> A  (FACE_SOUTH)      4 -> Left shoulder  (SHOULDER_L)
    1 -> B  (FACE_EAST)       5 -> Right shoulder (SHOULDER_R)
    2 -> X  (FACE_WEST)       6 -> Back           (BACK)
    3 -> Y  (FACE_NORTH)      7 -> Start          (START)
"""

import logging
from collections.abc import Iterable

from .backend import (
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
    BackendState,
)

logger = logging.getLogger(__name__)

# SDL2 default game-controller button indices -> semantic button names.
_BUTTON_MAP: dict[int, str] = {
    0: BTN_FACE_SOUTH,
    1: BTN_FACE_EAST,
    2: BTN_FACE_WEST,
    3: BTN_FACE_NORTH,
    4: BTN_SHOULDER_L,
    5: BTN_SHOULDER_R,
    6: BTN_BACK,
    7: BTN_START,
}

# Rescan every N poll() calls to catch adds/removes the event queue may miss.
_RESCAN_EVERY = 120


def _clamp(value: float) -> float:
    """Clamp ``value`` into the closed interval [-1.0, 1.0]."""
    if value < -1.0:
        return -1.0
    if value > 1.0:
        return 1.0
    return value


def normalize_state(
    hat: tuple[int, int],
    axes: Iterable[float],
    pressed_buttons: Iterable[int],
) -> BackendState:
    """Map raw controller readings onto a normalized :class:`BackendState`.

    This is a pure function: it takes plain Python values (no pygame objects),
    so mapping can be unit-tested without any real controller.

    Args:
        hat: The primary hat ``(x, y)`` as reported by SDL/pygame. SDL hat
            coordinates use ``x = -1`` left / ``+1`` right and, importantly,
            ``y = +1`` UP / ``-1`` DOWN (screen-inverted vs. the analog stick).
        axes: The joystick axis values; index 0 is left-stick X and index 1 is
            left-stick Y. Values are clamped to ``[-1.0, 1.0]``.
        pressed_buttons: The raw button indices currently held down; each is
            translated via the SDL2 default game-controller mapping.

    Returns:
        A :class:`BackendState` with the semantic buttons and the left-stick
        ``(x, y)`` axes.
    """
    buttons: set[str] = set()

    hat_x, hat_y = hat
    if hat_x < 0:
        buttons.add(BTN_DPAD_LEFT)
    elif hat_x > 0:
        buttons.add(BTN_DPAD_RIGHT)
    # SDL hat y is +1 for UP and -1 for DOWN.
    if hat_y > 0:
        buttons.add(BTN_DPAD_UP)
    elif hat_y < 0:
        buttons.add(BTN_DPAD_DOWN)

    for index in pressed_buttons:
        name = _BUTTON_MAP.get(index)
        if name is not None:
            buttons.add(name)

    axis_list = list(axes)
    axis_x = _clamp(axis_list[0]) if len(axis_list) > 0 else 0.0
    axis_y = _clamp(axis_list[1]) if len(axis_list) > 1 else 0.0

    return BackendState(buttons=frozenset(buttons), axes=(axis_x, axis_y))


class SdlBackend:
    """Passive SDL/pygame-ce controller backend.

    Reads controller state only when :meth:`poll` is called; it never runs a
    background thread. The router that owns this backend MUST stop calling
    :meth:`poll` while an emulator session is active so the two processes do not
    contend for the same physical controller.
    """

    def __init__(self, rescan_every: int = _RESCAN_EVERY) -> None:
        self._pygame = None  # lazily-imported pygame module, or None if absent
        self._joystick = None  # the currently open joystick, or None
        self._started = False
        self._rescan_every = max(1, rescan_every)
        self._poll_count = 0

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def start(self) -> None:
        """Initialize the joystick subsystem and open any connected controller.

        Does NOT open a display/window. If pygame-ce is not installed, logs a
        warning and stays disconnected; the backend then behaves like a null
        backend.
        """
        if self._started:
            return
        try:
            import pygame
        except ImportError:
            logger.warning("pygame-ce is not installed; SDL backend disabled")
            self._pygame = None
            self._started = True
            return

        self._pygame = pygame
        # Init ONLY the joystick subsystem — no display/window is created.
        pygame.joystick.init()
        self._started = True
        self._open_first_joystick()

    def stop(self) -> None:
        """Release the joystick and quit the joystick subsystem."""
        if self._joystick is not None:
            try:
                self._joystick.quit()
            except Exception:  # pragma: no cover - defensive cleanup
                logger.debug("error quitting joystick", exc_info=True)
        self._joystick = None
        if self._pygame is not None:
            try:
                self._pygame.joystick.quit()
            except Exception:  # pragma: no cover - defensive cleanup
                logger.debug("error quitting joystick subsystem", exc_info=True)
        self._started = False

    # ── device management ─────────────────────────────────────────────────────
    def _open_first_joystick(self) -> None:
        """Open the first available joystick, if any and none is open yet."""
        if self._pygame is None or self._joystick is not None:
            return
        try:
            count = self._pygame.joystick.get_count()
        except Exception:  # pragma: no cover - defensive
            return
        if count <= 0:
            return
        try:
            joystick = self._pygame.joystick.Joystick(0)
            # pygame-ce auto-initializes Joystick objects; only call init() on
            # older builds that construct them uninitialized (avoids a
            # deprecation warning on 2.4+).
            if not joystick.get_init():
                joystick.init()
            self._joystick = joystick
        except Exception:  # pragma: no cover - defensive
            logger.debug("failed to open joystick", exc_info=True)
            self._joystick = None

    def rescan(self) -> None:
        """Re-detect controllers: drop a stale handle and (re)open a device.

        Safe to call at any time; used both on hotplug events and periodically
        from :meth:`poll` so reconnects are picked up without a restart.
        """
        if self._pygame is None:
            return
        # Drop a joystick that is no longer attached.
        if self._joystick is not None:
            try:
                attached = self._joystick.get_init() and self._joystick.get_instance_id() is not None
            except Exception:
                attached = False
            if not attached:
                self._joystick = None
        if self._joystick is None:
            self._open_first_joystick()

    def is_connected(self) -> bool:
        """Return whether at least one controller is currently open."""
        return self._joystick is not None

    # ── polling ───────────────────────────────────────────────────────────────
    def poll(self) -> BackendState:
        """Pump events and return the first controller's normalized state.

        Cheap and non-blocking: it pumps the event queue, reads the current
        controller state, and returns. It never sleeps or spins. Returns
        :data:`NEUTRAL_STATE` when pygame is unavailable or no controller is
        connected.
        """
        pygame = self._pygame
        if pygame is None:
            return NEUTRAL_STATE

        # Pump the event queue and react to hotplug events. The event
        # subsystem may be unavailable when only the joystick subsystem was
        # initialized (no display/window is opened by design); in that case we
        # skip event handling and rely on the periodic rescan below. Joystick
        # state can still be read directly.
        try:
            events = pygame.event.get()
        except pygame.error:
            events = []
        for event in events:
            etype = event.type
            if etype == pygame.JOYDEVICEADDED:
                if self._joystick is None:
                    self._open_first_joystick()
            elif etype == pygame.JOYDEVICEREMOVED:
                self.rescan()

        # Periodic rescan to catch anything the event queue missed.
        self._poll_count += 1
        if self._poll_count % self._rescan_every == 0:
            self.rescan()

        joystick = self._joystick
        if joystick is None:
            return NEUTRAL_STATE

        try:
            hat = joystick.get_hat(0) if joystick.get_numhats() > 0 else (0, 0)
            num_axes = joystick.get_numaxes()
            axes = [joystick.get_axis(i) for i in range(min(2, num_axes))]
            pressed = [i for i in range(joystick.get_numbuttons()) if joystick.get_button(i)]
        except Exception:
            # Controller likely disconnected mid-read; drop it and report neutral.
            self._joystick = None
            return NEUTRAL_STATE

        return normalize_state(hat, axes, pressed)
