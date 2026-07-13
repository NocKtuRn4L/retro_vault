"""Headless tests for PR10 launch-session integration in MainWindow.

These verify the launch path now flows through the ``LaunchCoordinator`` and that
the coordinator's signals drive controller suspend/resume, control disabling,
foreground restore, view restore, the launch-failed dialog, and the resume
debounce. No real emulator process is started: a fake session drives the four
launch signals manually, or a fake coordinator records the launch call.
"""

import os
import unittest
from unittest import mock

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from retrovault.input.backend import NullBackend
    from retrovault.ui import launch_overlay as lo
    from retrovault.ui import main_window as mw
    from retrovault.ui.launch_overlay import LaunchCoordinator
    from retrovault.ui.main_window import MainWindow

    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False


FAKE_LIBRARY = [
    {"name": "Alpha", "system": "nes", "ext": ".nes", "path": "/roms/alpha.nes"},
    {"name": "Bravo", "system": "nes", "ext": ".nes", "path": "/roms/bravo.nes"},
    {"name": "Charlie", "system": "snes", "ext": ".sfc", "path": "/roms/charlie.sfc"},
]


class FakeSession(QObject):
    """Stand-in exposing the same four signals as LaunchSession."""

    starting = Signal()
    started = Signal()
    failed = Signal(str)
    exited = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.launch_calls = []

    def launch(self, rom, config):
        self.launch_calls.append((rom, config))


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class SessionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # Shrink the coordinator's "returning" grace so the finished() transition
        # fires quickly, and use a debounce comfortably larger than that residual
        # so the resume timing is deterministic. Both restored in tearDown.
        self._orig_debounce = mw.CONTROLLER_RESUME_DEBOUNCE_MS
        self._orig_grace = lo.RETURN_GRACE_MS
        mw.CONTROLLER_RESUME_DEBOUNCE_MS = 300
        lo.RETURN_GRACE_MS = 10

    def tearDown(self):
        mw.CONTROLLER_RESUME_DEBOUNCE_MS = self._orig_debounce
        lo.RETURN_GRACE_MS = self._orig_grace

    def _make_window(self, session=None):
        """Build a MainWindow whose coordinator drives a fake (real coordinator).

        Returns ``(window, session)``. The coordinator is the real
        ``LaunchCoordinator`` but its session factory yields ``session`` so no
        real process is launched.
        """
        session = session or FakeSession()

        def factory(host, **kwargs):
            return LaunchCoordinator(host, session_factory=lambda: session, **kwargs)

        with (
            mock.patch.object(mw, "load_library", return_value=list(FAKE_LIBRARY)),
            mock.patch.object(MainWindow, "_make_controller_backend", return_value=NullBackend()),
            mock.patch.object(mw, "LaunchCoordinator", side_effect=factory),
        ):
            window = MainWindow()
        return window, session

    def _wait_past_debounce(self):
        QApplication.processEvents()
        QTest.qWait(mw.CONTROLLER_RESUME_DEBOUNCE_MS + 40)
        QApplication.processEvents()

    # ── Routing ──────────────────────────────────────────────────────────────
    def test_launch_selected_routes_to_coordinator(self):
        window, session = self._make_window()
        try:
            window._select_proxy_row(0)
            rom = window._selected_rom()
            window.on_launch_selected()
            self.assertEqual(session.launch_calls, [(rom, window.config_data)])
        finally:
            window.close()

    def test_launch_selected_without_selection_does_not_launch(self):
        window, session = self._make_window()
        try:
            window.table.selectionModel().clearSelection()
            window.on_launch_selected()
            self.assertEqual(session.launch_calls, [])
        finally:
            window.close()

    # ── input_disabled(True): suspend + disable ──────────────────────────────
    def test_input_disabled_true_pauses_controller_and_disables_controls(self):
        window, session = self._make_window()
        try:
            with mock.patch.object(window.controller, "pause") as pause:
                window._select_proxy_row(0)
                window.on_launch_selected()  # emits input_disabled(True) synchronously
                self.assertTrue(window._controller_busy)
                pause.assert_called_once()
                self.assertFalse(window.centralWidget().isEnabled())
        finally:
            window.close()

    # ── finished(): restore + resume only after debounce ─────────────────────
    def test_finished_restores_view_foreground_and_resumes_after_debounce(self):
        window, session = self._make_window()
        try:
            window.show()
            # Select Bravo (row for /roms/bravo.nes) so we can prove it is restored.
            target_row = window._find_proxy_row_by_path("/roms/bravo.nes")
            window._select_proxy_row(target_row)
            window.table.verticalScrollBar().setValue(0)

            with (
                mock.patch.object(window, "restore_foreground") as restore_fg,
                mock.patch.object(window.controller, "resume") as resume,
            ):
                window.on_launch_selected()
                session.started.emit()
                session.exited.emit(0)
                # Move selection away to prove restore re-selects the saved ROM.
                window._select_proxy_row(window._find_proxy_row_by_path("/roms/alpha.nes"))

                # Pump past the (shrunk) RETURN_GRACE_MS overlay timer, which then
                # emits input_disabled(False) + finished. This stays well under
                # the 300ms resume debounce.
                QTest.qWait(60)
                QApplication.processEvents()

                # Controls re-enabled by input_disabled(False)...
                self.assertTrue(window.centralWidget().isEnabled())
                # ...foreground restored + view restored by finished()...
                restore_fg.assert_called()
                self.assertEqual(
                    window._selected_rom().get("path"), "/roms/bravo.nes"
                )
                # ...but the controller must NOT be resumed synchronously.
                resume.assert_not_called()
                self.assertTrue(window._controller_busy)

                # After the debounce elapses, resume fires and busy clears.
                self._wait_past_debounce()
                resume.assert_called_once()
                self.assertFalse(window._controller_busy)
        finally:
            window.close()

    def test_input_disabled_false_does_not_resume_synchronously(self):
        window, session = self._make_window()
        try:
            with mock.patch.object(window.controller, "resume") as resume:
                window._select_proxy_row(0)
                window.on_launch_selected()
                # Drive the disable(False) handler directly.
                window._on_launch_input_disabled(False)
                resume.assert_not_called()
                self.assertTrue(window.centralWidget().isEnabled())
        finally:
            window.close()

    # ── failed(): warning dialog + recover + debounced resume ────────────────
    def test_failed_shows_warning_reenables_and_resumes_after_debounce(self):
        window, session = self._make_window()
        try:
            with (
                mock.patch.object(mw.QMessageBox, "warning") as warning,
                mock.patch.object(window, "restore_foreground") as restore_fg,
                mock.patch.object(window.controller, "resume") as resume,
            ):
                window._select_proxy_row(0)
                window.on_launch_selected()
                session.failed.emit("boom")

                warning.assert_called_once()
                self.assertEqual(warning.call_args.args[2], "boom")
                restore_fg.assert_called()
                self.assertTrue(window.centralWidget().isEnabled())
                resume.assert_not_called()  # debounced

                self._wait_past_debounce()
                resume.assert_called_once()
                self.assertFalse(window._controller_busy)
        finally:
            window.close()

    # ── crash / instant-exit recovery ────────────────────────────────────────
    def test_instant_nonzero_exit_recovers_without_dialog(self):
        window, session = self._make_window()
        try:
            with (
                mock.patch.object(mw.QMessageBox, "warning") as warning,
                mock.patch.object(window.controller, "resume") as resume,
            ):
                window._select_proxy_row(0)
                window.on_launch_selected()
                # Un-waitable/instant crash: started then nonzero exit at once.
                session.started.emit()
                session.exited.emit(1)

                QTest.qWait(60)
                QApplication.processEvents()

                # No error dialog for a nonzero return code.
                warning.assert_not_called()
                # Controls re-enabled, no stuck disabled state.
                self.assertTrue(window.centralWidget().isEnabled())

                self._wait_past_debounce()
                resume.assert_called_once()
                self.assertFalse(window._controller_busy)
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
