import copy
import os
import subprocess
import sys
import unittest

from retrovault.core import launch
from retrovault.core.config import DEFAULT_CONFIG

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    from retrovault.ui.launch_session import LaunchSession

    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False


HARMLESS_CMD = [sys.executable, "-c", "import sys; sys.exit(0)"]
HARMLESS_EXIT_CMD = [sys.executable, "-c", "import sys; sys.exit(7)"]
LONG_RUNNING_CMD = [sys.executable, "-c", "import time; time.sleep(30)"]


class StartLaunchProcessTests(unittest.TestCase):
    def setUp(self):
        self.rom = {
            "name": "Mario Kart 64",
            "path": r"C:\ROMs\Nintendo 64\Mario Kart 64.z64",
            "system": "n64",
            "ext": ".z64",
        }
        self.config = copy.deepcopy(DEFAULT_CONFIG)

    def test_returns_popen_for_valid_command(self):
        original = launch.build_launch_command
        launch.build_launch_command = lambda *a, **k: (list(HARMLESS_CMD), None)
        try:
            proc, error = launch.start_launch_process(self.rom, self.config)
        finally:
            launch.build_launch_command = original

        self.assertIsNone(error)
        self.assertIsInstance(proc, subprocess.Popen)
        # Clean up the short-lived helper process.
        proc.wait(timeout=5)

    def test_returns_error_when_validation_fails(self):
        # No emulator configured and the ROM path does not exist -> validation fails.
        proc, error = launch.start_launch_process(self.rom, self.config)

        self.assertIsNone(proc)
        self.assertIsNotNone(error)


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class LaunchSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _record(self, session):
        events = []
        session.starting.connect(lambda: events.append(("starting", None)))
        session.started.connect(lambda: events.append(("started", None)))
        session.failed.connect(lambda msg: events.append(("failed", msg)))
        session.exited.connect(lambda code: events.append(("exited", code)))
        return events

    def _wait_for_exit(self, session, timeout_ms=2000):
        loop = QEventLoop()
        session.exited.connect(lambda _code: loop.quit())
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(timeout_ms)
        loop.exec()

    def test_emits_starting_started_exited_for_short_process(self):
        session = LaunchSession()
        events = self._record(session)

        proc = subprocess.Popen(HARMLESS_EXIT_CMD)
        original = launch.start_launch_process
        launch_session_mod = sys.modules["retrovault.ui.launch_session"]
        launch_session_mod.start_launch_process = lambda rom, config: (proc, None)
        try:
            session.launch({}, {})
            self._wait_for_exit(session)
        finally:
            launch_session_mod.start_launch_process = original

        names = [name for name, _ in events]
        self.assertEqual(names, ["starting", "started", "exited"])
        self.assertEqual(events[-1], ("exited", 7))
        self.assertFalse(session.is_running())

    def test_emits_failed_when_start_returns_error(self):
        session = LaunchSession()
        events = self._record(session)

        launch_session_mod = sys.modules["retrovault.ui.launch_session"]
        original = launch.start_launch_process
        launch_session_mod.start_launch_process = lambda rom, config: (None, "boom")
        try:
            session.launch({}, {})
        finally:
            launch_session_mod.start_launch_process = original

        names = [name for name, _ in events]
        self.assertEqual(names, ["starting", "failed"])
        self.assertEqual(events[-1], ("failed", "boom"))
        self.assertNotIn("started", names)
        self.assertNotIn("exited", names)
        self.assertFalse(session.is_running())

    def test_unwaitable_success_emits_started_then_exited(self):
        session = LaunchSession()
        events = self._record(session)

        launch_session_mod = sys.modules["retrovault.ui.launch_session"]
        original = launch.start_launch_process
        launch_session_mod.start_launch_process = lambda rom, config: (None, None)
        try:
            session.launch({}, {})
        finally:
            launch_session_mod.start_launch_process = original

        names = [name for name, _ in events]
        self.assertEqual(names, ["starting", "started", "exited"])
        self.assertEqual(events[-1], ("exited", LaunchSession.UNWAITABLE_EXIT_CODE))
        self.assertFalse(session.is_running())

    # ── shutdown (C5) ─────────────────────────────────────────────────────────
    def test_shutdown_without_a_session_is_a_noop(self):
        # Never launched: no wait-thread to join, returns True immediately.
        self.assertTrue(LaunchSession().shutdown())

    def test_shutdown_after_exit_returns_true(self):
        session = LaunchSession()
        self._record(session)
        proc = subprocess.Popen(HARMLESS_EXIT_CMD)
        launch_session_mod = sys.modules["retrovault.ui.launch_session"]
        original = launch_session_mod.start_launch_process
        launch_session_mod.start_launch_process = lambda rom, config: (proc, None)
        try:
            session.launch({}, {})
            self._wait_for_exit(session)
        finally:
            launch_session_mod.start_launch_process = original
        # The observer thread has finished and been cleared; shutdown is clean.
        self.assertTrue(session.shutdown())

    def test_shutdown_of_running_session_times_out_and_detaches(self):
        session = LaunchSession()
        proc = subprocess.Popen(LONG_RUNNING_CMD)
        launch_session_mod = sys.modules["retrovault.ui.launch_session"]
        original = launch_session_mod.start_launch_process
        launch_session_mod.start_launch_process = lambda rom, config: (proc, None)
        thread = None
        try:
            session.launch({}, {})
            thread = session._thread
            self.assertIsNotNone(thread)
            # Emulator still running: a short wait times out (False), and the
            # thread's signals are severed so it can't call into a torn-down app.
            self.assertFalse(session.shutdown(timeout_ms=100))
        finally:
            launch_session_mod.start_launch_process = original
            proc.terminate()
            if thread is not None:
                thread.wait(5000)  # join so the test leaves no running QThread


if __name__ == "__main__":
    unittest.main()
