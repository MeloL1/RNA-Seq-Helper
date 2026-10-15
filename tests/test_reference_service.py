from pathlib import Path

from rnaseq_helper.domain.models import ReferenceRequest, ReferenceStatus
from rnaseq_helper.services.reference_service import ReferenceService


def test_local_reference_preserves_ambiguous_mapping_without_copying_rows(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "annot.tsv"
    source.write_text("probe_id\tgene_symbol\nP1\tGENE1\nP2\tGENE2\nP2\tGENE2_ALT\n", encoding="utf-8")
    monkeypatch.setattr(ReferenceService, "CACHE_DIR", tmp_path / "cache")
    result = ReferenceService().resolve(ReferenceRequest(("P1", "P2", "P3"), source_paths=(source,)))
    assert result.status == ReferenceStatus.PARTIAL
    assert result.mapping["P2"] == ("GENE2", "GENE2_ALT")
    assert result.ambiguous_count == 1
    assert result.unmapped_count == 1
    assert result.coverage == 2 / 3


def test_text_reference_named_xls_is_read_as_delimited_text(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "gene.TPM.matrix.annotation.xls"
    source.write_text(
        "Gene id\tGene name\tDZ_1\n"
        "ENSMUSG00000000001\tGnai3\t1.0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ReferenceService, "CACHE_DIR", tmp_path / "cache")
    result = ReferenceService().resolve(
        ReferenceRequest(("ENSMUSG00000000001",), source_paths=(source,))
    )
    assert result.status == ReferenceStatus.READY
    assert result.mapping["ENSMUSG00000000001"] == ("Gnai3",)


def test_reference_failure_keeps_original_ids_usable(tmp_path: Path) -> None:
    result = ReferenceService().resolve(ReferenceRequest(("ENSG000001",), source_paths=(tmp_path / "missing.tsv",)))
    assert result.status == ReferenceStatus.UNAVAILABLE
    assert result.unmapped_count == 1


def test_malformed_reference_degrades_without_raising(tmp_path: Path) -> None:
    source = tmp_path / "broken.tsv"
    source.write_bytes(b"probe_id\tgene_symbol\n\xff\tGENE\n")
    result = ReferenceService().resolve(ReferenceRequest(("P1",), source_paths=(source,)))
    assert result.status == ReferenceStatus.UNAVAILABLE
    assert result.unmapped_count == 1
    assert "读取失败" in result.guide_zh


def test_offline_orgdb_is_used_when_local_reference_is_omitted(tmp_path: Path, monkeypatch) -> None:
    class FakeResponse:
        result = {
            "mapping": {"ENSG000001": ["GENE1"], "ENSG000002": ["GENE2", "GENE2_ALT"]},
            "package": "org.Hs.eg.db",
            "release": "test-release",
        }

    class FakeBridge:
        def run(self, method, payload, context, profile_id):
            assert method == "reference_orgdb"
            assert payload["species_taxid"] == "9606"
            assert payload["id_type"] == "ENSEMBL_GENE"
            return FakeResponse()

    result = ReferenceService(bridge=FakeBridge()).resolve(
        ReferenceRequest(("ENSG000001", "ENSG000002", "ENSG000003"), species_taxid="9606")
    )
    assert result.provider == "offline_orgdb"
    assert result.status == ReferenceStatus.PARTIAL
    assert result.mapping["ENSG000002"] == ("GENE2", "GENE2_ALT")
    assert result.unmapped_count == 1
