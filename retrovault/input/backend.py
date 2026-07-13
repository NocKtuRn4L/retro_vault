"""Controller backend protocol, normalized state, and a null implementation.

The :class:`Backend` protocol describes a polling-based source of normalized
controller state. Concrete backends (e.g. an SDL/pygame backend in a later PR)
implement it; :class:`NullBackend` is the always-disconnected fallback that lets
RetroVault run with no controller and no SDL installed.

Semantic button names are module-level constants so later PRs (SDL backend,
router) reuse the exact same strings.
"""

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# ── Semantic button names ─────────────────────────────────────────────────────
# Backend-agnostic names for normalized buttons. Backends map their raw
# hardware buttons onto these; the router maps these onto semantic Actions.
BTN_DPAD_UP = "dpad_up"
BTN_DPAD_DOWN = "dpad_down"
BTN_DPAD_LEFT = "dpad_left"
BTN_DPAD_RIGHT = "dpad_right"
BTN_FACE_SOUTH = "face_south"  # bottom face button (A on Xbox, B/cross layout)
BTN_FACE_EAST = "face_east"    # right face button (B on Xbox)
BTN_FACE_WEST = "face_west"    # left face button (X on Xbox)
BTN_FACE_NORTH = "face_north"  # top face button (Y on Xbox)
BTN_SHOULDER_L = "shoulder_l"
BTN_SHOULDER_R = "shoulder_r"
BTN_START = "start"
BTN_BACK = "back"

# All recognized semantic button names, for validation/reuse by later PRs.
BUTTON_NAMES = frozenset(
    {
        BTN_DPAD_UP,
        BTN_DPAD_DOWN,
        BTN_DPAD_LEFT,
        BTN_DPAD_RIGHT,
        BTN_FACE_SOUTH,
        BTN_FACE_EAST,
        BTN_FACE_WEST,
        BTN_FACE_NORTH,
        BTN_SHOULDER_L,
        BTN_SHOULDER_R,
        BTN_START,
        BTN_BACK,
    }
)


@dataclass(frozen=True)
class BackendState:
    """A normalized snapshot of controller state.

    ``buttons`` holds the semantic names (see the ``BTN_*`` constants) that are
    currently pressed. ``axes`` is the left-stick ``(x, y)`` with each component
    normalized to ``[-1.0, 1.0]``.
    """

    buttons: frozenset[str] = field(default_factory=frozenset)
    axes: tuple[float, float] = (0.0, 0.0)


# A shared neutral state: disconnected/no-input snapshot.
NEUTRAL_STATE = BackendState()


@runtime_checkable
class Backend(Protocol):
    """A polling-based source of normalized controller state."""

    def poll(self) -> BackendState:
        """Return a snapshot of the current normalized state."""
        ...

    def is_connected(self) -> bool:
        """Return whether a controller is currently connected."""
        ...

    def start(self) -> None:
        """Begin polling / acquire resources. No-ops are allowed."""
        ...

    def stop(self) -> None:
        """Stop polling / release resources. No-ops are allowed."""
        ...


class NullBackend:
    """Always-disconnected backend that emits a neutral state.

    Lets RetroVault run with no controller and no SDL installed.
    """

    def poll(self) -> BackendState:
        return NEUTRAL_STATE

    def is_connected(self) -> bool:
        return False

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass
