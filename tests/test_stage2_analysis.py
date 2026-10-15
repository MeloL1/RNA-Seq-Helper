from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import pytest

from rnaseq_helper.analysis.planning import PlanningService
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
from rnaseq_helper.grouping.service import GroupingService


SAMPLES = ("Ctrl_1", "Ctrl_2", "Ctrl_3", "Treat_1", "Treat_2", "Treat_3")


def _matrix(tmp_path: Path, measurement: MeasurementType, values: np.ndarray) -> ExpressionMatrix:
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    feature_ids = [f"gene_{index:04d}" for index in range(values.shape[0])]
    matrix_path = prepared / "expression_matrix.tsv"
    with matrix_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["feature_key", *SAMPLES])
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
    sample_path.write_text("sample_id\n" + "\n".join(SAMPLES) + "\n", encoding="utf-8")
    values_ref = MatrixStoreRef(matrix_path, "dense-tsv", "float64", values.shape, sha256_file(matrix_path))
    feature_ref = MatrixStoreRef(feature_path, "table-tsv", "string", (len(feature_ids), 2), sha256_file(feature_path))
    sample_ref = MatrixStoreRef(sample_path, "table-tsv", "string", (len(SAMPLES), 1), sha256_file(sample_path))
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


def test_grouping_blocks_completely_confounding_batch() -> None:
    validation = GroupingService().validate(
        _assignments(),
        SAMPLES,
        batch={sample: ("batch_a" if sample.startswith("Ctrl") else "batch_b") for sample in SAMPLES},
    )
    assert not validation.passed
    assert any(issue.code == "BATCH_CONFOUNDING" for issue in validation.issues)


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


def test_normalized_plan_runs_fixed_limma_profile(tmp_path: Path) -> None:
    rng = np.random.default_rng(17)
    values = rng.lognormal(3.0, 0.3, size=(600, 6))
    values[:20, 3:] *= 3.0
    matrix = _matrix(tmp_path, MeasurementType.TPM, values)
    plan = PlanningService().build(matrix, _assignments())
    assert plan.runnable
    assert plan.method == "LIMMA_ON_LOG2_TPM"
    assert plan.method_profile_id == "normalized-log-limma-trend-v1"
    result = AnalysisService().run(matrix, plan, JobContext(tmp_path))
    assert result["method"] == plan.method
    assert result["parameters"]["transform"] == "log2(x+1)"
    assert result["summary"]["tested_count"] == 600
    assert (tmp_path / "analysis" / "deg-result.json").exists()
    assert (tmp_path / "reports" / "analysis-report.html").exists()
    assert (tmp_path / "reports" / "deg-results.xlsx").exists()
    assert (tmp_path / "reports" / "interpretation-zh.txt").exists()
    assert all((tmp_path / "figures" / name).exists() for name in (
        "pca.png", "sample-correlation.png", "p-value-histogram.png", "volcano.png", "top-heatmap.png",
    ))
    assert (tmp_path / "figures" / "figure-manifest.json").exists()


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
