from __future__ import annotations

from pathlib import Path
import gzip

from rnaseq_helper.readers.geo_reader import GeoSeriesMatrixReader
from rnaseq_helper.recognition.scanner import AssetScanner


def test_geo_series_matrix_reads_table_and_metadata(tmp_path: Path) -> None:
    path = tmp_path / "GSE999_series_matrix.txt"
    path.write_text(
        "!Sample_geo_accession = GSM1\n"
        "!Sample_geo_accession = GSM2\n"
        "!Sample_title = control replicate 1\n"
        "!Sample_title = treatment replicate 1\n"
        "!Sample_platform_id = GPL111\n"
        "!Sample_platform_id = GPL111\n"
        "!Series_type\t\"Expression profiling by array\"\n"
        "!series_matrix_table_begin\n"
        "ID_REF\tGSM1\tGSM2\n"
        "probe_1\t1.0\t2.0\n"
        "probe_2\t3.0\t4.0\n"
        "!series_matrix_table_end\n",
        encoding="utf-8",
    )
    result = GeoSeriesMatrixReader().read(path)
    assert result.sample_accessions == ("GSM1", "GSM2")
    assert result.platform_ids == ("GPL111", "GPL111")
    assert result.sample_titles == ("control replicate 1", "treatment replicate 1")
    assert result.series_types == ("Expression profiling by array",)
    assert result.raw_table.rows[0] == ("ID_REF", "GSM1", "GSM2")
    assets = AssetScanner().scan((path,)).assets
    assert assets[0].kind == "GEO_SERIES_MATRIX"


def test_geo_reader_preserves_series_and_sample_processing_statements(tmp_path: Path) -> None:
    path = tmp_path / "processing_series_matrix.txt"
    path.write_text(
        '!Series_data_processing\t"Normalized to the 75th percentile; baseline transformed using the global median."\n'
        '!Sample_data_processing\t"GCRMA"\t"GCRMA"\n'
        "!series_matrix_table_begin\nID_REF\tGSM1\tGSM2\nprobe_1\t1\t2\n!series_matrix_table_end\n",
        encoding="utf-8",
    )

    result = GeoSeriesMatrixReader().read(path)

    assert result.series_processing == (
        "Normalized to the 75th percentile; baseline transformed using the global median.",
    )
    assert result.sample_metadata["data_processing"] == ("GCRMA", "GCRMA")


def test_geo_processing_evidence_redacts_possible_patient_identifiers(tmp_path: Path) -> None:
    path = tmp_path / "GSE999_processing_series_matrix.txt"
    path.write_text(
        '!Sample_data_processing\t"Processing performed for patient 17"\t"Processing performed for patient 18"\n'
        "!series_matrix_table_begin\nID_REF\tGSM1\tGSM2\nprobe_1\t1\t2\n!series_matrix_table_end\n",
        encoding="utf-8",
    )

    asset = AssetScanner().scan((path,)).assets[0]
    processing_evidence = [item for item in asset.evidence if item.evidence_level == "geo_processing_context"]

    assert len(processing_evidence) == 2
    assert all(item.excerpt_redacted for item in processing_evidence)
    assert all("patient 17" not in item.excerpt and "patient 18" not in item.excerpt for item in processing_evidence)


def test_geo_processing_evidence_maps_sample_statements_and_suffixed_fields(tmp_path: Path) -> None:
    path = tmp_path / "GSE999_processing_series_matrix.txt"
    path.write_text(
        '!Sample_geo_accession\t"GSM1"\t"GSM2"\n'
        '!Sample_data_processing\t"GCRMA"\t"RMA"\n'
        '!Sample_data_processing_2\t"Background corrected"\t"Background corrected"\n'
        '!Series_data_processing_extra\t"not the exact series field"\n'
        "!series_matrix_table_begin\nID_REF\tGSM1\tGSM2\nprobe_1\t1\t2\n!series_matrix_table_end\n",
        encoding="utf-8",
    )

    result = GeoSeriesMatrixReader().read(path)
    evidence = [
        item for item in AssetScanner().scan((path,)).assets[0].evidence
        if item.evidence_level == "geo_processing_context"
    ]

    assert result.sample_metadata["data_processing_2"] == ("Background corrected", "Background corrected")
    assert any(item.location == "!Sample_data_processing_2" for item in evidence)
    assert any("对应样本：GSM1" in item.basis for item in evidence)
    assert all("not the exact series field" not in item.excerpt for item in evidence)


def test_geo_processing_evidence_reports_omitted_statements(tmp_path: Path) -> None:
    path = tmp_path / "GSE999_processing_series_matrix.txt"
    statements = "".join(f'!Series_data_processing\t"step {index}"\n' for index in range(6))
    path.write_text(
        statements + "!series_matrix_table_begin\nID_REF\tGSM1\nprobe_1\t1\n!series_matrix_table_end\n",
        encoding="utf-8",
    )

    evidence = [
        item for item in AssetScanner().scan((path,)).assets[0].evidence
        if item.evidence_level == "geo_processing_context"
    ]

    assert any("另有 2 条不同的 GEO 处理说明未展开" in item.basis for item in evidence)


def test_geo_reader_rejects_mixed_platforms(tmp_path: Path) -> None:
    path = tmp_path / "series_matrix.txt"
    path.write_text(
        "!Sample_platform_id = GPL1\n!Sample_platform_id = GPL2\n"
        "!series_matrix_table_begin\nID_REF\tA\tB\nx\t1\t2\n!series_matrix_table_end\n",
        encoding="utf-8",
    )
    try:
        GeoSeriesMatrixReader().read(path)
    except ValueError as exc:
        assert "多个平台" in str(exc)
    else:
        raise AssertionError("mixed GEO platforms should be blocked")


def test_geo_reader_parses_single_line_quoted_metadata(tmp_path: Path) -> None:
    path = tmp_path / "quoted_series_matrix.txt"
    path.write_text(
        '!Sample_geo_accession = "GSM10" "GSM11"\n'
        '!Sample_title = "control replicate" "treatment replicate"\n'
        '!Sample_platform_id = "GPL1" "GPL1"\n'
        '!series_matrix_table_begin\n'
        'ID_REF\tGSM10\tGSM11\nprobe1\t1\t2\n'
        '!series_matrix_table_end\n',
        encoding="utf-8",
    )
    result = GeoSeriesMatrixReader().read(path)
    assert result.sample_accessions == ("GSM10", "GSM11")
    assert result.sample_titles == ("control replicate", "treatment replicate")
    assert result.platform_ids == ("GPL1", "GPL1")


def test_scanner_recognizes_gzipped_geo_series_matrix(tmp_path: Path) -> None:
    path = tmp_path / "GSE1_series_matrix.txt.gz"
    content = "!Sample_geo_accession = GSM1\n!Sample_platform_id = GPL111\n!series_matrix_table_begin\nID_REF\tGSM1\nprobe1\t1.0\n!series_matrix_table_end\n"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(content)
    from rnaseq_helper.recognition.scanner import AssetScanner

    assets = AssetScanner().scan((path,)).assets
    assert assets[0].kind == "GEO_SERIES_MATRIX"


def test_gzipped_geo_can_enter_preparation(tmp_path: Path) -> None:
    path = tmp_path / "GSE1_series_matrix.txt.gz"
    content = "!Sample_geo_accession = GSM1\n!Sample_platform_id = GPL111\n!series_matrix_table_begin\nID_REF\tGSM1\nprobe1\t1.0\n!series_matrix_table_end\n"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(content)
    from rnaseq_helper.domain.models import MeasurementType, ValueScale
    from rnaseq_helper.preparation.service import PreparationService

    asset = AssetScanner().scan((path,)).assets[0]
    service = PreparationService()
    session = service.start(asset, tmp_path / "project")
    session = service.apply(session, {"measurement_type": MeasurementType.TPM, "value_scale": ValueScale.LOG2})
    assert service.validate(session).passed


def test_geo_metadata_is_preserved_in_prepared_project(tmp_path: Path) -> None:
    path = tmp_path / "GSE1_series_matrix.txt"
    path.write_text(
        "!Sample_geo_accession = GSM1\n"
        "!Sample_geo_accession = GSM2\n"
        "!Sample_title = control replicate 1\n"
        "!Sample_title = treatment replicate 1\n"
        "!Sample_platform_id = GPL111\n"
        "!Sample_platform_id = GPL111\n"
        '!Sample_data_processing\t"GCRMA"\t"GCRMA"\n'
        "!series_matrix_table_begin\n"
        "ID_REF\tGSM1\tGSM2\n"
        "probe1\t1.0\t2.0\n"
        "probe2\t3.0\t4.0\n"
        "!series_matrix_table_end\n",
        encoding="utf-8",
    )
    from rnaseq_helper.domain.models import MeasurementType, ValueScale
    from rnaseq_helper.preparation.service import PreparationService

    asset = AssetScanner().scan((path,)).assets[0]
    service = PreparationService()
    session = service.start(asset, tmp_path / "project")
    session = service.apply(session, {"measurement_type": MeasurementType.TPM, "value_scale": ValueScale.LOG2})
    matrix = service.finish(session)
    sample_metadata = (tmp_path / "project" / "prepared" / "sample_metadata.tsv").read_text(encoding="utf-8")
    assert sample_metadata.splitlines()[0] == (
        "sample_id\tgeo_accession\tsample_title\tplatform_id\tdata_processing"
    )
    assert matrix.sample_metadata.shape == (2, 5)
    assert "GSM1\tcontrol replicate 1" in sample_metadata
    assert "GCRMA" in sample_metadata
    assert "GPL111" in sample_metadata
    assert matrix.platform_id == "GPL111"
