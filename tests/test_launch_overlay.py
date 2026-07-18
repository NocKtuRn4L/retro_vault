import os
import unittest

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QObject, Signal
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QWidget

    from retrovault.ui import launch_overlay as launch_overlay_module
    from retrovault.ui.launch_overlay import (
        LAUNCHING_CAPTION,
        RETURNING_CAPTION,
        LaunchCoordinator,
        LaunchOverlay,
    )

    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False


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
class LaunchOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_overlay(self):
        parent = QWidget()
        parent.resize(400, 300)
        overlay = LaunchOverlay(parent)
        return parent, overlay

    def test_show_launching_visible_with_caption(self):
        parent, overlay = self._make_overlay()
        parent.show()
        try:
            overlay.show_launching()
            self.assertTrue(overlay.isVisible())
            self.assertEqual(overlay.caption(), LAUNCHING_CAPTION)
        finally:
            parent.close()

    def test_show_returning_swaps_caption(self):
        parent, overlay = self._make_overlay()
        parent.show()
        try:
            overlay.show_launching()
            overlay.show_returning()
            self.assertTrue(overlay.isVisible())
            self.assertEqual(overlay.caption(), RETURNING_CAPTION)
        finally:
            parent.close()

    def test_hide_hides_overlay(self):
        parent, overlay = self._make_overlay()
        parent.show()
        try:
            overlay.show_launching()
            overlay.hide()
            self.assertFalse(overlay.isVisible())
        finally:
            parent.close()

    def test_cover_tracks_parent_geometry(self):
        parent, overlay = self._make_overlay()
        parent.show()
        try:
            parent.resize(640, 480)
            QApplication.processEvents()
            self.assertEqual(overlay.size(), parent.size())
        finally:
            parent.close()


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class LaunchCoordinatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _make_coordinator(self):
        host = QWidget()
        host.resize(400, 300)
        session = FakeSession()
        events = {
            "save_view": 0,
            "restore_view": 0,
            "input_disabled": [],
            "finished": 0,
            "failed": [],
        }

        def save_view():
            events["save_view"] += 1

        def restore_view():
            events["restore_view"] += 1

        coord = LaunchCoordinator(
            host,
            session_factory=lambda: session,
            save_view=save_view,
            restore_view=restore_view,
        )
        coord.input_disabled.connect(lambda flag: events["input_disabled"].append(flag))
        coord.finished.connect(lambda: events.__setitem__("finished", events["finished"] + 1))
        coord.failed.connect(lambda msg: events["failed"].append(msg))
        events["session_finished"] = []
        coord.session_finished.connect(lambda info: events["session_finished"].append(info))
        return host, session, coord, events

    def test_launch_shows_overlay_disables_input_saves_view(self):
        host, session, coord, events = self._make_coordinator()
        host.show()
        try:
            coord.launch({"name": "rom"}, {"cfg": True})
            self.assertTrue(coord.overlay.isVisible())
            self.assertEqual(coord.overlay.caption(), LAUNCHING_CAPTION)
            self.assertEqual(events["input_disabled"], [True])
            self.assertEqual(events["save_view"], 1)
            self.assertEqual(session.launch_calls, [({"name": "rom"}, {"cfg": True})])
        finally:
            host.close()

    def test_started_hides_overlay(self):
        host, session, coord, events = self._make_coordinator()
        host.show()
        try:
            coord.launch({}, {})
            session.started.emit()
            self.assertFalse(coord.overlay.isVisible())
        finally:
            host.close()

    def test_exited_returns_restores_and_finishes(self):
        host, session, coord, events = self._make_coordinator()
        host.show()
        try:
            coord.launch({}, {})
            session.started.emit()
            session.exited.emit(0)
            # The returning caption is shown immediately.
            self.assertTrue(coord.overlay.isVisible())
            self.assertEqual(coord.overlay.caption(), RETURNING_CAPTION)
            # Pump the event loop past the singleShot grace timer.
            QTest.qWait(700)
            QApplication.processEvents()
            self.assertFalse(coord.overlay.isVisible())
            self.assertEqual(events["restore_view"], 1)
            self.assertEqual(events["input_disabled"], [True, False])
            self.assertEqual(events["finished"], 1)
        finally:
            host.close()

    def test_session_finished_reports_rom_path_and_elapsed(self):
        host, session, coord, events = self._make_coordinator()
        host.show()
        # Feed a controlled monotonic delta: launch@100.0, exit@145.0 -> 45.0s.
        original = launch_overlay_module.time.monotonic
        ticks = iter([100.0, 145.0])
        launch_overlay_module.time.monotonic = lambda: next(ticks)
        try:
            coord.launch({"path": "/roms/game.nes"}, {})
            session.started.emit()
            session.exited.emit(0)
            QTest.qWait(700)
            QApplication.processEvents()
            self.assertEqual(events["finished"], 1)
            self.assertEqual(len(events["session_finished"]), 1)
            info = events["session_finished"][0]
            self.assertEqual(info["rom_path"], "/roms/game.nes")
            self.assertAlmostEqual(info["elapsed_seconds"], 45.0, places=3)
        finally:
            launch_overlay_module.time.monotonic = original
            host.close()

    def test_failed_launch_emits_no_session_finished(self):
        host, session, coord, events = self._make_coordinator()
        host.show()
        try:
            coord.launch({"path": "/roms/game.nes"}, {})
            session.failed.emit("boom")
            QTest.qWait(50)
            QApplication.processEvents()
            self.assertEqual(events["session_finished"], [])
        finally:
            host.close()

    def test_failed_reemits_reenables_and_hides(self):
        host, session, coord, events = self._make_coordinator()
        host.show()
        try:
            coord.launch({}, {})
            session.failed.emit("boom")
            self.assertFalse(coord.overlay.isVisible())
            self.assertEqual(events["failed"], ["boom"])
            self.assertEqual(events["input_disabled"], [True, False])
            self.assertEqual(events["finished"], 0)
        finally:
            host.close()


if __name__ == "__main__":
    unittest.main()
