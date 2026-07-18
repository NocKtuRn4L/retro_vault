"""Tests for MainWindow's play-time recording handler (PR C, #5).

These exercise ``MainWindow._on_play_session_finished`` in isolation using a
lightweight stub host plus a real ``LibraryModel``, so the accumulation logic
and the sub-threshold drop are verified without constructing the full window.
"""

import os
import unittest

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from retrovault.ui import main_window as main_window_module
    from retrovault.ui.launch_overlay import MIN_PLAY_SECONDS
    from retrovault.ui.library_model import LibraryModel
    from retrovault.ui.main_window import MainWindow

    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False


class _StubHost:
    """Minimal stand-in carrying just what the handler touches."""

    def __init__(self, library):
        self.library = library
        self.model = LibraryModel(library, {})
        self.dataChanged_rows = []
        self.model.dataChanged.connect(
            lambda tl, br, *_: self.dataChanged_rows.append(
                (tl.row(), br.row(), tl.column(), br.column())
            )
        )


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class PlayTimeTrackingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        # Prevent the handler from touching disk.
        self._saved = []
        self._orig_save = main_window_module.save_library
        main_window_module.save_library = lambda lib: self._saved.append(lib)

    def tearDown(self):
        main_window_module.save_library = self._orig_save

    def _call(self, host, info):
        # Invoke the real handler bound to the stub host.
        MainWindow._on_play_session_finished(host, info)

    def test_accumulates_seconds_and_increments_count(self):
        lib = [{"path": "/roms/a.nes", "name": "A"}]
        host = _StubHost(lib)
        self._call(host, {"rom_path": "/roms/a.nes", "elapsed_seconds": 45.7})

        self.assertEqual(lib[0]["play_seconds"], 45)
        self.assertEqual(lib[0]["play_count"], 1)
        self.assertIn("last_played", lib[0])
        self.assertTrue(lib[0]["last_played"].endswith("+00:00"))
        self.assertEqual(len(self._saved), 1)
        self.assertEqual(
            host.dataChanged_rows, [(0, 0, 0, host.model.columnCount() - 1)]
        )

    def test_accumulates_across_multiple_sessions(self):
        lib = [{"path": "/roms/a.nes", "name": "A", "play_seconds": 30, "play_count": 2}]
        host = _StubHost(lib)
        self._call(host, {"rom_path": "/roms/a.nes", "elapsed_seconds": 20.0})

        self.assertEqual(lib[0]["play_seconds"], 50)
        self.assertEqual(lib[0]["play_count"], 3)

    def test_sub_threshold_session_is_dropped(self):
        lib = [{"path": "/roms/a.nes", "name": "A"}]
        host = _StubHost(lib)
        self._call(
            host,
            {"rom_path": "/roms/a.nes", "elapsed_seconds": MIN_PLAY_SECONDS - 0.1},
        )

        self.assertNotIn("play_seconds", lib[0])
        self.assertNotIn("play_count", lib[0])
        self.assertNotIn("last_played", lib[0])
        self.assertEqual(self._saved, [])
        self.assertEqual(host.dataChanged_rows, [])

    def test_unknown_rom_path_is_ignored(self):
        lib = [{"path": "/roms/a.nes", "name": "A"}]
        host = _StubHost(lib)
        self._call(host, {"rom_path": "/roms/missing.nes", "elapsed_seconds": 60.0})

        self.assertNotIn("play_seconds", lib[0])
        self.assertEqual(self._saved, [])

    def test_malformed_payload_is_ignored(self):
        lib = [{"path": "/roms/a.nes", "name": "A"}]
        host = _StubHost(lib)
        self._call(host, None)
        self._call(host, {"rom_path": "/roms/a.nes"})
        self._call(host, {"elapsed_seconds": 60.0})

        self.assertNotIn("play_seconds", lib[0])
        self.assertEqual(self._saved, [])


if __name__ == "__main__":
    unittest.main()
