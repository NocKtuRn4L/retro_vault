"""PySide6 main window for RetroVault."""

import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from ..core.config import load_config, save_config
from ..core.launch import launch_rom
from ..core.library import load_library, save_library, scan_roms
from .library_model import LibraryFilterProxyModel, LibraryModel
from .settings_dialog import SettingsDialog
from .setup_wizard import SetupWizard


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

        if not self.config_data.get("setup", {}).get("completed", False):
            QTimer.singleShot(250, self.on_setup)

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

        scan_roms_btn = QPushButton("SCAN ROMS")
        scan_roms_btn.setProperty("accent", "true")
        scan_roms_btn.clicked.connect(self.on_scan_roms)
        layout.addWidget(scan_roms_btn)

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
        body_layout.addWidget(content, 1)
        return body_layout

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

    def _on_sidebar_changed(self, current, _previous):
        system_key = current.data(Qt.ItemDataRole.UserRole) if current else ""
        self.proxy.set_system_filter(system_key)
        self._update_count_label()
        self._refresh_empty_state()

    def _refresh_sidebar(self):
        selected = self.sidebar.currentItem().data(Qt.ItemDataRole.UserRole) if self.sidebar.currentItem() else ""
        counts = {}
        for rom in self.library:
            counts[rom.get("system", "")] = counts.get(rom.get("system", ""), 0) + 1
        self.sidebar.blockSignals(True)
        self.sidebar.clear()
        all_item = QListWidgetItem(f"ALL GAMES ({len(self.library)})")
        all_item.setData(Qt.ItemDataRole.UserRole, "")
        self.sidebar.addItem(all_item)
        selected_row = 0
        for sid, sdef in self.config_data.get("systems", {}).items():
            count = counts.get(sid, 0)
            if not count:
                continue
            item = QListWidgetItem(f"{sdef.get('short', sid.upper())} ({count})")
            item.setData(Qt.ItemDataRole.UserRole, sid)
            self.sidebar.addItem(item)
            if sid == selected:
                selected_row = self.sidebar.count() - 1
        self.sidebar.setCurrentRow(selected_row)
        self.sidebar.blockSignals(False)
        self.proxy.set_system_filter(self.sidebar.currentItem().data(Qt.ItemDataRole.UserRole))

    def _refresh_library(self, library):
        self.library = library
        self.model.set_library(library)
        self._refresh_sidebar()
        self._update_count_label()
        self._refresh_empty_state()

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
        menu.addAction(remove_action)
        menu.exec(self.table.viewport().mapToGlobal(pos))

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
        self.statusBar().showMessage("Scanning ROM folders...")
        worker = WorkerThread(scan_roms, self.config_data, parent=self)
        worker.succeeded.connect(self._scan_finished)
        worker.failed.connect(lambda msg: QMessageBox.warning(self, "Scan ROMs", msg))
        self._track_worker(worker)

    def _scan_finished(self, library):
        save_library(library)
        self._refresh_library(library)
        self.statusBar().showMessage(f"Scan complete: {len(library)} ROMs", 4000)

    def on_launch_selected(self):
        rom = self._selected_rom()
        if not rom:
            self.statusBar().showMessage("No ROM selected", 3000)
            return
        self.statusBar().showMessage(f"Launching {rom.get('name', 'ROM')}...")
        worker = WorkerThread(launch_rom, rom, self.config_data, parent=self)
        worker.succeeded.connect(lambda result: self._launch_finished(rom, result))
        worker.failed.connect(lambda msg: QMessageBox.warning(self, "Launch Failed", msg))
        self._track_worker(worker)

    def _launch_finished(self, rom, result):
        ok, message = result
        if ok:
            self.statusBar().showMessage(message, 4000)
        else:
            self.statusBar().showMessage("Launch failed", 4000)
            QMessageBox.warning(self, f"Could not launch {rom.get('name', 'ROM')}", message)
