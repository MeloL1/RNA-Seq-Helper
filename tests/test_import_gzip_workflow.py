from __future__ import annotations

import gzip
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from rnaseq_helper.domain.models import MeasurementType, ValueScale, sha256_file
from rnaseq_helper.ui.pages.import_page import ImportPage


def _wait_until(predicate, timeout_ms: int = 10_000) -> bool:
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


def test_import_page_gzip_to_preview_keeps_unknown_facts_blocked(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    source = tmp_path / "expression.csv.gz"
    content = "feature,S1,S2,S3\n" + "".join(
        f"feature_{index},{index + 1},{index + 2},{index + 3}\n"
        for index in range(12)
    )
    with gzip.open(source, "wt", encoding="utf-8", newline="") as handle:
        handle.write(content)
    source_hash = sha256_file(source)
    project_root = tmp_path / "projects"
    page = ImportPage(project_root=project_root)
    received = []
    page.matrixReady.connect(received.append)

    try:
        page.load_path(source)
        assert _wait_until(lambda: page._active_thread is None and bool(page.assets))
        assert len(page.assets) == 1
        assert page.assets[0].kind == "ARCHIVE"
        archive_asset_id = page.assets[0].asset_id
        assert page.selected_asset is not None
        assert page.continue_button.isEnabled()

        page.continue_button.click()
        assert _wait_until(
            lambda: page._active_thread is None
            and len(page.assets) == 1
            and page.assets[0].kind == "TABLE"
        )
        expression_asset = page.selected_asset
        assert expression_asset is not None and expression_asset.kind == "TABLE"
        extracted_path = expression_asset.source_paths[0]
        assert extracted_path.is_file()
        assert project_root.resolve() in extracted_path.resolve().parents
        assert expression_asset.parent_asset_id == archive_asset_id

        page.continue_button.click()
        assert _wait_until(lambda: page._active_thread is None and page.session is not None)
        assert page.session is not None
        assert page.session.raw_table.rows[0] == ("feature", "S1", "S2", "S3")
        assert page.measurement_combo.currentData() == MeasurementType.UNKNOWN.value
        assert page.scale_combo.currentData() == ValueScale.UNKNOWN.value

        page.prepare_button.click()
        assert page.organize_tabs.currentIndex() == 1
        assert not page.prepare_button.isEnabled()
        assert "数据类型/表达矩阵/单位" in page.organize_auto_judgement.text()
        assert not received
        assert sha256_file(source) == source_hash
    finally:
        page.close()
        application.processEvents()
