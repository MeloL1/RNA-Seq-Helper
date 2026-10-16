from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from tests._planning import PlanningService
from rnaseq_helper.domain.models import (
    ExpressionMatrix,
    MatrixStoreRef,
    MeasurementType,
    ObservationUnit,
    ValidationSummary,
    ValueScale,
    sha256_file,
)


SAMPLES = ("Ctrl_1", "Ctrl_2", "Ctrl_3", "Treat_1", "Treat_2", "Treat_3")


def _matrix(
    tmp_path: Path,
    values: np.ndarray,
    *,
    samples: tuple[str, ...] = SAMPLES,
    input_transform: str = "log2(expression)",
    provenance: str = "same quantification pipeline; comparable expression values",
) -> ExpressionMatrix:
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    matrix_path = prepared / "expression_matrix.tsv"
    with matrix_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["feature_key", *samples])
        for index, row in enumerate(values):
            writer.writerow([f"feature_{index:04d}", *row.tolist()])
    feature_path = prepared / "feature_metadata.tsv"
    feature_path.write_text(
        "feature_key\toriginal_id\n"
        + "\n".join(f"feature_{index:04d}\tfeature_{index:04d}" for index in range(values.shape[0]))
        + "\n",
        encoding="utf-8",
    )
    sample_path = prepared / "sample_metadata.tsv"
    sample_path.write_text("sample_id\n" + "\n".join(samples) + "\n", encoding="utf-8")
    values_ref = MatrixStoreRef(matrix_path, "dense-tsv", "float64", values.shape, sha256_file(matrix_path))
    feature_ref = MatrixStoreRef(
        feature_path, "table-tsv", "string", (values.shape[0], 2), sha256_file(feature_path)
    )
    sample_ref = MatrixStoreRef(
        sample_path, "table-tsv", "string", (len(samples), 1), sha256_file(sample_path)
    )
    return ExpressionMatrix(
        "review-log-gate",
        values_ref,
        feature_ref,
        sample_ref,
        ObservationUnit.BULK_SAMPLE,
        MeasurementType.OTHER_NORMALIZED,
        ValueScale.LOG2,
        input_transform,
        "CUSTOM_ORIGINAL",
        None,
        (),
        "recipe-review-log-gate",
        ValidationSummary(True, (), values.shape[0], values.shape[1], int(values.size)),
        values_ref.content_hash,
        measurement_provenance=provenance,
    )


def _assignments(samples: tuple[str, ...] = SAMPLES) -> dict[str, str]:
    return {sample: ("control" if sample.startswith("Ctrl") or sample.endswith("_C") else "test") for sample in samples}


def test_generic_log_blocks_when_all_twelve_features_are_constant(tmp_path: Path) -> None:
    values = np.full((12, len(SAMPLES)), 2.0)
    plan = PlanningService().build(_matrix(tmp_path, values), _assignments())

    assert plan.method == "LIMMA_ON_LOG_EXPRESSION"
    assert not plan.runnable
    assert any(issue.code == "INSUFFICIENT_TREND_DATA" for issue in plan.blockers)


def test_generic_log_with_variable_expression_features_passes_and_records_profile(tmp_path: Path) -> None:
    rng = np.random.default_rng(20260914)
    values = rng.normal(5.0, 0.35, size=(600, len(SAMPLES)))
    values += np.arange(600, dtype=float)[:, None] / 100.0
    plan = PlanningService().build(_matrix(tmp_path, values), _assignments())

    assert plan.runnable
    assert plan.method == "LIMMA_ON_LOG_EXPRESSION"
    assert plan.resolved_method_parameters["trend"] is True
    assert plan.resolved_method_parameters["robust"] is True
    assert plan.resolved_method_parameters["winsor.tail.p"] == [0.05, 0.1]
    assert plan.resolved_method_parameters["proportion"] == 0.01
    assert plan.resolved_method_parameters["stdev.coef.lim"] == [0.1, 4]
    assert plan.resolved_method_parameters["legacy_requested"] is True


def test_degenerate_gate_uses_batch_subject_design_residuals(tmp_path: Path) -> None:
    samples = ("S1_C", "S1_T", "S2_C", "S2_T", "S3_C", "S3_T", "S4_C", "S4_T")
    assignments = _assignments(samples)
    subjects = {sample: sample[:2] for sample in samples}
    batches = {
        "S1_C": "batch_1", "S1_T": "batch_2",
        "S2_C": "batch_2", "S2_T": "batch_1",
        "S3_C": "batch_1", "S3_T": "batch_2",
        "S4_C": "batch_2", "S4_T": "batch_1",
    }
    design_values = np.asarray([
        [float(assignments[s] == group) for group in ("control", "test")]
        for s in samples
    ])
    batch_values = np.asarray([float(batches[s] == "batch_2") for s in samples])
    subject_values = np.asarray([int(subjects[s][1:]) for s in samples], dtype=float)
    rng = np.random.default_rng(7)
    rows = []
    for index in range(600):
        group_effect = np.asarray([0.2 + index / 1000.0, 0.8 + index / 1000.0])
        exact = design_values @ group_effect + batch_values * 0.13 + subject_values * 0.017
        rows.append(exact if index < 60 else exact + rng.normal(0, 0.08, len(samples)))
    values = np.asarray(rows)

    plan = PlanningService().build(
        _matrix(tmp_path, values, samples=samples),
        assignments,
        paired_subjects=subjects,
        batch=batches,
    )

    assert not plan.runnable
    assert any(issue.code == "DEGENERATE_VARIANCE" for issue in plan.blockers)
    assert plan.preprocessing["precision_diagnostics"]["residual_df"] == 2
    assert plan.preprocessing["precision_diagnostics"]["z"] == 0.1


def test_generic_log_rejects_unknown_transform_evidence(tmp_path: Path) -> None:
    rng = np.random.default_rng(9)
    values = rng.normal(5.0, 0.35, size=(600, len(SAMPLES)))
    plan = PlanningService().build(
        _matrix(tmp_path, values, input_transform="", provenance="user-confirmed input facts"),
        _assignments(),
    )

    assert not plan.runnable
    assert any(issue.code == "INVALID_TRANSFORM" for issue in plan.blockers)


def test_generic_log_accepts_explicit_user_confirmed_log2_scale(tmp_path: Path) -> None:
    rng = np.random.default_rng(10)
    values = rng.normal(5.0, 0.35, size=(600, len(SAMPLES)))
    values += np.arange(600, dtype=float)[:, None] / 100.0
    matrix = _matrix(
        tmp_path,
        values,
        input_transform="",
        provenance="user-confirmed input facts; user-confirmed value_scale=LOG2",
    )

    plan = PlanningService().build(matrix, _assignments())

    assert plan.runnable
    assert plan.method == "LIMMA_ON_LOG_EXPRESSION"
    assert not any(issue.code == "INVALID_TRANSFORM" for issue in plan.blockers)
