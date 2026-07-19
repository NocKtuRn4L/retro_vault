"""SDL/pygame-ce controller backend.

Implements the :class:`~retrovault.input.backend.Backend` protocol on top of
``pygame-ce``. It is deliberately *passive*: it holds no thread and does no work
unless :meth:`SdlBackend.poll` is called. The owner (the input router) MUST stop
polling this backend while an emulator session is active, so RetroVault and the
launched emulator never fight over the same controller.

``pygame`` is imported lazily *inside* methods, never at module import time, so
this module imports cleanly on machines (and in CI/packaging) where pygame-ce is
not installed. When pygame is unavailable :meth:`SdlBackend.start` degrades
gracefully: it logs a warning, stays disconnected, and :meth:`poll` returns
:data:`~retrovault.input.backend.NEUTRAL_STATE`.

Two SDL details that are easy to get wrong and were the cause of "the controller
does nothing":

1. **The event queue must be pumped for input state to update.** SDL only
   refreshes joystick/controller button and axis values while the event queue is
   processed (``pygame.event.pump``/``get``). That in turn requires SDL's *video*
   subsystem to be initialized. We do NOT want a visible window, so we force the
   **dummy video driver** (``SDL_VIDEODRIVER=dummy``) before init: events pump,
   input updates, and no window ever appears. Without this, every read returns a
   frozen neutral state and the controller looks dead.

2. **Not every pad exposes a D-pad hat.** A Nintendo Switch Pro Controller, for
   example, reports zero hats and puts the D-pad on buttons, with a Nintendo
   face-button layout that does not match a raw Xbox button-index guess. So the
   primary path uses SDL's **GameController** API
   (``pygame._sdl2.controller``), whose community mapping database normalizes
   Xbox / PlayStation / Switch pads to the same semantic buttons (including the
   D-pad and a position-correct A=south face button). Devices SDL does not
   recognize as game controllers fall back to the raw joystick mapping in the
   pure :func:`normalize_state` helper.
"""

import logging
import os
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

# Raw-joystick fallback: SDL2 default game-controller button indices for a
# typical Xbox-style pad -> semantic button names. Only used for devices SDL
# does not recognize as game controllers.
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

# SDL GameController axis full-scale (Sint16) used to normalize sticks to [-1, 1].
_AXIS_FULL_SCALE = 32767.0

# Rescan every N poll() calls to catch adds/removes the event queue may miss.
_RESCAN_EVERY = 120


def _controller_button_map(pygame) -> dict[int, str]:
    """Build the SDL GameController button-constant -> semantic-name mapping.

    Uses ``pygame.CONTROLLER_BUTTON_*`` constants so the D-pad (which many pads,
    e.g. the Switch Pro Controller, expose as buttons rather than a hat) and the
    face buttons map correctly regardless of the pad's brand. SDL maps
    ``CONTROLLER_BUTTON_A`` to the physical south (bottom) face button on every
    controller, so south stays "accept" across Xbox/PlayStation/Switch.
    """
    return {
        pygame.CONTROLLER_BUTTON_A: BTN_FACE_SOUTH,
        pygame.CONTROLLER_BUTTON_B: BTN_FACE_EAST,
        pygame.CONTROLLER_BUTTON_X: BTN_FACE_WEST,
        pygame.CONTROLLER_BUTTON_Y: BTN_FACE_NORTH,
        pygame.CONTROLLER_BUTTON_LEFTSHOULDER: BTN_SHOULDER_L,
        pygame.CONTROLLER_BUTTON_RIGHTSHOULDER: BTN_SHOULDER_R,
        pygame.CONTROLLER_BUTTON_BACK: BTN_BACK,
        pygame.CONTROLLER_BUTTON_START: BTN_START,
        pygame.CONTROLLER_BUTTON_DPAD_UP: BTN_DPAD_UP,
        pygame.CONTROLLER_BUTTON_DPAD_DOWN: BTN_DPAD_DOWN,
        pygame.CONTROLLER_BUTTON_DPAD_LEFT: BTN_DPAD_LEFT,
        pygame.CONTROLLER_BUTTON_DPAD_RIGHT: BTN_DPAD_RIGHT,
    }


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
        self._controller_mod = None  # pygame._sdl2.controller module, or None
        self._controller = None  # an open GameController, or None
        self._controller_index = None  # device index of the open controller, or None
        self._button_map: dict[int, str] = {}  # controller-button const -> name
        self._joystick = None  # raw-joystick fallback handle, or None
        self._started = False
        self._rescan_every = max(1, rescan_every)
        self._poll_count = 0

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def start(self) -> None:
        """Initialize SDL for controller input without opening a visible window.

        Forces the dummy video driver so the event queue can be pumped (required
        for input state to update) while no window is ever shown. If pygame-ce is
        not installed, logs a warning and stays disconnected; the backend then
        behaves like a null backend.
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
        # Force a headless video driver BEFORE init so SDL can run its event
        # queue (needed for input updates) without ever creating a window.
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        # Without a focused SDL window, Windows/SDL otherwise DROP all joystick
        # input; this hint tells SDL to keep delivering controller events even
        # though we never show a window. Required for the pad to work at all.
        os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")
        try:
            pygame.display.init()
        except Exception:  # pragma: no cover - defensive; input may still work
            logger.debug("pygame.display.init failed", exc_info=True)
        pygame.joystick.init()
        try:
            from pygame._sdl2 import controller

            controller.init()
            self._controller_mod = controller
            self._button_map = _controller_button_map(pygame)
        except Exception:  # pragma: no cover - fall back to raw joystick
            logger.debug("SDL GameController API unavailable", exc_info=True)
            self._controller_mod = None
        self._started = True
        self._open_first_device()

    def stop(self) -> None:
        """Release any open device and quit the SDL input subsystems."""
        for handle in (self._controller, self._joystick):
            try:
                if handle is not None:
                    handle.quit()
            except Exception:  # pragma: no cover - defensive cleanup
                logger.debug("error quitting input device", exc_info=True)
        self._controller = None
        self._controller_index = None
        self._joystick = None
        if self._controller_mod is not None:
            try:
                self._controller_mod.quit()
            except Exception:  # pragma: no cover - defensive cleanup
                logger.debug("error quitting controller subsystem", exc_info=True)
        if self._pygame is not None:
            try:
                self._pygame.joystick.quit()
            except Exception:  # pragma: no cover - defensive cleanup
                logger.debug("error quitting joystick subsystem", exc_info=True)
        self._started = False

    # ── device management ─────────────────────────────────────────────────────
    def _open_first_device(self) -> None:
        """Open the first connected device, preferring the GameController API.

        Devices SDL recognizes as game controllers are opened via the
        GameController API (normalized mapping). Anything else falls back to the
        raw joystick handle.
        """
        if self._pygame is None or self._controller is not None or self._joystick is not None:
            return
        controller = self._controller_mod
        if controller is not None:
            try:
                for index in range(controller.get_count()):
                    if controller.is_controller(index):
                        self._controller = controller.Controller(index)
                        self._controller_index = index
                        return
            except Exception:  # pragma: no cover - defensive
                logger.debug("failed to open game controller", exc_info=True)
                self._controller = None
        # Fall back to a raw joystick for unrecognized devices.
        try:
            if self._pygame.joystick.get_count() > 0:
                joystick = self._pygame.joystick.Joystick(0)
                if not joystick.get_init():
                    joystick.init()
                self._joystick = joystick
        except Exception:  # pragma: no cover - defensive
            logger.debug("failed to open joystick", exc_info=True)
            self._joystick = None

    def rescan(self) -> None:
        """Re-detect devices: drop stale handles and (re)open a device.

        Safe to call at any time; used both on hotplug events and periodically
        from :meth:`poll` so reconnects are picked up without a restart.
        """
        if self._pygame is None:
            return
        if self._controller is not None:
            try:
                attached = self._controller.attached()
            except Exception:
                attached = False
            if not attached:
                self._controller = None
        if self._joystick is not None:
            try:
                attached = self._joystick.get_init() and self._joystick.get_instance_id() is not None
            except Exception:
                attached = False
            if not attached:
                self._joystick = None
        if self._controller is None and self._joystick is None:
            self._open_first_device()

    def is_connected(self) -> bool:
        """Return whether a controller or joystick is currently open."""
        return self._controller is not None or self._joystick is not None

    def controller_mapping(self) -> str | None:
        """Return the open GameController's SDL mapping string, or ``None``.

        The result is SDL's ``GUID,name,bindings`` form accepted by the
        ``SDL_GAMECONTROLLERCONFIG`` environment variable, so a launched
        SDL-based emulator can recognize the exact pad without the user mapping
        it by hand. Only the normalized GameController path exposes a mapping;
        the raw-joystick fallback and the no-pygame path return ``None``.
        Fail-soft: any error yields ``None`` and never raises.
        """
        pygame = self._pygame
        controller = self._controller
        if pygame is None or controller is None or self._controller_index is None:
            return None
        try:
            mapping = controller.get_mapping()
            if not mapping:
                return None
            guid = pygame.joystick.Joystick(self._controller_index).get_guid()
            name = getattr(controller, "name", "") or "Controller"
            bindings = ",".join(f"{key}:{value}" for key, value in mapping.items())
            return f"{guid},{name},{bindings},"
        except Exception:  # pragma: no cover - defensive; mapping is best-effort
            logger.debug("failed to read controller mapping", exc_info=True)
            return None

    # ── polling ───────────────────────────────────────────────────────────────
    def poll(self) -> BackendState:
        """Pump events and return the open device's normalized state.

        Cheap and non-blocking: it pumps the event queue (so SDL refreshes input
        state), reads the current device state, and returns. It never sleeps or
        spins. Returns :data:`NEUTRAL_STATE` when pygame is unavailable or no
        device is connected.
        """
        pygame = self._pygame
        if pygame is None:
            return NEUTRAL_STATE

        # Pumping the queue is what makes SDL refresh button/axis state; also
        # react to hotplug events. With the dummy video driver initialized in
        # start(), this succeeds without a window.
        try:
            events = pygame.event.get()
        except pygame.error:
            events = []
        added = {getattr(pygame, "CONTROLLERDEVICEADDED", -1), getattr(pygame, "JOYDEVICEADDED", -2)}
        removed = {getattr(pygame, "CONTROLLERDEVICEREMOVED", -3), getattr(pygame, "JOYDEVICEREMOVED", -4)}
        for event in events:
            if event.type in added and not self.is_connected():
                self._open_first_device()
            elif event.type in removed:
                self.rescan()

        # Periodic rescan to catch anything the event queue missed.
        self._poll_count += 1
        if self._poll_count % self._rescan_every == 0:
            self.rescan()

        if self._controller is not None:
            return self._read_controller()
        if self._joystick is not None:
            return self._read_joystick()
        return NEUTRAL_STATE

    def _read_controller(self) -> BackendState:
        """Read the open GameController via SDL's normalized button/axis API."""
        controller = self._controller
        pygame = self._pygame
        try:
            buttons = {
                name for const, name in self._button_map.items() if controller.get_button(const)
            }
            axis_x = controller.get_axis(pygame.CONTROLLER_AXIS_LEFTX) / _AXIS_FULL_SCALE
            axis_y = controller.get_axis(pygame.CONTROLLER_AXIS_LEFTY) / _AXIS_FULL_SCALE
        except Exception:
            # Controller likely disconnected mid-read; drop it and report neutral.
            self._controller = None
            return NEUTRAL_STATE
        return BackendState(buttons=frozenset(buttons), axes=(_clamp(axis_x), _clamp(axis_y)))

    def _read_joystick(self) -> BackendState:
        """Read the raw-joystick fallback and map it via :func:`normalize_state`."""
        joystick = self._joystick
        try:
            hat = joystick.get_hat(0) if joystick.get_numhats() > 0 else (0, 0)
            num_axes = joystick.get_numaxes()
            axes = [joystick.get_axis(i) for i in range(min(2, num_axes))]
            pressed = [i for i in range(joystick.get_numbuttons()) if joystick.get_button(i)]
        except Exception:
            self._joystick = None
            return NEUTRAL_STATE
        return normalize_state(hat, axes, pressed)
