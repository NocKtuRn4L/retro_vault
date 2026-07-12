"""PySide6 main window shell for RetroVault.

This is an intentionally empty shell for PR5: the top bar, sidebar, and
status bar are wired up, but the library list/grid, settings dialog, and
setup wizard are implemented in later PRs (PR6/7/8). Keep the public
method names (on_add_rom_dir, on_setup, on_settings, on_scan_roms,
on_launch_selected) stable so those PRs can replace bodies without
touching this file's structure.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.config import load_config
from ..core.library import load_library


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RetroVault")
        self.resize(1100, 700)
        self.setMinimumSize(800, 550)

        self.config_data = load_config()
        self.library = load_library()

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

    # ── construction ────────────────────────────────────────────────────

    def _build_top_bar(self):
        top_bar = QWidget()
        layout = QHBoxLayout(top_bar)
        layout.setContentsMargins(20, 10, 16, 10)
        layout.setSpacing(10)

        title_label = QLabel("▶ RETROVAULT")
        title_label.setProperty("role", "title")
        layout.addWidget(title_label)

        self.search_box = QLineEdit()
        self.search_box.setObjectName("searchBox")
        self.search_box.setPlaceholderText("Search games…")
        self.search_box.setFixedWidth(280)
        layout.addWidget(self.search_box)

        layout.addStretch(1)

        add_rom_dir_btn = QPushButton("+ ADD ROM DIR")
        add_rom_dir_btn.clicked.connect(self.on_add_rom_dir)
        layout.addWidget(add_rom_dir_btn)

        setup_btn = QPushButton("SETUP")
        setup_btn.clicked.connect(self.on_setup)
        layout.addWidget(setup_btn)

        settings_btn = QPushButton("⚙ SETTINGS")
        settings_btn.clicked.connect(self.on_settings)
        layout.addWidget(settings_btn)

        scan_roms_btn = QPushButton("⟳ SCAN ROMS")
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
        self.sidebar.addItem(QListWidgetItem("🗂 ALL GAMES"))
        body_layout.addWidget(self.sidebar)

        vdivider = QFrame()
        vdivider.setFrameShape(QFrame.Shape.VLine)
        vdivider.setFixedWidth(1)
        vdivider.setStyleSheet("background-color: #2a2a2a; border: none;")
        body_layout.addWidget(vdivider)

        self.placeholder_label = QLabel(
            "No ROMs in library.\n"
            "Click '+ ADD ROM DIR' to add a folder,\n"
            "then '⟳ SCAN ROMS'."
        )
        self.placeholder_label.setProperty("role", "subtext")
        self.placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body_layout.addWidget(self.placeholder_label, 1)

        return body_layout

    def _build_status_bar(self):
        status_bar = self.statusBar()
        status_bar.showMessage("Welcome to RetroVault")

        self.count_label = QLabel("")
        self.count_label.setObjectName("countLabel")
        count_text = f"{len(self.library)} ROMs" if self.library else ""
        self.count_label.setText(count_text)
        status_bar.addPermanentWidget(self.count_label)

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

    # ── stub actions (real implementations land in later PRs) ─────────────

    def on_add_rom_dir(self):
        self.statusBar().showMessage("Add ROM dir: coming in a later PR", 3000)

    def on_setup(self):
        self.statusBar().showMessage("Setup: coming in a later PR", 3000)

    def on_settings(self):
        self.statusBar().showMessage("Settings: coming in a later PR", 3000)

    def on_scan_roms(self):
        self.statusBar().showMessage("Scan ROMs: coming in a later PR", 3000)

    def on_launch_selected(self):
        self.statusBar().showMessage("Launch selected: coming in a later PR", 3000)
