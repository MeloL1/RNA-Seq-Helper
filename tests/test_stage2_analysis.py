from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from tests._planning import PlanningService
from rnaseq_helper.analysis.service import AnalysisService
from rnaseq_helper.domain.models import (
    DEGConfig,
    ExpressionMatrix,
    JobContext,
    MatrixStoreRef,
    MeasurementType,
    ObservationUnit,
    ValidationSummary,
    ValueScale,
    sha256_file,
)
from rnaseq_helper.domain.models import RJobResponse
from rnaseq_helper.grouping.service import GroupingService


SAMPLES = ("Ctrl_1", "Ctrl_2", "Ctrl_3", "Treat_1", "Treat_2", "Treat_3")


def _matrix(
    tmp_path: Path,
    measurement: MeasurementType,
    values: np.ndarray,
    sample_ids: tuple[str, ...] = SAMPLES,
) -> ExpressionMatrix:
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    feature_ids = [f"gene_{index:04d}" for index in range(values.shape[0])]
    matrix_path = prepared / "expression_matrix.tsv"
    with matrix_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["feature_key", *sample_ids])
        for feature_id, row in zip(feature_ids, values):
            writer.writerow([feature_id, *row.tolist()])
    feature_path = prepared / "feature_metadata.tsv"
    feature_path.write_text(
        "feature_key\toriginal_id\n"
        + "\n".join(f"{feature_id}\t{feature_id}" for feature_id in feature_ids)
        + "\n",
        encoding="utf-8",
    )
    sample_path = prepared / "sample_metadata.tsv"
    sample_path.write_text("sample_id\n" + "\n".join(sample_ids) + "\n", encoding="utf-8")
    values_ref = MatrixStoreRef(matrix_path, "dense-tsv", "float64", values.shape, sha256_file(matrix_path))
    feature_ref = MatrixStoreRef(feature_path, "table-tsv", "string", (len(feature_ids), 2), sha256_file(feature_path))
    sample_ref = MatrixStoreRef(sample_path, "table-tsv", "string", (len(sample_ids), 1), sha256_file(sample_path))
    return ExpressionMatrix(
        "matrix-test",
        values_ref,
        feature_ref,
        sample_ref,
        ObservationUnit.BULK_SAMPLE,
        measurement,
        ValueScale.LINEAR,
        "",
        "CUSTOM_ORIGINAL",
        None,
        (),
        "recipe-test",
        ValidationSummary(True, (), values.shape[0], values.shape[1], int(values.size)),
        values_ref.content_hash,
    )


def _assignments() -> dict[str, str]:
    return {sample: ("control" if sample.startswith("Ctrl") else "test") for sample in SAMPLES}


def test_analysis_payload_keeps_batch_and_subject_keys_for_r_design(tmp_path: Path) -> None:
    class CaptureBridge:
        def __init__(self) -> None:
            self.payload = None

        def run(self, _method, payload, _context, _profile):
            self.payload = payload
            raise RuntimeError("stop after payload capture")

    values = np.full((600, 6), 100.0)
    matrix = _matrix(tmp_path, MeasurementType.RAW_COUNT, values)
    batch = {
        SAMPLES[0]: "batch_a", SAMPLES[1]: "batch_b", SAMPLES[2]: "batch_a",
        SAMPLES[3]: "batch_a", SAMPLES[4]: "batch_b", SAMPLES[5]: "batch_b",
    }
    plan = PlanningService().build(matrix, _assignments(), batch=batch)
    assert plan.runnable
    bridge = CaptureBridge()
    with pytest.raises(RuntimeError, match="stop after payload capture"):
        AnalysisService(bridge).run(matrix, plan, JobContext(tmp_path))
    assert bridge.payload is not None
    assert bridge.payload["batch"] == batch
    assert bridge.payload["subject"] == {}


def test_analysis_blocks_raw_count_over_r_integer_limit_before_worker(tmp_path: Path) -> None:
    values = np.full((1, len(SAMPLES)), 2_147_483_648.0)
    matrix = _matrix(tmp_path, MeasurementType.RAW_COUNT, values)
    plan = PlanningService().build(matrix, _assignments())

    class MustNotRunBridge:
        def run(self, *_args, **_kwargs):
            raise AssertionError("R worker should not be called for overflowing counts")

    with pytest.raises(ValueError, match="超出当前 DESeq2 运行时可安全处理的整数范围"):
        AnalysisService(MustNotRunBridge()).run(matrix, plan, JobContext(tmp_path))


def test_cancel_after_r_returns_preserves_existing_analysis_outputs(tmp_path: Path) -> None:
    from rnaseq_helper.r_bridge.client import RBridgeError

    matrix = _matrix(tmp_path, MeasurementType.RAW_COUNT, np.full((4, len(SAMPLES)), 20.0))
    plan = PlanningService().build(matrix, _assignments())
    context = JobContext(tmp_path)
    existing_result = tmp_path / "analysis" / "deg-result.json"
    existing_result.parent.mkdir(parents=True)
    existing_result.write_text("previous result", encoding="utf-8")

    class CancelAfterBridge:
        def run(self, *_args, **_kwargs):
            context.cancel_event.set()
            return RJobResponse("test", True, {})

    with pytest.raises(RBridgeError, match="任务已取消；旧分析结果保持不变"):
        AnalysisService(CancelAfterBridge()).run(matrix, plan, context)

    assert existing_result.read_text(encoding="utf-8") == "previous result"
    assert not list(tmp_path.glob(".analysis-staging-*"))


def test_worker_result_contract_rejects_invalid_probabilities_and_labels(tmp_path: Path) -> None:
    matrix = _matrix(tmp_path, MeasurementType.RAW_COUNT, np.ones((1, len(SAMPLES))))
    plan = PlanningService().build(matrix, _assignments())
    valid_row = {
        "feature_key": "gene_0000", "original_id": "gene_0000", "gene_symbol": None,
        "log2FoldChange": 0.0, "pvalue": 0.5, "padj": 0.5,
        "direction": "flat", "tested": True, "reason_not_tested": "",
        "mean_control_expression": 1.0, "mean_treated_expression": 1.0,
        "analysis_method": "DESEQ2", "analysis_basis": "raw_count",
        "effect_scale": "log2_count_model", "mean_expression_unit": "RAW_COUNT",
    }
    AnalysisService._validate_result_table([valid_row], ["gene_0000"], plan, "RAW_COUNT")

    invalid_rows = (
        {**valid_row, "pvalue": 1.01},
        {**valid_row, "direction": "up"},
        {**valid_row, "effect_scale": "log2_expression"},
        {**valid_row, "pvalue": None},
        {**valid_row, "tested": False, "reason_not_tested": ""},
    )
    for invalid_row in invalid_rows:
        with pytest.raises(ValueError):
            AnalysisService._validate_result_table(
                [invalid_row], ["gene_0000"], plan, "RAW_COUNT",
            )


def test_result_contract_verifies_bh_values_and_requires_lm_padjustment(tmp_path: Path) -> None:
    matrix = _matrix(tmp_path, MeasurementType.RAW_COUNT, np.ones((2, len(SAMPLES))))
    plan = PlanningService().build(matrix, _assignments())
    rows = [
        {
            "feature_key": f"gene_{index:04d}", "original_id": f"gene_{index:04d}",
            "gene_symbol": None, "log2FoldChange": 0.0, "pvalue": pvalue,
            "padj": padj, "direction": "flat", "tested": True,
            "reason_not_tested": "", "mean_control_expression": 1.0,
            "mean_treated_expression": 1.0, "analysis_method": "DESEQ2",
            "analysis_basis": "raw_count", "effect_scale": "log2_count_model",
            "mean_expression_unit": "RAW_COUNT",
        }
        for index, (pvalue, padj) in enumerate(((0.01, 0.01), (0.5, 0.5)))
    ]
    with pytest.raises(ValueError, match="BH 校正"):
        AnalysisService._validate_result_table(
            rows, ["gene_0000", "gene_0001"], plan, "RAW_COUNT",
        )

    rows[0]["padj"] = 0.02
    AnalysisService._validate_result_table(
        rows, ["gene_0000", "gene_0001"], plan, "RAW_COUNT",
    )

    limma_plan = replace(plan, method="LIMMA_ON_LOG2_TPM", analysis_basis="normalized_expression")
    limma_rows = [dict(row, analysis_method="LIMMA_ON_LOG2_TPM", analysis_basis="normalized_expression",
                       effect_scale="log2_expression", mean_expression_unit="TPM", padj=None)
                  for row in rows]
    with pytest.raises(ValueError, match="缺少 BH 校正值"):
        AnalysisService._validate_result_table(
            limma_rows, ["gene_0000", "gene_0001"], limma_plan, "TPM",
        )


def test_limma_worker_must_echo_plan_filter_sample_count(tmp_path: Path) -> None:
    matrix = _matrix(tmp_path, MeasurementType.TPM, np.ones((4, len(SAMPLES))))
    plan = PlanningService().build(matrix, _assignments())
    parameters = {
        "p_adjust_method": "BH", "transform": "log2(x+1)", "filter_threshold": 1.0,
        "min_samples": plan.preprocessing["min_samples"], "trend": True, "robust": True,
        "winsor.tail.p": [0.05, 0.1], "proportion": 0.01,
        "stdev.coef.lim": [0.1, 4], "legacy_supported": True, "legacy": True,
    }
    AnalysisService._validate_parameters(plan, parameters)
    parameters["min_samples"] -= 1
    with pytest.raises(ValueError, match="min_samples 与分析计划不一致"):
        AnalysisService._validate_parameters(plan, parameters)


def test_result_summary_must_match_validated_result_rows(tmp_path: Path) -> None:
    matrix = _matrix(tmp_path, MeasurementType.RAW_COUNT, np.ones((2, len(SAMPLES))))
    plan = PlanningService().build(matrix, _assignments())
    table = [
        {"tested": True, "padj": 0.01, "log2FoldChange": 2.0},
        {"tested": True, "padj": 0.5, "log2FoldChange": -2.0},
        {"tested": False, "padj": None, "log2FoldChange": None},
    ]
    summary = {
        "feature_count": 3, "tested_count": 2, "not_tested_count": 1,
        "significant_count": 1, "significant_magnitude_count": 1,
        "up_count": 1, "down_count": 0,
        "fdr_threshold": plan.config.fdr_threshold,
        "lfc_threshold": plan.config.lfc_threshold,
    }
    AnalysisService._validate_summary(summary, table, plan)
    summary["up_count"] = 0
    with pytest.raises(ValueError, match="结果摘要 up_count 与结果表不一致"):
        AnalysisService._validate_summary(summary, table, plan)


def test_deseq2_independent_filtering_na_remains_compatible_with_bh_contract(tmp_path: Path) -> None:
    matrix = _matrix(tmp_path, MeasurementType.RAW_COUNT, np.ones((1, len(SAMPLES))))
    plan = PlanningService().build(matrix, _assignments())
    row = {
        "feature_key": "gene_0000", "original_id": "gene_0000", "gene_symbol": None,
        "log2FoldChange": 0.5, "pvalue": 0.001, "padj": None,
        "direction": "up", "tested": True, "reason_not_tested": "independent_filtering",
        "mean_control_expression": 1.0, "mean_treated_expression": 2.0,
        "analysis_method": "DESEQ2", "analysis_basis": "raw_count",
        "effect_scale": "log2_count_model", "mean_expression_unit": "RAW_COUNT",
    }
    AnalysisService._validate_result_table([row], ["gene_0000"], plan, "RAW_COUNT")


def test_deseq2_bh_contract_accounts_for_cooks_na_inside_filter_family(tmp_path: Path) -> None:
    matrix = _matrix(tmp_path, MeasurementType.RAW_COUNT, np.ones((4, len(SAMPLES))))
    plan = PlanningService().build(matrix, _assignments())
    rows = []
    for index, (pvalue, padj, base_mean, reason) in enumerate((
        (0.01, 0.02, 20.0, ""),
        (0.03, 0.03, 30.0, ""),
        (None, None, 40.0, "cooks_outlier"),
        (0.001, None, 1.0, "independent_filtering"),
    )):
        rows.append({
            "feature_key": f"gene_{index:04d}", "original_id": f"gene_{index:04d}",
            "gene_symbol": None, "log2FoldChange": 0.0 if pvalue is not None else None,
            "pvalue": pvalue, "padj": padj,
            "direction": "flat" if pvalue is not None else None,
            "tested": pvalue is not None, "reason_not_tested": reason,
            "mean_control_expression": 1.0, "mean_treated_expression": 1.0,
            "analysis_method": "DESEQ2", "analysis_basis": "raw_count",
            "effect_scale": "log2_count_model", "mean_expression_unit": "RAW_COUNT",
            "baseMean": base_mean,
        })

    AnalysisService._validate_result_table(
        rows, [row["feature_key"] for row in rows], plan, "RAW_COUNT",
        {"independent_filter_threshold": 10.0},
    )
    rows[0]["padj"] = 0.03
    with pytest.raises(ValueError, match="BH 校正"):
        AnalysisService._validate_result_table(
            rows, [row["feature_key"] for row in rows], plan, "RAW_COUNT",
            {"independent_filter_threshold": 10.0},
        )
    rows[0]["padj"] = 0.02
    rows[1]["padj"] = None
    with pytest.raises(ValueError, match="独立过滤后的检验集合"):
        AnalysisService._validate_result_table(
            rows, [row["feature_key"] for row in rows], plan, "RAW_COUNT",
            {"independent_filter_threshold": 10.0},
        )


def test_failed_plotting_does_not_replace_existing_analysis_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rnaseq_helper.services.plot_service import PlotService

    matrix = _matrix(
        tmp_path, MeasurementType.TPM,
        np.random.default_rng(303).lognormal(3.0, 0.25, size=(600, 6)),
    )
    plan = PlanningService().build(matrix, _assignments())
    assert plan.runnable
    table = [{
        "feature_key": feature_id,
        "original_id": feature_id,
        "gene_symbol": None,
        "log2FoldChange": 0.0,
        "pvalue": 0.5,
        "padj": 0.5,
        "direction": "flat",
        "tested": True,
        "reason_not_tested": "",
        "mean_control_expression": 1.0,
        "mean_treated_expression": 1.0,
        "analysis_method": plan.method,
        "analysis_basis": plan.analysis_basis,
        "effect_scale": "log2_expression",
        "mean_expression_unit": "TPM",
    } for feature_id in (f"gene_{index:04d}" for index in range(600))]
    result = {
        "method": plan.method,
        "profile_id": plan.method_profile_id,
        "parameters": {
            "p_adjust_method": "BH",
            "transform": plan.preprocessing["transform"],
            "filter_threshold": plan.preprocessing["filter_threshold"],
            "min_samples": plan.preprocessing["min_samples"],
            "trend": True,
            "robust": True,
            "winsor.tail.p": [0.05, 0.1],
            "proportion": 0.01,
            "stdev.coef.lim": [0.1, 4],
            "legacy_supported": True,
            "legacy": True,
        },
        "table": table,
        "summary": {
            "feature_count": len(table), "tested_count": len(table), "not_tested_count": 0,
            "significant_count": 0, "significant_magnitude_count": 0,
            "up_count": 0, "down_count": 0,
            "fdr_threshold": plan.config.fdr_threshold,
            "lfc_threshold": plan.config.lfc_threshold,
        },
        "plot_matrix": {
            "feature_ids": [row["feature_key"] for row in table],
            "sample_ids": list(SAMPLES),
            "transform": "log2(x+1)",
            "values": [[1.0] * len(SAMPLES) for _ in table],
        },
    }

    class StaticBridge:
        def run(self, *_args, **_kwargs):
            return RJobResponse("test", True, result)

    relative_outputs = (
        "analysis-plan.json", "analysis/analysis-plan.json", "analysis/deg-result.json",
        "figures/figure-manifest.json", "figures/pca.png", "figures/sample-correlation.png",
        "figures/p-value-histogram.png", "figures/volcano.png", "figures/top-heatmap.png",
        "reports/analysis-report.html", "reports/deg-results.xlsx",
        "reports/interpretation-zh.txt", "reports/analysis-manifest.json",
    )
    old_contents = {}
    for relative in relative_outputs:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"old:{relative}".encode())
        old_contents[relative] = path.read_bytes()

    def fail_plotting(*_args, **_kwargs):
        raise RuntimeError("forced plot failure")

    monkeypatch.setattr(PlotService, "build", fail_plotting)
    with pytest.raises(RuntimeError, match="forced plot failure"):
        AnalysisService(StaticBridge()).run(matrix, plan, JobContext(tmp_path))

    assert {relative: (tmp_path / relative).read_bytes() for relative in relative_outputs} == old_contents
    assert not list(tmp_path.glob(".analysis-staging-*"))


def test_output_publish_rolls_back_if_a_file_cannot_be_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    relative_outputs = (
        "analysis-plan.json", "analysis/analysis-plan.json", "analysis/deg-result.json",
        "figures/figure-manifest.json", "figures/pca.png", "figures/sample-correlation.png",
        "figures/p-value-histogram.png", "figures/volcano.png", "figures/top-heatmap.png",
        "reports/analysis-report.html", "reports/deg-results.xlsx",
        "reports/interpretation-zh.txt", "reports/analysis-manifest.json",
    )
    project_dir = tmp_path / "project"
    staging_dir = project_dir / ".analysis-staging-test"
    old_contents = {}
    for relative in relative_outputs:
        target = project_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f"old:{relative}".encode())
        old_contents[relative] = target.read_bytes()
        staged = staging_dir / relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(f"new:{relative}".encode())
    AnalysisService._write_transaction_journal(
        staging_dir, AnalysisService._new_transaction_journal(project_dir, phase="preparing"),
    )

    real_replace = os.replace
    failed_once = False

    def fail_second_staged_install(source, target):
        nonlocal failed_once
        if (
            not failed_once
            and Path(source) == staging_dir / "analysis/analysis-plan.json"
        ):
            failed_once = True
            raise OSError("forced publish failure")
        return real_replace(source, target)

    monkeypatch.setattr("rnaseq_helper.analysis.service.os.replace", fail_second_staged_install)
    with pytest.raises(OSError, match="forced publish failure"):
        AnalysisService._publish_outputs(project_dir, staging_dir)

    assert failed_once
    assert {
        relative: (project_dir / relative).read_bytes()
        for relative in relative_outputs
    } == old_contents


def test_cancel_during_output_publish_rolls_back_all_replaced_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os
    from threading import Event
    from rnaseq_helper.r_bridge.client import RBridgeError

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    staging_dir = project_dir / ".analysis-staging-cancel-test"
    old_contents = {}
    for relative_path in AnalysisService.OUTPUT_RELATIVE_PATHS:
        relative = relative_path.as_posix()
        target = project_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f"old:{relative}".encode())
        old_contents[relative] = target.read_bytes()
        staged = staging_dir / relative_path
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(f"new:{relative}".encode())
    AnalysisService._write_transaction_journal(
        staging_dir, AnalysisService._new_transaction_journal(project_dir, phase="preparing"),
    )

    cancel_event = Event()
    real_replace = os.replace
    first_new_file = project_dir / AnalysisService.OUTPUT_RELATIVE_PATHS[0]

    def cancel_after_first_install(source, target):
        result = real_replace(source, target)
        first_staged_file = staging_dir / AnalysisService.OUTPUT_RELATIVE_PATHS[0]
        if Path(target) == first_new_file and Path(source) == first_staged_file:
            cancel_event.set()
        return result

    monkeypatch.setattr("rnaseq_helper.analysis.service.os.replace", cancel_after_first_install)
    with pytest.raises(RBridgeError, match="任务已取消；旧分析结果保持不变"):
        AnalysisService._publish_outputs(project_dir, staging_dir, cancel_event.is_set)

    assert {
        relative: (project_dir / relative).read_bytes()
        for relative in old_contents
    } == old_contents


def test_output_publish_refuses_symlinked_output_directory(
    tmp_path: Path,
) -> None:
    import os

    relative_outputs = (
        "analysis-plan.json", "analysis/analysis-plan.json", "analysis/deg-result.json",
        "figures/figure-manifest.json", "figures/pca.png", "figures/sample-correlation.png",
        "figures/p-value-histogram.png", "figures/volcano.png", "figures/top-heatmap.png",
        "reports/analysis-report.html", "reports/deg-results.xlsx",
        "reports/interpretation-zh.txt", "reports/analysis-manifest.json",
    )
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    external_figures = tmp_path / "external-figures"
    external_figures.mkdir()
    external_old = external_figures / "pca.png"
    external_old.write_bytes(b"external user file")
    (project_dir / "figures").symlink_to(external_figures, target_is_directory=True)
    staging_dir = project_dir / ".analysis-staging-test"
    for relative in relative_outputs:
        staged = staging_dir / relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(f"new:{relative}".encode())
    AnalysisService._write_transaction_journal(
        staging_dir, AnalysisService._new_transaction_journal(project_dir, phase="preparing"),
    )
    old_analysis = project_dir / "analysis" / "analysis-plan.json"
    old_analysis.parent.mkdir()
    old_analysis.write_bytes(b"old plan")

    with pytest.raises(OSError, match="符号链接指向的结果目录"):
        AnalysisService._publish_outputs(project_dir, staging_dir)

    assert external_old.read_bytes() == b"external user file"
    assert old_analysis.read_bytes() == b"old plan"


def test_output_publish_preserves_recovery_files_if_rollback_also_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    staging_dir = project_dir / ".analysis-staging-test"
    relative_paths = tuple(path.as_posix() for path in AnalysisService.OUTPUT_RELATIVE_PATHS)
    old_contents = {}
    for relative in relative_paths:
        target = project_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f"old:{relative}".encode())
        old_contents[relative] = target.read_bytes()
        staged = staging_dir / relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(f"new:{relative}".encode())
    AnalysisService._write_transaction_journal(
        staging_dir, AnalysisService._new_transaction_journal(project_dir, phase="preparing"),
    )

    real_replace = os.replace
    install_failed = False
    rollback_failed = False

    def fail_install_and_rollback(source, target):
        nonlocal install_failed, rollback_failed
        source_path, target_path = Path(source), Path(target)
        if source_path == staging_dir / "analysis/analysis-plan.json" and not install_failed:
            install_failed = True
            raise OSError("forced install failure")
        if (
            source_path == staging_dir / ".previous/analysis/analysis-plan.json"
            and not rollback_failed
        ):
            rollback_failed = True
            raise OSError("forced rollback failure")
        return real_replace(source, target)

    monkeypatch.setattr("rnaseq_helper.analysis.service.os.replace", fail_install_and_rollback)
    with pytest.raises(RuntimeError, match="恢复材料保留在") as exc_info:
        AnalysisService._publish_outputs(project_dir, staging_dir)

    assert install_failed and rollback_failed
    recovery_path = Path(str(exc_info.value).split("恢复材料保留在：", 1)[1])
    assert recovery_path.is_dir()
    assert (
        recovery_path / ".previous/analysis/analysis-plan.json"
    ).read_bytes() == old_contents["analysis/analysis-plan.json"]


def test_analysis_payload_excludes_noncontrast_samples_and_matrix_columns(tmp_path: Path) -> None:
    class CaptureBridge:
        def __init__(self) -> None:
            self.payload = None

        def run(self, _method, payload, _context, _profile):
            self.payload = payload
            raise RuntimeError("stop after payload capture")

    sample_ids = (*SAMPLES, "Unused_1", "Unused_2")
    values = np.tile(np.arange(1, len(sample_ids) + 1, dtype=float), (600, 1))
    matrix = _matrix(tmp_path, MeasurementType.RAW_COUNT, values, sample_ids)
    assignments = _assignments() | {"Unused_1": "excluded", "Unused_2": "excluded"}
    plan = PlanningService().build(matrix, assignments)
    assert plan.runnable
    bridge = CaptureBridge()

    with pytest.raises(RuntimeError, match="stop after payload capture"):
        AnalysisService(bridge).run(matrix, plan, JobContext(tmp_path))

    assert bridge.payload is not None
    assert bridge.payload["sample_ids"] == list(SAMPLES)
    assert bridge.payload["groups"] == ["control"] * 3 + ["test"] * 3
    assert all(len(row) == len(SAMPLES) for row in bridge.payload["counts"])


def test_grouping_blocks_completely_confounding_batch() -> None:
    validation = GroupingService().validate(
        _assignments(),
        SAMPLES,
        batch={sample: ("batch_a" if sample.startswith("Ctrl") else "batch_b") for sample in SAMPLES},
    )
    assert not validation.passed
    assert any(issue.code == "BATCH_CONFOUNDING" for issue in validation.issues)


def test_grouping_warns_when_batch_has_no_variation() -> None:
    validation = GroupingService().validate(
        _assignments(), SAMPLES, batch={sample: "batch_a" for sample in SAMPLES},
    )

    assert validation.passed
    warning = next(issue for issue in validation.issues if issue.code == "BATCH_NO_VARIATION")
    assert warning.severity.value == "WARNING"
    assert "不会把这个批次列加入统计模型" in warning.message_zh


def test_raw_count_with_log_scale_is_blocked_by_analysis_plan(tmp_path: Path) -> None:
    matrix = _matrix(tmp_path, MeasurementType.RAW_COUNT, np.full((4, 6), 20.0))
    matrix = replace(matrix, value_scale=ValueScale.LOG2)

    plan = PlanningService().build(matrix, _assignments())

    assert not plan.runnable
    assert any(issue.code == "UNSUPPORTED_ANALYSIS_INPUT" for issue in plan.blockers)


def test_deseq2_runs_and_reports_single_level_batch_as_unadjusted(tmp_path: Path) -> None:
    rng = np.random.default_rng(20261016)
    values = rng.poisson(120, size=(600, 6)).astype(float)
    values[:30, 3:] = rng.poisson(360, size=(30, 3))
    matrix = _matrix(tmp_path, MeasurementType.RAW_COUNT, values)
    batch = {sample: "B1" for sample in SAMPLES}

    plan = PlanningService().build(matrix, _assignments(), batch=batch)

    assert plan.runnable
    assert any("无法估计批次差异" in warning for warning in plan.warnings)
    result = AnalysisService().run(matrix, plan, JobContext(tmp_path))
    assert result["parameters"]["design"] == "~0 + group"
    report = (tmp_path / "reports" / "analysis-report.html").read_text(encoding="utf-8")
    assert "不会把这个批次列加入统计模型" in report

    reverse_assignments = {
        sample: ("test" if group == "control" else "control")
        for sample, group in _assignments().items()
    }
    reverse_plan = PlanningService().build(
        matrix,
        reverse_assignments,
        config=DEGConfig(control_group="control", test_group="test"),
        batch=batch,
    )
    reverse = AnalysisService().run(matrix, reverse_plan, JobContext(tmp_path))
    assert [row["feature_key"] for row in reverse["table"]] == [
        row["feature_key"] for row in result["table"]
    ]
    np.testing.assert_allclose(
        [row["log2FoldChange"] for row in reverse["table"]],
        -np.asarray([row["log2FoldChange"] for row in result["table"]]),
        rtol=1e-7, atol=1e-10, equal_nan=True,
    )
    np.testing.assert_allclose(
        [row["pvalue"] for row in reverse["table"]],
        [row["pvalue"] for row in result["table"]],
        rtol=1e-7, atol=1e-10, equal_nan=True,
    )


def test_grouping_uses_geo_sample_titles_without_guessing_from_gsm_ids() -> None:
    samples = ("GSM1001", "GSM1002", "GSM2001", "GSM2002")
    metadata = {
        "GSM1001": {"geo_accession": "GSM1001", "sample_title": "control replicate 1"},
        "GSM1002": {"geo_accession": "GSM1002", "sample_title": "control replicate 2"},
        "GSM2001": {"geo_accession": "GSM2001", "sample_title": "treated replicate 1"},
        "GSM2002": {"geo_accession": "GSM2002", "sample_title": "treated replicate 2"},
    }
    suggestions = GroupingService().suggest(samples, metadata)
    suggestion = suggestions[0]
    assert suggestion.pattern == "ctrl_treat"
    assert suggestion.assignments == {
        "GSM1001": "control", "GSM1002": "control",
        "GSM2001": "test", "GSM2002": "test",
    }
    assert "样本注释" in suggestion.evidence_zh


def test_grouping_blocks_partial_optional_metadata() -> None:
    validation = GroupingService().validate(
        _assignments(),
        SAMPLES,
        batch={SAMPLES[0]: "batch_a"},
    )
    assert not validation.passed
    assert any(issue.code == "INCOMPLETE_BATCH_METADATA" for issue in validation.issues)


def test_grouping_blocks_two_pair_design_without_residual_df() -> None:
    samples = ("S1_Pre", "S1_Post", "S2_Pre", "S2_Post")
    assignments = {sample: ("control" if sample.endswith("Pre") else "test") for sample in samples}
    validation = GroupingService().validate(
        assignments,
        samples,
        paired_subjects={sample: sample[:2] for sample in samples},
    )
    assert not validation.passed
    assert any(issue.code == "NON_ESTIMABLE" for issue in validation.issues)


def test_design_gate_blocks_group_contrast_confounded_by_subject_and_batch() -> None:
    samples = tuple(f"S{index}" for index in range(1, 9))
    assignments = {
        "S1": "control", "S2": "test",
        "S3": "control", "S4": "test",
        "S5": "control", "S6": "test",
        "S7": "control", "S8": "control",
    }
    subjects = {
        "S1": "pair1", "S2": "pair1",
        "S3": "pair2", "S4": "pair2",
        "S5": "pair3", "S6": "pair3",
        "S7": "control_only", "S8": "control_only_2",
    }
    batches = {
        "S1": "batch_a", "S2": "batch_b",
        "S3": "batch_a", "S4": "batch_b",
        "S5": "batch_a", "S6": "batch_b",
        "S7": "batch_a", "S8": "batch_b",
    }

    # Neither marginal rule identifies the problem: there are three complete
    # pairs, and both groups occur in batch_b. Together, however, subject and
    # batch absorb the group contrast while leaving residual df == 2.
    grouping = GroupingService().validate(assignments, samples, subjects, batches)
    assert grouping.passed
    design, rank, residual_df = PlanningService._design_matrix(
        samples, assignments, subjects, batches,
    )
    assert rank == 6
    assert residual_df == 2
    contrast = np.zeros(design.shape[1])
    contrast[0] = -1.0
    contrast[1] = 1.0
    projection = np.linalg.pinv(design) @ design
    assert not np.allclose(contrast, projection @ contrast)

    issues = PlanningService._design_gate_issues(samples, assignments, subjects, batches)
    assert any(issue.code == "NON_ESTIMABLE" for issue in issues)


def test_design_gate_keeps_estimable_crossed_paired_batch_design() -> None:
    samples = ("S1_C", "S1_T", "S2_C", "S2_T", "S3_C", "S3_T", "S4_C", "S4_T")
    assignments = {sample: ("control" if sample.endswith("_C") else "test") for sample in samples}
    subjects = {sample: sample[:2] for sample in samples}
    batches = {
        "S1_C": "batch_a", "S1_T": "batch_b",
        "S2_C": "batch_b", "S2_T": "batch_a",
        "S3_C": "batch_a", "S3_T": "batch_b",
        "S4_C": "batch_b", "S4_T": "batch_a",
    }
    issues = PlanningService._design_gate_issues(samples, assignments, subjects, batches)
    assert not any(issue.code == "NON_ESTIMABLE" for issue in issues)


def test_design_gate_blocks_redundant_subject_and_batch_even_if_group_contrast_estimable() -> None:
    samples = tuple(f"S{subject}_{group}" for subject in range(1, 5) for group in ("C", "T"))
    assignments = {sample: ("control" if sample.endswith("_C") else "test") for sample in samples}
    subjects = {sample: sample.split("_")[0] for sample in samples}
    batches = {sample: subjects[sample] for sample in samples}

    design, rank, residual_df = PlanningService._design_matrix(samples, assignments, subjects, batches)
    issues = PlanningService._design_gate_issues(samples, assignments, subjects, batches)

    assert rank < design.shape[1]
    assert residual_df >= 2
    assert any(issue.code == "NON_ESTIMABLE" for issue in issues)


def test_deseq2_ratio_profile_blocks_matrix_without_common_positive_feature(tmp_path: Path) -> None:
    values = np.full((600, len(SAMPLES)), 10.0)
    values[np.arange(values.shape[0]), np.arange(values.shape[0]) % len(SAMPLES)] = 0.0
    matrix = _matrix(tmp_path, MeasurementType.RAW_COUNT, values)

    plan = PlanningService().build(matrix, _assignments())

    assert not plan.runnable
    assert any(issue.code == "DESEQ2_RATIO_SIZE_FACTORS_UNAVAILABLE" for issue in plan.blockers)


def test_gene_symbols_align_by_feature_key_not_metadata_row_order(tmp_path: Path) -> None:
    from rnaseq_helper.analysis.service import AnalysisService

    metadata = tmp_path / "feature_metadata.tsv"
    metadata.write_text(
        "feature_key\toriginal_id\tgene_symbol\n"
        "feature_b\tprobe_b\tSYMBOL_B\n"
        "feature_a\tprobe_a\tSYMBOL_A\n",
        encoding="utf-8",
    )
    assert AnalysisService._read_gene_symbols(metadata, ["feature_a", "feature_b"]) == [
        "SYMBOL_A", "SYMBOL_B",
    ]


def test_analysis_plan_expires_if_feature_metadata_changes(tmp_path: Path) -> None:
    values = np.ones((4, 6), dtype=float)
    matrix = _matrix(tmp_path, MeasurementType.RAW_COUNT, values)
    plan = PlanningService().build(matrix, _assignments())
    assert plan.runnable
    metadata = matrix.feature_metadata.path
    metadata.write_text(
        metadata.read_text(encoding="utf-8").replace("gene_0000", "renamed_gene"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="特征注释已变化"):
        AnalysisService().run(matrix, plan, JobContext(tmp_path))


def test_analysis_plan_expires_if_expression_matrix_file_changes(tmp_path: Path) -> None:
    values = np.full((4, 6), 20.0)
    matrix = _matrix(tmp_path, MeasurementType.RAW_COUNT, values)
    plan = PlanningService().build(matrix, _assignments())
    assert plan.runnable
    matrix_path = matrix.values.path
    changed = matrix_path.read_text(encoding="utf-8").replace("\t20.0", "\t21.0", 1)
    matrix_path.write_text(changed, encoding="utf-8")

    with pytest.raises(ValueError, match="表达矩阵已变化"):
        AnalysisService().run(matrix, plan, JobContext(tmp_path))


def test_normalized_plan_runs_fixed_limma_profile(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    rng = np.random.default_rng(17)
    values = rng.lognormal(3.0, 0.3, size=(600, 6))
    values[:20, 3:] *= 3.0
    matrix = _matrix(project, MeasurementType.TPM, values)
    (project / "preparation-recipe.json").write_text("{}\n", encoding="utf-8")
    plan = PlanningService().build(matrix, _assignments())
    assert plan.runnable
    assert plan.method == "LIMMA_ON_LOG2_TPM"
    assert plan.method_profile_id == "normalized-log-limma-trend-v1"
    result = AnalysisService().run(matrix, plan, JobContext(project))
    assert result["method"] == plan.method
    assert result["parameters"]["transform"] == "log2(x+1)"
    assert result["summary"]["tested_count"] == 600
    assert (project / "analysis" / "deg-result.json").exists()
    assert (project / "reports" / "analysis-report.html").exists()
    assert (project / "reports" / "deg-results.xlsx").exists()
    assert (project / "reports" / "interpretation-zh.txt").exists()
    manifest = json.loads((project / "reports" / "analysis-manifest.json").read_text(encoding="utf-8"))
    for key, path in (
        ("feature_metadata_hash", matrix.feature_metadata.path),
        ("analysis_plan_hash", project / "analysis" / "analysis-plan.json"),
        ("deg_result_hash", project / "analysis" / "deg-result.json"),
        ("html_hash", project / "reports" / "analysis-report.html"),
        ("xlsx_hash", project / "reports" / "deg-results.xlsx"),
    ):
        assert manifest[key] == hashlib.sha256(path.read_bytes()).hexdigest()
    expected_paths = {
        "html": "reports/analysis-report.html",
        "xlsx": "reports/deg-results.xlsx",
        "interpretation_zh": "reports/interpretation-zh.txt",
        "analysis_plan": "analysis/analysis-plan.json",
        "preparation_recipe": "preparation-recipe.json",
    }
    assert {key: manifest[key] for key in expected_paths} == expected_paths
    assert set(manifest["figures"].values()) == {
        "figures/pca.png", "figures/sample-correlation.png", "figures/p-value-histogram.png",
        "figures/volcano.png", "figures/top-heatmap.png",
    }
    assert all((project / "figures" / name).exists() for name in (
        "pca.png", "sample-correlation.png", "p-value-histogram.png", "volcano.png", "top-heatmap.png",
    ))
    figure_manifest = json.loads((project / "figures" / "figure-manifest.json").read_text(encoding="utf-8"))
    assert set(figure_manifest.values()) == set(manifest["figures"].values())

    relocated = tmp_path / "moved-project"
    project.rename(relocated)
    for relative_path in expected_paths.values():
        assert (relocated / relative_path).is_file()
    assert all((relocated / relative_path).is_file() for relative_path in manifest["figures"].values())


def test_linear_expression_with_nonfinite_log_transform_is_blocked_before_worker(tmp_path: Path) -> None:
    values = np.random.default_rng(882).lognormal(2.0, 0.5, size=(600, len(SAMPLES)))
    values[0] = [1.5, 1.5, 1.5, 1.5, 1.5, -1.0]
    matrix = _matrix(tmp_path, MeasurementType.OTHER_NORMALIZED, values)

    plan = PlanningService().build(matrix, _assignments())

    assert not plan.runnable
    assert "NONFINITE_LOG_TRANSFORM" in {issue.code for issue in plan.blockers}


def test_normalized_plan_records_low_precision_warning(tmp_path: Path) -> None:
    rng = np.random.default_rng(23)
    values = rng.integers(1, 11, size=(600, 6)).astype(float)
    matrix = _matrix(tmp_path, MeasurementType.TPM, values)
    plan = PlanningService().build(matrix, _assignments())
    assert plan.runnable
    assert any("数值精度" in warning for warning in plan.warnings)
    diagnostics = plan.preprocessing["precision_diagnostics"]
    assert diagnostics["q_1"] == pytest.approx(1.0)
    assert diagnostics["q_0.1"] == pytest.approx(1.0)
    assert diagnostics["severe_rounding"] is False


def test_normalized_plan_blocks_severe_rounding_with_degenerate_residuals(tmp_path: Path) -> None:
    values = np.tile(np.asarray([1.0, 1.0, 1.0, 2.0, 2.0, 2.0]), (600, 1))
    matrix = _matrix(tmp_path, MeasurementType.TPM, values)
    plan = PlanningService().build(matrix, _assignments())
    assert not plan.runnable
    assert any(issue.code == "ROUNDING_PRECISION_DEGENERATE" for issue in plan.blockers)
    diagnostics = plan.preprocessing["precision_diagnostics"]
    assert diagnostics["low_complexity_fraction"] == pytest.approx(1.0)
    assert diagnostics["z"] == pytest.approx(1.0)


def test_normalized_runner_keeps_means_aligned_after_filtering(tmp_path: Path) -> None:
    rng = np.random.default_rng(31)
    values = rng.lognormal(3.0, 0.3, size=(600, 6))
    values[:20, :] = 0.5
    matrix = _matrix(tmp_path, MeasurementType.TPM, values)
    plan = PlanningService().build(matrix, _assignments())
    assert plan.runnable
    result = AnalysisService().run(matrix, plan, JobContext(tmp_path))
    kept_row = result["table"][20]
    expected_control_mean = float(np.mean(np.log2(values[20, :3] + 1.0)))
    assert kept_row["reason_not_tested"] == ""
    assert kept_row["mean_control_expression"] == pytest.approx(expected_control_mean)


def test_count_plan_runs_deseq2_without_method_fallback(tmp_path: Path) -> None:
    rng = np.random.default_rng(17)
    values = rng.poisson(100, size=(600, 6)).astype(float)
    values[:20, 3:] = rng.poisson(400, size=(20, 3))
    matrix = _matrix(tmp_path, MeasurementType.RAW_COUNT, values)
    plan = PlanningService().build(matrix, _assignments())
    assert plan.runnable
    assert plan.method == "DESEQ2"
    result = AnalysisService().run(matrix, plan, JobContext(tmp_path))
    assert result["method"] == "DESEQ2"
    assert result["parameters"]["p_adjust_method"] == "BH"
    assert result["parameters"]["test"] == "Wald"
    assert result["parameters"]["size_factor_type"] == "ratio"
    assert result["parameters"]["dispersion_fit_type"] == "parametric"
    assert result["parameters"]["independent_filter_statistic"] == "baseMean"
    assert result["parameters"]["independent_filter_threshold"] is None or result["parameters"]["independent_filter_threshold"] >= 0
    assert result["parameters"]["cooks_cutoff"] is True


def test_result_contract_rejects_finite_pvalue_marked_not_tested(tmp_path: Path) -> None:
    values = np.random.default_rng(73).lognormal(3.0, 0.3, size=(600, 6))
    matrix = _matrix(tmp_path, MeasurementType.TPM, values)
    plan = PlanningService().build(matrix, _assignments())
    feature_ids, _, _ = AnalysisService._read_matrix(matrix.values.path)
    row = {
        "feature_key": feature_ids[0], "original_id": feature_ids[0], "gene_symbol": None,
        "log2FoldChange": 1.0, "pvalue": 0.01, "padj": 0.02, "direction": "up",
        "tested": False, "reason_not_tested": "filtered", "mean_control_expression": 1.0,
        "mean_treated_expression": 2.0, "analysis_method": plan.method,
        "analysis_basis": plan.analysis_basis, "effect_scale": "log2_expression",
        "mean_expression_unit": "TPM",
    }

    with pytest.raises(ValueError, match="有有效 pvalue 的结果标记为未检验"):
        AnalysisService._validate_result_table([row], [feature_ids[0]], plan, "TPM")


def test_unknown_observation_unit_blocks_analysis(tmp_path: Path) -> None:
    values = np.random.default_rng(79).poisson(100, size=(600, 6)).astype(float)
    matrix = replace(
        _matrix(tmp_path, MeasurementType.RAW_COUNT, values),
        observation_unit=ObservationUnit.UNKNOWN,
    )

    from rnaseq_helper.analysis.planning import PlanningService as RawPlanningService

    plan = RawPlanningService().build(matrix, _assignments())

    assert not plan.runnable
    assert any(issue.code == "UNKNOWN_REPLICATE_STRUCTURE" for issue in plan.blockers)


def test_unknown_observation_unit_needs_explicit_whole_sample_confirmation(tmp_path: Path) -> None:
    values = np.random.default_rng(791).poisson(100, size=(600, 6)).astype(float)
    matrix = replace(
        _matrix(tmp_path, MeasurementType.RAW_COUNT, values),
        observation_unit=ObservationUnit.UNKNOWN,
    )
    from rnaseq_helper.analysis.planning import PlanningService as RawPlanningService

    unresolved = RawPlanningService().build(matrix, _assignments())
    confirmed = RawPlanningService().build(
        matrix, _assignments(), replicate_structure="independent",
    )

    assert not unresolved.runnable
    assert any(issue.code == "UNKNOWN_REPLICATE_STRUCTURE" for issue in unresolved.blockers)
    assert confirmed.runnable, [issue.message_zh for issue in confirmed.blockers]
    assert confirmed.design["replicate_structure"] == "independent"
    assert confirmed.design["replicate_structure_confirmed"] is True


def test_planning_requires_explicit_independence_or_pairing_confirmation(tmp_path: Path) -> None:
    values = np.random.default_rng(79).poisson(100, size=(600, 6)).astype(float)
    matrix = _matrix(tmp_path, MeasurementType.RAW_COUNT, values)
    from rnaseq_helper.analysis.planning import PlanningService as RawPlanningService

    plan = RawPlanningService().build(matrix, _assignments())

    assert not plan.runnable
    assert plan.design["replicate_structure"] == "unknown"
    assert any(issue.code == "UNKNOWN_REPLICATE_STRUCTURE" for issue in plan.blockers)


def test_paired_confirmation_requires_subject_ids_and_independent_rejects_them(tmp_path: Path) -> None:
    values = np.random.default_rng(80).poisson(100, size=(600, 6)).astype(float)
    matrix = _matrix(tmp_path, MeasurementType.RAW_COUNT, values)
    from rnaseq_helper.analysis.planning import PlanningService as RawPlanningService

    missing_ids = RawPlanningService().build(
        matrix, _assignments(), replicate_structure="paired",
    )
    assert any(issue.code == "PAIR_IDS_REQUIRED" for issue in missing_ids.blockers)

    supplied_ids = {sample: f"subject-{index % 3}" for index, sample in enumerate(SAMPLES)}
    conflict = RawPlanningService().build(
        matrix, _assignments(), paired_subjects=supplied_ids, replicate_structure="independent",
    )
    assert any(issue.code == "REPLICATE_STRUCTURE_CONFLICT" for issue in conflict.blockers)


def test_reversing_contrast_reverses_effect_direction(tmp_path: Path) -> None:
    rng = np.random.default_rng(41)
    values = rng.lognormal(3.0, 0.25, size=(600, 6))
    values[:30, 3:] *= 3.0
    matrix = _matrix(tmp_path, MeasurementType.TPM, values)
    forward = PlanningService().build(matrix, _assignments(), DEGConfig("control", "test"))
    reverse = PlanningService().build(matrix, _assignments(), DEGConfig("test", "control"))
    assert forward.runnable and reverse.runnable
    forward_dir = tmp_path / "forward"
    reverse_dir = tmp_path / "reverse"
    forward_dir.mkdir()
    reverse_dir.mkdir()
    forward_result = AnalysisService().run(matrix, forward, JobContext(forward_dir))
    reverse_result = AnalysisService().run(matrix, reverse, JobContext(reverse_dir))
    for forward_row, reverse_row in zip(forward_result["table"], reverse_result["table"]):
        if forward_row["tested"] and reverse_row["tested"]:
            assert reverse_row["log2FoldChange"] == pytest.approx(-forward_row["log2FoldChange"])
            assert reverse_row["pvalue"] == pytest.approx(forward_row["pvalue"])


def test_fpkm_uses_normalized_log_runner_and_preserves_unit(tmp_path: Path) -> None:
    rng = np.random.default_rng(47)
    values = rng.lognormal(3.0, 0.3, size=(600, 6))
    values[:20, 3:] *= 3.0
    matrix = _matrix(tmp_path, MeasurementType.FPKM, values)
    plan = PlanningService().build(matrix, _assignments())
    assert plan.runnable
    assert plan.method == "LIMMA_ON_LOG2_FPKM"
    assert "当前选择为FPKM" in plan.method_reason_zh
    assert "已确认的FPKM" not in plan.method_reason_zh
    result = AnalysisService().run(matrix, plan, JobContext(tmp_path))
    assert result["method"] == "LIMMA_ON_LOG2_FPKM"
    assert {row["mean_expression_unit"] for row in result["table"]} == {"FPKM"}


def test_paired_linear_expression_filter_uses_complete_pair_count(tmp_path: Path) -> None:
    sample_ids = tuple([f"C{index}" for index in range(1, 6)] + [f"T{index}" for index in range(1, 6)])
    rng = np.random.default_rng(20261016)
    values = rng.lognormal(3.0, 0.35, size=(600, len(sample_ids)))
    matrix = _matrix(tmp_path, MeasurementType.TPM, values, sample_ids)
    assignments = {sample: "control" if sample.startswith("C") else "test" for sample in sample_ids}
    paired_subjects = {
        **{f"C{index}": f"S{index}" for index in range(1, 5)},
        "C5": "control_only",
        **{f"T{index}": f"S{index}" for index in range(1, 5)},
        "T5": "test_only",
    }

    plan = PlanningService().build(matrix, assignments, paired_subjects=paired_subjects)

    assert plan.runnable, [issue.message_zh for issue in plan.blockers]
    assert plan.preprocessing["min_samples"] == 4
    assert plan.config.expression_filter is not None
    assert plan.config.expression_filter.min_samples == 4
    assert "完整配对数" in plan.config.expression_filter.reason_zh


def test_confirmed_paired_count_design_runs_and_report_preserves_aliased_pairs(tmp_path: Path) -> None:
    sample_ids = ("C1", "C2", "C3", "T1", "T2", "T3")
    rng = np.random.default_rng(20261016)
    values = rng.poisson(100, size=(600, len(sample_ids))).astype(float)
    values[:25, 3:] = rng.poisson(280, size=(25, 3))
    matrix = _matrix(tmp_path, MeasurementType.RAW_COUNT, values, sample_ids)
    assignments = {sample: "control" if sample.startswith("C") else "test" for sample in sample_ids}
    subjects = {
        "C1": "participant-A", "T1": "participant-A",
        "C2": "participant-B", "T2": "participant-B",
        "C3": "participant-C", "T3": "participant-C",
    }

    plan = PlanningService().build(
        matrix, assignments, paired_subjects=subjects, replicate_structure="paired",
    )
    assert plan.runnable, [issue.message_zh for issue in plan.blockers]
    assert plan.design["type"] == "paired"
    result = AnalysisService().run(matrix, plan, JobContext(tmp_path))

    assert "subject" in result["parameters"]["design"]
    report = (tmp_path / "reports" / "analysis-report.html").read_text(encoding="utf-8")
    assert "样本关系：已确认同一对象的配对/重复测量" in report
    assert "C1: control；配对个体 个体1" in report
    assert "T1: test；配对个体 个体1" in report
    assert "participant-A" not in report


def test_regular_tpm_prespecified_effect_directions_are_stable_across_seeds(tmp_path: Path) -> None:
    correct = 0
    total = 0
    for seed in (101, 202, 303):
        seed_dir = tmp_path / f"seed-{seed}"
        seed_dir.mkdir()
        rng = np.random.default_rng(seed)
        values = rng.lognormal(3.0, 0.18, size=(600, 6))
        values[:40, 3:] *= 4.0
        matrix = _matrix(seed_dir, MeasurementType.TPM, values)
        plan = PlanningService().build(matrix, _assignments())
        assert plan.runnable
        result = AnalysisService().run(matrix, plan, JobContext(seed_dir))
        for row in result["table"][:40]:
            if row["tested"]:
                total += 1
                correct += int(row["log2FoldChange"] > 0)
    assert total == 120
    assert correct / total >= 0.95
