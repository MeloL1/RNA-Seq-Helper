from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from rnaseq_helper.grouping.service import GroupingService
from rnaseq_helper.domain.models import DataAsset
from rnaseq_helper.preparation.service import PreparationService
from rnaseq_helper.ui.pages.analysis_page import AnalysisPage
from rnaseq_helper.ui.pages.import_page import ImportPage


def test_unconfirmed_sample_is_treated_as_excluded() -> None:
    samples = ("ctrl_1", "ctrl_2", "test_1", "test_2", "extra")
    assignments = {
        "ctrl_1": "control", "ctrl_2": "control",
        "test_1": "test", "test_2": "test", "extra": "excluded",
    }
    result = GroupingService().validate(assignments, samples)
    assert result.passed
    assert result.group_sizes == {"control": 2, "test": 2}

    assignments["extra"] = ""
    result = GroupingService().validate(assignments, samples)
    assert result.passed
    assert result.group_sizes == {"control": 2, "test": 2}


def test_import_page_has_separate_import_and_organize_steps() -> None:
    QApplication.instance() or QApplication([])
    page = ImportPage()
    assert page.step_tabs.count() == 2
    assert page.step_tabs.objectName() == "importStepStack"
    assert page.organize_tabs.count() == 3
    assert page._question_titles == (
        "确认表格结构",
        "确认每个格子的数值",
        "确认基因编号与样本列",
    )
    assert page.question_label.text() == "确认表格"
    assert page.previous_sheet_button is None
    assert page.next_sheet_button is None


def test_import_actions_stay_inside_1024_and_narrow_viewports(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    page = ImportPage(project_root=tmp_path / "projects")
    source = tmp_path / "clear.tsv"
    source.write_text(
        "gene_id\tsample_a\tsample_b\n"
        + "".join(f"gene_{index}\t{index + 1}\t{index + 2}\n" for index in range(8)),
        encoding="utf-8",
    )
    asset = DataAsset("layout-test", (source,), "TABLE")
    page.session = PreparationService().start(asset, tmp_path / "projects" / "preview")
    page.sheet_combo.addItem("文本文件")
    page._refresh_controls()
    page.show()

    for width, height in ((1024, 768), (820, 560)):
        page.resize(width, height)
        page.step_tabs.setCurrentIndex(0)
        application.processEvents()
        assert page.continue_button.isVisible()
        origin = page.continue_button.mapTo(page, QPoint(0, 0))
        assert origin.x() >= 0 and origin.y() >= 0
        assert origin.x() + page.continue_button.width() <= page.width()
        assert origin.y() + page.continue_button.height() <= page.height()

        page.step_tabs.setCurrentIndex(1)
        page.organize_tabs.setCurrentIndex(0)
        page._update_question_state()
        application.processEvents()
        assert page.prepare_button.isVisible()
        origin = page.prepare_button.mapTo(page, QPoint(0, 0))
        assert origin.x() >= 0 and origin.y() >= 0
        assert origin.x() + page.prepare_button.width() <= page.width()
        assert origin.y() + page.prepare_button.height() <= page.height()

    page.close()
    application.processEvents()


def test_analysis_page_exposes_unconfirmed_as_exclusion() -> None:
    QApplication.instance() or QApplication([])
    page = AnalysisPage()
    assert page.sample_table.columnCount() == 8
    assert page.sample_filter is not None
    assert page.bulk_apply is not None
    assert page.bulk_group.itemData(1) == "excluded"
