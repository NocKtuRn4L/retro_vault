"""Qt-integrated, waitable emulator launch session.

:class:`LaunchSession` wraps :func:`retrovault.core.launch.start_launch_process`
so the GUI can start an emulator and be notified — without blocking the Qt event
loop — when the emulator process exits. Downstream PRs (the launch overlay, main
window integration) connect to its signals.

Importing this module must not require a running ``QApplication`` and must not
construct any widgets.
"""

from PySide6.QtCore import QObject, QThread, Signal

from retrovault.core.launch import start_launch_process


class _WaitThread(QThread):
    """Blocks on ``proc.wait()`` off the GUI thread, then reports the exit code.

    The blocking wait runs inside :meth:`run` on this thread; the ``finished_code``
    signal is delivered back to the GUI thread via Qt's queued connection, so
    :class:`LaunchSession` can emit ``exited`` on the GUI thread safely.
    """

    finished_code = Signal(int)

    def __init__(self, proc, parent=None):
        super().__init__(parent)
        self._proc = proc

    def run(self):
        try:
            code = self._proc.wait()
        except Exception:
            code = -1
        self.finished_code.emit(int(code if code is not None else -1))


class LaunchSession(QObject):
    """A single, waitable emulator launch.

    Signals:
        starting(): emitted immediately when :meth:`launch` begins.
        started(): emitted once the emulator process is confirmed running.
        failed(str): emitted with an error message if the launch could not start.
        exited(int): emitted with the process return code when the emulator exits.

    Un-waitable launches (the win32 ShellExecute fallback path, where
    ``start_launch_process`` returns ``(None, None)``) cannot be tracked, so the
    session treats them as having instantly returned: it emits ``started`` and
    then ``exited(0)``.
    """

    starting = Signal()
    started = Signal()
    failed = Signal(str)
    exited = Signal(int)

    # Return code reported for the un-waitable ShellExecute success path.
    UNWAITABLE_EXIT_CODE = 0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc = None
        self._thread = None

    def launch(self, rom, config, controller_mapping=None):
        """Start the emulator for ``rom`` using ``config`` and track its lifetime.

        Emits ``starting`` immediately. On validation/launch failure emits
        ``failed(error)``. On a successful, waitable launch emits ``started`` and
        later ``exited(code)`` when the process ends. On a successful but
        un-waitable launch emits ``started`` then ``exited(UNWAITABLE_EXIT_CODE)``.
        """
        self.starting.emit()

        proc, error = start_launch_process(rom, config, controller_mapping=controller_mapping)

        if error is not None:
            self.failed.emit(error)
            return

        if proc is None:
            # Launched, but not waitable (win32 ShellExecute fallback). We cannot
            # observe its exit, so report it as immediately returned.
            self.started.emit()
            self.exited.emit(self.UNWAITABLE_EXIT_CODE)
            return

        self._proc = proc
        self.started.emit()

        thread = _WaitThread(proc, parent=self)
        thread.finished_code.connect(self._on_exit)
        thread.finished.connect(self._on_thread_finished)
        # Keep a reference so the thread isn't garbage-collected mid-run.
        self._thread = thread
        thread.start()

    def is_running(self):
        """Return True if a waitable process was started and has not yet exited."""
        if self._proc is None:
            return False
        return self._proc.poll() is None

    def _on_exit(self, code):
        self._proc = None
        self.exited.emit(code)

    def _on_thread_finished(self):
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.deleteLater()
