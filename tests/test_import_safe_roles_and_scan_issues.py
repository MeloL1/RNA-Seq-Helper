from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from rnaseq_helper.domain.models import DataAsset
from rnaseq_helper.preparation.service import PreparationService
from rnaseq_helper.ui.pages.import_page import ImportPage


def _wait_until(predicate, timeout_ms: int = 10000) -> bool:
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


def _annotated_matrix(path: Path) -> None:
    path.write_text(
        "gene_id\tlength\tstart\tend\tGC\tCtrl_1\tCtrl_2\n"
        "g1\t1000\t1\t1000\t0.42\t12\t15\n"
        "g2\t850\t1200\t2050\t0.51\t20\t18\n",
        encoding="utf-8",
    )


def test_numeric_annotation_headers_are_not_suggested_as_sample_columns(tmp_path: Path) -> None:
    source = tmp_path / "annotated.tsv"
    _annotated_matrix(source)
    asset = DataAsset("annotated", (source,), "TABLE")

    session = PreparationService().start(asset, tmp_path / "project")

    assert session.recipe.sample_columns == (5, 6)
    assert session.recipe.feature_id_column == 0
    assert set(session.recipe.annotation_columns) >= {1, 2, 3, 4}
    assert PreparationService._numeric_columns(
        (("gene_id", "GC %", "sample-A", "sample-B"), ("g", "0.4", "10", "12")),
        1,
        4,
    ) == [2, 3]


def test_suspected_numeric_annotation_is_explained_expanded_and_overridable(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "annotated.tsv"
    _annotated_matrix(source)
    page = ImportPage()
    page.session = page.preparer.start(DataAsset("annotated-ui", (source,), "TABLE"), tmp_path / "project")
    page._refresh_controls()

    assert page._role_columns()[1] == [5, 6]
    assert not page.roles_editor.isHidden()
    assert "length、start、end、GC" in page.role_hint.text()
    assert "已从样本表达建议中排除" in page.role_hint.text()

    length_role = page.column_roles.cellWidget(1, 1)
    assert length_role is not None
    length_role.setCurrentIndex(length_role.findData("sample"))
    assert 1 in page._role_columns()[1]

    page.close()
    app.processEvents()


def test_scan_issue_is_visible_while_valid_candidate_remains_actionable(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "counts.tsv"
    source.write_text("gene_id\tcontrol_1\tcontrol_2\ng1\t10\t12\n", encoding="utf-8")
    missing = tmp_path / "missing.tsv"
    page = ImportPage()
    page.load_paths((source, missing))

    assert _wait_until(lambda: page._active_thread is None)
    assert len(page.assets) == 1
    assert page.assets[0].source_paths[0] == source
    assert page.continue_button.isEnabled()
    summary = page.asset_summary_label.text()
    assert "扫描问题" in summary
    assert str(missing.resolve()) in summary
    assert "请确认文件仍在原位置" in summary

    page.close()
    app.processEvents()
