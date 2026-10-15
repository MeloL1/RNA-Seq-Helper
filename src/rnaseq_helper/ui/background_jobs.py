from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThread, Qt, QTimer
from PySide6.QtWidgets import QWidget


class BackgroundJobCloseGuard(QObject):
    """Keep the window alive until its cooperative background jobs have stopped."""

    def __init__(
        self,
        window: QWidget,
        running_threads: Callable[[], Iterable[QThread]],
        cancel_jobs: Callable[[], None],
        show_waiting_status: Callable[[], None],
    ) -> None:
        super().__init__(window)
        self._window = window
        self._running_threads = running_threads
        self._cancel_jobs = cancel_jobs
        self._show_waiting_status = show_waiting_status
        self._waiting_for_jobs = False
        self._application_quit_pending = False
        self._application = QCoreApplication.instance()
        self._application_filter_installed = False
        if self._application is not None:
            # QApplication.quit() (for example macOS Cmd+Q) is a separate
            # application-level request; a window-only filter cannot defer it.
            self._application.installEventFilter(self)
            self._application_filter_installed = True

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt override
        is_window_close = watched is self._window and event.type() == QEvent.Type.Close
        application = QCoreApplication.instance()
        is_application_quit = watched is application and event.type() == QEvent.Type.Quit
        if not is_window_close and not is_application_quit:
            return False

        threads = self._live_threads()
        if not threads:
            self._waiting_for_jobs = False
            if is_window_close or is_application_quit:
                self._remove_event_filters()
            return False

        event.ignore()
        if is_application_quit:
            self._application_quit_pending = True
        if not self._waiting_for_jobs:
            self._waiting_for_jobs = True
            for thread in threads:
                thread.finished.connect(
                    self._on_thread_finished,
                    Qt.ConnectionType.QueuedConnection,
                )
            self._cancel_jobs()
            self._show_waiting_status()
            # A worker may have finished between the initial close event and signal
            # connection; checking again closes that race without blocking the UI.
            self._close_when_idle()
        return True

    def _live_threads(self) -> list[QThread]:
        live: list[QThread] = []
        for thread in self._running_threads():
            try:
                running = thread.isRunning()
            except RuntimeError:
                # A page may already have processed its finished/deleteLater events.
                continue
            if running:
                live.append(thread)
        return live

    def _on_thread_finished(self) -> None:
        QTimer.singleShot(0, self._close_when_idle)

    def _remove_application_filter(self) -> None:
        if not self._application_filter_installed:
            return
        self._application_filter_installed = False
        if self._application is None:
            return
        try:
            self._application.removeEventFilter(self)
        except RuntimeError:
            # QApplication may already be tearing down during a parent window's
            # destruction; the QObject parent will release this filter as well.
            pass

    def _remove_event_filters(self) -> None:
        self._remove_application_filter()
        try:
            self._window.removeEventFilter(self)
        except RuntimeError:
            pass

    def _close_when_idle(self) -> None:
        if not self._waiting_for_jobs or self._live_threads():
            return
        self._waiting_for_jobs = False
        if self._application_quit_pending:
            self._application_quit_pending = False
            self._remove_event_filters()
            QTimer.singleShot(0, QCoreApplication.quit)
            return
        self._remove_application_filter()
        QTimer.singleShot(0, self._window.close)
