from __future__ import annotations

import csv
import gzip
from dataclasses import dataclass
from pathlib import Path


class GPLReadError(ValueError):
    pass


@dataclass(frozen=True)
class GPLAnnotation:
    path: Path
    platform_id: str | None
    mapping: dict[str, tuple[str, ...]]


class GPLAnnotationReader:
    """读取用户提供的 GPL/SOFT/annot 或 Illumina manifest；不负责联网获取参考。"""

    def read(self, path: Path) -> GPLAnnotation:
        path = path.expanduser().resolve()
        lines = self._read_lines(path)
        platform_id = next((line.split("=", 1)[1].strip() for line in lines if line.startswith("!Platform_geo_accession")), None)
        if any(line == "!platform_table_begin" for line in lines):
            table = self._table(lines)
        elif any(line.strip() == "[Probes]" for line in lines):
            table = self._illumina_probe_table(lines)
        else:
            table = [line.split("\t") for line in lines if line.strip()]
        if len(table) < 2:
            raise GPLReadError("GPL 注释表没有可读取的数据行")
        header = [value.strip().casefold() for value in table[0]]
        id_index = self._find(header, {"id", "id_ref", "probe_id", "probe set id", "ensembl"})
        symbol_index = self._find(header, {"gene symbol", "gene_symbol", "symbol", "gene"})
        if id_index is None or symbol_index is None:
            raise GPLReadError("GPL 注释表缺少编号列或 gene symbol 列")
        mapping: dict[str, list[str]] = {}
        for row in table[1:]:
            if max(id_index, symbol_index) >= len(row):
                continue
            feature_id = row[id_index].strip()
            symbols = [value.strip() for value in row[symbol_index].replace(" /// ", ";").split(";") if value.strip()]
            if feature_id and symbols:
                target = mapping.setdefault(feature_id, [])
                for symbol in symbols:
                    if symbol not in target:
                        target.append(symbol)
        return GPLAnnotation(path, platform_id, {key: tuple(value) for key, value in mapping.items()})

    @staticmethod
    def looks_like(path: Path) -> bool:
        try:
            sample = "\n".join(GPLAnnotationReader._read_lines(path)[:40])
        except OSError:
            return False
        lowered = sample.casefold()
        return (
            "!platform_table_begin" in lowered
            or "gene symbol" in lowered
            or "[probes]" in lowered and "probe_id" in lowered and "symbol" in lowered
        )

    @staticmethod
    def _read_lines(path: Path) -> list[str]:
        if path.suffix.lower() == ".gz":
            with gzip.open(path, "rt", encoding="utf-8", errors="strict") as handle:
                return handle.read().splitlines()
        return path.read_text(encoding="utf-8", errors="strict").splitlines()

    @staticmethod
    def _illumina_probe_table(lines: list[str]) -> list[list[str]]:
        """读取 Illumina BGX/manifest 的 [Probes] 制表符表段。"""

        try:
            start = next(index for index, line in enumerate(lines) if line.strip() == "[Probes]") + 1
        except StopIteration as exc:
            raise GPLReadError("Illumina 注释表缺少 [Probes] 表段") from exc
        table: list[list[str]] = []
        for line in lines[start:]:
            if not line.strip():
                continue
            if line.startswith("[") and line.rstrip() != "[Probes]":
                break
            table.append(next(csv.reader([line], delimiter="\t")))
        return table

    @staticmethod
    def _table(lines: list[str]) -> list[list[str]]:
        table: list[list[str]] = []
        active = False
        for line in lines:
            if line == "!platform_table_begin":
                active = True
                continue
            if line == "!platform_table_end":
                break
            if active:
                table.append(next(csv.reader([line], delimiter="\t")))
        return table

    @staticmethod
    def _find(header: list[str], names: set[str]) -> int | None:
        return next((index for index, value in enumerate(header) if value in names), None)
