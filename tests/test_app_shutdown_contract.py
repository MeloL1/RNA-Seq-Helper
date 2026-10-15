from __future__ import annotations

import os
from threading import Event
from time import monotonic

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QWidget

from rnaseq_helper.ui.background_jobs import BackgroundJobCloseGuard


class _BoundedWorker(QObject):
    completed = Signal()

    def __init__(self, release: Event) -> None:
        super().__init__()
        self.release = release

    @Slot()
    def run(self) -> None:
        # The test owns release; timeout is a final safety bound, not the trigger.
        self.release.wait(timeout=2)
        self.completed.emit()


def test_application_quit_waits_for_active_thread_then_closes_window() -> None:
    application = QApplication.instance() or QApplication([])
    previous_quit_on_last_window = application.quitOnLastWindowClosed()
    # The quit request must be replayed explicitly after waiting; relying on
    # closing the last window would fail when this normal Qt option is disabled.
    application.setQuitOnLastWindowClosed(False)
    window = QWidget()
    window.show()

    release = Event()
    thread = QThread()
    worker = _BoundedWorker(release)
    worker.moveToThread(thread)
    thread.started.connect(worker.run, Qt.ConnectionType.QueuedConnection)
    worker.completed.connect(thread.quit, Qt.ConnectionType.QueuedConnection)
    thread.finished.connect(worker.deleteLater)

    cancelled: list[bool] = []
    guard = BackgroundJobCloseGuard(
        window,
        running_threads=lambda: (thread,),
        cancel_jobs=lambda: cancelled.append(True),
        show_waiting_status=lambda: None,
    )
    window.installEventFilter(guard)

    # The first quit request arrives while the worker is deterministically held.
    # If the application-level Quit event is not intercepted, exec() returns here
    # and the assertions below fail. Releasing it is timer-bounded for cleanup.
    QTimer.singleShot(0, application.quit)
    QTimer.singleShot(40, release.set)
    QTimer.singleShot(1800, application.quit)  # hard upper bound on the event loop

    try:
        thread.start()
        started = monotonic()
        exit_code = application.exec()
        elapsed = monotonic() - started

        assert exit_code == 0
        assert elapsed < 1.0, f"application quit was not resumed promptly ({elapsed:.2f}s)"
        assert cancelled == [True]
        assert not thread.isRunning()
        assert not window.isVisible()
    finally:
        release.set()
        if thread.isRunning():
            thread.quit()
            assert thread.wait(1000), "worker thread did not stop within cleanup bound"
        window.close()
        application.setQuitOnLastWindowClosed(previous_quit_on_last_window)
