from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from openpyxl import Workbook
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QScrollArea

from rnaseq_helper.preparation.service import PreparationService
from rnaseq_helper.recognition.scanner import AssetScanner
from rnaseq_helper.ui.pages.import_page import ImportPage


def _page() -> ImportPage:
    QApplication.instance() or QApplication([])
    return ImportPage()


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


def _write_table(path: Path, label: str) -> Path:
    path.write_text(
        f"{label}\tcontrol_1\tcontrol_2\nfeature_a\t12\t14\nfeature_b\t21\t19\n",
        encoding="utf-8",
    )
    return path


def test_import_entry_is_scrollable_and_explains_count_recommendation(tmp_path: Path) -> None:
    counts = _write_table(tmp_path / "b_counts.tsv", "raw counts")
    tpm = _write_table(tmp_path / "a_tpm.tsv", "TPM")
    page = _page()
    page.assets = AssetScanner().scan((tpm, counts)).assets
    page._render_assets()
    page._select_recommended_asset()

    assert page.findChild(QScrollArea, "importContentScroll") is not None
    assert page.selected_asset is not None
    assert page.selected_asset.source_paths[0].name == "b_counts.tsv"
    assert "建议优先查看" in page.asset_table.item(page.asset_table.currentRow(), 1).text()
    assert "推荐理由" in page.auto_judgement.text()
    assert "交付说明核实" in page.auto_judgement.text()

    page.close()


def test_equal_priority_count_candidates_require_explicit_choice(tmp_path: Path) -> None:
    one = _write_table(tmp_path / "one.tsv", "raw counts")
    two = _write_table(tmp_path / "two.tsv", "raw counts")
    page = _page()
    page.assets = AssetScanner().scan((one, two)).assets
    page._render_assets()
    page._select_recommended_asset()

    assert page.selected_asset is None
    assert not page.continue_button.isEnabled()
    assert "不会默认选第一个" in page.auto_judgement.text()

    page.close()


def test_beginner_recommendation_hides_internal_enum_and_density_score(tmp_path: Path) -> None:
    source = _write_table(tmp_path / "counts.tsv", "raw counts")
    asset = AssetScanner().scan((source,)).assets[0]
    page = _page()

    page._apply_auto_judgement(asset)

    text = page.auto_judgement.text()
    assert "原始 count" in text
    assert "RAW_COUNT" not in text
    assert "数值密度" not in text
    assert "0.88" not in text
    assert "原文摘录候选：counts.tsv · 表格记录第 1 行、第 1 列：“raw counts”" in text
    assert "现在先确认一项：先对照交付说明确认" in text

    page.measurement_combo.setCurrentIndex(
        page.measurement_combo.findData("RAW_COUNT")
    )
    assert "接着确认数字是否做过 log 转换" in page.auto_judgement.text()
    page.scale_combo.setCurrentIndex(page.scale_combo.findData("LINEAR"))
    assert "当前状态：你已选择数值单位和尺度" in page.auto_judgement.text()
    assert "只有尚未确认的事实会阻止开始分析" in page.auto_judgement.text()

    page.close()


def test_log2_candidate_without_formula_is_not_completed_by_guessing(tmp_path: Path) -> None:
    source = tmp_path / "expression.tsv"
    source.write_text(
        "Measurement\tTPM\n"
        "Transformation\tlog2 normalized expression\n"
        "feature_id\tsample_a\tsample_b\n",
        encoding="utf-8",
    )
    asset = AssetScanner().scan((source,)).assets[0]
    page = _page()
    page._apply_auto_judgement(asset)
    page.measurement_combo.setCurrentIndex(page.measurement_combo.findData("TPM"))
    page.scale_combo.setCurrentIndex(page.scale_combo.findData("LOG2"))

    text = page.auto_judgement.text()
    assert "文件没有写完整公式或伪计数" in text
    assert "不会反推或补造公式" in text
    assert "log2(TPM + 1)" not in text

    page.close()


def test_workbook_count_sheet_is_recommended_over_tpm_but_not_confirmed(tmp_path: Path) -> None:
    workbook = Workbook()
    counts = workbook.active
    counts.title = "raw_counts"
    counts.append(["feature_id", "control_1", "control_2"])
    counts.append(["gene_a", 12, 14])
    counts.append(["gene_b", 21, 19])
    tpm = workbook.create_sheet("TPM")
    tpm.append(["feature_id", "control_1", "control_2"])
    tpm.append(["gene_a", 2.4, 2.8])
    tpm.append(["gene_b", 4.2, 3.8])
    source = tmp_path / "delivery.xlsx"
    workbook.save(source)
    workbook.close()

    page = _page()
    page.load_path(source)
    assert _wait_until(lambda: page._active_thread is None)
    assert page.selected_asset is not None
    assert "原始 count 通常更适合当前 RNA-seq 统计模型" in page.auto_judgement.text()
    page.continue_button.click()
    assert _wait_until(
        lambda: page.session is not None and page._active_thread is None
    )

    assert page.session is not None
    assert page.session.recipe.sheet_name == "raw_counts"
    assert page.sheet_combo.currentText() == "raw_counts"
    assert page.sheet_combo.count() == 2
    assert page.measurement_combo.currentData() == "UNKNOWN"
    assert "原始计数更适合当前统计模型" in page.measurement_suggestion.text()
    assert "确认" in page.organize_auto_judgement.text()

    page.close()


def test_unknown_recognition_has_one_compact_summary_and_collapsed_evidence(tmp_path: Path) -> None:
    page = _page()
    source = _write_table(tmp_path / "expression.tsv", "feature_id")
    asset = AssetScanner().scan((source,)).assets[0]
    page._apply_auto_judgement(asset)

    assert "识别摘要" in page.organize_auto_judgement.text()
    assert "识别依据" not in page.organize_auto_judgement.text()
    assert "现在先确认一项" not in page.measurement_suggestion.text()
    assert page.evidence_scroll.isHidden()
    assert page.evidence_scroll.maximumHeight() == 180
    assert page.measurement_combo.currentData() == "UNKNOWN"
    assert page.scale_combo.currentData() == "UNKNOWN"
    page.evidence_toggle.click()
    assert not page.evidence_scroll.isHidden()
    page.close()


def test_text_candidates_keep_original_evidence_visible_before_confirmation(tmp_path: Path) -> None:
    page = _page()
    source = _write_table(tmp_path / "expression.tsv", "raw counts")
    asset = AssetScanner().scan((source,)).assets[0]
    page._apply_auto_judgement(asset)

    assert page.evidence_toggle.isChecked()
    assert not page.evidence_scroll.isHidden()
    assert "raw counts" in page.measurement_suggestion.text()
    assert "原文摘录" not in page.organize_auto_judgement.text()
    assert page.measurement_combo.currentData() == "UNKNOWN"
    assert page.use_evidence_button.isEnabled()
    page.evidence_toggle.click()
    assert not page.use_evidence_button.isEnabled()
    page.evidence_toggle.click()
    assert page.use_evidence_button.isEnabled()
    page.close()


def test_each_table_question_has_an_expandable_plain_language_reason(tmp_path: Path) -> None:
    page = _page()
    source = _write_table(tmp_path / "raw.tsv", "raw counts")
    asset = AssetScanner().scan((source,)).assets[0]
    page.session = PreparationService().start(asset, tmp_path / "project")
    page._refresh_controls()

    assert page.structure_why.isHidden()
    page.structure_why_toggle.click()
    assert not page.structure_why.isHidden()
    assert "表头行错了" in page.structure_why.text()

    assert page.roles_why.isHidden()
    page.roles_why_toggle.click()
    assert not page.roles_why.isHidden()
    assert "基因编号" in page.roles_why.text()
    assert "基因编号" in page.role_hint.text()

    page.close()


def test_clear_table_uses_compact_confirmation_with_editors_on_demand(tmp_path: Path) -> None:
    source = tmp_path / "clear.tsv"
    source.write_text(
        "gene_id\tsample_a\tsample_b\tsample_c\n"
        + "".join(f"gene_{index}\t{index + 1}\t{index + 2}\t{index + 3}\n" for index in range(6)),
        encoding="utf-8",
    )
    page = _page()
    asset = AssetScanner().scan((source,)).assets[0]
    page.session = PreparationService().start(asset, tmp_path / "project")
    page.sheet_combo.addItem("文本文件")
    page._refresh_controls()

    assert page.structure_controls.isHidden()
    assert page.roles_editor.isHidden()
    assert "gene_id" in page.role_hint.text()
    assert "3 列样本数值" in page.role_hint.text()

    page.structure_edit_toggle.click()
    page.roles_edit_toggle.click()
    assert not page.structure_controls.isHidden()
    assert not page.roles_editor.isHidden()
    assert page.structure_edit_toggle.text() == "收起表格结构设置"
    assert page.roles_edit_toggle.text() == "收起逐列设置"

    page.organize_tabs.setCurrentIndex(page.organize_facts_index)
    page._update_question_state()
    assert page.measurement_combo.currentData() == "UNKNOWN"
    assert page.scale_combo.currentData() == "UNKNOWN"
    assert not page.prepare_button.isEnabled()
    page.close()


def test_ambiguous_structure_and_duplicate_sample_names_expand_corrections(tmp_path: Path) -> None:
    source = tmp_path / "ambiguous.tsv"
    source.write_text(
        "item\tS\tS\n"
        "A\t10\t11\n"
        "B\t12\t13\n"
        "C\t14\t15\n",
        encoding="utf-8",
    )
    page = _page()
    asset = AssetScanner().scan((source,)).assets[0]
    page.session = PreparationService().start(asset, tmp_path / "project")
    page.sheet_combo.addItem("文本文件")
    page._refresh_controls()

    assert not page.structure_controls.isHidden()
    assert not page.roles_editor.isHidden()
    page.close()


def test_table_summary_uses_features_by_samples_language(tmp_path: Path) -> None:
    page = _page()
    source = _write_table(tmp_path / "raw.tsv", "raw counts")
    asset = AssetScanner().scan((source,)).assets[0]
    page.session = PreparationService().start(asset, tmp_path / "project")
    page._refresh_controls()

    assert "特征（如基因）" in page.sheet_summary.text()
    assert "2 个样本" in page.sheet_summary.text()
    assert "×" in page.sheet_summary.text()

    page.close()


def test_cancel_control_is_usable_again_after_a_cancelled_task() -> None:
    page = _page()
    page._set_busy(True, cancellable=True)
    assert page.cancel_button.isEnabled()
    assert page.organize_cancel_button.isEnabled()

    page.cancel_button.setEnabled(False)
    page.organize_cancel_button.setEnabled(False)
    page._set_busy(False)
    page._set_busy(True, cancellable=True)

    assert page.cancel_button.isEnabled()
    assert page.organize_cancel_button.isEnabled()
    page.close()
