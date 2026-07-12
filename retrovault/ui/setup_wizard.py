"""First-run setup wizard with emulator discovery and provisioning."""

from __future__ import annotations

import copy
import logging
import shutil
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core import audit as audit_mod
from ..core import config as config_mod
from ..platform import detect, recommend
from ..providers import discovery, installer
from ..providers.manifest import load_registry


class ProvisionWorker(QObject):
    progress = Signal(int, int)
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, operation):
        super().__init__()
        self.operation = operation

    @Slot()
    def run(self):
        try:
            self.succeeded.emit(self.operation(self._progress))
        except Exception as error:  # Worker failures must return to the GUI thread.
            self.failed.emit(str(error))
        finally:
            self.finished.emit()

    def _progress(self, done, total):
        self.progress.emit(done, total or 0)


class SetupWizard(QDialog):
    def __init__(self, config_data, parent=None, registry=None):
        super().__init__(parent)
        self.setWindowTitle("Setup")
        self.resize(1040, 650)
        self.config_data = config_mod.migrate_config(config_data)
        self.rows = {}
        self.platform_key = detect.current_platform()
        self.registry = registry or load_registry(self.config_data)
        self._threads = set()

        root = QVBoxLayout(self)
        root.addWidget(QLabel("Choose emulator paths for each system. Recommended defaults are preselected."))
        if self.platform_key == "linux-aarch64":
            banner = QWidget()
            banner_layout = QHBoxLayout(banner)
            banner_layout.setContentsMargins(0, 0, 0, 0)
            banner_layout.addWidget(QLabel("Raspberry Pi 5: RetroArch Flatpak is the recommended backend."))
            use_all = QPushButton("USE RETROARCH FOR ALL")
            use_all.setProperty("accent", "true")
            use_all.clicked.connect(self._use_retroarch_for_all)
            banner_layout.addWidget(use_all)
            root.addWidget(banner)

        actions = QHBoxLayout()
        detect_all = QPushButton("DETECT ALL")
        detect_all.clicked.connect(self._detect_all)
        install_all = QPushButton("INSTALL RECOMMENDED SET")
        install_all.setProperty("accent", "true")
        install_all.clicked.connect(self._install_recommended_set)
        actions.addWidget(detect_all)
        actions.addWidget(install_all)
        actions.addStretch(1)
        root.addLayout(actions)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        grid = QGridLayout(body)
        for col, header in enumerate(("SYSTEM", "RECOMMENDED", "PATH", "STATUS", "", "", "")):
            grid.addWidget(QLabel(header), 0, col)

        for row, (sid, sdef) in enumerate(self.config_data["systems"].items(), start=1):
            rec = recommend.get_recommended_emulator(sid, self.platform_key)
            manifest = self._manifest_for(sid, rec)
            emu = self.config_data.get("emulators", {}).get(sid, {})
            path = QLineEdit(emu.get("path", ""))
            status = QLabel("READY" if config_mod.is_emulator_configured(self.config_data, sid) else "NEEDED")
            status.setProperty("state", status.text().lower())
            progress = QProgressBar()
            progress.setRange(0, 100)
            progress.setVisible(False)
            detect_button = QPushButton("DETECT")
            install_button = QPushButton("INSTALL")
            browse = QPushButton("BROWSE")
            recommended = QLabel(f"{rec.get('name', 'Custom')}\n{rec.get('notes', '')}")
            recommended.setWordWrap(True)
            detect_button.clicked.connect(lambda _checked=False, s=sid: self._detect_system(s))
            install_button.clicked.connect(lambda _checked=False, s=sid: self._install_system(s))
            browse.clicked.connect(lambda _checked=False, s=sid: self._browse(s))
            install_button.setEnabled(manifest is not None and manifest.strategy_for(self.platform_key).available)
            if manifest is None:
                install_button.setToolTip("No provider manifest matches this recommendation")
            elif not manifest.strategy_for(self.platform_key).available:
                install_button.setToolTip(manifest.strategy_for(self.platform_key).reason)
            grid.addWidget(QLabel(sdef.get("short", sid.upper())), row, 0)
            grid.addWidget(recommended, row, 1)
            grid.addWidget(path, row, 2)
            grid.addWidget(status, row, 3)
            grid.addWidget(detect_button, row, 4)
            grid.addWidget(install_button, row, 5)
            grid.addWidget(browse, row, 6)
            grid.addWidget(progress, row + len(self.config_data["systems"]), 2, 1, 4)
            self.rows[sid] = {
                "path": path,
                "status": status,
                "progress": progress,
                "detect": detect_button,
                "install": install_button,
                "rec": rec,
                "manifest": manifest,
            }

        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        self.instruction = QLineEdit()
        self.instruction.setReadOnly(True)
        self.instruction.setPlaceholderText("Package-manager instructions appear here")
        self.instruction.setVisible(False)
        root.addWidget(self.instruction)
        self.audit_results = QLabel()
        self.audit_results.setWordWrap(True)
        self.audit_results.setTextInteractionFlags(self.audit_results.textInteractionFlags())
        self.audit_results.setVisible(False)
        root.addWidget(self.audit_results)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("CANCEL")
        cancel.clicked.connect(self.reject)
        save = QPushButton("SAVE EASY MODE")
        save.setProperty("accent", "true")
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

    def _manifest_for(self, sid, recommendation):
        profile = recommendation.get("profile", "")
        if profile in self.registry.manifests:
            return self.registry.get(profile)
        wanted = recommendation.get("name", "").lower()
        for manifest in self.registry.manifests.values():
            systems = {system for item in manifest.profiles for system in item.systems}
            if sid in systems and (manifest.name.lower() in wanted or wanted in manifest.name.lower()):
                return manifest
        return None

    def _set_state(self, sid, state):
        row = self.rows[sid]
        row["status"].setText(state)
        row["status"].setProperty("state", state.lower())
        row["status"].style().unpolish(row["status"])
        row["status"].style().polish(row["status"])

    def _set_busy(self, sids, busy):
        for sid in sids:
            row = self.rows[sid]
            row["detect"].setEnabled(not busy)
            strategy = row["manifest"].strategy_for(self.platform_key) if row["manifest"] else None
            row["install"].setEnabled(not busy and strategy is not None and strategy.available)
            row["progress"].setVisible(busy)
            if busy:
                self._set_state(sid, "INSTALLING")

    def _start_worker(self, operation, on_success, sids=(), on_progress=None):
        thread = QThread(self)
        worker = ProvisionWorker(operation)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(on_success)
        if on_progress is not None:
            worker.progress.connect(on_progress)
        worker.failed.connect(lambda message: self._worker_failed(sids, message))
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._threads.discard(thread))
        if sids:
            self._set_busy(sids, True)
        worker.finished.connect(lambda: self._set_busy(sids, False))
        self._threads.add(thread)
        thread.start()

    def _worker_failed(self, sids, message):
        for sid in sids:
            self._set_state(sid, "NEEDED")
        self.instruction.setText(message)
        self.instruction.setVisible(True)

    def _detect_system(self, sid):
        manifest = self.rows[sid]["manifest"]
        if manifest is None:
            return
        def operation(_progress):
            return discovery.detect_emulator(self.config_data, manifest)

        self._start_worker(operation, lambda result: self._detection_complete({manifest.id: result}), (sid,))

    def _detect_all(self):
        def operation(_progress):
            return discovery.discover_emulators(self.config_data, self.registry)

        self._start_worker(operation, self._detection_complete, tuple(self.rows))

    def _detection_complete(self, results):
        self.config_data = discovery.apply_detection(self.config_data, results, self.registry)
        for sid, row in self.rows.items():
            manifest = row["manifest"]
            result = results.get(manifest.id) if manifest else None
            if result and result.found:
                self._set_state(sid, "FOUND")
                slot = self.config_data["emulators"][sid]
                row["path"].setText(slot.get("path") or slot.get("flatpak_id", ""))
            elif config_mod.is_emulator_configured(self.config_data, sid):
                self._set_state(sid, "READY")
            else:
                self._set_state(sid, "NEEDED")

    def _install_system(self, sid):
        manifest = self.rows[sid]["manifest"]
        if manifest is None:
            return
        self._install_manifests((manifest,), (sid,))

    def _install_recommended_set(self):
        if self.platform_key == "linux-aarch64":
            manifest = self.registry.get("retroarch")
            manifests = (manifest,) if manifest else ()
        else:
            unique = {}
            for row in self.rows.values():
                if row["manifest"]:
                    unique[row["manifest"].id] = row["manifest"]
            manifests = tuple(unique.values())
        sids = tuple(sid for sid, row in self.rows.items() if row["manifest"] in manifests)
        self._install_manifests(manifests, sids)

    def _install_manifests(self, manifests, sids):
        available = tuple(m for m in manifests if m.strategy_for(self.platform_key).available)
        if not available:
            return

        def operation(progress):
            results = {}
            for manifest in available:
                results[manifest.id] = installer.install(
                    manifest.id,
                    "managed",
                    manifest.strategy_for(self.platform_key),
                    assume_yes=True,
                    progress=progress,
                )
            return results

        self._start_worker(
            operation,
            self._install_complete,
            sids,
            lambda done, total: self._update_progress(sids, done, total),
        )
        for sid in sids:
            self.rows[sid]["progress"].setRange(0, 0)

    def _update_progress(self, sids, done, total):
        for sid in sids:
            bar = self.rows[sid]["progress"]
            bar.setRange(0, total if total else 0)
            if total:
                bar.setValue(done)

    def _install_complete(self, installed):
        detected = {}
        for emulator_id, result in installed.items():
            manifest = self.registry.get(emulator_id)
            if isinstance(result, installer.InstallInstruction):
                self.instruction.setText(result.command)
                self.instruction.setVisible(True)
                for sid, row in self.rows.items():
                    if row["manifest"] and row["manifest"].id == emulator_id:
                        self._set_state(sid, "NEEDED")
                continue
            if isinstance(result, Path):
                detected[emulator_id] = discovery.DetectResult(True, "exe", str(result))
            else:
                detected[emulator_id] = discovery.DetectResult(True, "flatpak", str(result))
            if manifest and emulator_id == "retroarch" and self.platform_key == "linux-aarch64":
                # The legacy global RetroArch mode only accepts a local executable.
                # Flatpak is wired through each system's PR3 launcher configuration.
                self.config_data["use_retroarch"] = isinstance(result, Path)
                self.config_data["retroarch_path"] = "" if not isinstance(result, Path) else str(result)
                self.config_data["retroarch_cores"].update(manifest.cores)
        self.config_data = discovery.apply_detection(self.config_data, detected, self.registry)
        for sid, row in self.rows.items():
            manifest = row["manifest"]
            if manifest and manifest.id in detected:
                slot = self.config_data["emulators"][sid]
                row["path"].setText(slot.get("path") or slot.get("flatpak_id", ""))
                self._set_state(sid, "READY")
        config_mod.save_config(self.config_data)
        self._run_audit()

    def _run_audit(self):
        manifest = audit_mod.load_test_rom_manifest()
        configured = {sid: entry for sid, entry in manifest.items() if entry.get("path", "").strip()}
        if not configured:
            return
        results = audit_mod.audit_test_roms(self.config_data, configured)
        audit_lines = [f"{item['system'].upper()}: {item['status'].upper()} - {item['message']}" for item in results]
        audit_text = "POST-INSTALL AUDIT\n" + "\n".join(audit_lines)
        self.audit_results.setText(audit_text)
        self.audit_results.setVisible(True)
        logging.info("Post-install audit:\n%s", audit_text)

    def _open_url(self, rec):
        if rec.get("url"):
            QDesktopServices.openUrl(QUrl(rec["url"]))

    def _browse(self, sid):
        row = self.rows[sid]
        picked, _ = QFileDialog.getOpenFileName(self, "Choose emulator", row["path"].text())
        if picked:
            row["path"].setText(picked)
            self._set_state(sid, "READY")

    def _use_retroarch_for_all(self):
        retroarch = shutil.which("retroarch") or shutil.which("retroarch.exe") or ""
        manifest = self.registry.get("retroarch")
        if manifest:
            self.config_data["retroarch_cores"].update(manifest.cores)

        if retroarch:
            self.config_data["use_retroarch"] = True
            self.config_data["retroarch_path"] = retroarch
            for sid, row in self.rows.items():
                row["path"].setText(retroarch)
                self._set_state(sid, "READY")
        elif self.platform_key == "linux-aarch64" and manifest and manifest.detect.flatpak_id:
            self.config_data["use_retroarch"] = False
            self.config_data["retroarch_path"] = ""
            retroarch_flatpak = manifest.detect.flatpak_id
            for sid, row in self.rows.items():
                slot = self.config_data["emulators"].setdefault(sid, {})
                core_name = self.config_data["retroarch_cores"].get(sid, "")
                slot.update({
                    "launch_type": "flatpak",
                    "flatpak_id": retroarch_flatpak,
                    "path": "",
                    "args": manifest.profiles[0].args.replace("{core}", core_name) if core_name else manifest.profiles[0].args,
                    "profile": "retroarch",
                })
                row["path"].setText(retroarch_flatpak)
                self._set_state(sid, "READY")
        else:
            for sid, row in self.rows.items():
                row["path"].setText("")
                self._set_state(sid, "NEEDED")

    def _save(self):
        updated = config_mod.migrate_config(copy.deepcopy(self.config_data))
        updated["setup"]["mode"] = "easy"
        updated["setup"]["completed"] = True
        for sid, widgets in self.rows.items():
            slot = updated.get("emulators", {}).get(sid, {})
            if slot.get("launch_type") == "flatpak" and slot.get("flatpak_id"):
                slot["path"] = ""
                continue
            updated = recommend.apply_recommended_emulator(
                updated,
                sid,
                path=widgets["path"].text().strip(),
                platform_key=self.platform_key,
            )
        config_mod.save_config(updated)
        self.config_data = updated
        self.accept()

    def closeEvent(self, event):
        for thread in tuple(self._threads):
            thread.quit()
            thread.wait(1000)
        super().closeEvent(event)
