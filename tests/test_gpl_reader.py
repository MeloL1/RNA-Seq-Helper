import gzip
from pathlib import Path

from rnaseq_helper.readers.gpl_reader import GPLAnnotationReader
from rnaseq_helper.recognition.scanner import AssetScanner


def test_gpl_soft_reader_preserves_one_to_many_symbols(tmp_path: Path) -> None:
    path = tmp_path / "GPL1.soft"
    path.write_text(
        "!Platform_geo_accession = GPL1\n"
        "!platform_table_begin\n"
        "ID\tGene Symbol\nP1\tGENE1\nP2\tGENE2 /// GENE2_ALT\n"
        "!platform_table_end\n",
        encoding="utf-8",
    )
    result = GPLAnnotationReader().read(path)
    assert result.platform_id == "GPL1"
    assert result.mapping["P2"] == ("GENE2", "GENE2_ALT")
    assert AssetScanner().scan((path,)).assets[0].kind == "REFERENCE"


def test_illumina_manifest_gzip_reader_maps_probe_id_to_symbol(tmp_path: Path) -> None:
    path = tmp_path / "GPL10558_HumanHT-12.txt.gz"
    content = (
        "? Illumina, Inc.\n"
        "[Heading]\n"
        "[Probes]\n"
        "Species\tSymbol\tProbe_Id\n"
        "Homo sapiens\tEEF1A1\tILMN_1343291\n"
        "Homo sapiens\t\tILMN_0000000\n"
        "[Controls]\n"
        "Control\tValue\n"
    ).encode("utf-8")
    path.write_bytes(gzip.compress(content))

    result = GPLAnnotationReader().read(path)

    assert result.mapping["ILMN_1343291"] == ("EEF1A1",)
    assert GPLAnnotationReader.looks_like(path)
