from __future__ import annotations

from pathlib import Path

from rnaseq_helper.domain.models import MeasurementType, ValueScale, may_contain_sensitive_metadata
from rnaseq_helper.preparation.service import PreparationService
from rnaseq_helper.recognition.scanner import AssetScanner


def _scan_expression_table(path: Path):
    return AssetScanner().scan((path,)).assets[0]


def test_table_text_evidence_keeps_exact_cell_and_position(tmp_path: Path) -> None:
    source = tmp_path / "expression.tsv"
    source.write_text(
        "Measurement\tTPM\n"
        "Transformation\tlog2(TPM + 1)\n"
        "feature_id\tsample_a\tsample_b\n",
        encoding="utf-8",
    )

    asset = _scan_expression_table(source)

    assert asset.measurement_hint == MeasurementType.TPM
    assert asset.scale_hint == ValueScale.LOG2
    unit = next(item for item in asset.evidence if item.fact_key == "measurement_type")
    scale = next(item for item in asset.evidence if item.fact_key == "value_scale")
    assert unit.excerpt == "TPM"
    assert unit.location == "表格记录第 1 行、第 2 列"
    assert scale.excerpt == "log2(TPM + 1)"
    assert scale.location == "表格记录第 2 行、第 2 列"


def test_linked_readme_quotes_candidate_but_conflicting_units_stay_unknown(tmp_path: Path) -> None:
    source = tmp_path / "expression.tsv"
    source.write_text("feature_id\tsample_a\tsample_b\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "expression.tsv contains TPM values.\n"
        "expression.tsv alternate description says FPKM values.\n"
        "expression.tsv was transformed with log2(expression + 1).\n",
        encoding="utf-8",
    )

    asset = _scan_expression_table(source)

    assert asset.measurement_hint == MeasurementType.UNKNOWN
    assert asset.scale_hint == ValueScale.LOG2
    assert sum(item.fact_key == "measurement_type" for item in asset.evidence) == 2
    assert all(
        item.evidence_level == "linked_sidecar_text_candidate"
        for item in asset.evidence
        if item.fact_key
    )


def test_readme_not_linked_to_one_of_multiple_tables_is_not_used_as_evidence(tmp_path: Path) -> None:
    first = tmp_path / "first.tsv"
    second = tmp_path / "second.tsv"
    first.write_text("feature_id\tsample_a\tsample_b\n", encoding="utf-8")
    second.write_text("feature_id\tsample_a\tsample_b\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("Expression values are TPM and log2 transformed.\n", encoding="utf-8")

    asset = _scan_expression_table(first)

    assert asset.measurement_hint == MeasurementType.UNKNOWN
    assert asset.scale_hint == ValueScale.UNKNOWN
    assert any(item.evidence_level == "unlinked_sidecar" for item in asset.evidence)


def test_more_than_four_candidate_sidecars_are_not_partially_used(tmp_path: Path) -> None:
    source = tmp_path / "expression.tsv"
    source.write_text("feature_id\tsample_a\tsample_b\n", encoding="utf-8")
    for index in range(4):
        (tmp_path / f"README_{index}.txt").write_text(
            "expression.tsv contains TPM values.\n",
            encoding="utf-8",
        )
    (tmp_path / "README_4.txt").write_text(
        "expression.tsv alternate section contains FPKM values.\n",
        encoding="utf-8",
    )

    asset = _scan_expression_table(source)

    assert asset.measurement_hint == MeasurementType.UNKNOWN
    assert not any(item.fact_key == "measurement_type" for item in asset.evidence)
    assert any(item.evidence_level == "sidecar_scan_incomplete" for item in asset.evidence)


def test_readme_self_reference_does_not_link_to_an_expression_table(tmp_path: Path) -> None:
    # Text-only association contract; not a biological expression accuracy test.
    for name in ("a.tsv", "b.tsv"):
        (tmp_path / name).write_text("feature_id\tcolumn_a\tcolumn_b\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "README.md explains TPM values and log2 transformation.\n", encoding="utf-8",
    )

    for name in ("a.tsv", "b.tsv"):
        asset = _scan_expression_table(tmp_path / name)
        assert asset.measurement_hint == MeasurementType.UNKNOWN
        assert asset.scale_hint == ValueScale.UNKNOWN
        assert not any(item.fact_key for item in asset.evidence)
        assert any(item.evidence_level == "unlinked_sidecar" for item in asset.evidence)


def test_readme_links_an_explicit_short_expression_filename_only(tmp_path: Path) -> None:
    for name in ("a.tsv", "b.tsv"):
        (tmp_path / name).write_text("feature_id\tcolumn_a\tcolumn_b\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "a.tsv contains raw counts on a linear scale.\n", encoding="utf-8",
    )

    selected = _scan_expression_table(tmp_path / "a.tsv")
    unrelated = _scan_expression_table(tmp_path / "b.tsv")
    assert selected.measurement_hint == MeasurementType.RAW_COUNT
    assert selected.scale_hint == ValueScale.LINEAR
    assert unrelated.measurement_hint == MeasurementType.UNKNOWN
    assert unrelated.scale_hint == ValueScale.UNKNOWN


def test_readme_other_filename_substrings_are_not_association_evidence(tmp_path: Path) -> None:
    for name in ("a.tsv", "expression.tsv"):
        (tmp_path / name).write_text("feature_id\tcolumn_a\tcolumn_b\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "data.tsv and expression_old.tsv contain TPM on a linear scale.\n", encoding="utf-8",
    )

    for name in ("a.tsv", "expression.tsv"):
        asset = _scan_expression_table(tmp_path / name)
        assert asset.measurement_hint == MeasurementType.UNKNOWN
        assert asset.scale_hint == ValueScale.UNKNOWN


def test_readme_explicit_filename_allows_terminal_sentence_period(tmp_path: Path) -> None:
    for name in ("a.tsv", "b.tsv"):
        (tmp_path / name).write_text("feature_id\tcolumn_a\tcolumn_b\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "This document describes A.TSV. It contains raw counts on a linear scale.\n",
        encoding="utf-8",
    )
    asset = _scan_expression_table(tmp_path / "a.tsv")
    assert asset.measurement_hint == MeasurementType.RAW_COUNT
    assert asset.scale_hint == ValueScale.LINEAR


def test_overlong_sidecar_line_is_not_partially_used(tmp_path: Path) -> None:
    source = tmp_path / "expression.tsv"
    source.write_text("feature_id\tsample_a\tsample_b\n", encoding="utf-8")
    (tmp_path / "delivery_notes.txt").write_text(
        "expression.tsv contains TPM and FPKM values. " + ("x" * 8200) + "\n",
        encoding="utf-8",
    )

    asset = _scan_expression_table(source)

    assert asset.measurement_hint == MeasurementType.UNKNOWN
    assert any(item.evidence_level == "sidecar_scan_incomplete" for item in asset.evidence)


def test_sidecar_excerpt_redacts_identifiers_and_unrelated_numeric_values(tmp_path: Path) -> None:
    source = tmp_path / "expression.tsv"
    source.write_text("feature_id\tsample_a\tsample_b\n", encoding="utf-8")
    (tmp_path / "delivery_notes.txt").write_text(
        "expression.tsv uses TPM for patient ID: P-231; observed 3.1415; formula log2(TPM + 1).\n",
        encoding="utf-8",
    )

    asset = _scan_expression_table(source)
    excerpt = next(item for item in asset.evidence if item.fact_key == "value_scale").excerpt

    assert "P-231" not in excerpt
    assert "3.1415" not in excerpt
    assert "log2(TPM + 1)" not in excerpt
    scale_evidence = next(item for item in asset.evidence if item.fact_key == "value_scale")
    assert scale_evidence.excerpt_redacted
    assert scale_evidence.reported_transform == "log2(TPM + 1)"


def test_sensitive_context_hides_entire_excerpt_and_source_path(tmp_path: Path) -> None:
    source = tmp_path / "expression.tsv"
    source.write_text("feature_id\tsample_a\tsample_b\n", encoding="utf-8")
    sidecar = tmp_path / "delivery_notes.txt"
    sidecar.write_text(
        "expression.tsv Patient name: Alice Zhang; sample ID S17; values are TPM, log2(TPM + 1).\n",
        encoding="utf-8",
    )

    asset = _scan_expression_table(source)
    evidence = next(item for item in asset.evidence if item.fact_key == "value_scale")
    serialized = str(evidence.as_dict())

    assert evidence.excerpt_redacted
    assert "Alice" not in evidence.excerpt and "Zhang" not in evidence.excerpt
    assert "S17" not in evidence.excerpt
    assert "Alice" not in serialized and "Zhang" not in serialized and "S17" not in serialized
    assert str(sidecar) not in serialized
    assert evidence.reported_transform == "log2(TPM + 1)"


def test_reported_formula_rejects_arbitrary_identifier_names(tmp_path: Path) -> None:
    source = tmp_path / "expression.tsv"
    source.write_text("feature_id\tsample_a\tsample_b\n", encoding="utf-8")
    (tmp_path / "delivery_notes.txt").write_text(
        "expression.tsv values are TPM; transformation log2(AliceZhang + 1).\n",
        encoding="utf-8",
    )

    asset = _scan_expression_table(source)

    assert next(item for item in asset.evidence if item.fact_key == "value_scale").reported_transform == ""


def test_negated_log2_statement_is_not_classified_as_log2(tmp_path: Path) -> None:
    source = tmp_path / "expression.tsv"
    source.write_text("feature_id\tsample_a\tsample_b\n", encoding="utf-8")
    (tmp_path / "delivery_notes.txt").write_text(
        "expression.tsv was not log2-transformed.\n",
        encoding="utf-8",
    )

    asset = _scan_expression_table(source)

    assert asset.scale_hint == ValueScale.UNKNOWN
    assert not any(
        item.fact_key == "value_scale" and item.fact_value == ValueScale.LOG2.value
        for item in asset.evidence
    )


def test_log2_negation_covers_action_verbs_in_english_and_chinese(tmp_path: Path) -> None:
    for index, sentence in enumerate((
        "expression.tsv did not use log2 transformation.",
        "expression.tsv 未使用 log2 转换。",
    )):
        source = tmp_path / f"expression_{index}.tsv"
        source.write_text("feature_id\tsample_a\tsample_b\n", encoding="utf-8")
        (tmp_path / f"readme_{index}.txt").write_text(sentence, encoding="utf-8")

        asset = AssetScanner().scan((source,)).assets[0]

        assert asset.scale_hint == ValueScale.UNKNOWN


def test_same_line_conflicting_log2_formulas_are_both_retained(tmp_path: Path) -> None:
    source = tmp_path / "expression.tsv"
    source.write_text("feature_id\tsample_a\tsample_b\n", encoding="utf-8")
    (tmp_path / "delivery_notes.txt").write_text(
        "expression.tsv uses log2(TPM + 1) or log2(TPM + 0.5).\n",
        encoding="utf-8",
    )

    asset = _scan_expression_table(source)
    formulas = {
        item.reported_transform for item in asset.evidence
        if item.fact_key == "value_scale" and item.reported_transform
    }

    assert formulas == {"log2(TPM + 1)", "log2(TPM + 0.5)"}


def test_explicit_sample_marker_in_source_path_is_hidden_from_manifest(tmp_path: Path) -> None:
    source_dir = tmp_path / "patient_008"
    source_dir.mkdir()
    source = source_dir / "expression.tsv"
    source.write_text(
        "Measurement\tTPM\nfeature_id\tsample_a\tsample_b\n",
        encoding="utf-8",
    )

    asset = _scan_expression_table(source)
    manifest = asset.as_dict()
    recipe = PreparationService().start(asset, tmp_path / "project", preview_only=True).recipe.as_dict()

    assert manifest["source_paths_redacted"]
    assert "patient_008" not in str(manifest)
    assert recipe["source_path_redacted"]
    assert "patient_008" not in str(recipe)
    assert all(item.excerpt_redacted for item in asset.evidence if item.fact_key)


def test_person_or_sample_path_number_variants_are_detected() -> None:
    for path in (
        "/input/patient001/counts.tsv",
        "/input/sample 01/counts.tsv",
        "/input/样本-001/counts.tsv",
        "/input/标本 02/counts.tsv",
    ):
        assert may_contain_sensitive_metadata(path)


def test_chinese_sample_path_is_hidden_in_serialized_asset(tmp_path: Path) -> None:
    source_dir = tmp_path / "样本-001"
    source_dir.mkdir()
    source = source_dir / "expression.tsv"
    source.write_text("Measurement\tTPM\nfeature_id\tsample_a\tsample_b\n", encoding="utf-8")

    manifest = _scan_expression_table(source).as_dict()

    assert manifest["source_paths_redacted"]
    assert "样本-001" not in str(manifest)
