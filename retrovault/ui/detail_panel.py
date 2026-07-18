"""Game detail panel (PR #2b).

A collapsible widget shown on the right of the library body splitter. For the
currently selected ROM it renders box art, name, system, scraped ``metadata``
(synopsis, genre, players, rating, year), play statistics, and RetroAchievements
progress.

The panel is deliberately defensive: it is the read-side of the cross-PR
"library entry" contract, so it reads **every** field with ``.get()`` and must
render cleanly for a *bare* scan entry that has only ``name``/``path``/
``system``/``ext``. Missing artwork, a media path pointing at a file that no
longer exists, or absent metadata all fall back gracefully rather than crash.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

BOXART_WIDTH = 240
BOXART_HEIGHT = 320


def _format_duration(seconds) -> str:
    """Return a compact human duration (``"1h 23m"``) for a seconds count."""
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return ""
    if seconds < 0:
        seconds = 0
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m"
    return f"{seconds}s"


class DetailPanel(QWidget):
    """Right-hand detail view for the selected ROM.

    Construct with an optional ``systems`` mapping (the config's systems dict)
    so the system key can be shown as a friendly name. Call
    :meth:`update_for` with a library entry (or ``None``) to repaint.
    """

    def __init__(self, systems=None, parent=None):
        super().__init__(parent)
        self.systems = systems or {}
        self.setObjectName("detailPanel")
        self.setMinimumWidth(260)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Box art (or placeholder). Fixed size keeps the layout stable whether a
        # pixmap loads or the placeholder text is shown.
        self.boxart_label = QLabel()
        self.boxart_label.setObjectName("detailBoxart")
        self.boxart_label.setFixedSize(BOXART_WIDTH, BOXART_HEIGHT)
        self.boxart_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.boxart_label.setStyleSheet(
            "background-color: #1a1a1a; border: 1px solid #2a2a2a; color: #888888;"
        )
        layout.addWidget(self.boxart_label, 0, Qt.AlignmentFlag.AlignHCenter)

        self.name_label = QLabel()
        self.name_label.setProperty("role", "title")
        self.name_label.setWordWrap(True)
        layout.addWidget(self.name_label)

        self.system_label = QLabel()
        self.system_label.setProperty("role", "subtext")
        layout.addWidget(self.system_label)

        # Fact rows (year / genre / players / rating). Each is hidden when empty.
        self.year_label = self._make_row(layout)
        self.genre_label = self._make_row(layout)
        self.players_label = self._make_row(layout)
        self.rating_label = self._make_row(layout)

        # Play statistics and achievements.
        self.playtime_label = self._make_row(layout)
        self.achievements_label = self._make_row(layout)

        # Synopsis (word-wrapped block, hidden when empty).
        self.synopsis_label = QLabel()
        self.synopsis_label.setWordWrap(True)
        self.synopsis_label.setProperty("role", "subtext")
        self.synopsis_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.synopsis_label)

        layout.addStretch(1)

        self.update_for(None)

    def _make_row(self, layout) -> QLabel:
        label = QLabel()
        label.setWordWrap(True)
        layout.addWidget(label)
        return label

    # ── Public API ───────────────────────────────────────────────────────────
    def update_for(self, rom):
        """Repaint the panel for ``rom`` (a library entry) or ``None``."""
        if not rom:
            self._show_placeholder()
            return

        self.name_label.setText(str(rom.get("name") or "Unknown"))
        self.name_label.setVisible(True)

        self.system_label.setText(self._system_name(rom.get("system", "")))
        self.system_label.setVisible(bool(self.system_label.text()))

        metadata = rom.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}

        self._set_row(self.year_label, "Year: ", metadata.get("year"))
        self._set_row(self.genre_label, "Genre: ", metadata.get("genre"))
        self._set_row(self.players_label, "Players: ", metadata.get("players"))
        self._set_row(self.rating_label, "Rating: ", metadata.get("rating"))

        self._set_row(self.playtime_label, "Play time: ", self._play_summary(rom))
        self._set_row(self.achievements_label, "", self._achievement_summary(rom))

        synopsis = metadata.get("synopsis")
        self.synopsis_label.setText(str(synopsis) if synopsis else "")
        self.synopsis_label.setVisible(bool(synopsis))

        self._set_boxart(rom)

    # ── Internals ────────────────────────────────────────────────────────────
    def _show_placeholder(self):
        self.name_label.setText("No game selected")
        self.name_label.setVisible(True)
        for label in (
            self.system_label,
            self.year_label,
            self.genre_label,
            self.players_label,
            self.rating_label,
            self.playtime_label,
            self.achievements_label,
            self.synopsis_label,
        ):
            label.setText("")
            label.setVisible(False)
        self._set_placeholder_boxart()

    def _system_name(self, system_key) -> str:
        if not system_key:
            return ""
        sdef = self.systems.get(system_key, {}) if isinstance(self.systems, dict) else {}
        return sdef.get("name") or sdef.get("short") or str(system_key).upper()

    def _set_row(self, label: QLabel, prefix: str, value) -> None:
        text = "" if value is None else str(value).strip()
        if text:
            label.setText(f"{prefix}{text}")
            label.setVisible(True)
        else:
            label.setText("")
            label.setVisible(False)

    def _play_summary(self, rom) -> str:
        seconds = rom.get("play_seconds")
        count = rom.get("play_count")
        parts = []
        if seconds:
            duration = _format_duration(seconds)
            if duration:
                parts.append(duration)
        if count:
            try:
                n = int(count)
                if n > 0:
                    parts.append(f"{n} play{'s' if n != 1 else ''}")
            except (TypeError, ValueError):
                pass
        return "  •  ".join(parts)

    def _achievement_summary(self, rom) -> str:
        earned = rom.get("ra_earned")
        total = rom.get("ra_total")
        if earned is None and total is None:
            return ""
        try:
            earned = int(earned or 0)
            total = int(total or 0)
        except (TypeError, ValueError):
            return ""
        if total <= 0:
            return ""
        return f"{earned} / {total} achievements"

    def _set_boxart(self, rom) -> None:
        media = rom.get("media") or {}
        boxart = media.get("boxart") if isinstance(media, dict) else None
        if boxart:
            try:
                path = Path(boxart)
                if path.exists():
                    pixmap = QPixmap(str(path))
                    if not pixmap.isNull():
                        scaled = pixmap.scaled(
                            BOXART_WIDTH,
                            BOXART_HEIGHT,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                        self.boxart_label.setPixmap(scaled)
                        return
            except Exception:
                # Any unreadable/invalid path falls through to the placeholder.
                pass
        self._set_placeholder_boxart()

    def _set_placeholder_boxart(self) -> None:
        self.boxart_label.setPixmap(QPixmap())
        self.boxart_label.setText("NO IMAGE")
