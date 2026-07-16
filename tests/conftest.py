"""Shared pytest fixtures.

Keeps the GUI tests hermetic. ``MainWindow.__init__`` schedules the first-run
setup wizard (``QTimer.singleShot(250, self.on_setup)``) whenever the loaded
config has ``setup.completed`` False — which is the case on any machine without
a saved config, including CI. If a test then spins the Qt event loop for more
than ~250 ms (e.g. the launch-session debounce waits), that wizard pops as a
modal ``exec()`` with nothing to dismiss it and the test hangs forever.

Real launches are unaffected; tests just should not depend on the developer's
ambient config. This autouse fixture turns the auto-wizard into a no-op for the
whole test session. It is guarded so suites without PySide6 still run.
"""

import os

import pytest


@pytest.fixture(autouse=True)
def _disable_first_run_wizard():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from unittest import mock

        from retrovault.ui.main_window import MainWindow
    except Exception:
        # PySide6 not installed / import failed — nothing to patch.
        yield
        return
    with mock.patch.object(MainWindow, "on_setup", lambda self: None):
        yield
