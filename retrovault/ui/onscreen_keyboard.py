"""Controller-navigable on-screen keyboard.

Text entry (e.g. searching the library) needs characters, which a gamepad can't
provide directly. This modal dialog shows a grid of keys the controller drives:
Up/Down/Left/Right move the highlighted key, Accept presses it, Back is a quick
backspace, and Start confirms. The shoulder buttons are space/backspace
shortcuts. It follows the same ``handle_controller_action`` contract as the other
dialogs, so the main window's router delegates to it while it is the active
modal. It stays fully usable by mouse/touch (every key is a real button).

Search is case-insensitive, so the layout is lowercase letters + digits plus a
few editing keys; no shift is needed.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QGridLayout, QLabel, QPushButton, QVBoxLayout

from ..input.actions import Action

# Each key is (label, kind, value). kind drives behaviour on press.
_CHAR_ROWS = ["1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm"]
_SPECIAL_ROW = [
    ("SPACE", "space", " "),
    ("DEL", "del", None),
    ("CLEAR", "clear", None),
    ("DONE", "done", None),
    ("CANCEL", "cancel", None),
]


def _build_layout():
    rows = [[(ch, "char", ch) for ch in row] for row in _CHAR_ROWS]
    rows.append(list(_SPECIAL_ROW))
    return rows


class OnScreenKeyboard(QDialog):
    """A gamepad-navigable keyboard. After an accepted :meth:`exec`, :meth:`text`
    holds the entered string."""

    def __init__(self, initial_text="", parent=None, title="Text Entry"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self._text = initial_text or ""
        self._keys = _build_layout()
        self._buttons = []  # parallel 2D list of QPushButton
        self._row = 0
        self._col = 0

        layout = QVBoxLayout(self)
        self._heading = QLabel(title)
        self._heading.setProperty("role", "title")
        layout.addWidget(self._heading)

        self._preview = QLabel()
        self._preview.setObjectName("oskPreview")
        self._preview.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        layout.addWidget(self._preview)

        grid = QGridLayout()
        grid.setSpacing(4)
        for r, row in enumerate(self._keys):
            button_row = []
            for c, (label, kind, value) in enumerate(row):
                button = QPushButton(label)
                button.setObjectName("oskKey")
                button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
                button.clicked.connect(lambda _=False, k=(label, kind, value): self._press(k))
                grid.addWidget(button, r, c)
                button_row.append(button)
            self._buttons.append(button_row)
        layout.addLayout(grid)

        self._refresh_preview()
        self._focus_current()

    # ── text state ────────────────────────────────────────────────────────────
    def text(self):
        return self._text

    def _refresh_preview(self):
        self._preview.setText(self._text or "–")  # en dash placeholder when empty

    def _press(self, key):
        _label, kind, value = key
        if kind == "char":
            self._text += value
        elif kind == "space":
            self._text += " "
        elif kind == "del":
            self._text = self._text[:-1]
        elif kind == "clear":
            self._text = ""
        elif kind == "done":
            self.accept()
            return
        elif kind == "cancel":
            self.reject()
            return
        self._refresh_preview()

    def _backspace(self):
        self._text = self._text[:-1]
        self._refresh_preview()

    def _add_space(self):
        self._text += " "
        self._refresh_preview()

    # ── focus / navigation ──────────────────────────────────────────────────────
    def _focus_current(self):
        self._buttons[self._row][self._col].setFocus()

    def _move(self, d_row, d_col):
        if d_row:
            self._row = max(0, min(len(self._keys) - 1, self._row + d_row))
            # Clamp the column into the (possibly shorter) target row.
            self._col = min(self._col, len(self._keys[self._row]) - 1)
        if d_col:
            self._col = max(0, min(len(self._keys[self._row]) - 1, self._col + d_col))
        self._focus_current()

    def _current_key(self):
        return self._keys[self._row][self._col]

    def handle_controller_action(self, event) -> bool:
        """Drive the keyboard from a semantic controller action (PR9 contract)."""
        action = event.action
        if action is Action.UP:
            self._move(-1, 0)
        elif action is Action.DOWN:
            self._move(1, 0)
        elif action is Action.LEFT:
            self._move(0, -1)
        elif action is Action.RIGHT:
            self._move(0, 1)
        elif action is Action.ACCEPT:
            self._press(self._current_key())
        elif action is Action.BACK:
            self._backspace()  # quick backspace; CANCEL key dismisses the dialog
        elif action is Action.MENU:
            self.accept()  # Start confirms
        elif action is Action.PREV_SYSTEM:
            self._backspace()  # shoulder shortcut
        elif action is Action.NEXT_SYSTEM:
            self._add_space()  # shoulder shortcut
        else:
            return False
        return True
