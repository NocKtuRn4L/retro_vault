"""Fullscreen in-window launch overlay and transition orchestration.

RetroVault stays rendered *behind* the emulator during a launch; we never hide
or minimize the window (that would flash the desktop). Instead we paint a solid
black, full-window overlay over the app's controls during the launch and return
transitions so the user never sees the desktop or the UI flicker.

:class:`LaunchOverlay` is the black cover widget with a centered caption.
:class:`LaunchCoordinator` wires a :class:`~retrovault.ui.launch_session.LaunchSession`
to a :class:`LaunchOverlay` and the host window, translating session signals into
overlay show/hide transitions plus input-disable / view save-restore callbacks.

Importing this module must not require a running ``QApplication``; widgets are
only constructed when the classes are instantiated.

The actual OS-level fullscreen/raise policy (``showFullScreen``, ``raise_``,
``activateWindow``, Wayland handling) is *not* this module's concern — it is
handled elsewhere. Here we only manage the in-window black overlay and the
transition timing.
"""

import time

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .launch_session import LaunchSession

# Caption strings for the two overlay variants.
LAUNCHING_CAPTION = "LAUNCHING…"
RETURNING_CAPTION = "RETURNING…"

# Milliseconds the "returning" caption lingers before the overlay hides.
RETURN_GRACE_MS = 400

# Sessions shorter than this are treated as failed launches (e.g. the
# un-waitable win32 ShellExecute path that emits ``exited(0)`` immediately)
# and are discarded rather than recorded as play time.
MIN_PLAY_SECONDS = 5.0


class LaunchOverlay(QWidget):
    """A full-window black overlay with a centered, retro-styled caption.

    The overlay is a child of ``parent`` and always fills it: it installs an
    event filter on the parent so it re-covers on resize/move, and also exposes
    :meth:`cover` for explicit geometry syncing.

    While visible it swallows keyboard and mouse input so clicks and key presses
    do not leak through to the controls beneath it.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # Opaque so nothing behind bleeds through; own its background paint.
        self.setAutoFillBackground(True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("launchOverlay")
        self.setStyleSheet(
            "#launchOverlay { background-color: #000000; }"
            "#launchOverlay QLabel#launchOverlayCaption {"
            " color: #ff3c3c;"
            " font-family: 'Consolas', 'Courier New', monospace;"
            " font-size: 22px;"
            " font-weight: bold;"
            " letter-spacing: 3px;"
            " }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._caption = QLabel(LAUNCHING_CAPTION, self)
        self._caption.setObjectName("launchOverlayCaption")
        self._caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._caption)

        # Accept focus so we can steal it and swallow key events while shown.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.hide()
        if parent is not None:
            parent.installEventFilter(self)
            self.cover(parent.rect())

    # -- geometry -----------------------------------------------------------
    def cover(self, parent_rect):
        """Resize/move the overlay to exactly fill ``parent_rect``."""
        self.setGeometry(parent_rect)

    def eventFilter(self, obj, event):
        """Keep the overlay covering the parent when the parent is resized."""
        if obj is self.parent() and event.type() in (
            QEvent.Type.Resize,
            QEvent.Type.Move,
        ):
            self.cover(self.parent().rect())
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        # Keep the caption centered on any direct resize as well.
        super().resizeEvent(event)

    # -- captions / visibility ---------------------------------------------
    def caption(self):
        """Return the current caption text (useful for tests)."""
        return self._caption.text()

    def _show_with_caption(self, text):
        self._caption.setText(text)
        parent = self.parent()
        if parent is not None:
            self.cover(parent.rect())
        self.show()
        self.raise_()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def show_launching(self):
        """Show the overlay with the LAUNCHING caption, raised above siblings."""
        self._show_with_caption(LAUNCHING_CAPTION)

    def show_returning(self):
        """Show the overlay with the RETURNING caption, raised above siblings."""
        self._show_with_caption(RETURNING_CAPTION)

    # -- input swallowing ---------------------------------------------------
    def keyPressEvent(self, event):
        # Swallow keys so they never reach controls beneath the overlay.
        event.accept()

    def keyReleaseEvent(self, event):
        event.accept()

    def mousePressEvent(self, event):
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()

    def mouseDoubleClickEvent(self, event):
        event.accept()

    def wheelEvent(self, event):
        event.accept()


class LaunchCoordinator(QObject):
    """Orchestrates the overlay + session across a launch/return transition.

    The coordinator stays decoupled from ``MainWindow`` internals: the host
    passes ``save_view`` / ``restore_view`` callables (to snapshot and restore
    selection/scroll state) and connects to the coordinator's signals rather
    than the coordinator reaching into the window.

    Signals:
        input_disabled(bool): ``True`` when a launch begins (host should suspend
            controller polling and disable widgets), ``False`` once the emulator
            has exited or the launch failed.
        finished(): emitted after the emulator exits and the view is restored.
        session_finished(object): emitted alongside ``finished`` with a dict
            ``{"rom_path": <str>, "elapsed_seconds": <float>}`` carrying the
            wall-clock time the emulator ran. Sub-threshold sessions (see
            :data:`MIN_PLAY_SECONDS`) are still emitted with their (small)
            elapsed; the host decides whether to record them.
        failed(str): emitted with an error message when the launch could not
            start. The host connects this to show a ``QMessageBox`` — the
            coordinator never pops a dialog itself.
    """

    input_disabled = Signal(bool)
    finished = Signal()
    session_finished = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        host,
        overlay=None,
        session_factory=None,
        save_view=None,
        restore_view=None,
        parent=None,
    ):
        super().__init__(parent or host)
        self._host = host
        self._overlay = overlay if overlay is not None else LaunchOverlay(host)
        self._session_factory = session_factory or (lambda: LaunchSession())
        self._save_view = save_view or (lambda: None)
        self._restore_view = restore_view or (lambda: None)
        self._session = None
        # Play-time tracking state for the in-flight launch.
        self._launch_started_at = None
        self._launch_rom_path = None
        self._elapsed_seconds = None

    @property
    def overlay(self):
        """The :class:`LaunchOverlay` this coordinator drives."""
        return self._overlay

    def set_callbacks(self, save_view=None, restore_view=None):
        """Replace the view save/restore callbacks (used by PR10 integration)."""
        if save_view is not None:
            self._save_view = save_view
        if restore_view is not None:
            self._restore_view = restore_view

    def launch(self, rom, config):
        """Begin launching ``rom`` with ``config``, covering the UI in black."""
        # Snapshot the view before anything changes, then cover + disable input.
        self._save_view()
        # Start the play-time clock and remember which ROM this launch is for.
        self._launch_started_at = time.monotonic()
        self._launch_rom_path = rom.get("path") if hasattr(rom, "get") else None
        self._elapsed_seconds = None
        self._overlay.show_launching()
        self.input_disabled.emit(True)

        session = self._session_factory()
        session.starting.connect(self._on_starting)
        session.started.connect(self._on_started)
        session.exited.connect(self._on_exited)
        session.failed.connect(self._on_failed)
        # Keep a reference so the session (and its wait thread) survives.
        self._session = session
        session.launch(rom, config)

    # -- session signal handlers -------------------------------------------
    def _on_starting(self):
        # Already shown by launch(); ensure it is visible and on top.
        self._overlay.show_launching()

    def _on_started(self):
        # The emulator is now on top of the app; drop the overlay.
        self._overlay.hide()

    def _on_exited(self, _code):
        # Capture play time at the true exit point (excludes the return grace).
        if self._launch_started_at is not None:
            self._elapsed_seconds = time.monotonic() - self._launch_started_at
        # Briefly show the "returning" caption, then hide, restore, re-enable.
        self._overlay.show_returning()
        QTimer.singleShot(RETURN_GRACE_MS, self._finish_return)

    def _finish_return(self):
        self._overlay.hide()
        self._restore_view()
        self.input_disabled.emit(False)
        self._session = None
        rom_path = self._launch_rom_path
        elapsed = self._elapsed_seconds
        self._launch_started_at = None
        self._launch_rom_path = None
        self._elapsed_seconds = None
        self.finished.emit()
        if elapsed is not None:
            self.session_finished.emit(
                {"rom_path": rom_path, "elapsed_seconds": float(elapsed)}
            )

    def _on_failed(self, message):
        # Keep the app covering the desktop; just drop our overlay and re-enable.
        self._overlay.hide()
        self.input_disabled.emit(False)
        self._session = None
        # A launch that never started records no play time.
        self._launch_started_at = None
        self._launch_rom_path = None
        self._elapsed_seconds = None
        self.failed.emit(message)
