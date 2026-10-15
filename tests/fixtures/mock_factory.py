"""为阶段验收生成确定性的本地合成数据，不下载或覆盖任何用户数据。"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
from openpyxl import Workbook


def write_geo_series_matrix(path: Path, *, feature_count: int = 2000, sample_count: int = 8, seed: int = 1208) -> Path:
    rng = np.random.default_rng(seed)
    sample_ids = [f"GSM{100000 + index}" for index in range(sample_count)]
    values = rng.normal(8.0, 0.65, size=(feature_count, sample_count))
    values[:200, sample_count // 2 :] += 1.2
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write("!Series_title = synthetic local acceptance fixture\n")
        for sample_id in sample_ids:
            handle.write(f"!Sample_geo_accession = {sample_id}\n")
        for index, sample_id in enumerate(sample_ids):
            group = "control" if index < sample_count // 2 else "treated"
            handle.write(f"!Sample_title = {group} replicate {index % (sample_count // 2) + 1}\n")
            handle.write("!Sample_platform_id = GPLSYNTH\n")
        handle.write("!series_matrix_table_begin\n")
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["ID_REF", *sample_ids])
        for index, row in enumerate(values, start=1):
            writer.writerow([f"probe_{index:05d}", *[f"{value:.8f}" for value in row]])
        handle.write("!series_matrix_table_end\n")
    return path


def write_company_counts(path: Path, *, feature_count: int = 3000, sample_count: int = 12, seed: int = 2212) -> Path:
    rng = np.random.default_rng(seed)
    half = sample_count // 2
    sample_ids = [f"Ctrl_{index + 1}" for index in range(half)] + [f"Treat_{index + 1}" for index in range(sample_count - half)]
    counts = rng.poisson(120, size=(feature_count, sample_count)).astype(int)
    counts[:300, half:] = rng.poisson(420, size=(300, sample_count - half))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["company export; synthetic acceptance fixture"])
        writer.writerow(["说明：第 4 行是表头，前两列为编号和展示名称"])
        writer.writerow(["请勿把说明行当成数据"])
        writer.writerow(["gene_id", "gene_symbol", *sample_ids])
        for index, row in enumerate(counts, start=1):
            writer.writerow([f"ENSGSYN{index:07d}", f"SYN{index:05d}", *row.tolist()])
    return path


def write_multi_sheet_workbook(path: Path) -> Path:
    """生成带说明表和表达矩阵表的本地 Excel 交互 fixture。"""
    workbook = Workbook()
    notes = workbook.active
    notes.title = "说明"
    notes.append(["这是交付说明，不是表达矩阵"])
    matrix = workbook.create_sheet("表达矩阵")
    matrix.append(["gene_id", "Ctrl_1", "Ctrl_2", "Treat_1", "Treat_2"])
    for index in range(1, 81):
        matrix.append([f"ENSGMOCK{index:06d}", 100 + index, 102 + index, 200 + index, 202 + index])
    workbook.save(path)
    workbook.close()
    return path


def write_tenx_bundle(directory: Path, *, feature_count: int = 1000, cell_count: int = 600, seed: int = 3600) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    entries: list[tuple[int, int, int]] = []
    for feature in range(1, feature_count + 1):
        for cell in rng.choice(cell_count, size=3, replace=False):
            entries.append((feature, int(cell) + 1, int(rng.integers(1, 40))))
    with (directory / "matrix.mtx").open("w", encoding="utf-8") as handle:
        handle.write("%%MatrixMarket matrix coordinate integer general\n")
        handle.write("% synthetic local acceptance fixture\n")
        handle.write(f"{feature_count} {cell_count} {len(entries)}\n")
        handle.writelines(f"{row} {column} {value}\n" for row, column, value in entries)
    (directory / "barcodes.tsv").write_text(
        "".join(f"cell_{index:04d}\n" for index in range(1, cell_count + 1)),
        encoding="utf-8",
    )
    with (directory / "features.tsv").open("w", encoding="utf-8") as handle:
        for index in range(1, feature_count + 1):
            feature_type = "Gene Expression" if index <= feature_count - 50 else "Antibody Capture"
            handle.write(f"feature_{index:05d}\tF{index:05d}\t{feature_type}\n")
    return directory


def regular_normalized_values(*, feature_count: int = 8000, sample_count: int = 12, seed: int = 4800) -> np.ndarray:
    rng = np.random.default_rng(seed)
    half = sample_count // 2
    values = rng.lognormal(mean=3.0, sigma=0.35, size=(feature_count, sample_count))
    values[:200, half:] *= 4.0
    return values


def low_precision_values(*, feature_count: int = 600, sample_count: int = 6) -> np.ndarray:
    return np.tile(np.asarray([1.0, 1.0, 1.0, 2.0, 2.0, 2.0]), (feature_count, sample_count // 6)) if sample_count == 6 else np.ones((feature_count, sample_count))
