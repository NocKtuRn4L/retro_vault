import os
import unittest

from qt_support import qt_app

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from retrovault.ui.main_window import MainWindow

    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class MainWindowSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qt_app()

    def test_main_window_title_and_search_box(self):
        window = MainWindow()
        try:
            self.assertEqual(window.windowTitle(), "RetroVault")
            self.assertIsNotNone(window.search_box)
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
