"""Reusable controller-navigation helpers for modal dialogs (PR9).

Controller input flows through :class:`MainWindow._on_controller_action`. While
a modal dialog is open, ``MainWindow`` delegates each :class:`ActionEvent` to the
active modal via a ``handle_controller_action`` method (the *contract* below).
This module provides the small, generic building blocks each dialog handler is
built from so the per-dialog code stays tiny.

Contract — ``handle_controller_action(self, event) -> bool``:
    A dialog that wants controller support implements this method. It receives
    the same :class:`retrovault.input.actions.ActionEvent` the main window would,
    maps it onto focus movement / activation / tab switching using the helpers
    here, and returns ``True`` when the event was consumed (``False`` for a
    no-op, e.g. ``MENU`` inside a dialog). ``MainWindow`` returns immediately
    after delegating regardless of the boolean — the dialog owns input while it
    is open — but the return value keeps handlers honest and is convenient in
    tests.

Focus trap: navigation uses ``focusNextChild`` / ``focusPreviousChild``, which
Qt restricts to enabled, focusable widgets. Disabled controls (e.g. an INSTALL
button with no available strategy) are skipped automatically, so a controller
can never land on — or activate — an unavailable control.

Qt is a hard dependency of RetroVault, so the imports below are plain. They are
kept module-local (not re-exported) to mirror the rest of ``retrovault.ui``.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QPushButton, QTabWidget, QWidget


def make_focusable(*widgets: QWidget) -> None:
    """Give each widget strong keyboard focus so controller nav can reach it.

    Buttons default to click focus on some platforms/styles, which excludes them
    from ``focusNextChild`` traversal. Setting ``Qt.StrongFocus`` opts them in.
    ``None`` entries are ignored so callers can pass optional widgets directly.
    """
    for widget in widgets:
        if widget is not None:
            widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)


def move_focus(widget: QWidget, forward: bool):
    """Move keyboard focus to the next/previous focusable child.

    Delegates to ``focusNextChild`` / ``focusPreviousChild`` on ``widget`` (a
    container such as the dialog itself). Qt skips disabled and non-focusable
    widgets, which gives the focus trap for free. Returns the newly focused
    widget (``QApplication.focusWidget()`` after the move), or ``None``.
    """
    if forward:
        widget.focusNextChild()
    else:
        widget.focusPreviousChild()
    from PySide6.QtWidgets import QApplication

    return QApplication.focusWidget()


def activate_focused(widget: QWidget) -> bool:
    """"Press" the currently focused control within ``widget``'s window.

    - ``QPushButton``: animate a click (only if enabled).
    - ``QCheckBox``: toggle checked state.
    - ``QComboBox``: open the popup so the user can pick with UP/DOWN.
    - anything else: no-op.

    Returns ``True`` if something was activated, ``False`` otherwise.
    """
    from PySide6.QtWidgets import QApplication

    focused = QApplication.focusWidget()
    if focused is None:
        return False
    if isinstance(focused, QPushButton):
        if not focused.isEnabled():
            return False
        # .click() (not .animateClick()) so the effect is synchronous — no
        # timer, so a controller press is handled immediately and tests stay
        # deterministic.
        focused.click()
        return True
    if isinstance(focused, QCheckBox):
        focused.toggle()
        return True
    if isinstance(focused, QComboBox):
        focused.showPopup()
        return True
    return False


def switch_tab(tab_widget: QTabWidget, delta: int) -> int:
    """Change a ``QTabWidget``'s current index by ``delta``, clamped.

    Returns the resulting current index (unchanged if there are no tabs).
    """
    count = tab_widget.count()
    if count == 0:
        return tab_widget.currentIndex()
    target = max(0, min(count - 1, tab_widget.currentIndex() + delta))
    tab_widget.setCurrentIndex(target)
    return target
