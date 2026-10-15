from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable
from uuid import uuid4

from rnaseq_helper.domain.models import (
    DataAsset, Evidence, Issue, IssueSeverity, MeasurementType, ValueScale,
    may_contain_sensitive_metadata,
)
from rnaseq_helper.readers.table_reader import TableReader
from rnaseq_helper.readers.tenx_reader import TenXReader, TenXReadError
from rnaseq_helper.readers.geo_reader import GeoReadCancelled, GeoSeriesMatrixReader
from rnaseq_helper.readers.gpl_reader import GPLAnnotationReader


@dataclass(frozen=True)
class ScanProgress:
    phase: str
    completed: int
    total: int | None
    path: Path | None = None


@dataclass(frozen=True)
class ScanResult:
    assets: tuple[DataAsset, ...]
    issues: tuple[Issue, ...] = ()
    cancelled: bool = False


class AssetScanner:
    SUPPORTED_TABLES = TableReader.TEXT_SUFFIXES | TableReader.EXCEL_SUFFIXES
    PREVIEW_ROWS = 40
    PREVIEW_COLUMNS = 80
    SIDECAR_MAX_BYTES = 256 * 1024
    SIDECAR_TOTAL_MAX_BYTES = 512 * 1024
    SIDECAR_MAX_FILES = 4
    SIDECAR_NAME_MARKERS = (
        "readme", "read_me", "说明", "交付", "delivery", "data_dictionary", "metadata", "method", "处理",
    )
    MEASUREMENT_PATTERNS = (
        (MeasurementType.RAW_COUNT, re.compile(
            r"(?<![a-z0-9])(?:raw[\s_-]*counts?|gene[\s_-]*counts?|read[\s_-]*counts?)(?![a-z0-9])|原始\s*count|原始计数|基因计数|读段计数",
            re.IGNORECASE,
        ), "原始 count"),
        (MeasurementType.TPM, re.compile(r"(?<![a-z0-9])tpm(?![a-z0-9])", re.IGNORECASE), "TPM"),
        (MeasurementType.FPKM, re.compile(r"(?<![a-z0-9])fpkm(?![a-z0-9])", re.IGNORECASE), "FPKM"),
        (MeasurementType.RPKM, re.compile(r"(?<![a-z0-9])rpkm(?![a-z0-9])", re.IGNORECASE), "RPKM"),
        (MeasurementType.CPM, re.compile(r"(?<![a-z0-9])cpm(?![a-z0-9])", re.IGNORECASE), "CPM"),
        (MeasurementType.OTHER_NORMALIZED, re.compile(
            r"(?<![a-z0-9])(?:normalized|normalised)\s+expression|"
            r"(?:probe|signal)\s+intensit(?:y|ies)|芯片信号|探针信号",
            re.IGNORECASE,
        ), "其他标准化表达值"),
    )
    SCALE_PATTERNS = (
        (ValueScale.LOG2, re.compile(
            r"(?<![a-z0-9])log\s*_?\s*2(?![a-z0-9])|log₂|log\s+base\s+2|以\s*2\s*为底|对数底数\s*2",
            re.IGNORECASE,
        ), "log2"),
        (ValueScale.OTHER_TRANSFORM, re.compile(
            r"(?<![a-z0-9])(?:ln|log\s*_?\s*10|z[\s_-]*scores?|residuals?)(?![a-z0-9])|"
            r"自然对数|残差|z\s*分数|其他变换",
            re.IGNORECASE,
        ), "其他变换（如 ln、log10、z-score 或残差）"),
        (ValueScale.LINEAR, re.compile(
            r"(?<![a-z0-9])(?:linear\s+scale|untransformed|not\s+(?:log(?:arithmic)?(?:\s*[- ]?transformed)?|transformed)|without\s+log(?:\s+transformation)?)(?![a-z0-9])|"
            r"未取\s*log|未做\s*log|未对数转换|线性尺度|原始尺度",
            re.IGNORECASE,
        ), "没有取 log / 线性尺度"),
    )

    def __init__(self, reader: TableReader | None = None) -> None:
        self.reader = reader or TableReader()

    def scan(
        self,
        paths: list[Path] | tuple[Path, ...],
        *,
        progress: Callable[[ScanProgress], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> ScanResult:
        candidates: list[Path] = []
        issues: list[Issue] = []
        seen: set[Path] = set()
        selected_paths = tuple(dict.fromkeys(path.expanduser().resolve() for path in paths))
        has_directory = any(path.is_dir() for path in selected_paths)
        for selected in selected_paths:
            if cancelled and cancelled():
                return ScanResult((), tuple(issues), True)
            path = selected.expanduser().resolve()
            if path.is_dir():
                visited_entries = 0
                for child in path.rglob("*"):
                    visited_entries += 1
                    if cancelled and cancelled():
                        return ScanResult((), tuple(issues), True)
                    try:
                        relative_parts = child.relative_to(path).parts
                    except ValueError:
                        relative_parts = child.parts
                    hidden = any(part.startswith(".") for part in relative_parts)
                    if not hidden and child.is_file() and child not in seen:
                        candidates.append(child)
                        seen.add(child)
                    # Progress is based on visited directory entries, not the
                    # current file count: otherwise 25 files followed by a
                    # large run of directories emits the same event per item.
                    if progress and visited_entries % 25 == 0:
                        progress(ScanProgress("discover", len(candidates), None, child))
            elif path.is_file():
                if path not in seen:
                    candidates.append(path)
                    seen.add(path)
            else:
                issues.append(Issue("MISSING_PATH", IssueSeverity.BLOCKING, f"找不到文件：{path}", "请确认文件仍在原位置"))
        if has_directory:
            candidates.sort()
        total = len(candidates)
        assets: list[DataAsset] = []
        tenx_candidates: dict[Path, set[Path]] = {}
        tenx_names = {
            "matrix.mtx", "matrix.mtx.gz",
            "barcodes.tsv", "barcodes.tsv.gz",
            "features.tsv", "features.tsv.gz",
            "genes.tsv", "genes.tsv.gz",
        }
        for candidate in candidates:
            if candidate.name.lower() in tenx_names:
                tenx_candidates.setdefault(candidate.parent, set()).add(candidate)
        tenx_assets: dict[Path, DataAsset] = {}
        for index, path in enumerate(candidates, start=1):
            if cancelled and cancelled():
                return ScanResult(tuple(assets), tuple(issues), True)
            if path in tenx_candidates.get(path.parent, set()):
                if path.parent not in tenx_assets:
                    directory = path.parent
                    tenx_paths = tenx_candidates[directory]
                    try:
                        bundle = TenXReader().find_bundle(directory)
                        tenx_assets[directory] = DataAsset(
                            str(uuid4()),
                            tuple(sorted((bundle.matrix_path, bundle.barcodes_path, bundle.features_path))),
                            "TENX", "EXPRESSION_CANDIDATE", "10x-sparse", 0.95,
                            (Evidence("检测到完整 10x 三件套", str(directory), 0.95),),
                            (bundle.rows, bundle.columns), observation_unit_hint="CELL",
                            dimension_confidences={"features": 0.99, "observations": 0.99},
                        )
                    except TenXReadError as exc:
                        tenx_assets[directory] = DataAsset(
                            str(uuid4()), tuple(sorted(tenx_paths)), "TENX", "UNREADABLE", "10x-sparse", 0.0,
                            issues=(Issue("TENX_INCOMPLETE", IssueSeverity.BLOCKING, str(exc), "请提供同一目录下完整的 matrix、barcodes 和 features/genes 文件"),),
                        )
                    assets.append(tenx_assets[directory])
            else:
                try:
                    assets.append(self._detect(path, progress=progress, cancelled=cancelled))
                except GeoReadCancelled:
                    return ScanResult(tuple(assets), tuple(issues), True)
            if progress:
                progress(ScanProgress("inspect", index, total, path))
        return ScanResult(tuple(assets), tuple(issues))

    @staticmethod
    def recommended_sheet(sheets: tuple[str | None, ...]) -> str | None:
        """只依据工作表名称给出可撤销的导入建议，不把建议升级为已确认事实。"""

        if not sheets:
            return None

        def rank(sheet: str | None) -> int:
            name = (sheet or "").casefold().replace("-", "_").replace(" ", "_")
            normalized = any(token in name for token in ("normalized", "normalised", "norm_count", "normalized_count"))
            if not normalized and re.search(
                r"(?<![a-z0-9])(?:raw[_ ]*counts?|gene[_ ]*counts?|read[_ ]*counts?|counts?)(?![a-z0-9])",
                name,
            ):
                return 3
            if re.search(r"(?<![a-z0-9])tpm(?![a-z0-9])", name):
                return 2
            if any(token in name for token in ("expression", "matrix", "result", "表达", "矩阵")):
                return 1
            return 0

        ranked = [(rank(sheet), sheet) for sheet in sheets]
        best = max(item[0] for item in ranked)
        winners = [sheet for score, sheet in ranked if score == best]
        return winners[0] if best > 0 and len(winners) == 1 else None

    def _detect(
        self,
        path: Path,
        *,
        progress: Callable[[ScanProgress], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> DataAsset:
        def report_geo_progress(completed: int) -> None:
            if progress:
                progress(ScanProgress("geo-read", completed, None, path))

        suffix = path.suffix.lower()
        lower_name = path.name.casefold()
        if lower_name.endswith((".fastq.gz", ".fq.gz")) or suffix in {".fastq", ".fq", ".bam", ".sam"}:
            issue = Issue(
                "RAW_SEQUENCING_INPUT", IssueSeverity.INFO,
                "检测到原始测序文件；本软件不支持原始测序文件的比对或定量。",
                "请向提供方索取每个基因 × 每个样本的表达矩阵和样本分组说明",
            )
            return DataAsset(str(uuid4()), (path,), "RAW_SEQUENCING", "GUIDANCE_ONLY", "raw-sequencing", 0.95, issues=(issue,))
        if suffix in {".pdf", ".png", ".jpg", ".jpeg", ".doc", ".docx", ".md"} or self._is_named_sidecar(path):
            return DataAsset(
                str(uuid4()), (path,), "AUXILIARY", "IGNORE_CANDIDATE", "auxiliary", 0.9,
                (Evidence("这是说明或图片文件，不会作为表达矩阵读取", str(path), 0.9),),
                issues=(Issue("AUXILIARY_IGNORED", IssueSeverity.INFO, "该文件不会参与表达矩阵分析。", "可忽略；需要时可查看原始交付说明"),),
            )
        try:
            # 仅对可能是文本容器的后缀做有界 GEO 嗅探；zip/tar/其他二进制
            # 文件不应为了识别而被解压或完整读入。
            is_tar_gzip = lower_name.endswith((".tar.gz", ".tgz"))
            should_sniff_geo = suffix in {".gz", ".soft", ".annot"} and not is_tar_gzip
            if should_sniff_geo and GeoSeriesMatrixReader.looks_like(path):
                geo = GeoSeriesMatrixReader().read(
                    path,
                    max_table_rows=self.PREVIEW_ROWS,
                    max_table_columns=self.PREVIEW_COLUMNS,
                    progress=report_geo_progress,
                    cancelled=cancelled,
                )
                return DataAsset(
                    str(uuid4()), (path,), "GEO_SERIES_MATRIX", "EXPRESSION_CANDIDATE", "geo-series-matrix", 0.95,
                    self._geo_evidence(path, geo, "按文件内容检测到 GEO Series Matrix 表段"),
                    (geo.raw_table.row_count, geo.raw_table.column_count),
                    platform_ids=geo.platform_ids,
                    dimension_confidences={"features": 0.98, "observations": 0.98},
                    species_hint=_species_hint(geo.raw_table.rows),
                )
        except GeoReadCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - 扫描阶段保留单文件问题
            return DataAsset(
                str(uuid4()), (path,), "GEO_SERIES_MATRIX", "UNREADABLE", "geo-series-matrix", 0.0,
                issues=(Issue("GEO_READ_FAILED", IssueSeverity.BLOCKING, f"GEO 表段无法读取：{exc}", "请检查表段或另存为纯文本后重试"),),
            )
        if suffix == ".gz":
            try:
                if GeoSeriesMatrixReader.looks_like(path):
                    geo = GeoSeriesMatrixReader().read(
                        path,
                        max_table_rows=self.PREVIEW_ROWS,
                        max_table_columns=self.PREVIEW_COLUMNS,
                        progress=report_geo_progress,
                        cancelled=cancelled,
                    )
                    return DataAsset(
                        str(uuid4()), (path,), "GEO_SERIES_MATRIX", "EXPRESSION_CANDIDATE", "geo-series-matrix", 0.95,
                        self._geo_evidence(path, geo, "检测到 gzip 压缩的 GEO Series Matrix 表段"),
                        (geo.raw_table.row_count, geo.raw_table.column_count),
                        platform_ids=geo.platform_ids,
                        dimension_confidences={"features": 0.98, "observations": 0.98},
                        species_hint=_species_hint(geo.raw_table.rows),
                    )
            except GeoReadCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - 扫描阶段保留可读错误
                return DataAsset(str(uuid4()), (path,), "GEO_SERIES_MATRIX", "UNREADABLE", "geo-series-matrix", 0.0, issues=(Issue("GEO_READ_FAILED", IssueSeverity.BLOCKING, f"GEO 表段无法读取：{exc}", "请检查压缩文件或另存为纯文本后重试"),))
        if suffix in {".soft", ".annot"}:
            if GPLAnnotationReader.looks_like(path):
                return DataAsset(str(uuid4()), (path,), "REFERENCE", "REFERENCE_CANDIDATE", "gpl-annotation", 0.9, (Evidence("检测到 GPL/SOFT 或注释表", str(path), 0.9),))
            return DataAsset(str(uuid4()), (path,), "REFERENCE", "UNREADABLE", "gpl-annotation", 0.0, issues=(Issue("REFERENCE_READ_FAILED", IssueSeverity.BLOCKING, "参考文件无法识别为 GPL 注释表。", "请提供包含编号和 gene symbol 列的 SOFT/annot 文件"),))
        if suffix in self.SUPPORTED_TABLES:
            try:
                # .csv/.tsv/.txt/.tab 可能是 GEO Series Matrix；Excel 必须
                # 直接交给 TableReader，避免二进制内容进入文本嗅探器。
                if suffix in TableReader.TEXT_SUFFIXES and GeoSeriesMatrixReader.looks_like(path):
                    geo = GeoSeriesMatrixReader().read(
                        path,
                        max_table_rows=self.PREVIEW_ROWS,
                        max_table_columns=self.PREVIEW_COLUMNS,
                        progress=report_geo_progress,
                        cancelled=cancelled,
                    )
                    return DataAsset(
                        str(uuid4()), (path,), "GEO_SERIES_MATRIX", "EXPRESSION_CANDIDATE", "geo-series-matrix", 0.95,
                        self._geo_evidence(path, geo, "检测到 GEO Series Matrix 表段"),
                        (geo.raw_table.row_count, geo.raw_table.column_count),
                        platform_ids=geo.platform_ids,
                        dimension_confidences={"features": 0.98, "observations": 0.98},
                        species_hint=_species_hint(geo.raw_table.rows),
                    )
                sheets = self.reader.list_sheets(path)
                selected_sheet = self.recommended_sheet(sheets)
                if len(sheets) > 1 and selected_sheet is None:
                    return DataAsset(
                        str(uuid4()), (path,), "TABLE", "EXPRESSION_CANDIDATE", "table", 0.55,
                        (Evidence("工作簿含多张用途不明的工作表；软件未替你任选", str(path), 0.9),),
                    )
                preview = self.reader.read(
                    path,
                    selected_sheet,
                    max_rows=self.PREVIEW_ROWS,
                    max_columns=self.PREVIEW_COLUMNS,
                )
                shape = (preview.row_count, preview.column_count)
                density = self._numeric_density(preview.rows)
                measurement_hint, scale_hint, text_evidence = self.inspect_text_facts(
                    path, preview.rows, selected_sheet=selected_sheet, sheet_count=len(sheets),
                )
                evidence_location = path.name
                if selected_sheet:
                    evidence_location += f" · 工作表「{selected_sheet}」"
                evidence_location += " · 软件核查前 8 行、最多 80 列"
                evidence = [
                    Evidence("扩展名与内容可读取", str(path), 0.75),
                    Evidence(f"预览数值密度 {density:.2f}", "前 40 行", min(0.95, 0.45 + density / 2)),
                ]
                evidence.extend(text_evidence)
                if measurement_hint != MeasurementType.UNKNOWN:
                    measurement_name = {
                        MeasurementType.RAW_COUNT: "原始 count",
                        MeasurementType.TPM: "TPM",
                        MeasurementType.FPKM: "FPKM",
                        MeasurementType.RPKM: "RPKM",
                        MeasurementType.CPM: "CPM",
                        MeasurementType.OTHER_NORMALIZED: "其他连续表达值",
                    }.get(measurement_hint, "表达值")
                    if not any(item.fact_key == "measurement_type" for item in text_evidence):
                        evidence.append(Evidence(
                            f"文字线索提示可能是 {measurement_name}；需要对照数据说明确认",
                            evidence_location, 0.88,
                        ))
                if scale_hint != ValueScale.UNKNOWN:
                    scale_name = {
                        ValueScale.LINEAR: "原始/线性数值",
                        ValueScale.LOG2: "已取 log2",
                        ValueScale.OTHER_TRANSFORM: "其他数值变换",
                    }.get(scale_hint, "数值尺度")
                    if not any(item.fact_key == "value_scale" for item in text_evidence):
                        evidence.append(Evidence(
                            f"文字线索提示可能是{scale_name}；需要对照数据说明确认",
                            evidence_location, 0.88,
                        ))
                if len(sheets) > 1 and selected_sheet != sheets[0]:
                    evidence.append(Evidence(
                        f"工作表名称提示优先查看“{selected_sheet}”；这是可调整的导入建议",
                        str(path), 0.8,
                    ))
                if selected_sheet is not None and len(sheets) > 1:
                    selected_name = selected_sheet.casefold()
                    selected_looks_count = bool(re.search(
                        r"(?<![a-z0-9])(?:raw[_ ]*counts?|gene[_ ]*counts?|read[_ ]*counts?|counts?)(?![a-z0-9])",
                        selected_name,
                    ))
                    tpm_sheet = next((sheet for sheet in sheets if sheet and re.search(
                        r"(?<![a-z0-9])tpm(?![a-z0-9])", sheet.casefold()
                    )), None)
                    if selected_looks_count and tpm_sheet is not None:
                        evidence.append(Evidence(
                            f"同一工作簿还有“{tpm_sheet}”工作表；名称线索建议先看 count 表，因为原始计数更适合当前统计模型。名称不能证明内容，请对照交付说明确认。",
                            evidence_location, 0.8,
                        ))
                return DataAsset(
                    str(uuid4()), (path,), "TABLE", "EXPRESSION_CANDIDATE", "table",
                    max(e.score for e in evidence), tuple(evidence), shape,
                    measurement_hint=measurement_hint, scale_hint=scale_hint,
                    dimension_confidences={"features": 0.65, "observations": 0.75},
                    species_hint=_species_hint(preview.rows),
                )
            except GeoReadCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - 扫描阶段保留单文件问题
                code = "GEO_READ_FAILED" if "series_matrix" in path.name.lower() else "TABLE_READ_FAILED"
                return DataAsset(str(uuid4()), (path,), "TABLE", "UNREADABLE", "table", 0.0, issues=(Issue(code, IssueSeverity.BLOCKING, f"表格无法读取：{exc}", "请检查 GEO 表段或另存为 UTF-8 CSV/TSV 后重试"),))
        if suffix in {".gz", ".zip", ".tar", ".tgz"}:
            return DataAsset(str(uuid4()), (path,), "ARCHIVE", "ARCHIVE_CANDIDATE", "archive", 0.6, (Evidence("检测到压缩容器扩展名", str(path), 0.6),))
        return DataAsset(str(uuid4()), (path,), "UNKNOWN", "UNIDENTIFIED", "unknown", 0.25, (Issue("UNKNOWN_FILE", IssueSeverity.WARNING, "暂时无法判断这个文件的用途。", "请在整理向导中选择或忽略"),))

    @staticmethod
    def _geo_evidence(path: Path, geo, detection_basis: str) -> tuple[Evidence, ...]:
        evidence = [Evidence(detection_basis, str(path), 0.95)]
        series_types = {value.strip().casefold() for value in geo.series_types if value.strip()}
        if series_types == {"expression profiling by array"}:
            evidence.append(Evidence(
                "GEO 来源元数据标注为芯片阵列；这只能说明平台类型，不能确定矩阵单位或 log 公式。",
                str(path), 0.99, "source_modality", "MICROARRAY", "!Series_type",
                "Expression profiling by array", "geo_series_type",
            ))
        return tuple(evidence)

    @staticmethod
    def _numeric_density(rows: tuple[tuple[str, ...], ...]) -> float:
        values = [value for row in rows for value in row if value.strip()]
        if not values:
            return 0.0
        numeric = 0
        for value in values:
            try:
                float(value)
                numeric += 1
            except ValueError:
                pass
        return numeric / len(values)

    @classmethod
    def _hints(cls, path: Path, rows: tuple[tuple[str, ...], ...]) -> tuple[MeasurementType, ValueScale]:
        """兼容旧调用点；仅按可见表格文字给候选，不根据数值推断。"""
        evidence = cls._table_fact_evidence(path, rows, None)
        return cls._consensus_hint(evidence, "measurement_type", MeasurementType), cls._consensus_hint(
            evidence, "value_scale", ValueScale,
        )

    @classmethod
    def inspect_text_facts(
        cls,
        path: Path,
        rows: tuple[tuple[str, ...], ...],
        *,
        selected_sheet: str | None = None,
        sheet_count: int = 1,
    ) -> tuple[MeasurementType, ValueScale, tuple[Evidence, ...]]:
        """提取带来源和位置的文字候选；冲突时返回 UNKNOWN，绝不猜测。"""
        evidence = cls._table_fact_evidence(path, rows, selected_sheet)
        evidence.extend(cls._sidecar_fact_evidence(path, selected_sheet, sheet_count))
        return (
            cls._consensus_hint(evidence, "measurement_type", MeasurementType),
            cls._consensus_hint(evidence, "value_scale", ValueScale),
            tuple(evidence),
        )

    @classmethod
    def _table_fact_evidence(
        cls,
        path: Path,
        rows: tuple[tuple[str, ...], ...],
        sheet_name: str | None,
    ) -> list[Evidence]:
        evidence: list[Evidence] = []
        for row_index, row in enumerate(rows[:8], start=1):
            for column_index, cell in enumerate(row[:80], start=1):
                text = str(cell).strip()
                if not text or cls._is_numeric_cell(text):
                    continue
                location = (
                    f"工作表「{sheet_name}」!{_excel_column(column_index)}{row_index}"
                    if sheet_name else f"表格记录第 {row_index} 行、第 {column_index} 列"
                )
                evidence.extend(cls._match_fact_text(
                    text, source=str(path), location=location, evidence_level="table_text_candidate",
                ))
        return evidence

    @classmethod
    def _sidecar_fact_evidence(
        cls,
        path: Path,
        selected_sheet: str | None,
        sheet_count: int,
    ) -> list[Evidence]:
        def incomplete(message: str) -> list[Evidence]:
            return [Evidence(
                message,
                str(path.parent), 0.35, evidence_level="sidecar_scan_incomplete",
            )]

        try:
            siblings = sorted(path.parent.iterdir(), key=lambda item: item.name.casefold())
        except OSError:
            return incomplete("无法完整检查同目录说明文件；为避免漏掉冲突，不能一键采用任何文字候选。")
        if len(siblings) > 256:
            return [Evidence(
                "同目录文件较多，已跳过说明文件自动读取；请人工核对交付说明。",
                str(path.parent), 0.2, evidence_level="sidecar_scan_skipped",
            )]
        table_count = sum(
            1 for item in siblings
            if (
                not item.is_symlink()
                and item.is_file()
                and item.suffix.lower() in cls.SUPPORTED_TABLES
                and not cls._is_named_sidecar(item)
            )
        )
        candidates = [
            item for item in siblings
            if item != path
            and not item.is_symlink()
            and item.is_file()
            and item.suffix.lower() in {".md", ".txt"}
            and any(marker in item.name.casefold() for marker in cls.SIDECAR_NAME_MARKERS)
        ]
        if len(candidates) > cls.SIDECAR_MAX_FILES:
            return incomplete(
                f"同目录说明超过 {cls.SIDECAR_MAX_FILES} 份安全核查上限；为避免漏掉冲突，未使用任何说明候选。"
            )

        loaded: list[tuple[Path, str]] = []
        total_bytes = 0
        for sidecar in candidates:
            try:
                size = sidecar.stat().st_size
                if size <= 0 or size > cls.SIDECAR_MAX_BYTES:
                    return incomplete("同目录说明有文件超出大小上限或为空；为避免漏掉冲突，未使用说明候选。")
                if total_bytes + size > cls.SIDECAR_TOTAL_MAX_BYTES:
                    return incomplete("同目录说明合计超出读取上限；为避免漏掉冲突，未使用说明候选。")
                with sidecar.open("rb") as handle:
                    raw = handle.read(cls.SIDECAR_MAX_BYTES + 1)
                if len(raw) > cls.SIDECAR_MAX_BYTES:
                    return incomplete("同目录说明读取过程中超过大小上限；为避免漏掉冲突，未使用说明候选。")
            except OSError:
                return incomplete("同目录说明无法完整读取；为避免漏掉冲突，未使用说明候选。")
            total_bytes += len(raw)
            text = _decode_sidecar(raw)
            if text is None:
                return incomplete("同目录说明编码无法安全识别；为避免漏掉冲突，未使用说明候选。")
            loaded.append((sidecar, text))

        evidence: list[Evidence] = []
        for sidecar, text in loaded:
            folded = text.casefold()
            # 必须点名当前表达表；README 自称及其他文件名的子串不是关联证据。
            name_is_linked = bool(
                re.search(rf"(?<![\w.-]){re.escape(path.name.casefold())}(?![\w-]|\.\w)", folded)
                or (len(path.stem) >= 6 and re.search(
                    rf"(?<![\w.-]){re.escape(path.stem.casefold())}(?![\w.-])", folded,
                ))
            )
            single_table_folder = table_count == 1 and sheet_count <= 1
            sheet_is_linked = sheet_count <= 1 or bool(
                selected_sheet and selected_sheet.casefold() in folded
            )
            linked = sheet_is_linked and (name_is_linked or single_table_folder)
            if not linked:
                evidence.append(Evidence(
                    "发现同目录说明，但无法确认它对应当前表达表/工作表；未用于判断单位或变换。",
                    str(sidecar), 0.35, evidence_level="unlinked_sidecar",
                ))
                continue
            lines = text.splitlines()
            if len(lines) > 3000 or any(line.strip() and len(line) > 8192 for line in lines):
                return incomplete(
                    "关联说明超过行数或单行长度安全核查范围；为避免漏掉冲突，未使用任何说明候选。"
                )
            hits_before = len(evidence)
            seen_fact_values: set[tuple[str, str]] = set()
            seen_log2_formulas: set[str] = set()
            for line_number, line in enumerate(lines, start=1):
                if not line.strip():
                    continue
                line_evidence = cls._match_fact_text(
                    line.strip(), source=str(sidecar), location=f"第 {line_number} 行",
                    evidence_level="linked_sidecar_text_candidate",
                )
                for item in line_evidence:
                    fact_key = (item.fact_key, item.fact_value)
                    if item.fact_key == "value_scale" and item.fact_value == ValueScale.LOG2.value:
                        formula = item.reported_transform
                        if formula:
                            if formula in seen_log2_formulas:
                                continue
                            if len(seen_log2_formulas) >= 2:
                                continue
                            seen_log2_formulas.add(formula)
                            evidence.append(item)
                            continue
                    if fact_key in seen_fact_values:
                        continue
                    seen_fact_values.add(fact_key)
                    evidence.append(item)
            if len(evidence) == hits_before:
                evidence.append(Evidence(
                    "已读取并关联同目录说明，但未找到单位或变换的明确文字。",
                    str(sidecar), 0.55, evidence_level="linked_sidecar_no_fact_text",
                ))
        return evidence

    @classmethod
    def _match_fact_text(
        cls,
        text: str,
        *,
        source: str,
        location: str,
        evidence_level: str,
    ) -> list[Evidence]:
        hit_starts = [
            match.start()
            for _value, pattern, _label in (*cls.MEASUREMENT_PATTERNS, *cls.SCALE_PATTERNS)
            if (match := pattern.search(text)) is not None
        ]
        excerpt, excerpt_redacted = _bounded_excerpt(text, min(hit_starts) if hit_starts else 0)
        if may_contain_sensitive_metadata(f"{text} {source} {location}"):
            excerpt = "[句子包含可能的个人或样本标识，已隐藏整句]"
            excerpt_redacted = True
        result: list[Evidence] = []
        for value, pattern, label in cls.MEASUREMENT_PATTERNS:
            if pattern.search(text):
                result.append(Evidence(
                    f"原文包含“{label}”文字线索；仍需确认它描述的是当前矩阵。",
                    source, 0.92, "measurement_type", value.value, location, excerpt,
                    evidence_level, excerpt_redacted,
                ))
        for value, pattern, label in cls.SCALE_PATTERNS:
            matches = list(pattern.finditer(text))
            if value == ValueScale.LOG2:
                matches = [match for match in matches if not _is_negated_log2(text, match.start(), match.end())]
            if matches:
                formulas = _safe_reported_formulas(text) if value == ValueScale.LOG2 else ("",)
                for formula in formulas or ("",):
                    result.append(Evidence(
                        f"原文包含“{label}”文字线索；未据此补造公式或伪计数。",
                        source, 0.92, "value_scale", value.value, location, excerpt,
                        evidence_level, excerpt_redacted, formula,
                    ))
        return result

    @staticmethod
    def _consensus_hint(evidence: list[Evidence], fact_key: str, enum_type):
        values = {
            item.fact_value for item in evidence
            if item.fact_key == fact_key and item.fact_value
        }
        if len(values) != 1:
            return enum_type.UNKNOWN
        try:
            return enum_type(next(iter(values)))
        except ValueError:
            return enum_type.UNKNOWN

    @staticmethod
    def _is_numeric_cell(value: str) -> bool:
        try:
            float(value.replace(",", ""))
            return True
        except ValueError:
            return False

    @classmethod
    def _is_named_sidecar(cls, path: Path) -> bool:
        return (
            path.suffix.lower() in {".md", ".txt"}
            and any(
                marker in path.name.casefold()
                for marker in cls.SIDECAR_NAME_MARKERS
            )
        )


def _species_hint(rows: tuple[tuple[str, ...], ...]) -> str | None:
    """只提供可审查的 Ensembl 前缀提示；不把纯数字编号当作物种。"""
    values = [cell.strip().split(".", 1)[0] for row in rows[:40] for cell in row[:3] if cell.strip()]
    prefixes = {
        "ENSG": "9606",
        "ENSMUSG": "10090",
        "ENSRNOG": "10116",
    }
    for value in values:
        for prefix, taxid in prefixes.items():
            if value.upper().startswith(prefix):
                return taxid
    return None


def _excel_column(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(ord("A") + remainder) + result
    return result


def _decode_sidecar(raw: bytes) -> str | None:
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _bounded_excerpt(text: str, anchor: int, limit: int = 180) -> tuple[str, bool]:
    source = text.strip()
    start = max(0, min(anchor - limit // 3, max(0, len(source) - limit)))
    end = min(len(source), start + limit)
    excerpt = ("…" if start else "") + source[start:end] + ("…" if end < len(source) else "")
    redacted = False
    for pattern in (
        r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        r"(?i)/(?:Users|home|private)/[^\s,;]+",
        r"(?i)\b(?:GSM|GSE|SRR|ERR|DRR)\d+\b",
        r"(?i)\b(?:patient|subject|case|sample)[ _-]*(?:id|no\.?|number|编号)\s*[:=#]?\s*[A-Za-z0-9._-]+",
    ):
        excerpt, count = re.subn(pattern, "[已隐藏标识]", excerpt)
        redacted = redacted or count > 0

    # 摘录可能来自说明表的叙述句；表达数值和患者编号不作为识别证据展示。
    # 保留明确写出的 log2(...) 公式片段，其余独立数值用占位符代替。
    formulas = [
        (match.start(), match.end())
        for match in re.finditer(r"(?i)(?:log\s*_?2|log₂)\s*\([^)]{0,80}\)", excerpt)
    ]
    matches = list(re.finditer(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![A-Za-z])", excerpt))
    for match in reversed(matches):
        if any(start <= match.start() < end for start, end in formulas):
            continue
        excerpt = excerpt[:match.start()] + "[数值已隐藏]" + excerpt[match.end():]
        redacted = True
    return excerpt, redacted


def _is_negated_log2(text: str, start: int, end: int) -> bool:
    prefix = re.split(r"[.;!?。；！？\n]", text[max(0, start - 80):start])[-1]
    if re.search(
        r"(?i)(?:\b(?:not|never|without)|\b(?:was|were|has|have|had|do|does|did)\s+not|"
        r"\b(?:don't|doesn't|didn't))\s+(?:(?:use|using|used|apply|applying|applied|perform|performed|"
        r"transform|transformed)\s+)?(?:been\s+)?$|"
        r"(?:未|没有|并未|不曾|尚未)\s*(?:使用|用|进行|经过|做|取|应用|转换|变换)?\s*$",
        prefix,
    ):
        return True
    suffix = re.split(r"[.;!?。；！？\n]", text[end:end + 80])[0]
    return bool(re.match(
        r"(?i)^\s*(?:was|were|has|have|had)\s+not\s+(?:been\s+)?"
        r"(?:applied|performed|used|done|carried\s+out|calculated|implemented|converted|transformed)",
        suffix,
    ))


def _safe_reported_formulas(text: str) -> tuple[str, ...]:
    formulas: list[str] = []
    for match in re.finditer(r"(?i)(?:log\s*_?2|log₂)\s*\([^)]{1,120}\)", text):
        if _is_negated_log2(text, match.start(), match.end()):
            continue
        formula = match.group(0)
        if not re.fullmatch(r"(?i)(?:log\s*_?2|log₂)\s*\([A-Za-z0-9_ +*/().,-]{1,120}\)", formula):
            continue
        expression_match = re.search(r"\((.*)\)", formula)
        if expression_match is None:
            continue
        expression = expression_match.group(1)
        tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?|[()+*/.,-]", expression)
        if "".join(tokens).casefold() != re.sub(r"\s+", "", expression).casefold():
            continue
        allowed_names = {
            "x", "tpm", "fpkm", "rpkm", "cpm", "count", "counts",
            "expression", "normalized_expression", "normalised_expression",
            "value", "values", "abundance",
        }
        safe = True
        for token in tokens:
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token) and token.casefold() not in allowed_names:
                safe = False
                break
            if re.fullmatch(r"\d+(?:\.\d+)?", token) and float(token) > 1000:
                safe = False
                break
        if safe:
            if formula not in formulas:
                formulas.append(formula)
            if len(formulas) >= 2:
                break
    return tuple(formulas)
