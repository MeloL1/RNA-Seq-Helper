from __future__ import annotations

import io
import gzip
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

from rnaseq_helper.recognition.scanner import AssetScanner
from rnaseq_helper.readers.tenx_reader import TenXReader
from rnaseq_helper.services.archive_service import ArchiveLimits, ArchiveSafetyError, ArchiveService


def _write_tenx(directory: Path) -> None:
    directory.mkdir()
    (directory / "matrix.mtx").write_text(
        "%%MatrixMarket matrix coordinate integer general\n"
        "% comment\n4 3 5\n1 1 3\n2 1 2\n1 2 4\n3 3 1\n4 3 9\n",
        encoding="utf-8",
    )
    (directory / "barcodes.tsv").write_text("cell1\ncell2\ncell3\n", encoding="utf-8")
    (directory / "features.tsv").write_text(
        "gene1\tG1\tGene Expression\n"
        "gene2\tG2\tGene Expression\n"
        "gene3\tG3\tAntibody Capture\n"
        "gene4\tG4\tGene Expression\n",
        encoding="utf-8",
    )


def test_tenx_reader_keeps_sparse_metadata_only(tmp_path: Path) -> None:
    directory = tmp_path / "filtered_feature_bc_matrix"
    _write_tenx(directory)
    bundle = TenXReader().find_bundle(directory)
    assert bundle.is_complete
    assert bundle.rows == 4 and bundle.columns == 3 and bundle.nonzero_entries == 5
    assert bundle.gene_expression_rows == 3
    assert bundle.feature_type_counts == {"Gene Expression": 3, "Antibody Capture": 1}
    assets = AssetScanner().scan((directory,)).assets
    assert any(asset.kind == "TENX" and asset.observation_unit_hint == "CELL" for asset in assets)


def test_tenx_reader_writes_auditable_sparse_manifest(tmp_path: Path) -> None:
    directory = tmp_path / "filtered_feature_bc_matrix"
    _write_tenx(directory)
    bundle = TenXReader().find_bundle(directory)
    manifest_path = bundle.write_manifest(tmp_path / "project" / "tenx-manifest.json")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["storage"] == "sparse-matrix-market"
    assert payload["dimensions"] == {"features": 4, "cells": 3}
    assert payload["nonzero_entries"] == 5
    assert payload["bulk_analysis_allowed"] is False
    assert set(payload["file_sha256"]) == {"matrix.mtx", "barcodes.tsv", "features.tsv"}


def test_tenx_reader_blocks_dimension_mismatch(tmp_path: Path) -> None:
    directory = tmp_path / "bad"
    _write_tenx(directory)
    (directory / "barcodes.tsv").write_text("cell1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="维度不一致"):
        TenXReader().find_bundle(directory)


def test_tenx_reader_validates_sparse_entries_without_densifying(tmp_path: Path) -> None:
    directory = tmp_path / "bad_entries"
    _write_tenx(directory)
    (directory / "matrix.mtx").write_text(
        "%%MatrixMarket matrix coordinate integer general\n"
        "4 3 5\n1 1 3\n2 1 2\n1 2 4\n3 3 1\n5 3 9\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="超出矩阵维度"):
        TenXReader().find_bundle(directory)

    (directory / "matrix.mtx").write_text(
        "%%MatrixMarket matrix coordinate integer general\n"
        "4 3 6\n1 1 3\n2 1 2\n1 2 4\n3 3 1\n4 3 9\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="数量不一致"):
        TenXReader().find_bundle(directory)


def test_archive_service_extracts_only_inside_target(tmp_path: Path) -> None:
    archive_path = tmp_path / "safe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("matrix/data.tsv", "a\tb\n")
    manifest = ArchiveService().inspect(archive_path)
    output = tmp_path / "project" / "extracted"
    paths = ArchiveService().extract(manifest, output)
    assert paths == (output / "matrix" / "data.tsv",)
    assert (output / "matrix" / "data.tsv").read_text(encoding="utf-8") == "a\tb\n"


def test_archive_service_safely_expands_single_gzip_table_and_scans_it(tmp_path: Path) -> None:
    compressed = tmp_path / "expression.csv.gz"
    with gzip.open(compressed, "wt", encoding="utf-8", newline="") as handle:
        handle.write("feature,S1,S2\nG1,4,7\nG2,0,2\n")

    service = ArchiveService()
    manifest = service.inspect(compressed)
    assert manifest.archive_type == "gzip"
    assert manifest.safe
    assert [(item.name, item.size) for item in manifest.members] == [
        ("expression.csv", len(b"feature,S1,S2\nG1,4,7\nG2,0,2\n")),
    ]

    output = tmp_path / "project" / "input"
    extracted = service.extract(manifest, output)
    assert extracted == (output / "expression.csv",)
    assert extracted[0].read_text(encoding="utf-8") == "feature,S1,S2\nG1,4,7\nG2,0,2\n"
    asset = AssetScanner().scan(extracted).assets[0]
    assert asset.kind == "TABLE"
    assert asset.role == "EXPRESSION_CANDIDATE"


def test_archive_service_rejects_gzip_expansion_limit_and_corruption(tmp_path: Path) -> None:
    compressed = tmp_path / "large.tsv.gz"
    compressed.write_bytes(gzip.compress(b"x" * 4096))
    with pytest.raises(ArchiveSafetyError, match="压缩比异常"):
        ArchiveService().inspect(compressed, ArchiveLimits(max_compression_ratio=2))
    with pytest.raises(ArchiveSafetyError, match="过大"):
        ArchiveService().inspect(compressed, ArchiveLimits(max_member_bytes=1024))

    damaged = tmp_path / "damaged.tsv.gz"
    damaged.write_bytes(b"not a gzip stream")
    with pytest.raises(ArchiveSafetyError, match="gzip 文件损坏"):
        ArchiveService().inspect(damaged)

    unnamed = tmp_path / ".gz"
    unnamed.write_bytes(gzip.compress(b"table"))
    with pytest.raises(ArchiveSafetyError, match="缺少解压后的文件名"):
        ArchiveService().inspect(unnamed)


def test_archive_service_recursively_extracts_nested_archives(tmp_path: Path) -> None:
    nested_path = tmp_path / "nested.zip"
    with zipfile.ZipFile(nested_path, "w") as nested:
        nested.writestr("expression.tsv", "feature\tS1\nG1\t1\n")
    outer_path = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer_path, "w") as outer:
        outer.write(nested_path, "container/nested.zip")
    manifest = ArchiveService().inspect(outer_path)
    output = tmp_path / "recursive"
    paths = ArchiveService().extract_recursive(manifest, output)
    assert output / "container" / "nested.zip" in paths
    assert output / "container" / ".nested.zip.expanded" / "expression.tsv" in paths


def test_archive_service_rejects_path_escape(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../outside.txt", "do not extract")
    with pytest.raises(ArchiveSafetyError, match="逃逸"):
        ArchiveService().inspect(archive_path)


def test_archive_service_rejects_zip_symlink(tmp_path: Path) -> None:
    archive_path = tmp_path / "link.zip"
    info = zipfile.ZipInfo("link.txt")
    info.create_system = 3
    info.external_attr = 0o120777 << 16
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(info, "outside.txt")
    with pytest.raises(ArchiveSafetyError, match="符号链接"):
        ArchiveService().inspect(archive_path)


def test_archive_service_rejects_tar_special_file(tmp_path: Path) -> None:
    archive_path = tmp_path / "special.tar"
    with tarfile.open(archive_path, "w") as archive:
        member = tarfile.TarInfo("device")
        member.type = tarfile.CHRTYPE
        member.devmajor = 1
        member.devminor = 3
        archive.addfile(member)
    with pytest.raises(ArchiveSafetyError, match="非普通文件"):
        ArchiveService().inspect(archive_path)


def test_archive_service_applies_overall_tar_compression_limit(tmp_path: Path) -> None:
    archive_path = tmp_path / "compressed.tar"
    with tarfile.open(archive_path, "w") as archive:
        payload = b"x" * 1000
        member = tarfile.TarInfo("data.txt")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    with pytest.raises(ArchiveSafetyError, match="压缩比异常"):
        ArchiveService().inspect(archive_path, ArchiveLimits(max_compression_ratio=0.01))
