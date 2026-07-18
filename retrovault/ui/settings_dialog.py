"""Qt settings dialog."""

import sys
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core import config as config_mod
from ..core.paths import CONFIG_FILE
from ..input.actions import Action
from ..providers import discovery
from .controller_nav import activate_focused, make_focusable, move_focus, switch_tab


class DiscoveryThread(QThread):
    """Run emulator discovery off the UI thread (same pattern as WorkerThread)."""

    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, config_data, parent=None):
        super().__init__(parent)
        self.config_data = config_data

    def run(self):
        try:
            self.succeeded.emit(discovery.discover_emulators(self.config_data))
        except Exception as exc:  # Worker failures must return to the GUI thread.
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class PathPickerRow(QWidget):
    def __init__(self, text="", directory=False, parent=None):
        super().__init__(parent)
        self.directory = directory
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(text)
        self.button = QPushButton("BROWSE")
        self.button.clicked.connect(self.browse)
        layout.addWidget(self.edit, 1)
        layout.addWidget(self.button)

    def text(self):
        return self.edit.text().strip()

    def browse(self):
        if self.directory:
            picked = QFileDialog.getExistingDirectory(self, "Choose folder", self.text() or str(Path.home()))
        else:
            picked, _ = QFileDialog.getOpenFileName(self, "Choose executable", self.text() or str(Path.home()))
        if picked:
            self.edit.setText(picked)


class SettingsDialog(QDialog):
    def __init__(self, config_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(900, 620)
        self.config_data = config_mod.migrate_config(config_data)
        self.system_rows = {}
        self._threads = set()

        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_emulators_tab(), "EMULATORS")
        self.tabs.addTab(self._build_rom_dirs_tab(), "ROM DIRS")
        self.tabs.addTab(self._build_systems_tab(), "SYSTEMS")
        root.addWidget(self.tabs, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("CANCEL")
        cancel.clicked.connect(self.reject)
        save = QPushButton("SAVE")
        save.setProperty("accent", "true")
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

        # Controller navigation (PR9): make the key buttons reachable by pad.
        make_focusable(cancel, save)

    # ── Controller navigation (PR9) ──────────────────────────────────────────
    def handle_controller_action(self, event) -> bool:
        """Drive this dialog from a controller :class:`ActionEvent`.

        Returns ``True`` when the action was consumed. See
        :mod:`retrovault.ui.controller_nav` for the contract.
        """
        action = event.action
        if action in (Action.UP, Action.DOWN):
            move_focus(self, forward=action is Action.DOWN)
            return True
        if action in (Action.LEFT, Action.PREV_SYSTEM):
            switch_tab(self.tabs, -1)
            return True
        if action in (Action.RIGHT, Action.NEXT_SYSTEM):
            switch_tab(self.tabs, 1)
            return True
        if action is Action.ACCEPT:
            return activate_focused(self)
        if action is Action.BACK:
            self.reject()
            return True
        # MENU has no meaning inside the dialog.
        return False

    # Fullscreen preference: combo index <-> stored config value.
    _FULLSCREEN_OPTIONS = (
        ("Use emulator preference", "emulator"),
        ("Prefer fullscreen", "prefer"),
        ("Force windowed", "force_windowed"),
    )

    def _build_emulators_tab(self):
        page = QWidget()
        outer = QVBoxLayout(page)

        detect_group = QGroupBox("Detection")
        detect_layout = QHBoxLayout(detect_group)
        self.redetect_button = QPushButton("RE-DETECT")
        self.redetect_button.clicked.connect(self._redetect)
        self.detect_status = QLabel("")
        self.detect_status.setWordWrap(True)
        detect_layout.addWidget(self.redetect_button)
        detect_layout.addWidget(self.detect_status, 1)
        outer.addWidget(detect_group)
        make_focusable(self.redetect_button)

        display_group = QGroupBox("Display")
        display_form = QFormLayout(display_group)
        self.fullscreen_preference = QComboBox()
        self.fullscreen_preference.addItems([label for label, _ in self._FULLSCREEN_OPTIONS])
        current_value = self.config_data.get("fullscreen_preference", "emulator")
        values = [value for _, value in self._FULLSCREEN_OPTIONS]
        self.fullscreen_preference.setCurrentIndex(values.index(current_value) if current_value in values else 0)
        display_form.addRow("Fullscreen", self.fullscreen_preference)
        outer.addWidget(display_group)

        retro_group = QGroupBox("RetroArch")
        retro_form = QFormLayout(retro_group)
        self.use_retroarch = QCheckBox("Use RetroArch when launching games")
        self.use_retroarch.setChecked(bool(self.config_data.get("use_retroarch")))
        retro_form.addRow(self.use_retroarch)
        self.retroarch_path = PathPickerRow(self.config_data.get("retroarch_path", ""))
        retro_form.addRow("Binary path", self.retroarch_path)
        outer.addWidget(retro_group)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        grid = QGridLayout(body)
        headers = ("SYSTEM", "PATH / COMMAND", "ARGS", "PROFILE", "TYPE", "FLATPAK ID", "")
        for col, header in enumerate(headers):
            grid.addWidget(QLabel(header), 0, col)

        profile_names = list(self.config_data.get("emulator_profiles", {}).keys())
        launch_types = ("exe", "binary", "flatpak")
        for row, (sid, sdef) in enumerate(self.config_data["systems"].items(), start=1):
            emu = self.config_data["emulators"].get(sid, {})
            grid.addWidget(QLabel(sdef.get("short", sid.upper())), row, 0)
            path = PathPickerRow(emu.get("path", ""))
            args = QLineEdit(emu.get("args", "{rom}"))
            profile = QComboBox()
            profile.addItems(profile_names)
            profile.setCurrentText(emu.get("profile", "custom"))
            launch_type = QComboBox()
            launch_type.addItems(launch_types)
            launch_type.setCurrentText(emu.get("launch_type", "exe"))
            flatpak_id = QLineEdit(emu.get("flatpak_id", ""))
            use_button = QPushButton("USE")
            use_button.clicked.connect(lambda _checked=False, p=profile, a=args: self._apply_profile(p, a))

            if sys.platform == "win32":
                flatpak_id.setVisible(False)
                launch_type.removeItem(launch_type.findText("flatpak"))

            grid.addWidget(path, row, 1)
            grid.addWidget(args, row, 2)
            grid.addWidget(profile, row, 3)
            grid.addWidget(launch_type, row, 4)
            grid.addWidget(flatpak_id, row, 5)
            grid.addWidget(use_button, row, 6)
            self.system_rows[sid] = {
                "path": path,
                "args": args,
                "profile": profile,
                "launch_type": launch_type,
                "flatpak_id": flatpak_id,
            }

        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        return page

    def _build_rom_dirs_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.rom_dirs = QListWidget()
        self.rom_dirs.addItems(self.config_data.get("rom_dirs", []))
        layout.addWidget(self.rom_dirs, 1)
        buttons = QHBoxLayout()
        add = QPushButton("ADD")
        remove = QPushButton("REMOVE")
        add.clicked.connect(self._add_rom_dir)
        remove.clicked.connect(lambda: self.rom_dirs.takeItem(self.rom_dirs.currentRow()))
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return page

    def _build_systems_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel(f"Config: {CONFIG_FILE}"))
        table = QTableWidget(len(self.config_data["systems"]), 4)
        table.setHorizontalHeaderLabels(("KEY", "NAME", "SHORT", "EXTENSIONS"))
        for row, (sid, sdef) in enumerate(self.config_data["systems"].items()):
            table.setItem(row, 0, QTableWidgetItem(sid))
            table.setItem(row, 1, QTableWidgetItem(sdef.get("name", "")))
            table.setItem(row, 2, QTableWidgetItem(sdef.get("short", "")))
            table.setItem(row, 3, QTableWidgetItem(", ".join(sdef.get("extensions", []))))
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(table, 1)
        return page

    def _apply_profile(self, profile_combo, args_edit):
        profile = self.config_data.get("emulator_profiles", {}).get(profile_combo.currentText(), {})
        args_edit.setText(profile.get("args", "{rom}"))

    # ── Emulator re-detection ────────────────────────────────────────────────
    def _redetect(self):
        """Run discovery off the UI thread and apply results to empty slots."""
        self.redetect_button.setEnabled(False)
        self.detect_status.setText("Detecting installed emulators...")
        thread = DiscoveryThread(self.config_data, self)
        thread.succeeded.connect(self._apply_detection_results)
        thread.failed.connect(self._detection_failed)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._threads.discard(thread))
        thread.finished.connect(lambda: self.redetect_button.setEnabled(True))
        self._threads.add(thread)
        thread.start()

    def _detection_failed(self, message):
        self.detect_status.setText(message)

    def _apply_detection_results(self, results):
        """Fill empty emulator rows from a discovery result mapping."""
        updated = discovery.apply_detection(self.config_data, results)
        found = []
        for sid, widgets in self.system_rows.items():
            # Don't clobber a path the user just typed but hasn't saved.
            if widgets["path"].text() or widgets["flatpak_id"].text().strip():
                continue
            slot = updated.get("emulators", {}).get(sid, {})
            detected = slot.get("path") or slot.get("flatpak_id", "")
            if not detected:
                continue
            widgets["path"].edit.setText(slot.get("path", ""))
            widgets["flatpak_id"].setText(slot.get("flatpak_id", ""))
            widgets["args"].setText(slot.get("args", "{rom}"))
            widgets["launch_type"].setCurrentText(slot.get("launch_type", "exe"))
            profile = slot.get("profile", "custom")
            if widgets["profile"].findText(profile) < 0:
                widgets["profile"].addItem(profile)
            widgets["profile"].setCurrentText(profile)
            found.append(self.config_data["systems"].get(sid, {}).get("short", sid.upper()))
        self.config_data = updated
        self.detect_status.setText(
            "Detected: " + ", ".join(found) + "." if found else "No new emulators detected."
        )

    def closeEvent(self, event):
        for thread in tuple(self._threads):
            thread.requestInterruption()
            thread.wait(1000)
        super().closeEvent(event)

    def _add_rom_dir(self):
        picked = QFileDialog.getExistingDirectory(self, "Choose ROM folder", str(Path.home()))
        if picked:
            self.rom_dirs.addItem(picked)

    def _save(self):
        updated = config_mod.migrate_config(self.config_data)
        updated["fullscreen_preference"] = self._FULLSCREEN_OPTIONS[self.fullscreen_preference.currentIndex()][1]
        updated["use_retroarch"] = self.use_retroarch.isChecked()
        updated["retroarch_path"] = self.retroarch_path.text()
        updated["rom_dirs"] = [self.rom_dirs.item(i).text() for i in range(self.rom_dirs.count())]
        for sid, widgets in self.system_rows.items():
            emu = updated["emulators"].setdefault(sid, {})
            emu["path"] = widgets["path"].text()
            emu["args"] = widgets["args"].text().strip() or "{rom}"
            emu["profile"] = widgets["profile"].currentText()
            emu["launch_type"] = widgets["launch_type"].currentText()
            emu["flatpak_id"] = widgets["flatpak_id"].text().strip()
        config_mod.save_config(updated)
        self.config_data = updated
        self.accept()
