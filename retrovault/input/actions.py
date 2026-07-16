"""Semantic navigation actions and the emitted action-event value type.

This module defines the *contract* that controller input is normalized into.
Backends (see ``backend.py``) emit raw button/axis state; a later router PR
translates that state into :class:`ActionEvent` instances carrying an
:class:`Action`. The held-direction auto-repeat logic itself belongs to the
router; only the data types live here.
"""

import enum
from dataclasses import dataclass


class Action(enum.Enum):
    """Semantic navigation actions used across the UI, backend-agnostic."""

    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    ACCEPT = "accept"
    BACK = "back"
    MENU = "menu"
    PREV_SYSTEM = "previous_system"
    NEXT_SYSTEM = "next_system"


@dataclass(frozen=True)
class ActionEvent:
    """An emitted action signal.

    ``repeat`` is ``True`` when the event was produced by auto-repeat (a held
    direction) rather than an initial press.
    """

    action: Action
    repeat: bool = False
