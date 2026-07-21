"""Off-thread artwork scraping worker.

Runs :func:`retrovault.providers.scraper.scrape_library` on a background QThread
so the UI stays responsive while covers download. The default provider
(libretro-thumbnails) needs no credentials; the concrete network transport is
only constructed here, never in tests.
"""

from PySide6.QtCore import QThread, Signal

from ..providers.scraper import UrllibTransport, build_client, scrape_library


class ScrapeWorker(QThread):
    """Scrape artwork for a library off the UI thread.

    Signals:
        progress(done, total): after each entry is processed.
        finished_library(list): the updated library (media/metadata merged on).
        failed(str): a fatal error that aborted the whole run.
    """

    progress = Signal(int, int)
    finished_library = Signal(object)
    failed = Signal(str)

    def __init__(self, library, config, *, force=False, parent=None):
        super().__init__(parent)
        self._library = list(library or [])
        self._config = config
        self._force = force
        self._cancel = False

    def cancel(self):
        """Request cancellation; the batch stops after the current entry."""
        self._cancel = True

    def run(self):
        try:
            client = build_client(self._config, UrllibTransport())
            updated = scrape_library(
                self._library,
                self._config,
                client,
                force=self._force,
                on_progress=lambda done, total: self.progress.emit(done, total),
                should_cancel=lambda: self._cancel,
            )
        except Exception as exc:  # pragma: no cover - defensive; worker must not crash the app
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.finished_library.emit(updated)
