"""Controller-navigable main menu.

The library's top bar (Scan ROMs, Add ROM Folder, Setup, Settings, ...) is only
reachable with a mouse/keyboard. On a Pi or couch/kiosk setup with just a
gamepad there would otherwise be no way to trigger those actions, so the MENU
button (Start) opens this dialog: a simple vertical list the controller can
navigate with Up/Down, activate with Accept, and dismiss with Back/Menu.

It follows the same ``handle_controller_action`` contract as the other dialogs
(see :mod:`retrovault.ui.controller_nav`), so the main window's controller
router delegates to it automatically while it is the active modal.
"""

from PySide6.QtWidgets import QDialog, QLabel, QListWidget, QVBoxLayout

from ..input.actions import Action


class MainMenuDialog(QDialog):
    """A gamepad-navigable list of the library's top-bar actions.

    Constructed with a list of string labels; after :meth:`exec` returns
    ``Accepted``, :attr:`chosen_index` holds the selected row (``-1`` if the
    dialog was dismissed without a choice).
    """

    def __init__(self, labels, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Menu")
        self.setModal(True)
        self.chosen_index = -1

        layout = QVBoxLayout(self)
        heading = QLabel("MENU")
        heading.setProperty("role", "title")
        layout.addWidget(heading)

        self.list = QListWidget()
        self.list.setObjectName("menuList")
        self.list.addItems(list(labels))
        if self.list.count():
            self.list.setCurrentRow(0)
        # Mouse double-click / Enter also choose, so it stays usable by hand.
        self.list.itemActivated.connect(lambda *_: self._choose())
        layout.addWidget(self.list)
        self.list.setFocus()

    def _choose(self):
        self.chosen_index = self.list.currentRow()
        self.accept()

    def _move(self, delta):
        count = self.list.count()
        if count == 0:
            return
        current = self.list.currentRow()
        base = current if current >= 0 else 0
        self.list.setCurrentRow(max(0, min(count - 1, base + delta)))

    def handle_controller_action(self, event) -> bool:
        """Drive the menu from a semantic controller action (PR9 contract)."""
        action = event.action
        if action is Action.UP:
            self._move(-1)
        elif action is Action.DOWN:
            self._move(1)
        elif action is Action.ACCEPT:
            self._choose()
        elif action in (Action.BACK, Action.MENU):
            self.reject()
        else:
            return False
        return True
