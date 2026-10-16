from __future__ import annotations

import hashlib
import json
import os
import csv
from threading import Event
from pathlib import Path

import pytest
from openpyxl import Workbook
from PIL import Image
from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication

from rnaseq_helper.services.project_store import ProjectLoadCancelled, ProjectLoadError, ProjectStore
from rnaseq_helper.analysis.service import AnalysisService
from tests._planning import PlanningService
from rnaseq_helper.domain.models import JobContext
from rnaseq_helper.services.project_lock import project_directory_lock
from rnaseq_helper.ui.pages.analysis_page import AnalysisPage
from rnaseq_helper.ui.pages.results_page import ResultsPage
from rnaseq_helper.ui.workers.project_worker import ProjectLoadWorker
from rnaseq_helper.ui.pages.import_page import ImportPage


def _write_project(root: Path) -> tuple[Path, str]:
    prepared = root / "prepared"
    analysis = root / "analysis"
    reports = root / "reports"
    prepared.mkdir(parents=True)
    analysis.mkdir()
    reports.mkdir()
    matrix_path = prepared / "expression_matrix.tsv"
    matrix_path.write_text(
        "feature_key\tS1\tS2\nfeature-a\t1\t2\nfeature-b\t3\t4\n",
        encoding="utf-8",
    )
    matrix_hash = hashlib.sha256(matrix_path.read_bytes()).hexdigest()
    (prepared / "feature_metadata.tsv").write_text(
        "feature_key\toriginal_id\tgene_symbol\nfeature-a\tA\tAlpha\nfeature-b\tB\tBeta\n",
        encoding="utf-8",
    )
    (prepared / "sample_metadata.tsv").write_text(
        "sample_id\tsample_title\nS1\tone\nS2\ttwo\n", encoding="utf-8",
    )
    recipe = {
        "measurement_type": "TPM", "value_scale": "LOG2", "input_transform": "log2(TPM+1)",
        "species_taxid": "9606", "fact_confirmations": [
            {"fact_key": "measurement_type", "selected_value": "TPM", "status": "user_confirmed_without_direct_text"},
            {"fact_key": "value_scale", "selected_value": "LOG2", "status": "user_confirmed_without_direct_text"},
        ],
    }
    (root / "preparation-recipe.json").write_text(json.dumps(recipe), encoding="utf-8")
    manifest = {
        "project_id": "project-test", "matrix_id": "matrix-test", "source_asset_id": "asset-test",
        "feature_id_type": "CUSTOM_ORIGINAL", "matrix_content_hash": matrix_hash,
        "validation": {
            "passed": True, "feature_count": 2, "sample_count": 2, "numeric_cell_count": 4,
            "issues": [],
        },
    }
    (root / "project.json").write_text(json.dumps(manifest), encoding="utf-8")
    feature_hash = hashlib.sha256((prepared / "feature_metadata.tsv").read_bytes()).hexdigest()
    plan = {
        "plan_id": "plan-test", "matrix_hash": matrix_hash, "feature_metadata_hash": feature_hash,
        "method": "LIMMA_ON_LOG2_TPM", "analysis_basis": "normalized_log_expression",
        "method_profile_id": "normalized-log-limma-trend-v1",
        "design": {
            "type": "independent_two_group", "replicate_structure": "independent",
            "replicate_structure_confirmed": True,
            "assignments": {"S1": "control", "S2": "test"}, "paired_subjects": {}, "batch": {},
        },
    }
    (analysis / "analysis-plan.json").write_text(json.dumps(plan), encoding="utf-8")
    result = {"method": "LIMMA_ON_LOG2_TPM", "profile_id": "normalized-log-limma-trend-v1", "table": [
        {
            "feature_key": key, "original_id": key, "gene_symbol": None,
            "log2FoldChange": 1.0, "pvalue": 0.05, "padj": 0.1,
            "direction": "up", "tested": True, "reason_not_tested": "",
            "mean_control_expression": 1.0, "mean_treated_expression": 2.0,
            "analysis_method": "LIMMA_ON_LOG2_TPM", "analysis_basis": "normalized_log_expression",
            "effect_scale": "log2_expression_difference", "mean_expression_unit": "log2(TPM+1)",
        }
        for key in ("feature-a", "feature-b")
    ]}
    result_path = analysis / "deg-result.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    report_path = reports / "analysis-report.html"
    report_path.write_text(
        "<!doctype html><html lang='zh-CN'><head><title>RNA-Seq Helper</title></head>"
        "<body><main><h1>分析报告</h1><p>测试用的有效离线报告。</p></main></body></html>",
        encoding="utf-8",
    )
    xlsx_path = reports / "deg-results.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "DEG Results"
    sheet.append(["feature_key", "gene_symbol", "log2FoldChange", "pvalue", "padj"])
    for row in result["table"]:
        sheet.append([row["feature_key"], "NA", row["log2FoldChange"], row["pvalue"], row["padj"]])
    workbook.save(xlsx_path)
    figures = root / "figures"
    figures.mkdir()
    image_path = figures / "pca.png"
    Image.new("RGB", (2, 2), color="white").save(image_path, format="PNG")
    figure_names = {
        "pca": "pca.png",
        "sample_correlation": "sample-correlation.png",
        "pvalue_histogram": "p-value-histogram.png",
        "volcano": "volcano.png",
        "top_heatmap": "top-heatmap.png",
    }
    for filename in figure_names.values():
        path = figures / filename
        if filename != "pca.png":
            path.write_bytes(image_path.read_bytes())
    figure_manifest_path = figures / "figure-manifest.json"
    figure_manifest_path.write_text(
        json.dumps({key: str(figures / filename) for key, filename in figure_names.items()}),
        encoding="utf-8",
    )
    (reports / "analysis-manifest.json").write_text(json.dumps({
        "matrix_hash": matrix_hash,
        "feature_metadata_hash": feature_hash,
        "sample_metadata_hash": hashlib.sha256((prepared / "sample_metadata.tsv").read_bytes()).hexdigest(),
        "preparation_recipe_hash": hashlib.sha256((root / "preparation-recipe.json").read_bytes()).hexdigest(),
        "analysis_plan_hash": hashlib.sha256((analysis / "analysis-plan.json").read_bytes()).hexdigest(),
        "deg_result_hash": hashlib.sha256(result_path.read_bytes()).hexdigest(),
        "html_hash": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        "xlsx_hash": hashlib.sha256(xlsx_path.read_bytes()).hexdigest(),
        "figure_manifest_hash": hashlib.sha256(figure_manifest_path.read_bytes()).hexdigest(),
        "figure_hashes": {
            filename: hashlib.sha256((figures / filename).read_bytes()).hexdigest()
            for filename in figure_names.values()
        },
    }), encoding="utf-8")
    return matrix_path, matrix_hash


def test_load_saved_project_is_read_only_and_restores_matching_plan_and_result(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    matrix_path, matrix_hash = _write_project(project)
    before = {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()}

    snapshot = ProjectStore.load(project)

    assert snapshot.matrix.content_hash == matrix_hash
    assert snapshot.matrix.values.path == matrix_path
    assert snapshot.matrix.values.shape == (2, 2)
    assert snapshot.matrix.measurement_type.value == "TPM"
    assert snapshot.matrix.value_scale.value == "LOG2"
    assert snapshot.saved_plan["design"]["assignments"] == {"S1": "control", "S2": "test"}
    assert [row["feature_key"] for row in snapshot.saved_result["table"]] == ["feature-a", "feature-b"]
    assert snapshot.result_integrity_valid is True
    assert snapshot.report_valid is True
    assert {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()} == before


def test_moved_project_ignores_stale_absolute_report_links_and_restores_from_local_files(
    tmp_path: Path,
) -> None:
    original = tmp_path / "original" / "project"
    original.parent.mkdir()
    original.mkdir()
    _write_project(original)
    manifest_path = original / "reports" / "analysis-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({
        "html": str(original / "reports" / "analysis-report.html"),
        "xlsx": str(original / "reports" / "deg-results.xlsx"),
        "figures": {
            key: str(original / "figures" / filename)
            for key, filename in {
                "pca": "pca.png",
                "sample_correlation": "sample-correlation.png",
                "pvalue_histogram": "p-value-histogram.png",
                "volcano": "volcano.png",
                "top_heatmap": "top-heatmap.png",
            }.items()
        },
    })
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    relocated = tmp_path / "relocated" / "project"
    relocated.parent.mkdir()
    original.rename(relocated)

    snapshot = ProjectStore.load(relocated)

    assert snapshot.project_dir == relocated
    assert snapshot.report_path == relocated / "reports" / "analysis-report.html"
    assert snapshot.result_integrity_valid is True
    assert snapshot.report_valid is True
    assert snapshot.saved_result is not None


def test_restore_preserves_cell_observation_unit_from_project_manifest(tmp_path: Path) -> None:
    project = tmp_path / "cell-project"
    project.mkdir()
    _write_project(project)
    manifest_path = project / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["observation_unit"] = "BULK_SAMPLE"
    manifest["source_asset"] = {"observation_unit_hint": "CELL"}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    snapshot = ProjectStore.load(project)

    assert snapshot.matrix.observation_unit.value == "CELL"


def test_missing_original_source_warns_but_keeps_saved_project_read_only(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    manifest_path = project / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_path"] = str(tmp_path / "moved-or-missing-input.tsv")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    before = {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()}

    snapshot = ProjectStore.load(project)

    assert snapshot.matrix.values.shape == (2, 2)
    assert snapshot.saved_result is not None
    assert any("原始来源文件当前无法访问" in warning for warning in snapshot.warnings)
    assert {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()} == before
    page = ResultsPage()
    page.set_saved_project(snapshot)
    assert "原始来源文件当前无法访问" in page.status_label.text()


def test_invalid_original_source_path_does_not_prevent_read_only_recovery(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    manifest_path = project / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_path"] = "\0invalid-path"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    snapshot = ProjectStore.load(project)

    assert snapshot.saved_result is not None
    assert any("原始来源文件当前无法访问" in warning for warning in snapshot.warnings)


def test_legacy_geo_array_project_restores_modality_and_blocks_fpkm_reanalysis(tmp_path: Path) -> None:
    project = tmp_path / "legacy-geo-array"
    project.mkdir()
    _write_project(project)

    sample_path = project / "prepared" / "sample_metadata.tsv"
    sample_path.write_text(
        "sample_id\tsample_title\tdata_processing\tsupplementary_file\n"
        "S1\tarray sample 1\tAffymetrix STATISTICAL_ALGORITHM_TYPE\thttps://example.invalid/S1.CEL.gz\n"
        "S2\tarray sample 2\tAffymetrix STATISTICAL_ALGORITHM_TYPE\thttps://example.invalid/S2.CEL.gz\n",
        encoding="utf-8",
    )
    manifest_path = project / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["platform_id"] = "GPL96"
    manifest["source_asset"] = {"kind": "GEO_SERIES_MATRIX"}
    manifest.pop("source_modality", None)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    recipe_path = project / "preparation-recipe.json"
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    recipe.update({"measurement_type": "FPKM", "value_scale": "LINEAR"})
    recipe["fact_confirmations"] = [
        {"fact_key": "measurement_type", "selected_value": "FPKM", "status": "user_confirmed_without_direct_text"},
        {"fact_key": "value_scale", "selected_value": "LINEAR", "status": "user_confirmed_without_direct_text"},
    ]
    recipe_path.write_text(json.dumps(recipe), encoding="utf-8")

    snapshot = ProjectStore.load(project)
    assert snapshot.matrix.source_modality == "MICROARRAY"
    assert any("Affymetrix 处理说明和 CEL 来源文件" in warning for warning in snapshot.warnings)

    plan = PlanningService().build(
        snapshot.matrix,
        {"S1": "control", "S2": "test"},
        replicate_structure="independent",
    )
    assert not plan.runnable
    assert any(issue.code == "SOURCE_MODALITY_MEASUREMENT_CONFLICT" for issue in plan.blockers)


def test_legacy_modality_inference_does_not_guess_from_generic_geo_or_gpl_alone(tmp_path: Path) -> None:
    sample_path = tmp_path / "sample_metadata.tsv"
    sample_path.write_text("sample_id\tplatform_id\nS1\tGPL96\n", encoding="utf-8")

    ordinary_geo, reason = ProjectStore._infer_legacy_source_modality(
        {"source_asset": {"kind": "GEO_SERIES_MATRIX"}, "platform_id": "GPL96"},
        sample_path,
    )
    stale_non_geo, stale_reason = ProjectStore._infer_legacy_source_modality(
        {"source_asset": {"kind": "USER_TABLE"}, "series_types": ["Expression profiling by array"]},
        sample_path,
    )

    assert ordinary_geo is None and not reason
    assert stale_non_geo is None and not stale_reason


def test_changed_original_source_warns_but_keeps_saved_result_readable(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    source_path = tmp_path / "source.tsv"
    source_path.write_text("source at import\n", encoding="utf-8")
    manifest_path = project / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_path"] = str(source_path)
    manifest["source_sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    source_path.write_text("source changed later\n", encoding="utf-8")

    snapshot = ProjectStore.load(project)

    assert snapshot.saved_result is not None
    assert snapshot.result_integrity_valid is True
    assert any("原始来源文件内容与导入时记录不一致" in warning for warning in snapshot.warnings)


def test_project_source_hash_reports_progress_and_can_be_cancelled_without_changes(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    source_path = tmp_path / "source.tsv"
    source_path.write_bytes(b"x" * (18 * 1024 * 1024))
    manifest_path = project / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(source_path=str(source_path), source_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest())
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    before = {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()}
    progress: list[tuple[int, int]] = []
    cancel = Event()

    with pytest.raises(ProjectLoadCancelled):
        ProjectStore.load(
            project,
            progress=lambda done, total: (progress.append((done, total)), cancel.set() if done >= 8 * 1024 * 1024 else None),
            cancelled=cancel.is_set,
        )

    assert progress[0] == (0, 18 * 1024 * 1024)
    assert progress[-1][0] >= 8 * 1024 * 1024
    assert {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()} == before


def test_project_matrix_scan_checks_cancellation_between_rows(tmp_path: Path) -> None:
    matrix_path = tmp_path / "matrix.tsv"
    matrix_path.write_text(
        "feature_key\tS1\tS2\n" + "".join(f"gene-{index}\t1\t2\n" for index in range(1500)),
        encoding="utf-8",
    )
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 1

    with pytest.raises(ProjectLoadCancelled):
        ProjectStore._read_expression_matrix(matrix_path, cancelled=cancelled)


def test_project_without_source_can_be_cancelled_during_saved_matrix_verification(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    manifest_path = project / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_path"] = str(tmp_path / "source-no-longer-available.tsv")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    before = {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()}
    cancel = Event()

    with pytest.raises(ProjectLoadCancelled):
        ProjectStore.load(
            project,
            progress=lambda done, total: cancel.set() if total and done == total else None,
            cancelled=cancel.is_set,
        )

    assert {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()} == before


def test_project_load_worker_emits_cancelled_after_user_requests_it(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    source_path = tmp_path / "large-source.tsv"
    source_path.write_bytes(b"x" * (18 * 1024 * 1024))
    manifest_path = project / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(source_path=str(source_path), source_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest())
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    worker = ProjectLoadWorker(project)
    cancelled: list[bool] = []
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.progress.connect(lambda done, _total: worker.request_cancel() if done >= 8 * 1024 * 1024 else None)

    worker.run()

    assert cancelled == [True]


def test_import_page_disables_project_open_during_tasks_and_resets_external_cancel(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    page = ImportPage(project_root=tmp_path)
    page._set_busy(True)
    assert not page.open_project_button.isEnabled()
    page._set_busy(False)
    assert page.open_project_button.isEnabled()

    requested: list[bool] = []
    page.begin_external_check(lambda: requested.append(True))
    assert not page.cancel_button.isHidden()
    assert page.cancel_button.text() == "取消打开项目"
    assert not page.open_project_button.isEnabled()
    page.cancel_button.click()
    assert requested == [True]
    assert not page.cancel_button.isEnabled()
    page.end_external_check("已取消")
    assert page.cancel_button.isHidden()
    assert page.cancel_button.text() == "取消"
    assert page.open_project_button.isEnabled()
    page.close()
    application.processEvents()


def test_project_load_worker_emits_read_only_snapshot_and_finishes_thread(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    before = {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()}
    thread = QThread()
    worker = ProjectLoadWorker(project)
    completed: list[object] = []
    failed: list[str] = []
    worker.moveToThread(thread)
    worker.completed.connect(lambda snapshot: (completed.append(snapshot), thread.quit()))
    worker.failed.connect(lambda message: (failed.append(message), thread.quit()))
    thread.started.connect(worker.run)
    thread.finished.connect(worker.deleteLater)

    thread.start()
    assert thread.wait(10_000), "项目只读恢复 worker 未在 10 秒内结束"
    application.processEvents()
    assert not failed, failed
    assert completed
    assert completed[0].saved_result is not None
    assert {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()} == before
    thread.deleteLater()


def test_project_load_worker_converts_invalid_project_to_failure_signal(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    thread = QThread()
    worker = ProjectLoadWorker(tmp_path / "missing-project")
    completed: list[object] = []
    failed: list[str] = []
    worker.moveToThread(thread)
    worker.completed.connect(lambda snapshot: (completed.append(snapshot), thread.quit()))
    worker.failed.connect(lambda message: (failed.append(message), thread.quit()))
    thread.started.connect(worker.run)
    thread.finished.connect(worker.deleteLater)

    thread.start()
    assert thread.wait(10_000), "项目只读恢复 worker 的错误路径未在 10 秒内结束"
    application.processEvents()
    assert not completed
    assert failed and "missing-project" in failed[0]
    thread.deleteLater()


def test_load_rejects_matrix_changed_after_project_manifest_was_saved(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    matrix_path, _ = _write_project(project)
    matrix_path.write_text(matrix_path.read_text(encoding="utf-8") + "feature-c\t5\t6\n", encoding="utf-8")

    with pytest.raises(ProjectLoadError, match="校验值不一致"):
        ProjectStore.load(project)


def test_legacy_project_missing_optional_facts_loads_read_only_as_unknown(tmp_path: Path) -> None:
    project = tmp_path / "legacy-project"
    project.mkdir()
    _write_project(project)
    manifest_path = project / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("matrix_content_hash")
    manifest.pop("matrix_id")
    manifest.pop("source_asset_id")
    manifest.pop("feature_id_type")
    manifest["validation"] = {"passed": True, "feature_count": 2}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    recipe_path = project / "preparation-recipe.json"
    recipe_path.write_text(json.dumps({"input_transform": ""}), encoding="utf-8")
    report_manifest_path = project / "reports" / "analysis-manifest.json"
    report_manifest = json.loads(report_manifest_path.read_text(encoding="utf-8"))
    report_manifest.pop("preparation_recipe_hash")
    report_manifest_path.write_text(json.dumps(report_manifest), encoding="utf-8")

    snapshot = ProjectStore.load(project)

    assert snapshot.matrix.measurement_type.value == "UNKNOWN"
    assert snapshot.matrix.value_scale.value == "UNKNOWN"
    assert snapshot.matrix.feature_id_type == "UNKNOWN"
    assert snapshot.saved_result is not None
    assert any("没有保存矩阵校验值" in warning for warning in snapshot.warnings)
    assert any("UNKNOWN" in warning for warning in snapshot.warnings)


def test_old_recipe_choices_without_confirmation_ledger_block_new_analysis(tmp_path: Path) -> None:
    project = tmp_path / "legacy-project"
    project.mkdir()
    _write_project(project)
    recipe_path = project / "preparation-recipe.json"
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    recipe.pop("fact_confirmations")
    recipe_path.write_text(json.dumps(recipe), encoding="utf-8")
    report_manifest_path = project / "reports" / "analysis-manifest.json"
    report_manifest = json.loads(report_manifest_path.read_text(encoding="utf-8"))
    report_manifest.pop("preparation_recipe_hash")
    report_manifest_path.write_text(json.dumps(report_manifest), encoding="utf-8")

    snapshot = ProjectStore.load(project)

    assert snapshot.saved_result is not None
    assert snapshot.matrix.measurement_type.value == "UNKNOWN"
    assert snapshot.matrix.value_scale.value == "UNKNOWN"
    assert any("新分析将按 UNKNOWN 阻断" in warning for warning in snapshot.warnings)


def test_load_does_not_restore_plan_with_missing_sample_or_unmatched_result(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    plan_path = project / "analysis" / "analysis-plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["design"]["assignments"].pop("S2")
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    result_path = project / "analysis" / "deg-result.json"
    result_path.write_text(json.dumps({"table": [{"feature_key": "wrong-key"}]}), encoding="utf-8")

    snapshot = ProjectStore.load(project)

    assert snapshot.saved_plan is None
    assert snapshot.saved_result is None
    assert any("分组或样本编号" in warning for warning in snapshot.warnings)
    assert any("特征编号/顺序" in warning for warning in snapshot.warnings)


def test_results_page_marks_restored_project_read_only(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    snapshot = ProjectStore.load(project)
    page = ResultsPage()

    page.set_saved_project(snapshot)

    assert "没有重跑分析" in page.status_label.text()
    assert "按事务记录恢复旧结果或清理未完成的临时文件" in page.status_label.text()
    assert "恢复动作本身没有写入文件" not in page.status_label.text()
    assert page.open_report_button.isEnabled()
    assert page.open_project_button.isEnabled()


def test_report_with_matrix_hash_mismatch_is_not_loaded_or_opened(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    report = project / "reports" / "analysis-report.html"
    report.write_text("stale report", encoding="utf-8")
    (project / "reports" / "analysis-manifest.json").write_text(
        json.dumps({"matrix_hash": "not-the-current-matrix"}), encoding="utf-8",
    )

    snapshot = ProjectStore.load(project)
    page = ResultsPage()
    page.set_saved_project(snapshot)

    assert snapshot.saved_result is None
    assert snapshot.report_valid is False
    assert any("deg_result_hash" in warning for warning in snapshot.warnings)
    assert not page.open_report_button.isEnabled()
    assert "未启用" in page.status_label.text()


def test_result_hash_mismatch_is_rejected_and_report_is_disabled(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _matrix_path, matrix_hash = _write_project(project)
    result_path = project / "analysis" / "deg-result.json"
    report_path = project / "reports" / "analysis-report.html"
    report_path.write_text("report", encoding="utf-8")
    feature_path = project / "prepared" / "feature_metadata.tsv"
    plan_path = project / "analysis" / "analysis-plan.json"
    (project / "reports" / "deg-results.xlsx").write_bytes(b"workbook")
    sample_path = project / "prepared" / "sample_metadata.tsv"
    manifest = {
        "matrix_hash": matrix_hash,
        "feature_metadata_hash": hashlib.sha256(feature_path.read_bytes()).hexdigest(),
        "sample_metadata_hash": hashlib.sha256(sample_path.read_bytes()).hexdigest(),
        "preparation_recipe_hash": hashlib.sha256((project / "preparation-recipe.json").read_bytes()).hexdigest(),
        "analysis_plan_hash": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "deg_result_hash": hashlib.sha256(result_path.read_bytes()).hexdigest(),
        "html_hash": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        "xlsx_hash": hashlib.sha256((project / "reports" / "deg-results.xlsx").read_bytes()).hexdigest(),
    }
    (project / "reports" / "analysis-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    result_path.write_text(
        json.dumps({"table": [
            {"feature_key": "feature-a", "pvalue": 0.99},
            {"feature_key": "feature-b", "pvalue": 0.99},
        ]}),
        encoding="utf-8",
    )

    snapshot = ProjectStore.load(project)

    assert snapshot.saved_result is None
    assert snapshot.report_valid is False


def test_restored_project_does_not_save_new_plan_before_analysis(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    root_plan = project / "analysis-plan.json"
    root_plan.write_bytes((project / "analysis" / "analysis-plan.json").read_bytes())
    before_root_plan = root_plan.read_bytes()
    before_analysis_plan = (project / "analysis" / "analysis-plan.json").read_bytes()
    snapshot = ProjectStore.load(project)
    page = AnalysisPage()

    page.set_matrix(
        snapshot.matrix,
        initial_design=snapshot.saved_plan["design"],
        restored_project=True,
    )
    page.build_plan()

    assert root_plan.read_bytes() == before_root_plan
    assert (project / "analysis" / "analysis-plan.json").read_bytes() == before_analysis_plan


def test_sample_metadata_change_invalidates_saved_result_and_report(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    sample_path = project / "prepared" / "sample_metadata.tsv"
    sample_path.write_text("sample_id\tsample_title\nS1\tchanged\nS2\ttwo\n", encoding="utf-8")

    snapshot = ProjectStore.load(project)

    assert snapshot.saved_result is None
    assert snapshot.result_integrity_valid is False
    assert snapshot.report_valid is False
    assert any("sample_metadata_hash" in warning for warning in snapshot.warnings)


def test_incomplete_result_rows_are_not_restored(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    result_path = project / "analysis" / "deg-result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["table"] = [result["table"][0], {"feature_key": "feature-b"}]
    result_path.write_text(json.dumps(result), encoding="utf-8")

    snapshot = ProjectStore.load(project)

    assert snapshot.saved_result is None
    assert any("结果与矩阵" in warning for warning in snapshot.warnings)


def test_malformed_result_with_matching_hash_disables_html_report(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    result_path = project / "analysis" / "deg-result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["table"] = [result["table"][0], {"feature_key": "feature-b"}]
    result_path.write_text(json.dumps(result), encoding="utf-8")
    manifest_path = project / "reports" / "analysis-manifest.json"
    report_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report_manifest["deg_result_hash"] = hashlib.sha256(result_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(report_manifest), encoding="utf-8")

    snapshot = ProjectStore.load(project)

    assert snapshot.saved_result is None
    assert snapshot.report_valid is False
    assert any("离线 HTML 报告已禁用" in warning for warning in snapshot.warnings)


def test_restore_rejects_in_project_symlink_for_matrix(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    matrix_path, _ = _write_project(project)
    internal_target = project / "matrix-copy.tsv"
    internal_target.write_bytes(matrix_path.read_bytes())
    matrix_path.unlink()
    matrix_path.symlink_to(internal_target)

    with pytest.raises(ProjectLoadError, match="不能是符号链接"):
        ProjectStore.load(project)


def test_missing_sample_hash_keeps_history_unverified_but_disables_report(tmp_path: Path) -> None:
    project = tmp_path / "legacy-project"
    project.mkdir()
    _write_project(project)
    manifest_path = project / "reports" / "analysis-manifest.json"
    report_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report_manifest.pop("sample_metadata_hash")
    manifest_path.write_text(json.dumps(report_manifest), encoding="utf-8")

    snapshot = ProjectStore.load(project)

    assert snapshot.saved_result is not None
    assert snapshot.result_integrity_valid is False
    assert snapshot.report_valid is False
    assert any("sample_metadata_hash" in warning for warning in snapshot.warnings)


def test_restored_analysis_page_recovers_saved_groups_and_allows_editing(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    snapshot = ProjectStore.load(project)
    page = AnalysisPage()

    page.set_matrix(snapshot.matrix, initial_design=snapshot.saved_plan["design"], restored_project=True)

    assert page._assignments() == {"S1": "control", "S2": "test"}
    assert "将覆盖此项目中的分析计划" in page.matrix_label.text()
    sample_row = next(
        row for row in range(page.sample_table.rowCount())
        if page.sample_table.item(row, 0).text() == "S1"
    )
    combo = page.sample_table.cellWidget(sample_row, 1)
    combo.setCurrentIndex(combo.findData("excluded"))
    assert page._assignments()["S1"] == "excluded"


@pytest.mark.parametrize("invalid_confirmation", ["missing", "false", "type_mismatch"])
def test_legacy_project_plan_requires_replicate_confirmation_before_new_plan(
    tmp_path: Path, invalid_confirmation: str,
) -> None:
    QApplication.instance() or QApplication([])
    project = tmp_path / "legacy-project"
    project.mkdir()
    _write_project(project)
    plan_path = project / "analysis" / "analysis-plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if invalid_confirmation == "missing":
        plan["design"].pop("replicate_structure")
        plan["design"].pop("replicate_structure_confirmed")
        plan["design"].pop("type")
    elif invalid_confirmation == "false":
        plan["design"]["replicate_structure_confirmed"] = False
    else:
        plan["design"]["replicate_structure"] = "paired"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    manifest_path = project / "reports" / "analysis-manifest.json"
    report_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    report_manifest["analysis_plan_hash"] = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(report_manifest), encoding="utf-8")

    snapshot = ProjectStore.load(project)
    assert snapshot.saved_result is not None
    assert snapshot.saved_plan is not None
    assert snapshot.matrix.observation_unit.value == "UNKNOWN"
    assert snapshot.result_integrity_valid is True
    assert snapshot.report_valid is False
    assert any("没有保存样本独立性/配对确认" in warning for warning in snapshot.warnings)
    page = AnalysisPage()
    page.set_matrix(snapshot.matrix, initial_design=snapshot.saved_plan["design"], restored_project=True)
    assert page.replicate_structure.currentData() is None
    independent_index = page.replicate_structure.findData("independent")
    assert "不是单个细胞" in page.replicate_structure.itemText(independent_index)
    assert "pseudobulk" in page.replicate_structure.toolTip()

    page.build_plan()

    assert any(issue.code == "UNKNOWN_REPLICATE_STRUCTURE" for issue in page.plan.blockers)
    page.replicate_structure.setCurrentIndex(page.replicate_structure.findData("independent"))
    page.build_plan()
    assert not any(issue.code == "UNKNOWN_REPLICATE_STRUCTURE" for issue in page.plan.blockers)


def test_analysis_page_restores_confirmed_paired_design_and_subject_mapping(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    project = tmp_path / "paired-project"
    project.mkdir()
    _write_project(project)
    snapshot = ProjectStore.load(project)
    design = dict(snapshot.saved_plan["design"])
    design.update({
        "type": "paired",
        "replicate_structure": "paired",
        "replicate_structure_confirmed": True,
        "paired_subjects": {"S1": "private-subject", "S2": "private-subject"},
    })
    page = AnalysisPage()

    page.set_matrix(snapshot.matrix, initial_design=design)

    assert page.replicate_structure.currentData() == "paired"
    assert page._mapping_column(2) == {"S1": "private-subject", "S2": "private-subject"}
    page.build_plan()
    assert page.plan.design["replicate_structure"] == "paired"
    assert any(issue.code == "INCOMPLETE_PAIRS" for issue in page.plan.blockers)


def test_restore_edit_rerun_overwrites_project_and_restores_consistent_artifacts(tmp_path: Path) -> None:
    QApplication.instance() or QApplication([])
    project = tmp_path / "restored-project"
    prepared = project / "prepared"
    prepared.mkdir(parents=True)
    analysis = project / "analysis"
    reports = project / "reports"
    figures = project / "figures"
    analysis.mkdir()
    reports.mkdir()
    figures.mkdir()

    sample_ids = [f"{group}_{index}" for group in ("Ctrl", "Treat") for index in range(1, 4)]
    matrix_path = prepared / "expression_matrix.tsv"
    with matrix_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["feature_key", *sample_ids])
        for feature in range(600):
            values = [
                5.0 + feature * 0.17 + sample * 0.31 + ((feature * (sample + 3)) % 19) * 0.07
                for sample in range(6)
            ]
            writer.writerow([f"feature-{feature:04d}", *values])
    feature_path = prepared / "feature_metadata.tsv"
    feature_path.write_text(
        "feature_key\toriginal_id\tgene_symbol\n"
        + "\n".join(f"feature-{index:04d}\tID{index}\tGENE{index}" for index in range(600))
        + "\n",
        encoding="utf-8",
    )
    sample_path = prepared / "sample_metadata.tsv"
    sample_path.write_text(
        "sample_id\tsample_title\n" + "\n".join(f"{sample}\t{sample}" for sample in sample_ids) + "\n",
        encoding="utf-8",
    )
    original_source = project / "original-input.tsv"
    original_source.write_text("immutable user source\n", encoding="utf-8")
    original_source_hash = hashlib.sha256(original_source.read_bytes()).hexdigest()
    matrix_hash = hashlib.sha256(matrix_path.read_bytes()).hexdigest()
    feature_hash = hashlib.sha256(feature_path.read_bytes()).hexdigest()
    (project / "preparation-recipe.json").write_text(json.dumps({
        "measurement_type": "TPM",
        "value_scale": "LINEAR",
        "input_transform": "none",
        "fact_confirmations": [
            {"fact_key": "measurement_type", "selected_value": "TPM", "status": "user_confirmed_without_direct_text"},
            {"fact_key": "value_scale", "selected_value": "LINEAR", "status": "user_confirmed_without_direct_text"},
        ],
    }), encoding="utf-8")
    (project / "project.json").write_text(json.dumps({
        "project_id": "restore-rerun-integration",
        "matrix_id": "matrix-integration",
        "source_asset_id": "asset-integration",
        "source_path": str(original_source),
        "source_sha256": original_source_hash,
        "feature_id_type": "CUSTOM_ORIGINAL",
        "matrix_content_hash": matrix_hash,
        "validation": {
            "passed": True, "feature_count": 600, "sample_count": 6,
            "numeric_cell_count": 3600, "issues": [],
        },
    }), encoding="utf-8")

    first_snapshot = ProjectStore.load(project)
    initial_assignments = {
        sample: ("control" if sample.startswith("Ctrl") else "test") for sample in sample_ids
    }
    initial_plan = PlanningService().build(first_snapshot.matrix, initial_assignments)
    assert initial_plan.runnable, [item.message_zh for item in initial_plan.blockers]
    AnalysisService().run(first_snapshot.matrix, initial_plan, JobContext(project))

    replaceable = (
        project / "analysis" / "analysis-plan.json",
        project / "analysis" / "deg-result.json",
        project / "reports" / "analysis-report.html",
        project / "reports" / "deg-results.xlsx",
    )
    before_restore = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in replaceable}
    restored = ProjectStore.load(project)
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in replaceable} == before_restore
    assert restored.saved_result is not None and restored.report_valid

    page = AnalysisPage()
    page.set_matrix(restored.matrix, initial_design=restored.saved_plan["design"], restored_project=True)
    sample_row = next(
        row for row in range(page.sample_table.rowCount())
        if page.sample_table.item(row, 0).text() == "Ctrl_1"
    )
    assignment = page.sample_table.cellWidget(sample_row, 1)
    assignment.setCurrentIndex(assignment.findData("excluded"))
    page.build_plan()
    assert page.plan is not None and page.plan.runnable
    assert page.plan.design["assignments"]["Ctrl_1"] == "excluded"
    AnalysisService().run(restored.matrix, page.plan, JobContext(project))

    final_snapshot = ProjectStore.load(project)
    assert final_snapshot.saved_plan is not None
    assert final_snapshot.saved_plan["design"]["assignments"]["Ctrl_1"] == "excluded"
    assert final_snapshot.saved_result is not None
    assert final_snapshot.result_integrity_valid is True
    assert final_snapshot.report_valid is True
    assert hashlib.sha256(original_source.read_bytes()).hexdigest() == original_source_hash
    assert final_snapshot.saved_result["table"]
    assert [row["feature_key"] for row in final_snapshot.saved_result["table"]] == [
        f"feature-{index:04d}" for index in range(600)
    ]
    assert hashlib.sha256(replaceable[0].read_bytes()).hexdigest() != before_restore[replaceable[0]]
    assert hashlib.sha256(replaceable[1].read_bytes()).hexdigest() != before_restore[replaceable[1]]
    result_manifest = json.loads((project / "reports" / "analysis-manifest.json").read_text(encoding="utf-8"))
    for key, path in (
        ("analysis_plan_hash", project / "analysis" / "analysis-plan.json"),
        ("deg_result_hash", project / "analysis" / "deg-result.json"),
        ("html_hash", project / "reports" / "analysis-report.html"),
    ):
        assert result_manifest[key] == hashlib.sha256(path.read_bytes()).hexdigest()


def test_project_report_symlink_cannot_escape_project_directory(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    external_report = tmp_path / "outside.html"
    external_report.write_text("outside", encoding="utf-8")
    (project / "reports" / "analysis-report.html").unlink()
    (project / "reports" / "analysis-report.html").symlink_to(external_report)

    with pytest.raises(ProjectLoadError, match="符号链接"):
        ProjectStore.load(project)


def test_tampered_figure_disables_saved_report_but_keeps_verified_result(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    (project / "figures" / "pca.png").write_bytes(b"tampered figure")

    snapshot = ProjectStore.load(project)

    assert snapshot.saved_result is not None
    assert snapshot.result_integrity_valid is True
    assert snapshot.report_valid is False
    assert any("图表 pca.png" in warning for warning in snapshot.warnings)


@pytest.mark.parametrize("tamper", ["xlsx-content", "html-content"])
def test_report_content_forgery_with_matching_hash_disables_report_but_keeps_result(
    tmp_path: Path, tamper: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    manifest_path = project / "reports" / "analysis-manifest.json"
    report_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if tamper == "xlsx-content":
        artifact = project / "reports" / "deg-results.xlsx"
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "DEG Results"
        sheet.append(["feature_key", "gene_symbol", "log2FoldChange", "pvalue", "padj"])
        sheet.append(["forged-feature", "NA", 1.0, 0.05, 0.1])
        sheet.append(["feature-b", "NA", 1.0, 0.05, 0.1])
        workbook.save(artifact)
        hash_key = "xlsx_hash"
    else:
        artifact = project / "reports" / "analysis-report.html"
        artifact.write_text("not an HTML report", encoding="utf-8")
        hash_key = "html_hash"
    report_manifest[hash_key] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(report_manifest), encoding="utf-8")

    snapshot = ProjectStore.load(project)

    assert snapshot.saved_result is not None
    assert snapshot.result_integrity_valid is True
    assert snapshot.report_valid is False
    assert any("报告文档" in warning or "XLSX 工作簿内容" in warning for warning in snapshot.warnings)


def test_missing_required_figure_disables_report_but_keeps_verified_result(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    (project / "figures" / "volcano.png").unlink()

    snapshot = ProjectStore.load(project)

    assert snapshot.saved_result is not None
    assert snapshot.result_integrity_valid is True
    assert snapshot.report_valid is False
    assert any("五张规定图表" in warning or "volcano.png" in warning for warning in snapshot.warnings)


def test_figure_manifest_listing_only_one_image_disables_report(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    figures = project / "figures"
    figure_manifest_path = figures / "figure-manifest.json"
    figure_manifest_path.write_text(json.dumps({"pca": str(figures / "pca.png")}), encoding="utf-8")
    report_manifest_path = project / "reports" / "analysis-manifest.json"
    report_manifest = json.loads(report_manifest_path.read_text(encoding="utf-8"))
    report_manifest["figure_manifest_hash"] = hashlib.sha256(figure_manifest_path.read_bytes()).hexdigest()
    report_manifest_path.write_text(json.dumps(report_manifest), encoding="utf-8")

    snapshot = ProjectStore.load(project)

    assert snapshot.saved_result is not None
    assert snapshot.result_integrity_valid is True
    assert snapshot.report_valid is False
    assert any("没有恰好包含规定的五张图" in warning for warning in snapshot.warnings)


def test_opening_project_recovers_outputs_after_mid_publish_process_exit(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    old_heatmap = (project / "figures" / "top-heatmap.png").read_bytes()
    root_plan = project / "analysis-plan.json"
    root_plan.write_bytes((project / "analysis" / "analysis-plan.json").read_bytes())
    staging = project / ".analysis-staging-interrupted"
    staging.mkdir()
    records = {}
    for relative in AnalysisService.OUTPUT_RELATIVE_PATHS:
        staged = staging / relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(f"new:{relative}".encode())
        target = project / relative
        records[relative.as_posix()] = {
            "had_original": target.is_file(),
            "old_sha256": hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None,
            "new_sha256": hashlib.sha256(staged.read_bytes()).hexdigest(),
        }
    journal = AnalysisService._new_transaction_journal(
        project, phase="publishing", outputs=records,
    )
    journal["pid"] = 999_999_999
    AnalysisService._write_transaction_journal(staging, journal)

    # Simulate a crash after replacing two old files and installing one new file.
    for relative in (
        Path("analysis-plan.json"), Path("analysis/deg-result.json"),
        Path("figures/top-heatmap.png"),
    ):
        target = project / relative
        staged = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file():
            backup = staging / ".previous" / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            os.replace(target, backup)
        os.replace(staged, target)

    snapshot = ProjectStore.load(project)

    assert snapshot.saved_result is not None
    assert snapshot.result_integrity_valid is True
    assert snapshot.report_valid is True
    assert any("已恢复旧结果" in warning for warning in snapshot.warnings)
    assert root_plan.read_bytes() == (project / "analysis" / "analysis-plan.json").read_bytes()
    assert (project / "figures" / "top-heatmap.png").read_bytes() == old_heatmap
    assert not staging.exists()
    QApplication.instance() or QApplication([])
    page = ResultsPage()
    page.set_saved_project(snapshot)
    assert "上次分析在发布期间中断" in page.status_label.text()
    assert "已恢复旧结果" in page.status_label.text()


def test_opening_project_blocks_while_analysis_transaction_process_is_live(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    staging = project / ".analysis-staging-active"
    staging.mkdir()
    AnalysisService._write_transaction_journal(
        staging, AnalysisService._new_transaction_journal(project, phase="preparing"),
    )

    with project_directory_lock(project):
        with pytest.raises(ProjectLoadError, match="正在被另一个 RNA-Seq Helper 任务使用"):
            ProjectStore.load(project)

    assert staging.is_dir()


def test_project_loading_does_not_clean_transaction_named_folder_that_is_not_a_project(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "ordinary-folder"
    staging = folder / ".analysis-recovery-user-data"
    staging.mkdir(parents=True)
    user_file = staging / "notes.txt"
    user_file.write_text("keep me", encoding="utf-8")
    (staging / ".recovery-complete").write_text("not an app transaction", encoding="utf-8")

    with pytest.raises(ProjectLoadError, match="不是可识别的 RNA-Seq Helper 项目"):
        ProjectStore.load(folder)

    assert user_file.read_text(encoding="utf-8") == "keep me"


def test_interrupted_recovery_refuses_to_overwrite_post_crash_user_edit(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    root_plan = project / "analysis-plan.json"
    root_plan.write_bytes((project / "analysis" / "analysis-plan.json").read_bytes())
    staging = project / ".analysis-staging-user-edit"
    staging.mkdir()
    records = {}
    for relative in AnalysisService.OUTPUT_RELATIVE_PATHS:
        staged = staging / relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(f"new:{relative}".encode())
        target = project / relative
        records[relative.as_posix()] = {
            "had_original": target.is_file(),
            "old_sha256": hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None,
            "new_sha256": hashlib.sha256(staged.read_bytes()).hexdigest(),
        }
    AnalysisService._write_transaction_journal(
        staging,
        AnalysisService._new_transaction_journal(project, phase="publishing", outputs=records),
    )
    target = project / "analysis-plan.json"
    backup = staging / ".previous/analysis-plan.json"
    backup.parent.mkdir(parents=True)
    os.replace(target, backup)
    os.replace(staging / "analysis-plan.json", target)
    target.write_text("user edit after interruption", encoding="utf-8")

    with pytest.raises(ProjectLoadError, match="用户修改，拒绝覆盖"):
        ProjectStore.load(project)

    assert target.read_text(encoding="utf-8") == "user edit after interruption"
    assert backup.is_file()
    assert staging.is_dir()


def test_interrupted_recovery_preserves_unexpected_file_at_new_output_path(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _write_project(project)
    staging = project / ".analysis-staging-unexpected-output"
    staging.mkdir()
    records = {}
    unexpected_relative = Path("figures/top-heatmap.png")
    (project / unexpected_relative).unlink()
    for relative in AnalysisService.OUTPUT_RELATIVE_PATHS:
        staged = staging / relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(f"new:{relative}".encode())
        target = project / relative
        if relative == unexpected_relative:
            assert not target.exists()
            records[relative.as_posix()] = {
                "had_original": False,
                "old_sha256": None,
                "new_sha256": hashlib.sha256(staged.read_bytes()).hexdigest(),
            }
        else:
            records[relative.as_posix()] = {
                "had_original": target.is_file(),
                "old_sha256": hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None,
                "new_sha256": hashlib.sha256(staged.read_bytes()).hexdigest(),
            }
    AnalysisService._write_transaction_journal(
        staging,
        AnalysisService._new_transaction_journal(project, phase="publishing", outputs=records),
    )
    unexpected_target = project / unexpected_relative
    unexpected_target.write_bytes(b"external file created after interruption")

    with pytest.raises(ProjectLoadError, match="目标.*被占用"):
        ProjectStore.load(project)

    assert unexpected_target.read_bytes() == b"external file created after interruption"
    assert (staging / unexpected_relative).read_bytes() == f"new:{unexpected_relative}".encode()
    assert staging.is_dir()
