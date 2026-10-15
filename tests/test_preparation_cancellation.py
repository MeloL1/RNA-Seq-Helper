from __future__ import annotations

import os
import time
from pathlib import Path
from threading import Event

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from rnaseq_helper.domain.models import DataAsset, MeasurementType, ValueScale, sha256_file
from rnaseq_helper.preparation.service import PreparationCancelled, PreparationService
from rnaseq_helper.ui.background_jobs import BackgroundJobCloseGuard
from rnaseq_helper.ui.pages.import_page import ImportPage


def _write_counts(path: Path, rows: int) -> None:
    path.write_text(
        "gene_id\tcontrol_1\tcontrol_2\n"
        + "".join(f"gene_{index}\t{index + 1}\t{index + 2}\n" for index in range(rows)),
        encoding="utf-8",
    )


def _wait_until(predicate, timeout_ms: int = 10000) -> bool:
    if predicate():
        return True
    application = QApplication.instance()
    assert application is not None
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(10)
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    poll.start()
    timeout.start(timeout_ms)
    loop.exec()
    poll.stop()
    timeout.stop()
    application.processEvents()
    return predicate()


def _confirmed_session(source: Path, project: Path, *, rows: int = 600):
    _write_counts(source, rows)
    service = PreparationService()
    session = service.start(DataAsset("counts", (source,), "TABLE"), project)
    return service.apply(session, {
        "header_row": 0,
        "data_start_row": 1,
        "feature_id_column": 0,
        "sample_columns": [1, 2],
        "measurement_type": MeasurementType.RAW_COUNT,
        "value_scale": ValueScale.LINEAR,
    })


def test_validation_reports_progress_and_honors_cancellation(tmp_path: Path) -> None:
    session = _confirmed_session(tmp_path / "counts.tsv", tmp_path / "project")
    service = PreparationService()
    checks = 0

    def cancel_after_materialization_begins() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 6

    with pytest.raises(PreparationCancelled):
        service.validate(session, cancelled=cancel_after_materialization_begins)
    assert checks >= 6

    progress: list[tuple[int, int]] = []
    summary = service.validate(session, progress=lambda done, total: progress.append((done, total)))
    assert summary.passed
    assert progress
    assert progress[0] == (0, 600)
    assert progress[-1] == (600, 600)


def test_import_page_keeps_cancel_available_during_validation(tmp_path: Path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    source = tmp_path / "counts.tsv"
    original_content = "gene_id\tcontrol_1\tcontrol_2\n" + "".join(
        f"gene_{index}\t{index + 1}\t{index + 2}\n" for index in range(1500)
    )
    source.write_text(original_content, encoding="utf-8")
    page = ImportPage(project_root=tmp_path / "projects")
    received = []
    page.matrixReady.connect(received.append)
    validation_started = Event()

    def wait_for_cancel(session, *, cancelled=None, progress=None):
        validation_started.set()
        if progress is not None:
            progress(0, session.raw_table.row_count)
        while cancelled is None or not cancelled():
            time.sleep(0.005)
        raise PreparationCancelled("用户已取消完整校验")

    monkeypatch.setattr(page.preparer, "validate", wait_for_cancel)
    page.load_path(source)
    assert _wait_until(lambda: page._active_thread is None)
    page.continue_button.click()
    assert _wait_until(lambda: page.session is not None and page._active_thread is None)
    page.measurement_combo.setCurrentIndex(page.measurement_combo.findData("RAW_COUNT"))
    page.scale_combo.setCurrentIndex(page.scale_combo.findData("LINEAR"))
    page.prepare_button.click()
    page.prepare_button.click()
    page.prepare_button.click()

    assert _wait_until(validation_started.is_set)
    assert _wait_until(lambda: not page.organize_cancel_button.isHidden())
    assert page.organize_cancel_button.isEnabled()
    page.organize_cancel_button.click()
    assert _wait_until(lambda: page._active_thread is None)

    assert not received
    assert "已取消" in page.status_label.text()
    assert not (tmp_path / "projects").exists()
    assert source.read_text(encoding="utf-8") == original_content
    page.close()
    application.processEvents()


def test_import_page_cancels_real_validation_in_background(tmp_path: Path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    source = tmp_path / "cancel-only-counts.tsv"
    _write_counts(source, 80_000)
    original_sha = sha256_file(source)
    project_root = tmp_path / "projects"
    page = ImportPage(project_root=project_root)
    received = []
    page.matrixReady.connect(received.append)

    validation_paused = Event()
    release_validation = Event()
    validate = page.preparer.validate

    def pause_after_real_validation_progress(session, *, cancelled=None, progress=None):
        paused_once = False

        def report_progress(completed: int, total: int) -> None:
            nonlocal paused_once
            if completed >= 128 and not paused_once:
                paused_once = True
                validation_paused.set()
                if not release_validation.wait(timeout=15):
                    raise RuntimeError("测试未及时发送取消信号")
            if progress is not None:
                progress(completed, total)

        return validate(session, cancelled=cancelled, progress=report_progress)

    monkeypatch.setattr(page.preparer, "validate", pause_after_real_validation_progress)

    try:
        page.load_path(source)
        assert _wait_until(lambda: page._active_thread is None, timeout_ms=30_000)
        page.continue_button.click()
        assert _wait_until(
            lambda: page.session is not None and page._active_thread is None,
            timeout_ms=30_000,
        )
        page.measurement_combo.setCurrentIndex(page.measurement_combo.findData("RAW_COUNT"))
        page.scale_combo.setCurrentIndex(page.scale_combo.findData("LINEAR"))
        for _ in range(3):
            page.prepare_button.click()

        reached_real_validation = _wait_until(validation_paused.is_set, timeout_ms=30_000)
        cancel_was_available = page.organize_cancel_button.isEnabled()
        if reached_real_validation and cancel_was_available:
            page.organize_cancel_button.click()
    finally:
        release_validation.set()
        assert _wait_until(lambda: page._active_thread is None, timeout_ms=30_000)
        page.close()
        application.processEvents()

    assert reached_real_validation
    assert cancel_was_available
    assert not received
    assert "已取消" in page.status_label.text()
    assert not project_root.exists()
    assert sha256_file(source) == original_sha


def test_window_close_waits_for_real_import_validation_thread(tmp_path: Path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    previous_quit_on_last_window = application.quitOnLastWindowClosed()
    application.setQuitOnLastWindowClosed(False)
    source = tmp_path / "close-only-counts.tsv"
    _write_counts(source, 2_000)
    original_sha = sha256_file(source)
    project_root = tmp_path / "projects"
    page = ImportPage(project_root=project_root)
    received = []
    page.matrixReady.connect(received.append)

    window = QWidget()
    layout = QVBoxLayout(window)
    layout.addWidget(page)
    cancel_requested: list[bool] = []

    def cancel_import_worker() -> None:
        cancel_requested.append(True)
        if page._active_worker is not None:
            page._active_worker.request_cancel()

    guard = BackgroundJobCloseGuard(
        window,
        running_threads=lambda: (page._active_thread,) if page._active_thread is not None else (),
        cancel_jobs=cancel_import_worker,
        show_waiting_status=lambda: page._set_status("正在等待导入任务安全结束"),
    )
    window.installEventFilter(guard)

    validation_paused = Event()
    release_validation = Event()
    validate = page.preparer.validate

    def pause_after_real_validation_progress(session, *, cancelled=None, progress=None):
        paused_once = False

        def report_progress(completed: int, total: int) -> None:
            nonlocal paused_once
            if completed >= 128 and not paused_once:
                paused_once = True
                validation_paused.set()
                if not release_validation.wait(timeout=15):
                    raise RuntimeError("测试未及时关闭窗口")
            if progress is not None:
                progress(completed, total)

        return validate(session, cancelled=cancelled, progress=report_progress)

    monkeypatch.setattr(page.preparer, "validate", pause_after_real_validation_progress)

    try:
        window.show()
        page.load_path(source)
        assert _wait_until(lambda: page._active_thread is None, timeout_ms=15_000)
        page.continue_button.click()
        assert _wait_until(
            lambda: page.session is not None and page._active_thread is None,
            timeout_ms=15_000,
        )
        page.measurement_combo.setCurrentIndex(page.measurement_combo.findData("RAW_COUNT"))
        page.scale_combo.setCurrentIndex(page.scale_combo.findData("LINEAR"))
        for _ in range(3):
            page.prepare_button.click()

        assert _wait_until(validation_paused.is_set, timeout_ms=15_000)
        assert page._active_thread is not None and page._active_thread.isRunning()
        window.close()
        application.processEvents()
        assert cancel_requested == [True]
        assert window.isVisible(), "窗口必须等真实导入线程结束后才关闭"

        release_validation.set()
        assert _wait_until(
            lambda: page._active_thread is None and not window.isVisible(),
            timeout_ms=15_000,
        )
        assert not guard._application_filter_installed
    finally:
        release_validation.set()
        if page._active_thread is not None:
            page.cancel_import()
            _wait_until(lambda: page._active_thread is None, timeout_ms=15_000)
        if window.isVisible():
            window.close()
            application.processEvents()
        application.setQuitOnLastWindowClosed(previous_quit_on_last_window)

    assert not received
    assert not project_root.exists()
    assert sha256_file(source) == original_sha


def test_worker_failure_shows_recovery_hint_without_raw_path(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    page = ImportPage()
    page._task_name = "正在检查文件"
    page._on_task_failure(
        page._task_generation,
        "PermissionError: [Errno 13] Permission denied: '/Users/person/private/counts.tsv'",
    )
    assert "检查文件未完成" in page.status_label.text()
    assert "权限" in page.status_label.text()
    assert "/Users/person/private/counts.tsv" not in page.status_label.text()
    assert "/Users/person/private/counts.tsv" in page.status_label.toolTip()
    page.close()
    application.processEvents()
