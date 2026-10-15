from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from openpyxl import Workbook
from PySide6.QtWidgets import QApplication, QFileDialog, QLabel, QScrollArea, QTableWidget, QVBoxLayout, QWidget
from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer

from rnaseq_helper.domain.models import DataAsset, Evidence, ExpressionMatrix
from rnaseq_helper.readers.geo_reader import GeoSeriesMatrixReader
from rnaseq_helper.ui.pages.analysis_page import AnalysisPage
from rnaseq_helper.ui.pages.import_page import ArchiveCandidateDialog, GeoWizardDialog, ImportPage, TenXWizardDialog
from tests.fixtures.mock_factory import write_tenx_bundle


def wait_until(predicate, timeout_ms: int = 10000) -> bool:
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


def test_orientation_change_rederives_valid_columns(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    source = tmp_path / "matrix.tsv"
    source.write_text(
        "gene_id\tCtrl_1\tCtrl_2\n"
        "g1\t10\t12\n"
        "g2\t20\t22\n",
        encoding="utf-8",
    )
    page = ImportPage()
    asset = DataAsset("asset-test", (source,), "TABLE")
    page.session = page.preparer.start(asset, tmp_path / "project")
    page._refresh_controls()
    page.transpose_check.setChecked(True)

    assert page.session.recipe.transpose is True
    rows = page.preparer._view_rows(page.session.raw_table.rows, True)
    width = max(len(row) for row in rows)
    assert page.session.recipe.feature_id_column < width
    assert all(column < width for column in page.session.recipe.sample_columns)
    page.close()
    application.processEvents()


def test_column_roles_are_explicit_and_feature_id_is_unique(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    source = tmp_path / "annotated.tsv"
    source.write_text(
        "gene_id\tgene_symbol\tCtrl_1\tCtrl_2\n"
        "g1\tG1\t10\t12\n"
        "g2\tG2\t20\t22\n",
        encoding="utf-8",
    )
    page = ImportPage()
    asset = DataAsset("asset-roles", (source,), "TABLE")
    page.session = page.preparer.start(asset, tmp_path / "project")
    page._refresh_controls()

    feature, samples, annotations, ignored = page._role_columns()
    assert feature == 0
    assert samples == [2, 3]
    assert annotations == [1]
    assert ignored == []

    second_role = page.column_roles.cellWidget(1, 1)
    assert second_role is not None
    second_role.setCurrentIndex(0)
    application.processEvents()
    feature, samples, annotations, _ = page._role_columns()
    assert feature == 1
    assert 0 not in samples
    assert 0 in annotations
    page.close()
    application.processEvents()


def test_column_roles_page_keeps_guidance_readable_and_footer_fixed_at_compact_sizes(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    source = tmp_path / "annotated.tsv"
    sample_headers = [f"Control_sample_{index}" for index in range(18)]
    source.write_text(
        "\t".join(["gene_id", "gene_symbol", *sample_headers]) + "\n"
        + "\t".join(["g1", "G1", *["10" for _ in sample_headers]]) + "\n"
        + "\t".join(["g2", "G2", *["12" for _ in sample_headers]]) + "\n",
        encoding="utf-8",
    )
    page = ImportPage()
    asset = DataAsset(
        "asset-layout",
        (source,),
        "TABLE",
        evidence=(Evidence(
            "列名提示该表包含特征编号和多个样本表达列，但没有足够信息确认数值单位、归一化方式或是否进行过对数转换",
            "fixture metadata",
            0.5,
        ),),
    )
    page.session = page.preparer.start(asset, tmp_path / "project")
    page._refresh_controls()
    page._apply_auto_judgement(asset)
    page.step_tabs.setCurrentIndex(1)
    page.organize_tabs.setCurrentIndex(page.organize_roles_index)
    page.roles_edit_toggle.setChecked(True)
    host = QWidget()
    host_layout = QVBoxLayout(host)
    host_layout.setContentsMargins(14, 12, 14, 14)
    host_layout.setSpacing(12)
    navigation = QWidget()
    navigation.setFixedHeight(48)
    host_layout.addWidget(navigation)
    host_layout.addWidget(page, 1)

    for width, height in ((1024, 768), (820, 560)):
        host.resize(width, height)
        host.show()
        application.processEvents()

        hint_height = page.role_hint.heightForWidth(page.role_hint.width())
        assert hint_height <= page.role_hint.height()
        judgement_height = page.organize_auto_judgement.heightForWidth(
            page.organize_auto_judgement.width()
        )
        assert judgement_height <= page.organize_auto_judgement.height()
        judgement_bottom = (
            page.organize_auto_judgement.mapTo(page, QPoint(0, 0)).y()
            + page.organize_auto_judgement.height()
        )
        organize_tabs_top = page.organize_tabs.mapTo(page, QPoint(0, 0)).y()
        assert judgement_bottom < organize_tabs_top
        assert page.role_hint.geometry().bottom() < page.roles_edit_toggle.geometry().top()
        assert page.roles_edit_toggle.geometry().bottom() < page.roles_why_toggle.geometry().top()
        assert page.roles_why_toggle.geometry().bottom() < page.roles_editor.geometry().top()
        assert page.roles_editor.geometry().bottom() <= page.roles_editor.parentWidget().height()
        assert page.prepare_button.isVisible()

        scroll = page.findChild(QScrollArea, "organizeContentScroll")
        assert scroll is not None
        assert scroll.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
        assert scroll.geometry().bottom() < page.prepare_button.geometry().top()
        assert page.role_hint.isVisible() and page.roles_editor.isVisible()
        assert page.column_roles.verticalScrollBar().maximum() > 0
        if height == 560:
            assert scroll.verticalScrollBar().maximum() > 0

    host.close()
    application.processEvents()


def test_multi_sheet_summary_and_navigation(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    source = tmp_path / "multi.xlsx"
    workbook = Workbook()
    first = workbook.active
    first.title = "说明"
    first.append(["这是说明表"])
    second = workbook.create_sheet("表达矩阵")
    second.append(["gene_id", "Ctrl_1", "Ctrl_2"])
    second.append(["g1", 10, 12])
    second.append(["g2", 20, 22])
    workbook.save(source)
    workbook.close()

    page = ImportPage()
    page.load_path(source)
    assert wait_until(lambda: page._active_thread is None)
    assert page.sheet_combo.count() == 0
    page.continue_button.click()
    assert wait_until(lambda: page.session is not None and page._active_thread is None)
    assert page.sheet_combo.count() == 2
    assert page.sheet_combo.currentText() == "表达矩阵"
    assert "当前工作表：表达矩阵" in page.sheet_summary.text()
    page.sheet_combo.setCurrentText("说明")
    assert wait_until(lambda: page.session is not None and page.session.recipe.sheet_name == "说明" and page._active_thread is None)
    assert "当前工作表：说明" in page.sheet_summary.text()
    assert page.previous_sheet_button is None
    page.close()
    application.processEvents()


def test_file_picker_path_completes_import_and_updates_group_page(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    source = Path(__file__).parent.resolve() / "fixtures" / "company_counts.tsv"
    original = source.read_bytes()
    page = ImportPage(project_root=tmp_path / "projects")
    group_page = AnalysisPage()
    received: list[ExpressionMatrix] = []
    page.matrixReady.connect(group_page.set_matrix)
    page.matrixReady.connect(received.append)
    selection: dict[str, object] = {"accepted": False, "done": False}

    def choose_in_open_dialog() -> None:
        if selection["done"]:
            return
        dialog = next(
            (widget for widget in QApplication.topLevelWidgets() if isinstance(widget, QFileDialog)),
            None,
        )
        if dialog is None:
            QTimer.singleShot(10, choose_in_open_dialog)
            return
        selection["done"] = True
        selection["accepted"] = dialog.testOption(QFileDialog.Option.DontUseNativeDialog)
        selection["accepted"] = selection["accepted"] and dialog.fileMode() == QFileDialog.FileMode.ExistingFiles
        dialog.selectFile(str(source))
        dialog.accept()

    def stop_if_picker_did_not_open() -> None:
        selection["done"] = True
        modal = application.activeModalWidget()
        if modal is not None:
            modal.reject()

    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(stop_if_picker_did_not_open)
    timeout.start(3000)
    QTimer.singleShot(0, choose_in_open_dialog)
    page.choose_file()
    timeout.stop()

    assert selection["accepted"] is True
    assert wait_until(lambda: page._active_thread is None and bool(page.assets))
    assert page.assets[0].source_paths == (source,)
    assert page.selected_asset is not None
    assert page.selected_asset.source_paths == (source,)

    page.continue_button.click()
    assert wait_until(lambda: page.session is not None and page._active_thread is None)
    page.prepare_button.click()  # structure -> facts
    assert page.organize_tabs.currentIndex() == page.organize_facts_index
    assert not page.prepare_button.isEnabled()
    page.prepare_button.click()  # unknown facts are still blocked
    assert page.organize_tabs.currentIndex() == page.organize_facts_index
    page.measurement_combo.setCurrentIndex(page.measurement_combo.findData("RAW_COUNT"))
    page.scale_combo.setCurrentIndex(page.scale_combo.findData("LINEAR"))
    assert page.prepare_button.isEnabled()
    page.prepare_button.click()  # facts -> column roles
    assert page.organize_tabs.currentIndex() == page.organize_roles_index
    page.prepare_button.click()  # full read, validation, save, matrixReady
    assert wait_until(lambda: bool(received) and page._active_thread is None, timeout_ms=20000)

    assert len(received) == 1
    matrix = received[0]
    assert isinstance(matrix, ExpressionMatrix)
    assert matrix.values.shape == (4, 6)
    assert group_page.matrix is matrix
    assert group_page.sample_table.rowCount() == 6
    assert "4 个特征 × 6 个样本" in group_page.matrix_label.text()
    assert matrix.values.path.is_file()
    assert matrix.values.path.parent.name == "prepared"
    assert source.read_bytes() == original  # chooser/scan read, but do not rewrite, the fixture
    page.close()
    group_page.close()
    application.processEvents()


def test_import_screen_keeps_large_table_preview_bounded(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    source = tmp_path / "large_counts.tsv"
    source.write_text(
        "gene_id\tCtrl_1\tCtrl_2\n"
        + "".join(f"gene_{index}\t{index + 1}\t{index + 2}\n" for index in range(1500)),
        encoding="utf-8",
    )
    page = ImportPage()
    page.load_path(source)
    assert wait_until(lambda: page._active_thread is None)
    page.continue_button.click()
    assert wait_until(lambda: page.session is not None and page._active_thread is None)

    assert page.session is not None
    assert page.session.raw_table.row_count == 40
    assert page.session.raw_table.is_complete is False
    assert "完整特征数会在最终校验时统计" in page.sheet_summary.text()
    assert "完整行数和数据有效性将在最终校验时检查" in page.organize_status_label.text()

    page.close()
    application.processEvents()


def test_mixed_delivery_list_recommends_counts_and_explains_ignored_files(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    package = tmp_path / "delivery"
    package.mkdir()
    (package / "a.pdf").write_bytes(b"%PDF-1.4 delivery note")
    (package / "b_counts.tsv").write_text(
        "raw counts\tcontrol_1\tcontrol_2\nfeature_a\t12\t14\nfeature_b\t21\t19\n",
        encoding="utf-8",
    )
    (package / "sample.fastq.gz").write_bytes(b"raw sequencing placeholder")
    page = ImportPage()
    page.load_path(package)
    assert wait_until(lambda: page._active_thread is None)

    rows = {
        page.asset_table.item(row, 0).text(): row
        for row in range(page.asset_table.rowCount())
    }
    assert set(rows) == {"a.pdf", "b_counts.tsv", "sample.fastq.gz"}
    pdf_row = rows["a.pdf"]
    count_row = rows["b_counts.tsv"]
    fastq_row = rows["sample.fastq.gz"]
    assert "忽略" in page.asset_table.item(pdf_row, 1).text()
    assert "不会读取为表达矩阵" in page.asset_table.item(pdf_row, 3).text()
    assert "建议优先查看" in page.asset_table.item(count_row, 1).text()
    assert "原始 count" in page.asset_table.item(count_row, 3).text()
    assert "原始测序文件（不支持）" in page.asset_table.item(fastq_row, 1).text()
    assert "不支持比对/定量" in page.asset_table.item(fastq_row, 3).text()
    assert page.selected_asset is not None
    assert page.selected_asset.source_paths[0].name == "b_counts.tsv"
    assert page.continue_button.isEnabled()

    page.close()
    application.processEvents()


def test_full_import_emits_compatible_matrix_after_background_validation(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    source = tmp_path / "counts.tsv"
    source.write_text(
        "raw counts\tcontrol_1\tcontrol_2\n"
        + "".join(f"gene_{index}\t{index + 1}\t{index + 2}\n" for index in range(1500)),
        encoding="utf-8",
    )
    page = ImportPage(project_root=tmp_path / "projects")
    received = []
    page.matrixReady.connect(received.append)
    page.load_path(source)
    assert wait_until(lambda: page._active_thread is None)
    page.continue_button.click()
    assert wait_until(lambda: page.session is not None and page._active_thread is None)
    assert page.session is not None and page.session.raw_table.row_count == 40

    page.measurement_combo.setCurrentIndex(page.measurement_combo.findData("RAW_COUNT"))
    page.scale_combo.setCurrentIndex(page.scale_combo.findData("LINEAR"))
    page.prepare_button.click()  # 表格结构 -> 数值事实
    page.prepare_button.click()  # 数值事实 -> 列角色
    page.prepare_button.click()  # 完整后台读取、校验、保存并发出 matrixReady
    assert wait_until(lambda: bool(received) and page._active_thread is None, timeout_ms=20000)

    assert len(received) == 1
    matrix = received[0]
    assert isinstance(matrix, ExpressionMatrix)
    assert matrix.values.shape == (1500, 2)
    assert matrix.values.path.is_file()
    assert matrix.values.path.parent.name == "prepared"
    assert matrix.measurement_provenance.startswith("user-selected input facts:")
    assert "measurement_type=RAW_COUNT[linked_text_candidate]" in matrix.measurement_provenance
    assert len(list((tmp_path / "projects").iterdir())) == 1

    page.close()
    application.processEvents()


def test_archive_reference_is_visible_but_not_selectable(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    candidates = [
        DataAsset("expression", (tmp_path / "expression" / "counts.tsv",), "TABLE", "EXPRESSION_CANDIDATE", shape_hint=(4, 6)),
        DataAsset("reference", (tmp_path / "reference" / "GPL.annot",), "REFERENCE", "REFERENCE_CANDIDATE"),
    ]
    for candidate in candidates:
        candidate.source_paths[0].parent.mkdir(parents=True, exist_ok=True)
        candidate.source_paths[0].write_text("placeholder", encoding="utf-8")
    dialog = ArchiveCandidateDialog(candidates)
    reference_leaf = dialog.tree.topLevelItem(1).child(0)
    assert reference_leaf.data(0, Qt.ItemDataRole.UserRole) == -1
    assert "不作为表达矩阵" in reference_leaf.text(1)
    dialog.close()
    application.processEvents()


def test_raw_sequencing_input_gets_guidance_and_does_not_enter_matrix_flow(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    source = tmp_path / "reads.fastq"
    source.write_text("@read1\nACGT\n+\nIIII\n", encoding="utf-8")
    page = ImportPage()
    page.load_path(source)
    assert wait_until(lambda: page._active_thread is None)
    assert "不支持 FASTQ/BAM/SAM" in page.status_label.text()
    assert page.session is None
    page.close()
    application.processEvents()


def test_tenx_ui_shows_sparse_preview_and_keeps_bulk_button_unavailable(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    directory = write_tenx_bundle(tmp_path / "filtered_feature_bc_matrix", feature_count=10, cell_count=6)
    page = ImportPage(project_root=tmp_path / "projects")
    page.load_path(directory)
    assert wait_until(lambda: page._active_thread is None)
    page.continue_button.click()
    assert wait_until(lambda: page.tenx_bundle is not None and page._active_thread is None)
    # The page is intentionally not shown in this offscreen test, so
    # isVisible() also depends on the parent window.  isHidden() checks the
    # label's explicit visibility state set by load_path().
    assert not page.tenx_preview.isHidden()
    assert "稀疏度" in page.tenx_preview.text()
    assert "不会把细胞当作独立 bulk" in page.tenx_preview.text()
    assert not page.prepare_button.isEnabled()
    assert page.tenx_wizard_button.isEnabled()
    assert page.tenx_bundle is not None
    assert page.tenx_manifest_path is not None
    dialog = TenXWizardDialog(page.tenx_bundle, page.tenx_manifest_path, page)
    assert dialog.pages.count() == 3
    assert dialog.back_button.isEnabled() is False
    dialog.next_button.click()
    assert dialog.pages.currentIndex() == 1
    dialog.next_button.click()
    assert dialog.pages.currentIndex() == 2
    assert not dialog.done_button.isHidden()
    dialog.close()
    page.close()
    application.processEvents()


def test_geo_wizard_exposes_platform_and_sample_metadata(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    source = tmp_path / "GSE1_series_matrix.txt"
    source.write_text(
        "!Sample_geo_accession = GSM1\n"
        "!Sample_geo_accession = GSM2\n"
        "!Sample_title = control replicate 1\n"
        "!Sample_title = treated replicate 1\n"
        "!Sample_platform_id = GPL1\n"
        "!Sample_platform_id = GPL1\n"
        "!series_matrix_table_begin\n"
        "ID_REF\tGSM1\tGSM2\nprobe1\t8.0\t9.0\n"
        "!series_matrix_table_end\n",
        encoding="utf-8",
    )
    dialog = GeoWizardDialog(GeoSeriesMatrixReader().read(source))
    assert dialog.pages.count() == 3
    dialog.next_button.click()
    sample_table = dialog.pages.currentWidget().findChild(QTableWidget)
    assert sample_table is not None
    assert sample_table.rowCount() == 2
    assert sample_table.item(0, 0).text() == "GSM1"
    assert sample_table.item(0, 1).text() == "control replicate 1"
    dialog.next_button.click()
    assert "不会自动提交分析" in " ".join(label.text() for label in dialog.pages.currentWidget().findChildren(QLabel))
    dialog.close()
    application.processEvents()


def test_archive_candidate_dialog_builds_directory_tree(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    candidates = [
        DataAsset("table", (tmp_path / "expression" / "counts.tsv",), "TABLE", "EXPRESSION_CANDIDATE", shape_hint=(4, 6)),
        DataAsset("reference", (tmp_path / "reference" / "GPL.annot",), "REFERENCE", "REFERENCE_CANDIDATE", shape_hint=None),
    ]
    dialog = ArchiveCandidateDialog(candidates)
    assert dialog.tree.topLevelItemCount() == 2
    directory = dialog.tree.topLevelItem(0)
    assert directory.childCount() == 1
    leaf = directory.child(0)
    assert leaf.data(0, Qt.ItemDataRole.UserRole) in {0, 1}
    assert "TABLE" in leaf.text(1) or "REFERENCE" in leaf.text(1)
    dialog.close()
    application.processEvents()
