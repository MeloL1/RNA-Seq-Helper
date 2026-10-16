from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

from rnaseq_helper.domain.models import MeasurementType, ValueScale
from tests._planning import PlanningService
from rnaseq_helper.preparation.service import PreparationService
from rnaseq_helper.recognition.scanner import AssetScanner


def _session(tmp_path: Path, series_type: str | None, measurement: MeasurementType):
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "series_matrix.txt"
    metadata = "!Sample_platform_id\tGPL96\tGPL96\tGPL96\tGPL96\tGPL96\tGPL96\n"
    if series_type:
        metadata += f"!Series_type\t\"{series_type}\"\n"
    source.write_text(
        metadata
        + "!series_matrix_table_begin\n"
        + "ID_REF\tGSM1\tGSM2\tGSM3\tGSM4\tGSM5\tGSM6\n"
        + "probe_a\t1.1\t2.1\t3.1\t1.4\t2.4\t3.4\n"
        + "probe_b\t2.2\t3.2\t4.2\t2.5\t3.5\t4.5\n"
        + "probe_c\t3.3\t4.3\t5.3\t3.6\t4.6\t5.6\n"
        + "probe_d\t4.4\t5.4\t6.4\t4.7\t5.7\t6.7\n"
        + "!series_matrix_table_end\n",
        encoding="utf-8",
    )
    asset = AssetScanner().scan((source,)).assets[0]
    service = PreparationService()
    session = service.start(asset, tmp_path / "project")
    session = service.apply(session, {
        "header_row": 0,
        "data_start_row": 1,
        "feature_id_column": 0,
        "sample_columns": [1, 2, 3, 4, 5, 6],
        "measurement_type": measurement,
        "value_scale": ValueScale.LINEAR,
    })
    return asset, service, session


def test_geo_array_series_type_is_visible_as_source_modality(tmp_path: Path) -> None:
    asset, _service, _session_value = _session(
        tmp_path, "Expression profiling by array", MeasurementType.FPKM,
    )

    modality = next(item for item in asset.evidence if item.fact_key == "source_modality")
    assert modality.fact_value == "MICROARRAY"
    assert modality.location == "!Series_type"
    assert "不能确定矩阵单位或 log 公式" in modality.basis


def test_geo_array_rejects_rnaseq_units_but_accepts_generic_expression_signal(tmp_path: Path) -> None:
    _asset, service, fpkm_session = _session(
        tmp_path / "fpkm", "Expression profiling by array", MeasurementType.FPKM,
    )
    fpkm_summary = service.validate(fpkm_session)
    assert not fpkm_summary.passed
    assert "GEO_ARRAY_MEASUREMENT_CONFLICT" in {issue.code for issue in fpkm_summary.issues}

    _asset, service, signal_session = _session(
        tmp_path / "signal", "Expression profiling by array", MeasurementType.OTHER_NORMALIZED,
    )
    signal_summary = service.validate(signal_session)
    assert signal_summary.passed, [issue.message_zh for issue in signal_summary.issues]

    signal_matrix = service.finish(signal_session, summary=signal_summary)
    plan = PlanningService().build(signal_matrix, {
        "GSM1": "control", "GSM2": "control", "GSM3": "control",
        "GSM4": "test", "GSM5": "test", "GSM6": "test",
    })
    assert signal_matrix.source_modality == "MICROARRAY"
    manifest = json.loads((tmp_path / "signal" / "project" / "project.json").read_text(encoding="utf-8"))
    assert manifest["source_modality"] == "MICROARRAY"
    assert manifest["series_types"] == ["Expression profiling by array"]
    assert plan.method == "BLOCKED"
    assert "MICROARRAY_REQUIRES_LOG2" in {issue.code for issue in plan.blockers}

    confirmed_log_matrix = replace(
        signal_matrix,
        value_scale=ValueScale.LOG2,
        input_transform="already_log2",
        measurement_provenance="user-confirmed value_scale=log2",
    )
    log_plan = PlanningService().build(confirmed_log_matrix, {
        "GSM1": "control", "GSM2": "control", "GSM3": "control",
        "GSM4": "test", "GSM5": "test", "GSM6": "test",
    })
    assert log_plan.method == "LIMMA_ON_LOG_EXPRESSION"
    assert "MICROARRAY_REQUIRES_LOG2" not in {issue.code for issue in log_plan.blockers}


def test_analysis_planner_also_blocks_geo_array_fpkm_bypass(tmp_path: Path) -> None:
    _asset, service, session = _session(
        tmp_path, "Expression profiling by array", MeasurementType.OTHER_NORMALIZED,
    )
    summary = service.validate(session)
    matrix = service.finish(session, summary=summary)
    matrix = replace(matrix, measurement_type=MeasurementType.FPKM)
    plan = PlanningService().build(matrix, {
        "GSM1": "control", "GSM2": "control", "GSM3": "control",
        "GSM4": "test", "GSM5": "test", "GSM6": "test",
    })

    assert not plan.runnable
    assert "SOURCE_MODALITY_MEASUREMENT_CONFLICT" in {issue.code for issue in plan.blockers}
    assert plan.source_modality == "MICROARRAY"
    assert plan.as_dict()["source_modality"] == "MICROARRAY"


def test_geo_without_series_type_keeps_existing_unit_workflow(tmp_path: Path) -> None:
    _asset, service, session = _session(tmp_path, None, MeasurementType.FPKM)
    summary = service.validate(session)

    assert summary.passed
    assert "GEO_ARRAY_MEASUREMENT_CONFLICT" not in {issue.code for issue in summary.issues}
