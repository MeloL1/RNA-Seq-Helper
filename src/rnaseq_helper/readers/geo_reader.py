from __future__ import annotations

import csv
import gzip
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .table_reader import RawTable


class GeoReadError(ValueError):
    pass


class GeoReadCancelled(RuntimeError):
    """用户在后台读取 GEO 文件期间请求停止。"""


@dataclass(frozen=True)
class GeoSeriesMatrix:
    path: Path
    sample_accessions: tuple[str, ...]
    platform_ids: tuple[str, ...]
    sample_titles: tuple[str, ...]
    raw_table: RawTable
    sample_metadata: dict[str, tuple[str, ...]] = field(default_factory=dict)
    series_types: tuple[str, ...] = ()
    series_processing: tuple[str, ...] = ()


class GeoSeriesMatrixReader:
    """读取用户提供的 Series Matrix 表段和样本注释，不负责联网下载。"""

    def read(
        self,
        path: Path,
        *,
        max_table_rows: int | None = None,
        max_table_columns: int | None = None,
        progress: Callable[[int], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> GeoSeriesMatrix:
        path = path.expanduser().resolve()
        sample_accessions: list[str] = []
        platform_ids: list[str] = []
        sample_titles: list[str] = []
        series_types: list[str] = []
        series_processing: list[str] = []
        sample_metadata: dict[str, list[str]] = {}
        table_rows: list[tuple[str, ...]] = []
        row_limit_reached = False
        columns_truncated = False
        in_table = False
        with _open_text(path) as handle:
            for line_number, line in enumerate(handle, start=1):
                if cancelled and cancelled():
                    raise GeoReadCancelled("已取消读取 GEO 表格")
                line = line.rstrip("\r\n")
                if line == "!series_matrix_table_begin":
                    in_table = True
                    continue
                if line == "!series_matrix_table_end":
                    in_table = False
                    continue
                if in_table:
                    if max_table_rows is not None and len(table_rows) >= max_table_rows:
                        row_limit_reached = True
                        if progress:
                            progress(len(table_rows))
                        break
                    row = tuple(next(csv.reader([line], delimiter="\t")))
                    if max_table_columns is not None and len(row) > max_table_columns:
                        columns_truncated = True
                    table_rows.append(row if max_table_columns is None else row[:max_table_columns])
                    if progress and len(table_rows) % 1000 == 0:
                        progress(len(table_rows))
                    continue
                if line.startswith("!Sample_geo_accession"):
                    sample_accessions.extend(_metadata_values(line))
                elif line.startswith("!Sample_platform_id"):
                    platform_ids.extend(_metadata_values(line))
                elif line.startswith("!Sample_title"):
                    sample_titles.extend(_metadata_values(line))
                elif line.startswith("!Series_type"):
                    series_types.extend(_metadata_values(line))
                elif line.split("\t", 1)[0].partition("=")[0].strip() == "!Series_data_processing":
                    series_processing.extend(_metadata_values(line))
                elif line.startswith("!Sample_"):
                    # GEO 官方文件通常使用制表符，部分导出器才使用等号；
                    # 不能用 partition("=") 处理前一种格式，否则整行会变成字段名。
                    key = line.split("\t", 1)[0] if "\t" in line else line.partition("=")[0]
                    field_name = key.strip()[len("!Sample_"):].strip().lower()
                    if field_name:
                        values = _metadata_values(line)
                        if field_name not in sample_metadata:
                            sample_metadata[field_name] = list(values)
                        elif len(sample_metadata[field_name]) == len(values):
                            sample_metadata[field_name] = [
                                f"{old}; {new}".strip("; ")
                                for old, new in zip(sample_metadata[field_name], values)
                            ]
                        else:
                            suffix = 2
                            candidate = f"{field_name}_{suffix}"
                            while candidate in sample_metadata:
                                suffix += 1
                                candidate = f"{field_name}_{suffix}"
                            sample_metadata[candidate] = list(values)
                elif progress and line_number % 1000 == 0:
                    progress(line_number)
        if not table_rows or len(table_rows) < 2:
            raise GeoReadError("GEO Series Matrix 缺少可读取的 table begin/end 表段")
        if len(platform_ids) > 1 and len(set(platform_ids)) > 1:
            raise GeoReadError("GEO 文件包含多个平台；请分别整理，不要混合平台")
        raw = RawTable(
            path, None, tuple(table_rows), len(table_rows),
            max(len(row) for row in table_rows), "utf-8", "\t",
            is_complete=not row_limit_reached and not columns_truncated,
        )
        return GeoSeriesMatrix(
            path, tuple(sample_accessions), tuple(platform_ids), tuple(sample_titles), raw,
            {key: tuple(values) for key, values in sample_metadata.items()}, tuple(series_types),
            tuple(series_processing),
        )

    @staticmethod
    def looks_like(path: Path) -> bool:
        # Excel 是二进制容器，不应被当作 UTF-8 文本尝试读取。这里保留
        # 防御性判断，因为该嗅探器也会被其他识别入口直接调用。
        if path.suffix.lower() in {".xls", ".xlsx", ".xlsm"}:
            return False
        try:
            with _open_text(path) as handle:
                scanned = 0
                scan_limit = 2 * 1024 * 1024
                while scanned < scan_limit:
                    line = handle.readline(min(65536, scan_limit - scanned))
                    if not line:
                        break
                    scanned += len(line.encode("utf-8", errors="ignore"))
                    if line.startswith("!series_matrix_table_begin"):
                        return True
                    if line.startswith("!series_matrix_table_end"):
                        break
                    if line.startswith("!Sample_geo_accession"):
                        return True
        except (OSError, UnicodeDecodeError):
            return False
        return False


def _metadata_values(line: str) -> list[str]:
    """解析 GEO 的重复行和单行多值两种元数据写法。"""

    if "\t" in line:
        fields = line.split("\t")
        return [value.strip().strip('"') for value in fields[1:] if value.strip()]
    if "=" in line:
        payload = line.split("=", 1)[1].strip()
        if '"' not in payload:
            return [payload] if payload else []
        try:
            return [value for value in shlex.split(payload) if value]
        except ValueError as exc:
            raise GeoReadError(f"GEO 样本元数据引号不完整：{exc}") from exc
    fields = line.split("\t")
    if len(fields) == 1:
        return []
    return [value.strip().strip('"') for value in fields[1:] if value.strip()]


def _open_text(path: Path):
    return gzip.open(path, "rt", encoding="utf-8", errors="strict") if path.suffix == ".gz" else path.open("r", encoding="utf-8")
