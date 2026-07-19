"""Box-art thumbnails in the library model (DecorationRole)."""

import os
import tempfile
import unittest
from pathlib import Path

try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon, QImage, QPixmapCache
    from PySide6.QtWidgets import QApplication

    from retrovault.ui.library_model import LibraryModel

    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False


@unittest.skipUnless(QT_AVAILABLE, "PySide6 is not installed")
class BoxartDecorationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        QPixmapCache.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.png = Path(self.tmp.name) / "boxart.png"
        QImage(8, 8, QImage.Format.Format_RGB32).save(str(self.png), "PNG")

    def tearDown(self):
        self.tmp.cleanup()

    def _icon(self, rom):
        model = LibraryModel([rom])
        return model.data(model.index(0, 0), Qt.ItemDataRole.DecorationRole)

    def test_icon_returned_when_boxart_present(self):
        rom = {"name": "G", "system": "nes", "media": {"boxart": str(self.png)}}
        icon = self._icon(rom)
        self.assertIsInstance(icon, QIcon)
        self.assertFalse(icon.isNull())

    def test_none_when_no_media(self):
        self.assertIsNone(self._icon({"name": "G", "system": "nes"}))

    def test_none_when_boxart_file_missing(self):
        rom = {"name": "G", "system": "nes", "media": {"boxart": str(self.png) + ".missing"}}
        self.assertIsNone(self._icon(rom))


if __name__ == "__main__":
    unittest.main()
