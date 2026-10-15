from __future__ import annotations

import hashlib
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QPoint, QPointF, QMimeData, QTimer, QUrl, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication

from rnaseq_helper.domain.models import ExpressionMatrix, MeasurementType, ValueScale
from rnaseq_helper.ui.pages.analysis_page import AnalysisPage
from rnaseq_helper.ui.pages.import_page import ImportPage


FIXTURE = Path(__file__).parent / "fixtures" / "company_counts.tsv"


def _wait_until(predicate, timeout_ms: int = 15000) -> bool:
    if predicate():
        return True
    app = QApplication.instance()
    assert app is not None
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
    app.processEvents()
    return predicate()


def _drop_urls(app: QApplication, page: ImportPage, urls: list[QUrl]) -> tuple[QDragEnterEvent, QDropEvent]:
    mime = QMimeData()
    mime.setUrls(urls)
    enter = QDragEnterEvent(
        QPoint(8, 8), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    app.sendEvent(page, enter)
    drop = QDropEvent(
        QPointF(8, 8), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    app.sendEvent(page, drop)
    return enter, drop


def test_qt_file_url_drop_scans_multiple_candidates_and_delivers_matrix_to_group_consumer(
    tmp_path: Path,
) -> None:
    """Qt URL-event automation; it does not constitute a manual Finder drag-and-drop check."""
    app = QApplication.instance() or QApplication([])
    original_bytes = FIXTURE.read_bytes()
    original_hash = hashlib.sha256(original_bytes).hexdigest()
    candidate_dir = tmp_path / "candidate_directory"
    candidate_dir.mkdir()
    second = candidate_dir / "other_counts.tsv"
    second.write_text(
        "gene_id\tTreat_1\tTreat_2\nalpha\t3\t4\nbeta\t6\t8\n",
        encoding="utf-8",
    )
    page = ImportPage(project_root=tmp_path / "projects")
    group_page = AnalysisPage()
    received: list[ExpressionMatrix] = []
    page.matrixReady.connect(group_page.set_matrix)
    page.matrixReady.connect(received.append)

    try:
        enter, drop = _drop_urls(
            app,
            page,
            [
                QUrl.fromLocalFile(str(FIXTURE.resolve())),
                QUrl.fromLocalFile(str(candidate_dir)),
                QUrl("https://example.invalid/table.tsv"),
            ],
        )
        assert enter.isAccepted()
        assert drop.isAccepted()
        assert _wait_until(lambda: page._active_thread is None and bool(page.assets))
        assert len(page.assets) == 2
        assert {asset.source_paths[0].resolve() for asset in page.assets} == {FIXTURE.resolve(), second.resolve()}

        fixture_row = next(
            row for row, asset in enumerate(page.assets)
            if asset.source_paths[0].resolve() == FIXTURE.resolve()
        )
        page.asset_table.setCurrentCell(fixture_row, 0)
        page.asset_table.selectRow(fixture_row)
        app.processEvents()
        assert page.selected_asset is page.assets[fixture_row]

        page.continue_button.click()
        assert _wait_until(lambda: page.session is not None and page._active_thread is None)
        assert page.measurement_combo.currentData() == MeasurementType.UNKNOWN.value
        assert page.scale_combo.currentData() == ValueScale.UNKNOWN.value

        page.prepare_button.click()  # 表格结构确认进入数据事实页
        assert page.organize_tabs.currentIndex() == page.organize_facts_index
        assert not page.prepare_button.isEnabled()  # 未知单位/尺度必须先阻断
        assert received == []

        page.measurement_combo.setCurrentIndex(
            page.measurement_combo.findData(MeasurementType.RAW_COUNT.value)
        )
        page.scale_combo.setCurrentIndex(page.scale_combo.findData(ValueScale.LINEAR.value))
        assert page.prepare_button.isEnabled()
        page.prepare_button.click()  # 明确确认后进入列角色页
        assert page.organize_tabs.currentIndex() == page.organize_roles_index
        page.prepare_button.click()  # 运行完整读取、校验、保存和 matrixReady 交接

        assert _wait_until(lambda: page._active_thread is None and len(received) == 1, timeout_ms=20000)
        assert len(received) == 1
        assert isinstance(received[0], ExpressionMatrix)
        assert group_page.matrix is received[0]
        assert received[0].values.shape == (4, 6)
        assert group_page.sample_table.rowCount() == 6
        assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == original_hash
        assert FIXTURE.read_bytes() == original_bytes
    finally:
        page.close()
        group_page.close()
        app.processEvents()


def test_nonlocal_url_drop_is_ignored_and_does_not_report_success() -> None:
    """A URL list without local files must be ignored by both Qt drag event handlers."""
    app = QApplication.instance() or QApplication([])
    page = ImportPage()
    try:
        enter, drop = _drop_urls(
            app,
            page,
            [QUrl("https://example.invalid/counts.tsv"), QUrl("mailto:someone@example.invalid")],
        )
        app.processEvents()
        assert not enter.isAccepted()
        assert not drop.isAccepted()
        assert page.assets == ()
        assert page.session is None
        assert page._active_thread is None
        assert "正在检查文件" not in page.auto_judgement.text()
    finally:
        page.close()
        app.processEvents()
