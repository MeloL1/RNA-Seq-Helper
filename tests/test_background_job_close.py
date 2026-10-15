from __future__ import annotations

import os
from threading import Event
from time import monotonic, sleep

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QObject, QThread, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QWidget

from rnaseq_helper.ui.background_jobs import BackgroundJobCloseGuard


class _FakeSignal:
    def __init__(self) -> None:
        self._slots = []

    def connect(self, slot, *_args) -> None:
        self._slots.append(slot)

    def emit(self) -> None:
        for slot in tuple(self._slots):
            slot()


class _FakeThread:
    def __init__(self) -> None:
        self.running = True
        self.finished = _FakeSignal()

    def isRunning(self) -> bool:  # noqa: N802 - mirrors QThread
        return self.running

    def finish(self) -> None:
        self.running = False
        self.finished.emit()


def test_close_waits_for_all_background_threads_and_requests_cancellation() -> None:
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    window = QWidget()
    window.show()
    threads = [_FakeThread(), _FakeThread()]
    cancelled = []
    waiting_status = []
    guard = BackgroundJobCloseGuard(
        window,
        running_threads=lambda: threads,
        cancel_jobs=lambda: cancelled.append(True),
        show_waiting_status=lambda: waiting_status.append(True),
    )
    window.installEventFilter(guard)

    close_event = QCloseEvent()
    QCoreApplication.sendEvent(window, close_event)

    assert close_event.isAccepted() is False
    assert window.isVisible()
    assert cancelled == [True]
    assert waiting_status == [True]

    threads[0].finish()
    application.processEvents()
    assert window.isVisible()

    threads[1].finish()
    for _ in range(3):
        application.processEvents()
    assert not window.isVisible()


class _WaitWorker(QObject):
    completed = Signal()

    def __init__(self, release: Event) -> None:
        super().__init__()
        self.release = release

    @Slot()
    def run(self) -> None:
        self.release.wait(timeout=2)
        self.completed.emit()


def test_close_does_not_destroy_a_running_qthread() -> None:
    application = QApplication.instance() or QApplication([])
    application.setQuitOnLastWindowClosed(False)
    window = QWidget()
    window.show()
    release = Event()
    thread = QThread()
    worker = _WaitWorker(release)
    worker.moveToThread(thread)
    thread.started.connect(worker.run, Qt.ConnectionType.QueuedConnection)
    worker.completed.connect(thread.quit, Qt.ConnectionType.QueuedConnection)
    thread.finished.connect(worker.deleteLater)
    guard = BackgroundJobCloseGuard(
        window,
        running_threads=lambda: (thread,),
        cancel_jobs=release.set,
        show_waiting_status=lambda: None,
    )
    window.installEventFilter(guard)

    try:
        thread.start()
        deadline = monotonic() + 1
        while not thread.isRunning() and monotonic() < deadline:
            application.processEvents()
            sleep(0.005)
        assert thread.isRunning()

        close_event = QCloseEvent()
        QCoreApplication.sendEvent(window, close_event)
        assert close_event.isAccepted() is False
        assert window.isVisible()

        deadline = monotonic() + 2
        while (thread.isRunning() or window.isVisible()) and monotonic() < deadline:
            application.processEvents()
            sleep(0.005)

        assert not thread.isRunning()
        assert not window.isVisible()
    finally:
        release.set()
        if thread.isRunning():
            thread.quit()
            thread.wait(2000)
        application.processEvents()
        window.close()
