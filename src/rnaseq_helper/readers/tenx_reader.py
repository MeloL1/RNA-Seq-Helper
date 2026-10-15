from __future__ import annotations

import gzip
import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


class TenXReadError(ValueError):
    pass


@dataclass(frozen=True)
class TenXBundle:
    directory: Path
    matrix_path: Path
    barcodes_path: Path
    features_path: Path
    rows: int
    columns: int
    nonzero_entries: int
    feature_types: tuple[str, ...]

    @property
    def is_complete(self) -> bool:
        return self.rows == self.feature_count and self.columns == self.barcode_count

    @property
    def feature_count(self) -> int:
        return sum(1 for _ in _open_text(self.features_path))

    @property
    def barcode_count(self) -> int:
        return sum(1 for _ in _open_text(self.barcodes_path))

    @property
    def gene_expression_rows(self) -> int:
        return sum(value.lower() in {"gene expression", "gene_expression", "gene"} for value in self.feature_types)

    @property
    def feature_type_counts(self) -> dict[str, int]:
        return dict(Counter(self.feature_types))

    def as_dict(self) -> dict[str, object]:
        return {
            "observation_unit": "CELL",
            "storage": "sparse-matrix-market",
            "source_directory": str(self.directory),
            "source_paths": [str(self.matrix_path), str(self.barcodes_path), str(self.features_path)],
            "dimensions": {"features": self.rows, "cells": self.columns},
            "nonzero_entries": self.nonzero_entries,
            "sparsity": 1.0 - (self.nonzero_entries / max(1, self.rows * self.columns)),
            "feature_type_counts": self.feature_type_counts,
            "file_sha256": {
                str(path.name): _sha256(path)
                for path in (self.matrix_path, self.barcodes_path, self.features_path)
            },
            "bulk_analysis_allowed": False,
        }

    def write_manifest(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path


class TenXReader:
    """只做 10x 三件套完整性检查和稀疏元信息读取，不把细胞稠密化。"""

    MATRIX_NAMES = ("matrix.mtx", "matrix.mtx.gz")
    BARCODE_NAMES = ("barcodes.tsv", "barcodes.tsv.gz")
    FEATURE_NAMES = ("features.tsv", "features.tsv.gz", "genes.tsv", "genes.tsv.gz")

    def find_bundle(self, directory: Path) -> TenXBundle:
        directory = directory.expanduser().resolve()
        matrix = self._find(directory, self.MATRIX_NAMES)
        barcodes = self._find(directory, self.BARCODE_NAMES)
        features = self._find(directory, self.FEATURE_NAMES)
        if not all((matrix, barcodes, features)):
            raise TenXReadError("10x 三件套不完整；需要 matrix.mtx、barcodes.tsv 和 features.tsv/genes.tsv")
        rows, columns, nonzero = self._matrix_header(matrix)
        self._validate_sparse_entries(matrix, rows, columns, nonzero)
        feature_types = tuple(self._feature_types(features))
        bundle = TenXBundle(directory, matrix, barcodes, features, rows, columns, nonzero, feature_types)
        if not bundle.is_complete:
            raise TenXReadError(
                f"10x 维度不一致：matrix 为 {rows}×{columns}，"
                f"features={bundle.feature_count}，barcodes={bundle.barcode_count}"
            )
        return bundle

    @staticmethod
    def _find(directory: Path, names: tuple[str, ...]) -> Path | None:
        for name in names:
            candidate = directory / name
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _matrix_header(path: Path) -> tuple[int, int, int]:
        with _open_text(path) as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("%"):
                    continue
                parts = line.split()
                if len(parts) != 3:
                    raise TenXReadError("Matrix Market 维度行格式错误")
                return int(parts[0]), int(parts[1]), int(parts[2])
        raise TenXReadError("Matrix Market 文件没有维度行")

    @staticmethod
    def _validate_sparse_entries(path: Path, rows: int, columns: int, expected_nonzero: int) -> None:
        """逐条检查坐标边界和条目数量；只流式读取，不创建稠密矩阵。"""

        observed = 0
        dimensions_seen = False
        with _open_text(path) as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("%"):
                    continue
                if not dimensions_seen:
                    dimensions_seen = True
                    continue
                fields = line.split()
                if len(fields) != 3:
                    raise TenXReadError("Matrix Market 稀疏条目格式错误；每行应为行号、列号和值")
                try:
                    row_index = int(fields[0])
                    column_index = int(fields[1])
                    value = float(fields[2])
                except ValueError as exc:
                    raise TenXReadError("Matrix Market 稀疏条目包含无法解析的数字") from exc
                if not (1 <= row_index <= rows and 1 <= column_index <= columns):
                    raise TenXReadError("Matrix Market 稀疏坐标超出矩阵维度")
                if not math.isfinite(value):
                    raise TenXReadError("Matrix Market 稀疏条目包含 Inf/NaN")
                observed += 1
        if not dimensions_seen:
            raise TenXReadError("Matrix Market 文件没有维度行")
        if observed != expected_nonzero:
            raise TenXReadError(
                f"Matrix Market 非零条目数量不一致：维度行声明 {expected_nonzero}，实际读取 {observed}"
            )

    @staticmethod
    def _feature_types(path: Path) -> list[str]:
        types: list[str] = []
        with _open_text(path) as handle:
            for line in handle:
                fields = line.rstrip("\n").split("\t")
                types.append(fields[2] if len(fields) >= 3 else "Gene Expression")
        return types


def _open_text(path: Path):
    return gzip.open(path, "rt", encoding="utf-8") if path.suffix == ".gz" else path.open("r", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
