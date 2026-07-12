"""Qt model/proxy classes for the ROM library."""

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor


class LibraryModel(QAbstractTableModel):
    COLUMNS = ("GAME", "SYSTEM", "EXT")

    def __init__(self, library=None, systems=None, parent=None):
        super().__init__(parent)
        self.library = list(library or [])
        self.systems = systems or {}

    def set_library(self, library):
        self.beginResetModel()
        self.library = list(library or [])
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.library)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.COLUMNS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        rom = self.library[index.row()]
        system_key = rom.get("system", "")
        system = self.systems.get(system_key, {})

        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == 0:
                return rom.get("name", "")
            if index.column() == 1:
                return system.get("short") or system.get("name") or system_key.upper()
            if index.column() == 2:
                return rom.get("ext", "")

        if role == Qt.ItemDataRole.ToolTipRole:
            return rom.get("path", "")

        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 1:
            return QColor(system.get("color", "#ff3c3c"))

        if role == Qt.ItemDataRole.UserRole:
            return rom

        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.COLUMNS[section]
        return None

    def rom_at(self, row):
        if 0 <= row < len(self.library):
            return self.library[row]
        return None


class LibraryFilterProxyModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.system_key = ""
        self.search_text = ""
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_system_filter(self, system_key):
        self.system_key = system_key or ""
        self._refresh_filter()

    def set_search_text(self, text):
        self.search_text = (text or "").strip().lower()
        self._refresh_filter()

    def _refresh_filter(self):
        if hasattr(self, "beginFilterChange"):
            self.beginFilterChange()
            self.endFilterChange()
        else:
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        rom = model.rom_at(source_row)
        if not rom:
            return False
        if self.system_key and rom.get("system") != self.system_key:
            return False
        if self.search_text and self.search_text not in rom.get("name", "").lower():
            return False
        return True
