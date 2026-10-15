from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from rnaseq_helper.ui.workers.runtime_worker import RuntimeWorker


def test_runtime_worker_emits_completion_after_qthread_run(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    thread = QThread()
    worker = RuntimeWorker(tmp_path)
    completed: list[object] = []
    failed: list[str] = []
    progress: list[str] = []
    worker.moveToThread(thread)
    worker.progress.connect(progress.append)
    worker.completed.connect(lambda result: (completed.append(result), thread.quit()))
    worker.failed.connect(lambda error: (failed.append(error), thread.quit()))
    thread.started.connect(worker.run_micro_test)
    thread.finished.connect(worker.deleteLater)
    thread.start()
    assert thread.wait(20_000), "R worker 未在 20 秒内结束"
    application.processEvents()
    assert not failed, failed
    assert completed
    assert any("R worker" in message for message in progress)
    thread.deleteLater()
