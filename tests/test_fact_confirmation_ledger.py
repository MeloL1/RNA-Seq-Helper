from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from rnaseq_helper.domain.models import MeasurementType, ValueScale
from rnaseq_helper.preparation.service import PreparationService
from rnaseq_helper.recognition.scanner import AssetScanner
from rnaseq_helper.ui.pages.import_page import ImportPage


def test_text_candidate_confirmation_is_saved_in_recipe_and_project_manifest(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    source = tmp_path / "expression.tsv"
    source.write_text(
        "Measurement\tTPM\n"
        "Transformation\tlog2(TPM + 1)\n"
        "feature_id\tcontrol_1\tcase_1\n"
        "gene_a\t1.1\t2.1\n"
        "gene_b\t1.2\t2.2\n"
        "gene_c\t1.3\t2.3\n"
        "gene_d\t1.4\t2.4\n",
        encoding="utf-8",
    )
    asset = AssetScanner().scan((source,)).assets[0]
    preparation = PreparationService()
    page = ImportPage()
    page._apply_auto_judgement(asset)
    page.session = preparation.start(asset, tmp_path / "project", preview_only=True)

    assert page.use_evidence_button.isEnabled()
    page.use_evidence_button.click()
    patch = page._current_patch()
    patch.update({
        "header_row": 2,
        "data_start_row": 3,
        "feature_id_column": 0,
        "sample_columns": [1, 2],
        "annotation_columns": [],
        "ignored_columns": [],
    })
    session = preparation.apply(page.session, patch)
    session = preparation.complete_read(session)
    summary = preparation.validate(session)
    assert summary.passed, [issue.message_zh for issue in summary.issues]

    matrix = preparation.finish(session, summary=summary)
    recipe_path = session.project_dir / "preparation-recipe.json"
    project_path = session.project_dir / "project.json"
    recipe = json.loads(recipe_path.read_text(encoding="utf-8"))
    project = json.loads(project_path.read_text(encoding="utf-8"))
    confirmations = recipe["fact_confirmations"]

    assert [item["status"] for item in confirmations] == [
        "user_confirmed_text_candidate",
        "user_confirmed_text_candidate",
    ]
    assert confirmations[0]["evidence"][0]["excerpt"] == "TPM"
    assert confirmations[1]["evidence"][0]["excerpt"] == "log2(TPM + 1)"
    assert project["fact_confirmations"] == confirmations
    assert recipe["reported_transform"] == "log2(TPM + 1)"
    assert project["reported_transform"] == "log2(TPM + 1)"
    assert "user-confirmed value_scale=LOG2" in matrix.measurement_provenance

    page.close()
    application.processEvents()


def test_manual_fact_selection_is_not_reported_as_source_documented() -> None:
    provenance = PreparationService._measurement_provenance((
        {
            "fact_key": "measurement_type",
            "selected_value": "FPKM",
            "status": "user_confirmed_without_direct_text",
        },
        {
            "fact_key": "value_scale",
            "selected_value": "LINEAR",
            "status": "user_confirmed_without_direct_text",
        },
    ))

    assert provenance.startswith("user-selected input facts:")
    assert "measurement_type=FPKM[manual_without_direct_text]" in provenance
    assert "value_scale=LINEAR[manual_without_direct_text]" in provenance
    assert "user-confirmed input facts" not in provenance


def test_redacted_text_candidates_cannot_be_confirmed_with_one_click(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    source = tmp_path / "expression.tsv"
    source.write_text("feature_id\tsample_a\tsample_b\n", encoding="utf-8")
    (tmp_path / "delivery_notes.txt").write_text(
        "expression.tsv patient name: Alice Zhang; the matrix uses TPM and log2(TPM + 1).\n",
        encoding="utf-8",
    )
    asset = AssetScanner().scan((source,)).assets[0]
    page = ImportPage()

    page._apply_auto_judgement(asset)

    assert not page.use_evidence_button.isEnabled()
    assert "Alice" not in page.auto_judgement.text()
    page.close()
    application.processEvents()


def test_unreadable_sidecar_directory_blocks_one_click_confirmation(tmp_path: Path, monkeypatch) -> None:
    application = QApplication.instance() or QApplication([])
    source = tmp_path / "expression.tsv"
    source.write_text("Measurement\tTPM\nfeature_id\tsample_a\tsample_b\n", encoding="utf-8")
    original_iterdir = Path.iterdir

    def deny_source_directory(self: Path):
        if self == source.parent:
            raise PermissionError("test-only directory access denial")
        return original_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", deny_source_directory)
    asset = AssetScanner().scan((source,)).assets[0]
    page = ImportPage()

    page._apply_auto_judgement(asset)

    assert asset.measurement_hint.value == "TPM"
    assert any(item.evidence_level == "sidecar_scan_incomplete" for item in asset.evidence)
    assert not page.use_evidence_button.isEnabled()
    page.close()
    application.processEvents()


def test_confirmation_ledger_preserves_late_conflicting_candidate(tmp_path: Path) -> None:
    application = QApplication.instance() or QApplication([])
    source = tmp_path / "expression.tsv"
    source.write_text("feature_id\tsample_a\tsample_b\n", encoding="utf-8")
    (tmp_path / "delivery_notes.txt").write_text(
        "".join("expression.tsv reports TPM.\n" for _ in range(16))
        + "expression.tsv alternate section reports FPKM.\n",
        encoding="utf-8",
    )
    asset = AssetScanner().scan((source,)).assets[0]
    page = ImportPage()
    page._apply_auto_judgement(asset)
    preparation = PreparationService()
    page.session = preparation.start(asset, tmp_path / "project", preview_only=True)

    recorded = next(
        item for item in page._current_patch()["fact_confirmations"]
        if item["fact_key"] == "measurement_type"
    )

    assert recorded["status"] == "not_confirmed"
    assert {item["fact_value"] for item in recorded["evidence"]} == {"TPM", "FPKM"}
    page.close()
    application.processEvents()


def test_project_records_redact_marked_input_paths(tmp_path: Path) -> None:
    source_dir = tmp_path / "patient_009"
    source_dir.mkdir()
    source = source_dir / "expression.tsv"
    source.write_text(
        "feature_id\tcontrol_1\tcontrol_2\tcontrol_3\tcase_1\tcase_2\tcase_3\n"
        "gene_a\t1\t2\t1\t3\t4\t3\n"
        "gene_b\t2\t1\t2\t4\t3\t4\n"
        "gene_c\t3\t2\t4\t5\t6\t5\n"
        "gene_d\t4\t5\t4\t7\t8\t7\n",
        encoding="utf-8",
    )
    asset = AssetScanner().scan((source,)).assets[0]
    preparation = PreparationService()
    session = preparation.start(asset, source_dir / "analysis-project", preview_only=True)
    session = preparation.apply(session, {
        "header_row": 0,
        "data_start_row": 1,
        "feature_id_column": 0,
        "sample_columns": [1, 2, 3, 4, 5, 6],
        "annotation_columns": [],
        "ignored_columns": [],
        "measurement_type": MeasurementType.RAW_COUNT,
        "value_scale": ValueScale.LINEAR,
    })
    session = preparation.complete_read(session)
    summary = preparation.validate(session)
    assert summary.passed, [issue.message_zh for issue in summary.issues]
    preparation.finish(session, summary=summary)

    recipe = json.loads((session.project_dir / "preparation-recipe.json").read_text(encoding="utf-8"))
    project = json.loads((session.project_dir / "project.json").read_text(encoding="utf-8"))

    assert recipe["source_path_redacted"]
    assert "patient_009" not in str(recipe)
    assert project["source_path_redacted"]
    assert "patient_009" not in str(project)
