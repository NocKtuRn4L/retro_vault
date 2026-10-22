"""Qt model/proxy classes for the ROM library."""

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSize, QSortFilterProxyModel, Qt
from PySide6.QtGui import QColor, QIcon, QPixmap, QPixmapCache

# Box-art thumbnail size for the library list's decoration (portrait-ish).
BOXART_THUMB = QSize(34, 46)


class LibraryModel(QAbstractTableModel):
    """The library as a table, sorted in Python.

    Column sorting lives here rather than in :class:`LibraryFilterProxyModel`:
    a QSortFilterProxyModel compares rows pairwise through ``data()``, which
    for a 20,000-game library is over a million Python calls (seconds) every
    time the view is re-sorted, while ``list.sort`` with a key touches each
    row once and takes milliseconds.
    """

    COLUMNS = ("GAME", "SYSTEM", "EXT")

    def __init__(self, library=None, systems=None, parent=None):
        super().__init__(parent)
        self.library = list(library or [])
        self.systems = systems or {}
        self._sort_column = -1
        self._sort_order = Qt.SortOrder.AscendingOrder

    def set_library(self, library):
        self.beginResetModel()
        self.library = list(library or [])
        self._sort_rows()
        self.endResetModel()

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        self._sort_column, self._sort_order = column, order
        self.layoutAboutToBeChanged.emit()
        # Keep selections and other persistent indexes on the same games.
        old_indexes = self.persistentIndexList()
        old_roms = [self.library[index.row()] for index in old_indexes]
        self._sort_rows()
        new_rows = {id(rom): row for row, rom in enumerate(self.library)}
        self.changePersistentIndexList(
            old_indexes,
            [self.index(new_rows[id(rom)], index.column()) for rom, index in zip(old_roms, old_indexes)],
        )
        self.layoutChanged.emit()

    def _sort_rows(self):
        column = self._sort_column
        if not 0 <= column < len(self.COLUMNS):
            return

        def key(rom):
            name = str(rom.get("name", "")).casefold()
            if column == 1:
                return (self._system_text(rom).casefold(), name)
            if column == 2:
                return (str(rom.get("ext", "")).casefold(), name)
            return name

        self.library.sort(key=key, reverse=self._sort_order == Qt.SortOrder.DescendingOrder)

    def _system_text(self, rom):
        system_key = rom.get("system", "")
        system = self.systems.get(system_key, {})
        return system.get("short") or system.get("name") or system_key.upper()

    def refresh_rom(self, rom):
        """Repaint the row holding ``rom`` (the same dict object) after it changed."""
        for row, entry in enumerate(self.library):
            if entry is rom:
                self.dataChanged.emit(self.index(row, 0), self.index(row, self.columnCount() - 1))
                return

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
                return self._system_text(rom)
            if index.column() == 2:
                return rom.get("ext", "")

        if role == Qt.ItemDataRole.DecorationRole and index.column() == 0:
            return self._boxart_icon(rom)

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

    def _boxart_icon(self, rom):
        """Return a box-art thumbnail QIcon for ``rom``, always the same size.

        Loads the cached box art lazily (scaled copy kept in Qt's global
        QPixmapCache so scrolling never re-decodes from disk). When a row has no
        box art — no ``media.boxart``, or the file is missing/unreadable — it
        returns a transparent placeholder of the same size rather than ``None``,
        so every row reserves identical icon space and the list stays aligned and
        uniform in height whether or not a game has a cover.
        """
        path = (rom.get("media") or {}).get("boxart")
        if path:
            key = f"rv_boxart::{path}"
            pixmap = QPixmapCache.find(key)
            if pixmap is None or pixmap.isNull():
                source = QPixmap(path)
                if not source.isNull():
                    pixmap = source.scaled(
                        BOXART_THUMB,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    QPixmapCache.insert(key, pixmap)
            if pixmap is not None and not pixmap.isNull():
                return QIcon(pixmap)
        return self._placeholder_icon()

    def _placeholder_icon(self):
        """A cached, transparent, thumbnail-sized icon that reserves row space."""
        key = "rv_boxart_placeholder"
        pixmap = QPixmapCache.find(key)
        if pixmap is None or pixmap.isNull():
            pixmap = QPixmap(BOXART_THUMB)
            pixmap.fill(Qt.GlobalColor.transparent)
            QPixmapCache.insert(key, pixmap)
        return QIcon(pixmap)

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

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        """Sort by ``column`` in the source model; see :class:`LibraryModel`.

        The proxy itself stays in source order (sort column -1) except in the
        "Recently Played" view, whose few rows it orders most-recent-first.
        """
        model = self.sourceModel()
        if model is not None and column >= 0:
            model.sort(column, order)
        if self.system_key != RECENT_FILTER:
            super().sort(-1)

    def set_system_filter(self, system_key):
        leaving_recent = self.system_key == RECENT_FILTER
        if leaving_recent:
            # Drop the recency ordering while only the recent rows are mapped,
            # so it never runs the Python lessThan over the whole library.
            super().sort(-1)
        self.system_key = system_key or ""
        if self.system_key == RECENT_FILTER:
            self._compute_recent()
        self._refresh_filter()
        if self.system_key == RECENT_FILTER:
            super().sort(0)

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
        # Games removed from the library are flagged hidden rather than deleted,
        # so removal survives a rescan (merge_scan preserves the flag). They are
        # never shown in any view.
        if rom.get("hidden"):
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
