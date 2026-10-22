"""Shared QApplication for the UI tests, with leftover widgets freed at exit.

Windows, dialogs and keyboards built by the tests are never freed: their
signal connections to Python callables form reference cycles through Qt that
Python's garbage collector can't see. PySide6 then destroys every widget
Python still owns while the interpreter exits, in an order set by memory
addresses, and with a few hundred left over that intermittently crashed the
run (segfault or bus error) after every test had passed.

:func:`qt_app` registers an exit hook that deletes the remaining top-level
widgets while Python and Qt are still fully running. PySide installs its own
exit hooks when QtCore is imported, and ``atexit`` runs hooks last-in,
first-out, so this one runs before them.
"""

import atexit
import gc

_cleanup_registered = False


def qt_app():
    """Return the shared QApplication, creating it on first use."""
    from PySide6.QtWidgets import QApplication

    global _cleanup_registered
    if not _cleanup_registered:
        atexit.register(_delete_leftover_widgets)
        _cleanup_registered = True
    return QApplication.instance() or QApplication([])


def _delete_leftover_widgets():
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    if QApplication.instance() is None:
        return
    # Delete without close(): close handlers are app behaviour the tests have
    # already exercised, not something to rerun at exit.
    for widget in QApplication.topLevelWidgets():
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()
