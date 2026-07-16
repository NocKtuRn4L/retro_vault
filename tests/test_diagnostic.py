"""Hardware-free tests for the controller diagnostic command."""

import io
import unittest
from contextlib import redirect_stdout

from retrovault.input import diagnostic
from retrovault.input.backend import NEUTRAL_STATE, BackendState, NullBackend


class _FakeDisconnectedBackend:
    """Stand-in SdlBackend that never sees a controller (deterministic)."""

    def __init__(self, *args, **kwargs):
        self.started = False
        self.stopped = False
        self.polls = 0

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def poll(self) -> BackendState:
        self.polls += 1
        return NEUTRAL_STATE

    def is_connected(self) -> bool:
        return False


class _FakeConnectedBackend(_FakeDisconnectedBackend):
    """Fake backend reporting a connected controller with one button held."""

    def poll(self) -> BackendState:
        self.polls += 1
        return BackendState(buttons=frozenset({"face_south"}), axes=(0.5, -0.25))

    def is_connected(self) -> bool:
        return True


class SelfTestModeTests(unittest.TestCase):
    def test_self_test_returns_zero_and_prints_ok(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            rc = diagnostic.main(["--self-test"])
        self.assertEqual(rc, 0)
        self.assertIn("OK", buffer.getvalue())

    def test_self_test_uses_null_backend(self):
        # The self-test path must not touch SdlBackend at all.
        constructed = []

        def _boom(*args, **kwargs):  # pragma: no cover - must never be called
            constructed.append((args, kwargs))
            raise AssertionError("self-test must not construct SdlBackend")

        original = diagnostic.SdlBackend
        diagnostic.SdlBackend = _boom
        try:
            rc = diagnostic.main(["--self-test"])
        finally:
            diagnostic.SdlBackend = original
        self.assertEqual(rc, 0)
        self.assertEqual(constructed, [])

    def test_null_backend_polls_neutral(self):
        # Guards the invariant the self-test relies on.
        backend = NullBackend()
        backend.start()
        self.assertEqual(backend.poll(), NEUTRAL_STATE)
        self.assertFalse(backend.is_connected())
        backend.stop()


class OnceModeTests(unittest.TestCase):
    def _run_once_with(self, fake_cls) -> str:
        original = diagnostic.SdlBackend
        diagnostic.SdlBackend = fake_cls
        buffer = io.StringIO()
        try:
            with redirect_stdout(buffer):
                rc = diagnostic.main(["--once"])
        finally:
            diagnostic.SdlBackend = original
        self.assertEqual(rc, 0)
        return buffer.getvalue()

    def test_once_returns_zero_when_no_controller(self):
        output = self._run_once_with(_FakeDisconnectedBackend)
        self.assertIn("controller detected: no", output)

    def test_default_no_args_behaves_like_once(self):
        original = diagnostic.SdlBackend
        diagnostic.SdlBackend = _FakeDisconnectedBackend
        buffer = io.StringIO()
        try:
            with redirect_stdout(buffer):
                rc = diagnostic.main([])
        finally:
            diagnostic.SdlBackend = original
        self.assertEqual(rc, 0)
        self.assertIn("controller detected: no", buffer.getvalue())

    def test_once_reports_connected_controller_state(self):
        output = self._run_once_with(_FakeConnectedBackend)
        self.assertIn("controller detected: yes", output)
        self.assertIn("face_south", output)


class WatchModeTests(unittest.TestCase):
    def test_watch_is_bounded_and_returns_zero(self):
        original = diagnostic.SdlBackend
        diagnostic.SdlBackend = _FakeDisconnectedBackend
        buffer = io.StringIO()
        try:
            with redirect_stdout(buffer):
                # A tiny duration keeps the test fast and bounded.
                rc = diagnostic.main(["--watch", "0"])
        finally:
            diagnostic.SdlBackend = original
        self.assertEqual(rc, 0)
        self.assertTrue(buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
