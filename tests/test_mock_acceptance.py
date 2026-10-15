from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from rnaseq_helper.analysis.planning import PlanningService
from rnaseq_helper.domain.models import (
    DEGConfig,
    ExpressionMatrix,
    MatrixStoreRef,
    MeasurementType,
    ObservationUnit,
    ValidationSummary,
    ValueScale,
    sha256_file,
)
from rnaseq_helper.readers.geo_reader import GeoSeriesMatrixReader
from rnaseq_helper.readers.tenx_reader import TenXReader
from rnaseq_helper.recognition.scanner import AssetScanner

from tests.fixtures.mock_factory import (
    low_precision_values,
    regular_normalized_values,
    write_company_counts,
    write_geo_series_matrix,
    write_tenx_bundle,
)


def _assignments(sample_ids: list[str]) -> dict[str, str]:
    half = len(sample_ids) // 2
    return {sample_id: ("control" if index < half else "test") for index, sample_id in enumerate(sample_ids)}


def _matrix(tmp_path: Path, measurement: MeasurementType, values: np.ndarray) -> ExpressionMatrix:
    prepared = tmp_path / "prepared"
    prepared.mkdir(parents=True, exist_ok=True)
    samples = [f"Ctrl_{index + 1}" for index in range(values.shape[1] // 2)] + [f"Treat_{index + 1}" for index in range(values.shape[1] - values.shape[1] // 2)]
    matrix_path = prepared / "expression_matrix.tsv"
    with matrix_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["feature_key", *samples])
        for index, row in enumerate(values, start=1):
            writer.writerow([f"feature_{index:06d}", *row.tolist()])
    feature_path = prepared / "feature_metadata.tsv"
    feature_path.write_text(
        "feature_key\toriginal_id\n" + "\n".join(
            f"feature_{index:06d}\tfeature_{index:06d}" for index in range(1, values.shape[0] + 1)
        ) + "\n",
        encoding="utf-8",
    )
    sample_path = prepared / "sample_metadata.tsv"
    sample_path.write_text("sample_id\n" + "\n".join(samples) + "\n", encoding="utf-8")
    refs = [
        MatrixStoreRef(matrix_path, "dense-tsv", "float64", values.shape, sha256_file(matrix_path)),
        MatrixStoreRef(feature_path, "table-tsv", "string", (values.shape[0], 2), sha256_file(feature_path)),
        MatrixStoreRef(sample_path, "table-tsv", "string", (values.shape[1], 1), sha256_file(sample_path)),
    ]
    return ExpressionMatrix(
        "mock-matrix", refs[0], refs[1], refs[2], ObservationUnit.BULK_SAMPLE,
        measurement, ValueScale.LINEAR, "", "CUSTOM_ORIGINAL", None, (), "mock-recipe",
        ValidationSummary(True, (), values.shape[0], values.shape[1], int(values.size)),
        refs[0].content_hash or "",
    )


def test_geo_mock_is_2000_by_8_and_keeps_sample_metadata(tmp_path: Path) -> None:
    path = write_geo_series_matrix(tmp_path / "GSEsynthetic_series_matrix.txt")
    geo = GeoSeriesMatrixReader().read(path)
    assert geo.raw_table.row_count == 2001
    assert geo.raw_table.column_count == 9
    assert len(geo.sample_accessions) == 8
    assert set(geo.platform_ids) == {"GPLSYNTH"}
    assert AssetScanner().scan((path,)).assets[0].kind == "GEO_SERIES_MATRIX"


def test_company_mock_has_fourth_row_header_and_3000_features(tmp_path: Path) -> None:
    path = write_company_counts(tmp_path / "company_counts.tsv")
    rows = path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 3004
    assert rows[3].split("\t")[:2] == ["gene_id", "gene_symbol"]
    assert len(rows[3].split("\t")) == 14
    asset = AssetScanner().scan((path,)).assets[0]
    assert asset.kind == "TABLE"
    assert asset.shape_hint == (40, 14)


def test_tenx_mock_remains_sparse_and_blocks_bulk_semantics(tmp_path: Path) -> None:
    directory = write_tenx_bundle(tmp_path / "filtered_feature_bc_matrix")
    bundle = TenXReader().find_bundle(directory)
    assert bundle.rows == 1000 and bundle.columns == 600
    assert bundle.nonzero_entries == 3000
    assert bundle.gene_expression_rows == 950
    assert bundle.feature_type_counts["Antibody Capture"] == 50
    payload = bundle.as_dict()
    assert payload["storage"] == "sparse-matrix-market"
    assert payload["bulk_analysis_allowed"] is False


def test_regular_tpm_and_fpkm_pass_the_500_feature_trend_gate(tmp_path: Path) -> None:
    values = regular_normalized_values()
    for offset, measurement in enumerate((MeasurementType.TPM, MeasurementType.FPKM)):
        matrix = _matrix(tmp_path / f"normalized-{offset}", measurement, values)
        sample_ids = [f"Ctrl_{index + 1}" for index in range(6)] + [f"Treat_{index + 1}" for index in range(6)]
        plan = PlanningService().build(matrix, _assignments(sample_ids), DEGConfig("control", "test"))
        assert plan.runnable
        assert plan.method == f"LIMMA_ON_LOG2_{measurement.value}"
        assert plan.preprocessing["precision_diagnostics"]["evidence_sufficient"] is True


def test_severe_rounding_mock_is_blocked_but_normal_data_is_not(tmp_path: Path) -> None:
    severe = _matrix(tmp_path / "severe", MeasurementType.TPM, low_precision_values())
    sample_ids = ["Ctrl_1", "Ctrl_2", "Ctrl_3", "Treat_1", "Treat_2", "Treat_3"]
    severe_plan = PlanningService().build(severe, _assignments(sample_ids))
    assert not severe_plan.runnable
    assert any(issue.code == "ROUNDING_PRECISION_DEGENERATE" for issue in severe_plan.blockers)

    regular = _matrix(tmp_path / "regular", MeasurementType.TPM, regular_normalized_values(feature_count=8000, sample_count=6))
    regular_plan = PlanningService().build(regular, _assignments(sample_ids))
    assert regular_plan.runnable
    assert not any(issue.code == "ROUNDING_PRECISION_DEGENERATE" for issue in regular_plan.blockers)
