import os
import unittest

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from retrovault.ui.main_window import MainWindow

    PYSIDE6_AVAILABLE = True
except ImportError:
    PYSIDE6_AVAILABLE = False


@unittest.skipUnless(PYSIDE6_AVAILABLE, "PySide6 is not installed")
class MainWindowSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_main_window_title_and_search_box(self):
        window = MainWindow()
        try:
            self.assertEqual(window.windowTitle(), "RetroVault")
            self.assertIsNotNone(window.search_box)
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
