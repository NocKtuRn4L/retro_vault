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


# Sentinel filter keys understood by ``set_system_filter``. A plain system id
# (e.g. "nes") filters by that system; these sentinels select virtual views
# instead. ``collection:<name>`` is matched by prefix, not by equality.
FAVORITES_FILTER = "__favorites__"
RECENT_FILTER = "__recent__"
COLLECTION_PREFIX = "collection:"

# How many most-recently-played games the "Recently Played" view shows.
RECENT_LIMIT = 50


class LibraryFilterProxyModel(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.system_key = ""
        self.search_text = ""
        # name -> set of member paths, pushed in by the window from collections.json.
        self._collections = {}
        # Paths of the RECENT_LIMIT most-recently-played games; recomputed
        # whenever the "__recent__" view is (re)selected.
        self._recent_paths = set()
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)

    def set_system_filter(self, system_key):
        self.system_key = system_key or ""
        if self.system_key == RECENT_FILTER:
            self._compute_recent()
        # invalidate() re-runs both filtering AND sorting so the "__recent__"
        # view's custom lessThan ordering takes effect (and is undone on exit).
        self.invalidate()

    def set_collections(self, collections):
        """Store collections as ``{name: set(paths)}`` for ``collection:<name>`` filtering.

        The sidebar carries a bare ``collection:<name>`` string, so the proxy
        needs the membership data pushed in separately by the window.
        """
        self._collections = {
            c.get("name", ""): set(c.get("paths", []) or [])
            for c in (collections or [])
        }
        if self.system_key.startswith(COLLECTION_PREFIX):
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

    def _compute_recent(self):
        """Cache the paths of the most-recently-played games (desc, capped)."""
        self._recent_paths = set()
        model = self.sourceModel()
        if model is None:
            return
        played = []
        for row in range(model.rowCount()):
            rom = model.rom_at(row)
            if rom and rom.get("last_played"):
                played.append(rom)
        played.sort(key=lambda r: r.get("last_played") or "", reverse=True)
        self._recent_paths = {r.get("path") for r in played[:RECENT_LIMIT]}

    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        rom = model.rom_at(source_row)
        if not rom:
            return False
        key = self.system_key
        if key == FAVORITES_FILTER:
            if not rom.get("favorite"):
                return False
        elif key == RECENT_FILTER:
            if rom.get("path") not in self._recent_paths:
                return False
        elif key.startswith(COLLECTION_PREFIX):
            name = key[len(COLLECTION_PREFIX):]
            if rom.get("path") not in self._collections.get(name, set()):
                return False
        elif key:
            if rom.get("system") != key:
                return False
        if self.search_text and self.search_text not in rom.get("name", "").lower():
            return False
        return True

    def lessThan(self, left, right):
        """Order the "Recently Played" view most-recent-first; else default order."""
        if self.system_key == RECENT_FILTER:
            model = self.sourceModel()
            lrom = model.rom_at(left.row()) or {}
            rrom = model.rom_at(right.row()) or {}
            # With the view sorting ascending, a newer timestamp must sort
            # earlier, so treat the newer entry as "less than".
            return (lrom.get("last_played") or "") > (rrom.get("last_played") or "")
        return super().lessThan(left, right)
