"""PySide6 main window for RetroVault."""

import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..core.config import load_config, save_config
from ..core.launch import launch_rom
from ..core.library import (
    load_collections,
    load_library,
    merge_scan,
    save_collections,
    save_library,
    scan_roms,
)
from ..input.actions import Action, ActionEvent
from ..input.backend import Backend, NullBackend
from ..input.router import ControllerRouter, InputStateMachine
from ..input.sdl_backend import SdlBackend
from .detail_panel import DetailPanel
from .launch_overlay import MIN_PLAY_SECONDS, LaunchCoordinator
from .library_model import (
    BOXART_THUMB,
    RECENT_FILTER,
    LibraryFilterProxyModel,
    LibraryModel,
)
from .main_menu import MainMenuDialog
from .onscreen_keyboard import OnScreenKeyboard
from .scrape_worker import ScrapeWorker
from .settings_dialog import SettingsDialog
from .setup_wizard import SetupWizard

logger = logging.getLogger(__name__)

# Delay before the controller resumes polling after an emulator exits. resume()
# already resets the input state machine, but a physical button may still be held
# as the emulator closes; this debounce prevents an instant relaunch loop.
CONTROLLER_RESUME_DEBOUNCE_MS = 400


class WorkerThread(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, *args, parent=None):
        super().__init__(parent)
        self.fn = fn
        self.args = args

    def run(self):
        try:
            self.succeeded.emit(self.fn(*self.args))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RetroVault")
        self.resize(1100, 700)
        self.setMinimumSize(800, 550)

        self.config_data = load_config()
        self.library = load_library()
        self._workers = []

        # Window-mode policy (PR7). Applied by app.main after construction, not
        # here, so tests and dev runs stay windowed unless asked.
        self._window_mode = "desktop"
        self._kiosk = False

        # Controller integration. `controller` always exists as an attribute so
        # closeEvent/handlers can reference it unconditionally; the real stack is
        # built at the end of __init__ inside a try/except.
        self.controller = None
        self._controller_busy = False
        self._menu_open = False
        # Which column controller Up/Down navigates: "systems" or "games".
        self._nav_column = "games"

        # Launch-session integration (PR10). Built after the controller below.
        self.launch_coordinator = None
        self._saved_rom_path = None
        self._saved_scroll = None
        # A subtle audible "return" cue when an emulator exits. Off by default so
        # headless/CI runs stay silent; flip to True for a couch-console beep.
        self._return_cue_enabled = False

        central = QWidget()
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_top_bar())
        root_layout.addWidget(self._build_divider())
        root_layout.addLayout(self._build_body(), 1)

        self.setCentralWidget(central)
        self._build_status_bar()
        self._build_shortcuts()
        self._refresh_sidebar()
        self._refresh_empty_state()

        self._build_controller()
        self._build_launch_coordinator()

    def maybe_prompt_first_run_setup(self):
        """Open the setup wizard shortly after launch if setup is incomplete.

        Deliberately NOT called from ``__init__``: a constructor must not schedule
        a modal side effect, or merely building a window (as tests do) would pop
        the wizard and, under a running event loop, hang. The real GUI entry point
        (:func:`retrovault.ui.app.main`) calls this after the window is shown.
        """
        if not self.config_data.get("setup", {}).get("completed", False):
            QTimer.singleShot(250, self.on_setup)

    def _build_launch_coordinator(self):
        """Create the single per-window launch coordinator, tolerating failure.

        Wires the overlay + launch session into the window: ``save_view`` /
        ``restore_view`` snapshot and restore the selected ROM and scroll
        position, and the coordinator's signals drive controller suspend/resume,
        control disabling, foreground restore, and the launch-failed dialog. A
        construction failure must never crash the UI, so it is guarded.
        """
        try:
            self.launch_coordinator = LaunchCoordinator(
                self,
                save_view=self._save_launch_view,
                restore_view=self._restore_launch_view,
                parent=self,
            )
            self.launch_coordinator.input_disabled.connect(self._on_launch_input_disabled)
            self.launch_coordinator.finished.connect(self._on_launch_session_finished)
            self.launch_coordinator.session_finished.connect(self._on_play_session_finished)
            self.launch_coordinator.failed.connect(self._on_launch_session_failed)
        except Exception as exc:  # pragma: no cover - defensive; never crash UI
            logger.warning("Launch coordinator disabled: %s: %s", type(exc).__name__, exc)
            self.launch_coordinator = None

    def _make_controller_backend(self) -> Backend:
        """Return the controller backend for this window.

        Isolated so tests can monkeypatch it to return a :class:`NullBackend`
        and never touch pygame/SDL or real hardware.
        """
        if self.config_data.get("controller", {}).get("enabled", True):
            return SdlBackend()
        return NullBackend()

    def _build_controller(self):
        """Build and start the controller stack, tolerating any failure.

        A controller/backend problem must never crash the UI, so the whole
        stack is created inside a try/except that logs and leaves
        ``self.controller`` as ``None``.
        """
        try:
            backend = self._make_controller_backend()
            machine = InputStateMachine.from_config(self.config_data["controller"])
            self.controller = ControllerRouter(backend, machine, parent=self)
            self.controller.action.connect(self._on_controller_action)
            self.controller.start()
        except Exception as exc:  # pragma: no cover - defensive; never crash UI
            logger.warning("Controller input disabled: %s: %s", type(exc).__name__, exc)
            self.controller = None

    def _build_top_bar(self):
        top_bar = QWidget()
        layout = QHBoxLayout(top_bar)
        layout.setContentsMargins(20, 10, 16, 10)
        layout.setSpacing(10)

        title_label = QLabel("> RETROVAULT")
        title_label.setProperty("role", "title")
        layout.addWidget(title_label)

        self.search_box = QLineEdit()
        self.search_box.setObjectName("searchBox")
        self.search_box.setPlaceholderText("Search games...")
        self.search_box.setFixedWidth(280)
        self.search_box.textChanged.connect(self._on_search_changed)
        layout.addWidget(self.search_box)

        layout.addStretch(1)

        add_rom_dir_btn = QPushButton("+ ADD ROM DIR")
        add_rom_dir_btn.clicked.connect(self.on_add_rom_dir)
        layout.addWidget(add_rom_dir_btn)

        setup_btn = QPushButton("SETUP")
        setup_btn.clicked.connect(self.on_setup)
        layout.addWidget(setup_btn)

        settings_btn = QPushButton("SETTINGS")
        settings_btn.clicked.connect(self.on_settings)
        layout.addWidget(settings_btn)

        self.scrape_btn = QPushButton("SCRAPE ART")
        self.scrape_btn.clicked.connect(self.on_scrape_artwork)
        layout.addWidget(self.scrape_btn)

        self.scan_btn = QPushButton("SCAN ROMS")
        self.scan_btn.setProperty("accent", "true")
        self.scan_btn.clicked.connect(self.on_scan_roms)
        layout.addWidget(self.scan_btn)

        return top_bar

    def _build_divider(self):
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(2)
        divider.setStyleSheet("background-color: #ff3c3c; border: none;")
        return divider

    def _build_body(self):
        body_layout = QHBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(190)
        self.sidebar.currentItemChanged.connect(self._on_sidebar_changed)
        body_layout.addWidget(self.sidebar)

        vdivider = QFrame()
        vdivider.setFrameShape(QFrame.Shape.VLine)
        vdivider.setFixedWidth(1)
        vdivider.setStyleSheet("background-color: #2a2a2a; border: none;")
        body_layout.addWidget(vdivider)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(16, 16, 16, 16)

        self.model = LibraryModel(self.library, self.config_data.get("systems", {}), self)
        self.proxy = LibraryFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.sort(0, Qt.SortOrder.AscendingOrder)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setIconSize(BOXART_THUMB)  # room for box-art thumbnails
        self.table.setWordWrap(False)  # single-line names; uniform rows
        self.table.verticalHeader().setDefaultSectionSize(BOXART_THUMB.height() + 6)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.doubleClicked.connect(lambda _index: self.on_launch_selected())
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._open_context_menu)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        content_layout.addWidget(self.table, 1)

        self.placeholder_label = QLabel(
            "No ROMs in library.\n"
            "Click '+ ADD ROM DIR' to add a folder,\n"
            "then 'SCAN ROMS'."
        )
        self.placeholder_label.setProperty("role", "subtext")
        self.placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(self.placeholder_label, 1)

        # Game detail panel (PR #2b): the games table and the collapsible detail
        # panel share a horizontal splitter so the user can resize/hide the panel.
        self.detail_panel = DetailPanel(self.config_data.get("systems", {}), self)
        self.body_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.body_splitter.addWidget(content)
        self.body_splitter.addWidget(self.detail_panel)
        self.body_splitter.setStretchFactor(0, 1)
        self.body_splitter.setStretchFactor(1, 0)
        self.body_splitter.setCollapsible(0, False)
        self.body_splitter.setCollapsible(1, True)
        self.body_splitter.setSizes([760, 300])
        body_layout.addWidget(self.body_splitter, 1)

        # Update the panel whenever the selected ROM changes. Drive it off
        # selectionChanged (what _selected_rom reads) as well as currentRowChanged:
        # after a model reset the current index and the selection can diverge, so
        # currentRowChanged alone would leave the panel showing a stale game.
        self.table.selectionModel().currentRowChanged.connect(
            lambda *_: self._update_detail_panel()
        )
        self.table.selectionModel().selectionChanged.connect(
            lambda *_: self._update_detail_panel()
        )
        self._update_detail_panel()

        # Simple show/hide toggle for the detail panel (Ctrl+D).
        detail_toggle = QShortcut(QKeySequence("Ctrl+D"), self)
        detail_toggle.activated.connect(
            lambda: self.detail_panel.setVisible(not self.detail_panel.isVisible())
        )

        return body_layout

    def _update_detail_panel(self):
        """Refresh the detail panel for the currently selected ROM (PR #2b)."""
        if hasattr(self, "detail_panel"):
            self.detail_panel.update_for(self._selected_rom())

    def _build_status_bar(self):
        self.statusBar().showMessage("Welcome to RetroVault")
        self.count_label = QLabel("")
        self.count_label.setObjectName("countLabel")
        self.statusBar().addPermanentWidget(self.count_label)
        self._update_count_label()

    def _build_shortcuts(self):
        focus_search = QShortcut(QKeySequence("Ctrl+F"), self)
        focus_search.activated.connect(self._focus_search)
        launch_selected = QShortcut(QKeySequence(Qt.Key.Key_Return), self)
        launch_selected.activated.connect(self.on_launch_selected)
        launch_selected_enter = QShortcut(QKeySequence(Qt.Key.Key_Enter), self)
        launch_selected_enter.activated.connect(self.on_launch_selected)

    def _focus_search(self):
        self.search_box.setFocus()
        self.search_box.selectAll()

    # ── Window-mode policy (PR7) ─────────────────────────────────────────────
    def apply_window_mode(self, mode: str | None = None):
        """Apply a window-mode policy and show the window accordingly.

        ``mode`` is one of ``"desktop"``, ``"fullscreen"``, or ``"kiosk"``. When
        ``None`` (or unrecognised) the value is resolved from
        ``self.config_data["window_mode"]``, defaulting to ``"desktop"``.

        - ``"desktop"``: normal windowed frontend (keeps the constructor's
          resize/minimum-size); used for dev/PC by default.
        - ``"fullscreen"``: borderless fullscreen frontend.
        - ``"kiosk"``: frameless + fullscreen for boot-to-frontend. Keyboard
          quit shortcuts stay live — no global input grabs — so the user is
          never trapped.

        This is called by ``app.main`` after construction (never from
        ``__init__``) so tests and dev runs stay windowed unless asked.
        """
        if mode not in ("desktop", "fullscreen", "kiosk"):
            mode = self.config_data.get("window_mode", "desktop")
        if mode not in ("desktop", "fullscreen", "kiosk"):
            mode = "desktop"

        if mode == "kiosk":
            self._kiosk = True
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
            self.showFullScreen()
        elif mode == "fullscreen":
            self._kiosk = False
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, False)
            self.showFullScreen()
        else:  # desktop
            self._kiosk = False
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, False)
            self.showNormal()

        self._window_mode = mode

    def restore_foreground(self):
        """Bring RetroVault back to the front after a child emulator exits.

        Uses the same Qt path on every platform (NO window reparenting): when
        the current mode is fullscreen/kiosk it re-asserts fullscreen, then
        always requests activation via ``raise_()`` + ``activateWindow()``.

        On Windows this reliably reactivates the window. On Raspberry
        Pi/Wayland (labwc) and X11/Xwayland these calls are best-effort hints
        the compositor may honour — we rely on compositor stacking rather than
        any X11-specific reparenting. PR10 calls this after the emulator
        process exits.
        """
        if getattr(self, "_window_mode", None) in ("fullscreen", "kiosk"):
            self.showFullScreen()
        self.raise_()
        self.activateWindow()

    # ── Controller navigation ────────────────────────────────────────────────
    def _on_controller_action(self, event: ActionEvent):
        """Map a semantic :class:`ActionEvent` onto main-window navigation.

        A modal dialog/file picker owns controller input while it is open: the
        router's timer keeps firing inside the dialog's nested event loop, so we
        first check for an active modal and delegate to it. When the modal has a
        ``handle_controller_action`` method (our dialogs) it drives the dialog;
        otherwise (e.g. a native ``QFileDialog``) we simply consume the event so
        the controller never moves the library table behind the dialog.
        """
        modal = QApplication.activeModalWidget()
        if modal is not None and modal is not self:
            handler = getattr(modal, "handle_controller_action", None)
            if callable(handler):
                handler(event)
            # Either way, the dialog owns input while open — never fall through
            # to the main-window navigation below.
            return

        if self._controller_busy:
            # Ignore controller input during scans/installs/launches.
            return
        action = event.action
        if action in (Action.UP, Action.DOWN):
            # Up/Down navigate within whichever column currently has focus.
            self._nav_move(-1 if action is Action.UP else 1)
        elif action in (Action.LEFT, Action.BACK):
            # Left/Back step into the systems column (pick NES, N64, ...).
            self._focus_systems_column()
        elif action is Action.RIGHT:
            # Right steps into the games column.
            self._focus_games_column()
        elif action is Action.PREV_SYSTEM:
            # Shoulders quick-cycle the system filter regardless of focus.
            self._move_sidebar_selection(-1)
        elif action is Action.NEXT_SYSTEM:
            self._move_sidebar_selection(1)
        elif action is Action.ACCEPT:
            # In the systems column, Accept drills into the games; in the games
            # column it launches the selected ROM.
            if self._nav_column == "systems":
                self._focus_games_column()
            else:
                self.on_launch_selected()
        elif action is Action.MENU:
            # Defer the menu to the next event-loop turn rather than opening it
            # inline. This slot runs from the controller router's QTimer tick;
            # calling _open_menu() here would enter the dialog's blocking exec()
            # while still inside that tick, and Qt will not re-enter the timer's
            # timeout slot while it's on the stack — so the backend would never
            # be polled again and the controller could not navigate the menu it
            # just opened. singleShot(0) lets this tick return first so polling
            # continues inside the dialog's nested event loop.
            QTimer.singleShot(0, self._open_menu)

    def _nav_move(self, delta):
        """Move selection by ``delta`` within the active column (systems/games)."""
        if self._nav_column == "systems":
            self._move_sidebar_selection(delta)
        else:
            self._move_table_selection(delta)

    def _focus_systems_column(self):
        """Make the systems sidebar the active column, ensuring a row is current."""
        if self.sidebar.count() == 0:
            return
        self._nav_column = "systems"
        if self.sidebar.currentRow() < 0:
            self.sidebar.setCurrentRow(0)
        self.sidebar.setFocus()

    def _focus_games_column(self):
        """Make the games table the active column, selecting the first ROM if none."""
        self._nav_column = "games"
        self.table.setFocus()
        self._select_first_visible_row()

    def _selected_proxy_row(self):
        indexes = self.table.selectionModel().selectedRows()
        return indexes[0].row() if indexes else -1

    def _select_proxy_row(self, row):
        """Select ``row`` in the proxy and scroll it into view."""
        if row < 0 or row >= self.proxy.rowCount():
            return
        index = self.proxy.index(row, 0)
        self.table.selectionModel().setCurrentIndex(
            index,
            QItemSelectionModel.SelectionFlag.ClearAndSelect | QItemSelectionModel.SelectionFlag.Rows,
        )
        self.table.scrollTo(index)

    def _select_first_visible_row(self):
        """Select the first visible ROM if any rows exist and none is selected."""
        if self.proxy.rowCount() > 0 and self._selected_proxy_row() < 0:
            self._select_proxy_row(0)

    def _move_table_selection(self, delta):
        """Move the table selection by ``delta`` rows, clamped at the ends."""
        count = self.proxy.rowCount()
        if count == 0:
            return
        current = self._selected_proxy_row()
        if current < 0:
            target = 0
        else:
            target = max(0, min(count - 1, current + delta))
        self._select_proxy_row(target)
        self.table.setFocus()

    def _move_sidebar_selection(self, delta):
        """Move the sidebar (system filter) by ``delta`` rows, clamped."""
        count = self.sidebar.count()
        if count == 0:
            return
        current = self.sidebar.currentRow()
        if current < 0:
            target = 0
        else:
            target = max(0, min(count - 1, current + delta))
        if target != current:
            # currentItemChanged -> _on_sidebar_changed updates the filter.
            self.sidebar.setCurrentRow(target)
        # After changing the filter, auto-select the first visible ROM.
        self._select_first_visible_row()

    def _menu_actions(self):
        """The top-bar actions exposed to the controller, as (label, callback)."""
        return [
            ("Search Games", self.on_search_via_keyboard),
            ("Scan ROMs", self.on_scan_roms),
            ("Add ROM Folder", self.on_add_rom_dir),
            ("Scrape Artwork", self.on_scrape_artwork),
            ("Toggle Favorite (selected game)", self._toggle_favorite_selected),
            ("Setup Wizard", self.on_setup),
            ("Settings", self.on_settings),
            ("Exit RetroVault", self.close),
        ]

    def on_search_via_keyboard(self):
        """Text-search the library using the controller-navigable on-screen keyboard."""
        keyboard = OnScreenKeyboard(self.search_box.text(), self, title="Search Games")
        if keyboard.exec() == QDialog.DialogCode.Accepted:
            self.search_box.setText(keyboard.text())  # triggers _on_search_changed
            self._focus_games_column()

    def _open_menu(self):
        """MENU: open the controller-navigable main menu, guarding reentrancy.

        This is the only way to reach the top-bar actions (scan, setup, settings,
        quit) without a mouse/keyboard — essential for Pi/kiosk use.
        """
        if self._menu_open:
            return
        self._menu_open = True
        try:
            actions = self._menu_actions()
            dialog = MainMenuDialog([label for label, _ in actions], self)
            chose = dialog.exec() == QDialog.DialogCode.Accepted
            index = dialog.chosen_index
        finally:
            self._menu_open = False
        # Run the chosen action AFTER the menu closes so any dialog it opens
        # (Settings/Setup) becomes the active modal cleanly.
        if chose and 0 <= index < len(actions):
            actions[index][1]()

    def _selected_rom(self):
        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return None
        source_index = self.proxy.mapToSource(indexes[0])
        return self.model.rom_at(source_index.row())

    def _on_search_changed(self, text):
        self.proxy.set_search_text(text)
        self._update_count_label()
        self._refresh_empty_state()
        self._select_first_visible_row()

    def _on_sidebar_changed(self, current, _previous):
        system_key = current.data(Qt.ItemDataRole.UserRole) if current else ""
        self.proxy.set_system_filter(system_key)
        self._update_count_label()
        self._refresh_empty_state()
        self._select_first_visible_row()

    def _get_collections(self):
        """Return the user's collections list, loading it from disk once."""
        if getattr(self, "collections", None) is None:
            self.collections = load_collections()
        return self.collections

    def _refresh_sidebar(self):
        selected = self.sidebar.currentItem().data(Qt.ItemDataRole.UserRole) if self.sidebar.currentItem() else ""
        counts = {}
        for rom in self.library:
            counts[rom.get("system", "")] = counts.get(rom.get("system", ""), 0) + 1
        favorite_count = sum(1 for rom in self.library if rom.get("favorite"))
        collections = self._get_collections()
        # Keep the proxy's collection membership in sync with the sidebar.
        self.proxy.set_collections(collections)

        self.sidebar.blockSignals(True)
        self.sidebar.clear()

        # Virtual views above the systems list: Favorites, Recently Played, and
        # one entry per collection. Each carries its sentinel filter string as
        # UserRole data, so the existing _on_sidebar_changed path just works.
        fav_item = QListWidgetItem(f"★ Favorites ({favorite_count})")
        fav_item.setData(Qt.ItemDataRole.UserRole, "__favorites__")
        self.sidebar.addItem(fav_item)

        recent_item = QListWidgetItem("Recently Played")
        recent_item.setData(Qt.ItemDataRole.UserRole, "__recent__")
        self.sidebar.addItem(recent_item)

        for coll in collections:
            name = coll.get("name", "")
            if not name:
                continue
            item = QListWidgetItem(f"{name} ({len(coll.get('paths', []) or [])})")
            item.setData(Qt.ItemDataRole.UserRole, f"collection:{name}")
            self.sidebar.addItem(item)

        all_item = QListWidgetItem(f"ALL GAMES ({len(self.library)})")
        all_item.setData(Qt.ItemDataRole.UserRole, "")
        self.sidebar.addItem(all_item)
        selected_row = self.sidebar.count() - 1  # default: ALL GAMES

        for sid, sdef in self.config_data.get("systems", {}).items():
            count = counts.get(sid, 0)
            if not count:
                continue
            item = QListWidgetItem(f"{sdef.get('short', sid.upper())} ({count})")
            item.setData(Qt.ItemDataRole.UserRole, sid)
            self.sidebar.addItem(item)

        # Restore the previously selected filter (system id or sentinel) by key.
        for row in range(self.sidebar.count()):
            if self.sidebar.item(row).data(Qt.ItemDataRole.UserRole) == selected:
                selected_row = row
                break

        self.sidebar.setCurrentRow(selected_row)
        self.sidebar.blockSignals(False)
        self.proxy.set_system_filter(self.sidebar.currentItem().data(Qt.ItemDataRole.UserRole))

    def _refresh_library(self, library):
        self.library = library
        self.model.set_library(library)
        self._refresh_sidebar()
        self._update_count_label()
        self._refresh_empty_state()
        # The model reset clears the selection without firing currentRowChanged,
        # so resync the detail panel explicitly (else it shows a stale game).
        self._update_detail_panel()

    def _refresh_empty_state(self):
        has_rows = self.proxy.rowCount() > 0
        self.table.setVisible(has_rows)
        self.placeholder_label.setVisible(not has_rows)

    def _update_count_label(self):
        shown = self.proxy.rowCount() if hasattr(self, "proxy") else len(self.library)
        total = len(self.library)
        self.count_label.setText(f"{shown} / {total} ROMs" if total else "")

    def _open_context_menu(self, pos):
        rom = self._selected_rom()
        if not rom:
            return
        menu = QMenu(self)
        launch_action = QAction("Launch", self)
        location_action = QAction("Open file location", self)
        remove_action = QAction("Remove from library", self)
        launch_action.triggered.connect(self.on_launch_selected)
        location_action.triggered.connect(lambda: self._open_location(rom))
        remove_action.triggered.connect(lambda: self._remove_rom(rom))
        menu.addAction(launch_action)
        menu.addAction(location_action)
        menu.addSeparator()

        fav_label = "Remove from favorites" if rom.get("favorite") else "Add to favorites"
        fav_action = QAction(fav_label, self)
        fav_action.triggered.connect(lambda: self._toggle_favorite(rom))
        menu.addAction(fav_action)

        collections = self._get_collections()
        coll_menu = menu.addMenu("Add to collection")
        new_action = QAction("New collection...", self)
        new_action.triggered.connect(lambda: self._add_to_new_collection(rom))
        coll_menu.addAction(new_action)
        if collections:
            coll_menu.addSeparator()
        path = rom.get("path")
        for coll in collections:
            name = coll.get("name", "")
            if not name:
                continue
            member = path in (coll.get("paths", []) or [])
            act = QAction(("✓ " if member else "") + name, self)
            act.triggered.connect(lambda _checked=False, n=name: self._toggle_collection_membership(rom, n))
            coll_menu.addAction(act)

        menu.addSeparator()
        menu.addAction(remove_action)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _toggle_favorite(self, rom):
        """Flip a game's favorite flag, persist the library, and refresh views."""
        rom["favorite"] = not rom.get("favorite")
        save_library(self.library)
        state = "added to" if rom["favorite"] else "removed from"
        self.statusBar().showMessage(f"{rom.get('name', 'Game')} {state} favorites", 3000)
        self._refresh_sidebar()

    def _toggle_favorite_selected(self):
        """MENU-reachable favorite toggle for the currently selected game."""
        rom = self._selected_rom()
        if not rom:
            self.statusBar().showMessage("No ROM selected", 3000)
            return
        self._toggle_favorite(rom)

    def _toggle_collection_membership(self, rom, name):
        """Add/remove a game's path in the named collection and persist it."""
        collections = self._get_collections()
        path = rom.get("path")
        for coll in collections:
            if coll.get("name") == name:
                paths = coll.setdefault("paths", [])
                if path in paths:
                    paths.remove(path)
                    msg = f"Removed from {name}"
                else:
                    paths.append(path)
                    msg = f"Added to {name}"
                break
        else:
            return
        save_collections(collections)
        self.proxy.set_collections(collections)
        self.statusBar().showMessage(msg, 3000)
        self._refresh_sidebar()

    def _add_to_new_collection(self, rom):
        """Prompt for a new collection name and add the game to it."""
        name, ok = QInputDialog.getText(self, "New Collection", "Collection name:")
        name = name.strip() if ok else ""
        if not name:
            return
        collections = self._get_collections()
        for coll in collections:
            if coll.get("name") == name:
                paths = coll.setdefault("paths", [])
                if rom.get("path") not in paths:
                    paths.append(rom.get("path"))
                break
        else:
            collections.append({"name": name, "paths": [rom.get("path")]})
        save_collections(collections)
        self.proxy.set_collections(collections)
        self.statusBar().showMessage(f"Added to {name}", 3000)
        self._refresh_sidebar()

    def _open_location(self, rom):
        path = Path(rom.get("path", ""))
        if not path.exists():
            QMessageBox.warning(self, "Open Location", f"File not found:\n{path}")
            return
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _remove_rom(self, rom):
        self._refresh_library([item for item in self.library if item.get("path") != rom.get("path")])
        save_library(self.library)
        self.statusBar().showMessage("Removed from library", 3000)

    def _track_worker(self, worker):
        self._workers.append(worker)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        worker.start()

    def closeEvent(self, event):
        if self.controller:
            self.controller.stop()
        for worker in self._workers:
            # A scrape worker runs a blocking network loop; ask it to stop at the
            # next entry so close doesn't hang or leave the thread running.
            if hasattr(worker, "cancel"):
                worker.cancel()
        for worker in self._workers:
            worker.quit()
            worker.wait(500)
        event.accept()

    def on_add_rom_dir(self):
        picked = QFileDialog.getExistingDirectory(self, "Choose ROM folder", str(Path.home()))
        if not picked:
            return
        if picked not in self.config_data["rom_dirs"]:
            self.config_data["rom_dirs"].append(picked)
            save_config(self.config_data)
        self.on_scan_roms()

    def on_setup(self):
        dialog = SetupWizard(self.config_data, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.config_data = load_config()
            self.statusBar().showMessage("Setup saved", 3000)

    def on_settings(self):
        dialog = SettingsDialog(self.config_data, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.config_data = load_config()
            self.model.systems = self.config_data.get("systems", {})
            self._refresh_sidebar()
            self.statusBar().showMessage("Settings saved", 3000)

    def on_scan_roms(self):
        self._set_controller_busy(True)
        self.statusBar().showMessage("Scanning ROM folders...")
        worker = WorkerThread(scan_roms, self.config_data, parent=self)
        worker.succeeded.connect(self._scan_finished)
        worker.failed.connect(self._scan_failed)
        self._track_worker(worker)

    def _scan_finished(self, library):
        # Preserve favorites/play-time/artwork/metadata added since the last
        # scan; scan_roms only rebuilds the disk-derived fields.
        library = merge_scan(self.library, library)
        save_library(library)
        self._refresh_library(library)
        self.statusBar().showMessage(f"Scan complete: {len(library)} ROMs", 4000)
        self._set_controller_busy(False)

    def _scan_failed(self, msg):
        self._set_controller_busy(False)
        QMessageBox.warning(self, "Scan ROMs", msg)

    # ── Artwork scraping (libretro-thumbnails by default; see providers.scraper) ──
    def on_scrape_artwork(self):
        """Fetch box art / metadata for the library on a background thread."""
        if not self.library:
            self.statusBar().showMessage("No games to scrape — scan ROMs first", 4000)
            return
        if getattr(self, "_scrape_worker", None) is not None:
            return  # a scrape is already running
        self.scrape_btn.setEnabled(False)
        # Block a concurrent rescan while the (multi-minute) scrape runs so the
        # two don't fight over self.library. The scrape result is also merged by
        # path (see _scrape_finished) as a second line of defence.
        self.scan_btn.setEnabled(False)
        self.statusBar().showMessage("Scraping artwork…")
        worker = ScrapeWorker(self.library, self.config_data, parent=self)
        self._scrape_worker = worker
        worker.progress.connect(self._scrape_progress)
        worker.finished_library.connect(self._scrape_finished)
        worker.failed.connect(self._scrape_failed)
        worker.finished.connect(self._scrape_cleanup)
        self._track_worker(worker)

    def _scrape_progress(self, done, total):
        self.statusBar().showMessage(f"Scraping artwork… {done}/{total}")

    def _scrape_finished(self, updated):
        # Merge the scraped media/metadata onto the CURRENT library by path rather
        # than replacing it wholesale: the worker ran against a snapshot taken when
        # the scrape started, so a rescan or removal that landed meanwhile must not
        # be lost. Paths no longer present are simply skipped.
        merged = self._merge_scrape_result(updated)
        save_library(merged)
        self._refresh_library(merged)
        covers = sum(1 for rom in merged if (rom.get("media") or {}).get("boxart"))
        self.statusBar().showMessage(f"Artwork updated — {covers} covers", 5000)

    def _merge_scrape_result(self, updated):
        """Overlay scraped ``media``/``metadata`` from ``updated`` onto ``self.library``.

        Matched by path; entries in ``updated`` whose path is gone from the live
        library are dropped, and live entries the scrape didn't touch are left as-is.
        Returns ``self.library`` (mutated in place) for the caller to persist.
        """
        by_path = {e.get("path"): e for e in (updated or []) if e.get("path") is not None}
        for entry in self.library:
            scraped = by_path.get(entry.get("path"))
            if not scraped:
                continue
            if scraped.get("media"):
                entry["media"] = scraped["media"]
            if scraped.get("metadata"):
                entry["metadata"] = scraped["metadata"]
        return self.library

    def _scrape_failed(self, msg):
        QMessageBox.warning(self, "Scrape Artwork", msg)

    def _scrape_cleanup(self):
        worker = getattr(self, "_scrape_worker", None)
        self._scrape_worker = None
        self.scrape_btn.setEnabled(True)
        self.scan_btn.setEnabled(True)
        if worker is not None:
            worker.deleteLater()

    def on_launch_selected(self):
        rom = self._selected_rom()
        if not rom:
            self.statusBar().showMessage("No ROM selected", 3000)
            return
        self.statusBar().showMessage(f"Launching {rom.get('name', 'ROM')}...")
        if self.launch_coordinator is not None:
            # Seamless couch-console handoff: the coordinator covers the UI,
            # suspends the controller, runs the emulator, and restores on exit.
            self.launch_coordinator.launch(rom, self.config_data)
            return
        # Fallback (coordinator unavailable): legacy fire-and-forget launch.
        self._set_controller_busy(True)
        worker = WorkerThread(launch_rom, rom, self.config_data, parent=self)
        worker.succeeded.connect(lambda result: self._launch_finished(rom, result))
        worker.failed.connect(lambda msg: self._launch_failed(rom, msg))
        self._track_worker(worker)

    # ── Launch-session integration (PR10) ────────────────────────────────────
    def _save_launch_view(self):
        """Snapshot the selected ROM identity and scroll position before launch."""
        rom = self._selected_rom()
        self._saved_rom_path = rom.get("path") if rom else None
        self._saved_scroll = self.table.verticalScrollBar().value()

    def _restore_launch_view(self):
        """Re-select the previously launched ROM, restore scroll, and focus table."""
        if self._saved_rom_path is not None:
            row = self._find_proxy_row_by_path(self._saved_rom_path)
            if row >= 0:
                self._select_proxy_row(row)
        if self._saved_scroll is not None:
            # After selection (which may scrollTo), re-assert the saved offset.
            self.table.verticalScrollBar().setValue(self._saved_scroll)
        self.table.setFocus()

    def _find_proxy_row_by_path(self, path):
        """Return the proxy row whose ROM has ``path``, or -1 if not visible."""
        for row in range(self.proxy.rowCount()):
            source_index = self.proxy.mapToSource(self.proxy.index(row, 0))
            rom = self.model.rom_at(source_index.row())
            if rom and rom.get("path") == path:
                return row
        return -1

    def _on_launch_input_disabled(self, disabled):
        """React to the coordinator's input-disable toggle.

        On ``True`` (launch begins) suspend the controller and disable the main
        controls so neither pad nor mouse/keyboard can relaunch. On ``False``
        (emulator exited / launch failed) re-enable the controls, but do NOT
        resume the controller here — that is debounced from finished/failed.
        """
        central = self.centralWidget()
        if disabled:
            # Fully RELEASE the controller (not just pause) so the launched
            # emulator has uncontested access to the physical device — RetroVault
            # must never sit between the pad and the emulator during play.
            self._controller_busy = True
            if self.controller:
                try:
                    self.controller.stop()
                except Exception:  # pragma: no cover - release is best-effort
                    pass
            if central is not None:
                central.setEnabled(False)
        else:
            if central is not None:
                central.setEnabled(True)

    def _on_launch_session_finished(self):
        """Emulator exited and the return transition is done: reactivate + resume."""
        self.restore_foreground()
        self.table.setFocus()
        self._play_return_cue()
        self._resume_controller_after_debounce()

    def _on_play_session_finished(self, info):
        """Record play time for a completed emulator session.

        ``info`` is ``{"rom_path": <str>, "elapsed_seconds": <float>}`` from the
        coordinator's ``session_finished`` signal. Accumulates ``play_seconds``,
        bumps ``play_count``, and stamps ``last_played`` (ISO-8601, UTC) on the
        matching library entry, then persists and refreshes just that row.
        Implausibly short sessions (``< MIN_PLAY_SECONDS``) are discarded — they
        are failed launches or the un-waitable ShellExecute path.
        """
        if not isinstance(info, dict):
            return
        elapsed = info.get("elapsed_seconds")
        rom_path = info.get("rom_path")
        if elapsed is None or rom_path is None:
            return
        if elapsed < MIN_PLAY_SECONDS:
            return
        for row, entry in enumerate(self.library):
            if entry.get("path") != rom_path:
                continue
            entry["play_seconds"] = int(entry.get("play_seconds", 0)) + int(elapsed)
            entry["play_count"] = int(entry.get("play_count", 0)) + 1
            entry["last_played"] = datetime.now(timezone.utc).isoformat()
            save_library(self.library)
            # Refresh only the affected source row so the view reflects the update.
            top_left = self.model.index(row, 0)
            bottom_right = self.model.index(row, self.model.columnCount() - 1)
            self.model.dataChanged.emit(top_left, bottom_right)
            # "Recently Played" is computed once when the view is selected, so a
            # session that finishes while sitting in that view would otherwise not
            # surface or re-sort the just-played game. Re-apply the filter to
            # recompute + re-order it live.
            proxy = getattr(self, "proxy", None)
            if proxy is not None and getattr(proxy, "system_key", "") == RECENT_FILTER:
                proxy.set_system_filter(RECENT_FILTER)
            break

    def _on_launch_session_failed(self, message):
        """Launch could not start: show the dialog (coordinator never does) + recover."""
        self.statusBar().showMessage("Launch failed", 4000)
        QMessageBox.warning(self, "Launch Failed", message)
        self.restore_foreground()
        self.table.setFocus()
        self._resume_controller_after_debounce()

    def _resume_controller_after_debounce(self):
        """Resume controller polling after a short debounce (guards held buttons)."""
        QTimer.singleShot(CONTROLLER_RESUME_DEBOUNCE_MS, self._resume_controller_now)

    def _resume_controller_now(self):
        """Re-acquire the controller after a session (post-debounce).

        Uses ``start()`` rather than ``resume()`` so the device released in
        :meth:`_on_launch_input_disabled` is re-opened and re-detected (also
        picks up a pad that was hot-plugged while the emulator ran).
        """
        self._controller_busy = False
        if not self.controller:
            return
        try:
            self.controller.start()
        except Exception:  # pragma: no cover - resume is a nice-to-have
            pass

    def _play_return_cue(self):
        """Optionally play a subtle audible cue on return; never raises."""
        if not self._return_cue_enabled:
            return
        try:  # pragma: no cover - audio path not exercised headless
            QApplication.beep()
        except Exception:
            pass

    def _launch_finished(self, rom, result):
        self._set_controller_busy(False)
        ok, message = result
        if ok:
            self.statusBar().showMessage(message, 4000)
        else:
            self.statusBar().showMessage("Launch failed", 4000)
            QMessageBox.warning(self, f"Could not launch {rom.get('name', 'ROM')}", message)

    def _launch_failed(self, rom, message):
        self._set_controller_busy(False)
        QMessageBox.warning(self, "Launch Failed", message)

    def _set_controller_busy(self, busy):
        """Toggle the busy guard and (best-effort) pause/resume polling.

        While busy, ``_on_controller_action`` ignores input so scans, installs,
        and launches are not disturbed by controller navigation.
        """
        self._controller_busy = bool(busy)
        if not self.controller:
            return
        try:
            self.controller.pause() if busy else self.controller.resume()
        except Exception:  # pragma: no cover - pause/resume is a nice-to-have
            pass
