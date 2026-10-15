from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping
from uuid import uuid4

from rnaseq_helper.domain.models import (
    DataAsset, ExpressionMatrix, Issue, IssueSeverity, MatrixStoreRef,
    MeasurementType, ObservationUnit, PreparationRecipe, ReferenceRequest,
    TablePreview, ValidationSummary, ValueScale, may_contain_sensitive_metadata,
    persisted_local_path, sha256_file,
)
from rnaseq_helper.readers.table_reader import RawTable, TableReader
from rnaseq_helper.readers.geo_reader import GeoSeriesMatrix, GeoSeriesMatrixReader
from rnaseq_helper.services.reference_service import ReferenceService


@dataclass(frozen=True)
class WizardSession:
    session_id: str
    revision: int
    asset: DataAsset
    raw_table: RawTable
    recipe: PreparationRecipe
    project_dir: Path
    history: tuple[str, ...] = ()
    reference_path: Path | None = None
    geo_matrix: GeoSeriesMatrix | None = None
    preview_shape: tuple[int, int] | None = None


class PreparationBlocked(RuntimeError):
    def __init__(self, summary: ValidationSummary):
        self.summary = summary
        message = "；".join(issue.message_zh for issue in summary.blockers)
        super().__init__(message or "整理结果未通过验证")


class PreparationCancelled(RuntimeError):
    """用户在完整校验期间取消；此阶段尚未写入整理结果。"""


class PreparationService:
    # 只拦截明确表示基因/转录本结构注释的列名；不对任意数值列做语义猜测。
    _NUMERIC_ANNOTATION_HEADERS = {
        "length", "gene_length", "transcript_length", "effective_length",
        "start", "gene_start", "transcript_start", "start_position",
        "end", "gene_end", "transcript_end", "end_position",
        "gc", "gc_content", "gc_percent", "gc_percentage",
    }

    def __init__(self, reader: TableReader | None = None) -> None:
        self.reader = reader or TableReader()

    def start(
        self,
        asset: DataAsset,
        project_dir: Path,
        sheet_name: str | None = None,
        *,
        preview_only: bool = False,
        preview_rows: int = 40,
        preview_columns: int = 80,
        progress: Callable[[int], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> WizardSession:
        if cancelled and cancelled():
            raise RuntimeError("已取消读取表格")
        path = asset.source_paths[0]
        sheets = (None,) if asset.kind == "GEO_SERIES_MATRIX" else self.reader.list_sheets(path)
        sheet = sheet_name if sheet_name in sheets else sheets[0]
        raw, geo_matrix = self._read_asset(
            asset,
            sheet,
            max_rows=preview_rows if preview_only else None,
            max_columns=preview_columns if preview_only else None,
            progress=progress,
            cancelled=cancelled,
        )
        header_candidates = self.candidate_header_rows(raw.rows)
        header = header_candidates[0] if header_candidates else 0
        width = raw.column_count
        data_start = min(header + 1, max(0, raw.row_count))
        sample_columns = self._numeric_columns(raw.rows, data_start, width)
        feature_id = self._feature_id_column(raw.rows, data_start, width, sample_columns)
        annotation = tuple(index for index in range(width) if index not in sample_columns and index != feature_id)
        recipe = PreparationRecipe(
            asset_id=asset.asset_id, source_path=path, sheet_name=sheet,
            header_row=header, data_start_row=data_start, transpose=False,
            feature_id_column=feature_id, sample_columns=tuple(sample_columns),
            annotation_columns=annotation, measurement_type=MeasurementType.UNKNOWN,
            value_scale=ValueScale.UNKNOWN,
        )
        return WizardSession(
            str(uuid4()), 0, asset, raw, recipe, project_dir,
            geo_matrix=geo_matrix,
            preview_shape=(raw.row_count, raw.column_count),
        )

    def complete_read(
        self,
        session: WizardSession,
        *,
        progress: Callable[[int], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> WizardSession:
        """在用户确认表格结构后，于后台读取完整数据用于最终校验。"""
        if session.raw_table.is_complete:
            return session
        if cancelled and cancelled():
            raise RuntimeError("已取消完整读取")
        raw, geo_matrix = self._read_asset(
            session.asset,
            session.recipe.sheet_name,
            progress=progress,
            cancelled=cancelled,
        )
        return replace(
            session,
            raw_table=raw,
            geo_matrix=geo_matrix if geo_matrix is not None else session.geo_matrix,
        )

    def _read_asset(
        self,
        asset: DataAsset,
        sheet_name: str | None,
        *,
        max_rows: int | None = None,
        max_columns: int | None = None,
        progress: Callable[[int], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> tuple[RawTable, GeoSeriesMatrix | None]:
        if asset.kind == "GEO_SERIES_MATRIX":
            geo = GeoSeriesMatrixReader().read(
                asset.source_paths[0],
                max_table_rows=max_rows,
                max_table_columns=max_columns,
                progress=progress,
                cancelled=cancelled,
            )
            return geo.raw_table, geo
        raw = self.reader.read(
            asset.source_paths[0], sheet_name, max_rows=max_rows, max_columns=max_columns,
            progress=progress, cancelled=cancelled,
        )
        return raw, None

    def preview(self, session: WizardSession, patch: Mapping[str, Any] | None = None, window: tuple[int, int] = (0, 30)) -> TablePreview:
        recipe = self._patch_recipe(session.recipe, patch or {})
        rows = self._view_rows(session.raw_table.rows, recipe.transpose)
        start, count = window
        shown = tuple(tuple(cell for cell in row[:80]) for row in rows[start:start + count])
        return TablePreview(session.raw_table.path, recipe.sheet_name, shown, len(rows), max((len(row) for row in rows), default=0), tuple(self.candidate_header_rows(rows)), recipe.transpose)

    def apply(self, session: WizardSession, decision: Mapping[str, Any]) -> WizardSession:
        recipe = self._patch_recipe(session.recipe, decision)
        return replace(session, revision=session.revision + 1, recipe=recipe, history=session.history + (json.dumps(dict(decision), ensure_ascii=False, sort_keys=True),))

    def validate(
        self,
        session: WizardSession,
        *,
        cancelled: Callable[[], bool] | None = None,
        progress: Callable[[int, int], None] | None = None,
    ) -> ValidationSummary:
        self._raise_if_cancelled(cancelled)
        try:
            header, data, feature_ids, sample_ids, matrix, annotation_rows = self._materialize(
                session.recipe,
                session.raw_table,
                cancelled=cancelled,
            )
        except (IndexError, ValueError) as exc:
            issue = Issue("PREPARATION_INVALID", IssueSeverity.BLOCKING, f"整理结果无法生成矩阵：{exc}", "回到预览检查表头、数据起始行和列角色")
            return ValidationSummary(False, (issue,), 0, 0, 0)
        issues: list[Issue] = []
        if session.preview_shape is not None:
            visible_sample_axis = session.preview_shape[1] if not session.recipe.transpose else session.preview_shape[0]
            actual_sample_axis = session.raw_table.column_count if not session.recipe.transpose else session.raw_table.row_count
            if actual_sample_axis > visible_sample_axis:
                issues.append(Issue(
                    "PREVIEW_LIMIT_EXCEEDED",
                    IssueSeverity.BLOCKING,
                    f"完整文件的候选样本方向有 {actual_sample_axis:,} 列/行，首轮只显示了 {visible_sample_axis:,}；不能安全地略过未核对部分。",
                    "请先检查是否能在工作表中去掉不需要的列/行，或重新导出只包含本次样本的表格后再导入。",
                ))
        if session.recipe.measurement_type == MeasurementType.UNKNOWN:
            issues.append(Issue("UNKNOWN_MEASUREMENT", IssueSeverity.BLOCKING, "还不能确认这些数字是原始计数、TPM、FPKM 还是其他表达量。", "请确认交付说明中的单位"))
        if session.recipe.value_scale == ValueScale.UNKNOWN:
            issues.append(Issue("UNKNOWN_SCALE", IssueSeverity.BLOCKING, "还不能确认这些数值是否已经取 log。", "请确认数值尺度和转换公式"))
        if self._geo_array_unit_conflict(session):
            issues.append(Issue(
                "GEO_ARRAY_MEASUREMENT_CONFLICT",
                IssueSeverity.BLOCKING,
                "GEO 来源元数据标注为芯片阵列；当前选择的数值单位与该平台类别不相容。",
                "不要选 raw count、TPM、FPKM、RPKM 或 CPM。若这是芯片表达信号，请选“其他连续表达值”，并依据交付说明确认线性或 log2 尺度。",
            ))
        issues.extend(self._formula_issues(session))
        if not sample_ids:
            issues.append(Issue("NO_SAMPLE_COLUMNS", IssueSeverity.BLOCKING, "没有指定样本表达列。", "请把表达量列标记为样本列"))
        if len(set(sample_ids)) != len(sample_ids):
            issues.append(Issue("DUPLICATE_SAMPLE_IDS", IssueSeverity.BLOCKING, "样本名称重复，无法确认每一列对应哪个样本。", "请回到预览修改列名或排除重复列"))
        if any(not value for value in feature_ids):
            issues.append(Issue("MISSING_FEATURE_ID", IssueSeverity.BLOCKING, "存在没有特征编号的行。", "请指定正确的编号列并排除说明行"))
        if len(set(feature_ids)) != len(feature_ids):
            issues.append(Issue("DUPLICATE_FEATURE_IDS", IssueSeverity.BLOCKING, "特征编号重复；软件不会静默合并重复编号。", "请核实重复行的含义"))
        numeric_count = 0
        total_rows = len(matrix)
        for index, (row_number, row) in enumerate(
            zip(range(session.recipe.data_start_row + 1, session.recipe.data_start_row + 1 + total_rows), matrix)
        ):
            if index % 128 == 0:
                self._raise_if_cancelled(cancelled)
                if progress is not None:
                    progress(index, total_rows)
            for column_number, value in enumerate(row):
                if not value.strip():
                    issues.append(Issue("MISSING_NUMERIC_VALUE", IssueSeverity.BLOCKING, f"第 {row_number} 行存在空的表达值。", "请补充数据或排除该行"))
                    continue
                try:
                    number = float(value)
                except ValueError:
                    issues.append(Issue("INVALID_NUMERIC_VALUE", IssueSeverity.BLOCKING, f"第 {row_number} 行存在非数字表达值：{value}", "请确认没有把说明文字当数据"))
                    continue
                if not math.isfinite(number):
                    issues.append(Issue("NONFINITE_VALUE", IssueSeverity.BLOCKING, f"第 {row_number} 行存在 Inf/NaN。", "请回到原表修正异常值"))
                    continue
                numeric_count += 1
                if session.recipe.measurement_type == MeasurementType.RAW_COUNT and (number < 0 or not number.is_integer()):
                    issues.append(Issue("INVALID_RAW_COUNT", IssueSeverity.BLOCKING, f"第 {row_number} 行含负数或非整数 count。", "请确认原始 count 文件而不是四舍五入后的表达表"))
                if session.recipe.value_scale == ValueScale.LINEAR and number < 0:
                    issues.append(Issue("NEGATIVE_LINEAR_VALUE", IssueSeverity.BLOCKING, f"第 {row_number} 行含线性尺度负值。", "请核实是否已取 log 或数据是否损坏"))
        self._raise_if_cancelled(cancelled)
        if progress is not None:
            progress(total_rows, total_rows)
        return ValidationSummary(not any(issue.severity == IssueSeverity.BLOCKING for issue in issues), tuple(self._dedupe_issues(issues)), len(feature_ids), len(sample_ids), numeric_count)

    @staticmethod
    def _geo_array_unit_conflict(session: WizardSession) -> bool:
        geo = session.geo_matrix
        if geo is None:
            return False
        series_types = {value.strip().casefold() for value in geo.series_types if value.strip()}
        return (
            series_types == {"expression profiling by array"}
            and session.recipe.measurement_type != MeasurementType.OTHER_NORMALIZED
        )

    def finish(
        self,
        session: WizardSession,
        *,
        summary: ValidationSummary | None = None,
    ) -> ExpressionMatrix:
        summary = summary or self.validate(session)
        if not summary.passed:
            raise PreparationBlocked(summary)
        header, _, feature_ids, sample_ids, matrix, annotation_rows = self._materialize(session.recipe, session.raw_table)
        prepared = session.project_dir / "prepared"
        prepared.mkdir(parents=True, exist_ok=True)
        matrix_path = prepared / "expression_matrix.tsv"
        feature_path = prepared / "feature_metadata.tsv"
        sample_path = prepared / "sample_metadata.tsv"
        recipe_path = session.project_dir / "preparation-recipe.json"
        reference_result = None
        if session.reference_path is not None:
            reference_result = ReferenceService().resolve(ReferenceRequest(
                tuple(feature_ids),
                species_taxid=session.recipe.species_taxid,
                source_paths=(session.reference_path,),
            ))
        annotation_headers = [
            header[index].strip() if index < len(header) and header[index].strip() else f"annotation_{index + 1}"
            for index in session.recipe.annotation_columns
        ]
        has_gene_symbol = any(value.casefold() in {"gene_symbol", "gene symbol", "symbol", "gene"} for value in annotation_headers)
        if reference_result is not None and reference_result.mapping and not has_gene_symbol:
            annotation_headers.append("gene_symbol")
        with matrix_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
            writer.writerow(["feature_key", *sample_ids])
            writer.writerows([[feature_id, *values] for feature_id, values in zip(feature_ids, matrix)])
        with feature_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
            writer.writerow(["feature_key", "original_id", *annotation_headers])
            for feature_id, annotations in zip(feature_ids, annotation_rows):
                values = list(annotations)
                if reference_result is not None and reference_result.mapping and not has_gene_symbol:
                    values.append(";".join(reference_result.mapping.get(feature_id, ())))
                writer.writerow([feature_id, feature_id, *values])
        geo_accessions: tuple[str, ...] = ()
        geo_titles: tuple[str, ...] = ()
        platform_id: str | None = None
        if session.asset.kind == "GEO_SERIES_MATRIX":
            geo = session.geo_matrix or GeoSeriesMatrixReader().read(session.asset.source_paths[0])
            if len(geo.sample_accessions) == len(sample_ids):
                geo_accessions = geo.sample_accessions
            if len(geo.sample_titles) == len(sample_ids):
                geo_titles = geo.sample_titles
            unique_platforms = tuple(dict.fromkeys(geo.platform_ids))
            if len(unique_platforms) == 1:
                platform_id = unique_platforms[0]
        geo_extra: dict[str, tuple[str, ...]] = {}
        if session.asset.kind == "GEO_SERIES_MATRIX":
            geo_extra = {
                key: values for key, values in geo.sample_metadata.items()
                if len(values) == len(sample_ids)
                and key not in {"geo_accession", "title", "platform_id"}
            }
        with sample_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
            sample_headers = ["sample_id"]
            if geo_accessions:
                sample_headers.append("geo_accession")
            if geo_titles:
                sample_headers.append("sample_title")
            if platform_id:
                sample_headers.append("platform_id")
            sample_headers.extend(geo_extra)
            writer.writerow(sample_headers)
            for index, sample_id in enumerate(sample_ids):
                row = [sample_id]
                if geo_accessions:
                    row.append(geo_accessions[index])
                if geo_titles:
                    row.append(geo_titles[index])
                if platform_id:
                    row.append(platform_id)
                row.extend(values[index] for values in geo_extra.values())
                writer.writerow(row)
        recipe_payload = session.recipe.as_dict()
        recipe_path.write_text(json.dumps(recipe_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        recipe_id = __import__("hashlib").sha256(json.dumps(recipe_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        matrix_id = str(uuid4())
        project_manifest = session.project_dir / "project.json"
        source_path = session.asset.source_paths[0]
        source_modality = (
            "MICROARRAY"
            if session.geo_matrix is not None
            and {value.strip().casefold() for value in session.geo_matrix.series_types if value.strip()}
            == {"expression profiling by array"}
            else None
        )
        project_manifest.write_text(json.dumps({
            "project_id": persisted_local_path(session.project_dir.name),
            "project_id_redacted": may_contain_sensitive_metadata(session.project_dir.name),
            "matrix_id": matrix_id,
            "source_asset_id": session.asset.asset_id,
            "source_path": persisted_local_path(source_path),
            "source_path_redacted": may_contain_sensitive_metadata(source_path),
            "source_asset": session.asset.as_dict(),
            "preparation_recipe": persisted_local_path(recipe_path),
            "fact_confirmations": recipe_payload.get("fact_confirmations", []),
            "reported_transform": recipe_payload.get("reported_transform", ""),
            "matrix_content_hash": sha256_file(matrix_path),
            "reference_result": persisted_local_path(session.project_dir / "references" / "reference-result.json") if reference_result is not None else None,
            "platform_id": platform_id,
            "series_types": list(session.geo_matrix.series_types) if session.geo_matrix else [],
            "source_modality": source_modality,
            "feature_id_type": self._feature_id_type(feature_ids),
            "sample_metadata": persisted_local_path(sample_path),
            "validation": summary.as_dict(),
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if reference_result is not None:
            references_dir = session.project_dir / "references"
            references_dir.mkdir(parents=True, exist_ok=True)
            (references_dir / "reference-result.json").write_text(json.dumps({
                "status": reference_result.status.value,
                "provider": reference_result.provider,
                "species_taxid": reference_result.species_taxid,
                "platform_id": reference_result.platform_id,
                "checksum": reference_result.checksum,
                "coverage": reference_result.coverage,
                "ambiguous_count": reference_result.ambiguous_count,
                "unmapped_count": reference_result.unmapped_count,
                "guide_zh": reference_result.guide_zh,
                "release": reference_result.release,
                "retrieved_at": reference_result.retrieved_at,
                "request": {
                    "feature_ids_count": len(reference_result.request.feature_ids),
                    "species_taxid": reference_result.request.species_taxid,
                    "platform_id": reference_result.request.platform_id,
                    "source_paths": [persisted_local_path(path) for path in reference_result.request.source_paths],
                } if reference_result.request else None,
                "mapping": reference_result.mapping,
            }, ensure_ascii=False, indent=2, default=list) + "\n", encoding="utf-8")
        content_hash = sha256_file(matrix_path)
        matrix_ref = MatrixStoreRef(matrix_path, "dense-tsv", "float64", (summary.feature_count, summary.sample_count), content_hash)
        feature_ref = MatrixStoreRef(feature_path, "table-tsv", "string", (summary.feature_count, 2 + len(annotation_headers)), sha256_file(feature_path))
        sample_ref = MatrixStoreRef(
            sample_path,
            "table-tsv",
            "string",
            (summary.sample_count, 1 + int(bool(geo_accessions)) + int(bool(geo_titles)) + int(bool(platform_id))),
            sha256_file(sample_path),
        )
        return ExpressionMatrix(
            matrix_id, matrix_ref, feature_ref, sample_ref, ObservationUnit.BULK_SAMPLE,
            session.recipe.measurement_type, session.recipe.value_scale, session.recipe.input_transform,
            self._feature_id_type(feature_ids), session.recipe.species_taxid, (session.asset.asset_id,), recipe_id,
            summary, content_hash,
            measurement_provenance=self._measurement_provenance(session.recipe.fact_confirmations),
            platform_id=platform_id,
            source_modality=source_modality,
        )

    @staticmethod
    def _measurement_provenance(confirmations: tuple[Mapping[str, Any], ...]) -> str:
        """区分关联文字候选和无关联来源文字的手动选择。"""
        entries: list[str] = []
        for item in confirmations:
            fact_key = str(item.get("fact_key", "")).strip()
            selected = str(item.get("selected_value", "")).strip()
            if not fact_key or not selected or selected == "UNKNOWN":
                continue
            status = str(item.get("status", ""))
            if status == "user_confirmed_without_direct_text":
                source = "manual_without_direct_text"
            elif status in {"user_confirmed_text_candidate", "user_resolved_conflicting_text"}:
                source = "linked_text_candidate"
            elif status == "user_overrode_text_candidate":
                source = "manual_override_of_text_candidate"
            else:
                source = status or "unspecified_confirmation"
            entries.append(f"{fact_key}={selected}[{source}]")
        provenance = "user-selected input facts: " + ("; ".join(entries) if entries else "no confirmed values")
        scale_confirmed = any(
            item.get("fact_key") == "value_scale"
            and item.get("selected_value") == ValueScale.LOG2.value
            and item.get("status") != "not_confirmed"
            for item in confirmations
        )
        if scale_confirmed:
            provenance += "; user-confirmed value_scale=LOG2"
        return provenance

    @staticmethod
    def _formula_issues(session: WizardSession) -> list[Issue]:
        """只读取 Excel 缓存值，不执行公式；无缓存值时阻断。"""
        if not session.raw_table.formula_cells:
            return []
        issues: list[Issue] = []
        missing: list[str] = []
        for coordinate in session.raw_table.formula_cells:
            match = re.fullmatch(r"([A-Z]+)([0-9]+)", coordinate.upper())
            if match is None:
                continue
            column = 0
            for letter in match.group(1):
                column = column * 26 + ord(letter) - ord("A") + 1
            row = int(match.group(2))
            cached = session.raw_table.rows[row - 1][column - 1] if row <= len(session.raw_table.rows) and column <= len(session.raw_table.rows[row - 1]) else ""
            if not cached.strip():
                missing.append(coordinate)
        if missing:
            issues.append(Issue(
                "FORMULA_WITHOUT_CACHE",
                IssueSeverity.BLOCKING,
                f"Excel 中发现没有缓存结果的公式单元格：{', '.join(missing[:8])}。软件不会执行这些公式。",
                "请在 Excel 中重新计算并保存，或导出为纯数值 CSV/TSV",
            ))
        else:
            issues.append(Issue(
                "FORMULA_CACHE_READ_ONLY",
                IssueSeverity.WARNING,
                f"Excel 中发现 {len(session.raw_table.formula_cells)} 个公式单元格；本次只读取文件内已有缓存值，不执行公式。",
                "如需可重放结果，建议导出为纯数值 CSV/TSV",
            ))
        return issues

    @staticmethod
    def candidate_header_rows(rows: tuple[tuple[str, ...], ...] | list[tuple[str, ...]]) -> list[int]:
        scored: list[tuple[float, int]] = []
        for index, row in enumerate(rows[:30]):
            nonempty = [value.strip() for value in row if value.strip()]
            if len(nonempty) < 2:
                continue
            unique_bonus = len(set(nonempty)) / len(nonempty)
            text_score = sum(not PreparationService._is_number(value) for value in nonempty) / len(nonempty)
            scored.append((text_score * 0.7 + unique_bonus * 0.3, index))
        return [index for _, index in sorted(scored, reverse=True)[:5]]

    def _materialize(
        self,
        recipe: PreparationRecipe,
        raw: RawTable,
        *,
        cancelled: Callable[[], bool] | None = None,
    ):
        rows = self._view_rows(raw.rows, recipe.transpose, cancelled=cancelled)
        if recipe.header_row >= len(rows):
            raise ValueError("表头行超出表格范围")
        header = list(rows[recipe.header_row])
        if not header:
            raise ValueError("表头为空")
        data_rows = rows[recipe.data_start_row:]
        sample_ids = [header[index].strip() if index < len(header) else "" for index in recipe.sample_columns]
        feature_ids: list[str] = []
        matrix: list[list[str]] = []
        annotations: list[list[str]] = []
        for index, row in enumerate(data_rows):
            if index % 128 == 0:
                self._raise_if_cancelled(cancelled)
            feature_ids.append(row[recipe.feature_id_column].strip() if recipe.feature_id_column < len(row) else "")
            matrix.append([row[index].strip() if index < len(row) else "" for index in recipe.sample_columns])
            annotations.append([row[index].strip() if index < len(row) else "" for index in recipe.annotation_columns])
        return header, data_rows, feature_ids, sample_ids, matrix, annotations

    @staticmethod
    def _view_rows(
        rows: tuple[tuple[str, ...], ...],
        transpose: bool,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> tuple[tuple[str, ...], ...]:
        if not transpose:
            return rows
        width = max((len(row) for row in rows), default=0)
        transposed: list[tuple[str, ...]] = []
        for column in range(width):
            PreparationService._raise_if_cancelled(cancelled)
            transposed.append(
                tuple(
                    rows[row_index][column] if column < len(rows[row_index]) else ""
                    for row_index in range(len(rows))
                )
            )
        return tuple(transposed)

    @staticmethod
    def _raise_if_cancelled(cancelled: Callable[[], bool] | None) -> None:
        if cancelled is not None and cancelled():
            raise PreparationCancelled("用户已取消完整校验")

    @staticmethod
    def _patch_recipe(recipe: PreparationRecipe, patch: Mapping[str, Any]) -> PreparationRecipe:
        values = dict(patch)
        for key in ("sample_columns", "annotation_columns", "ignored_columns", "sample_ids"):
            if key in values:
                values[key] = tuple(int(item) for item in values[key])
        if "fact_confirmations" in values:
            values["fact_confirmations"] = tuple(dict(item) for item in values["fact_confirmations"])
        for key, enum_type in (("measurement_type", MeasurementType), ("value_scale", ValueScale)):
            if key in values and not isinstance(values[key], enum_type):
                values[key] = enum_type(values[key])
        allowed = {field for field in PreparationRecipe.__dataclass_fields__ if field != "asset_id" and field != "source_path" and field != "sheet_name"}
        return replace(recipe, **{key: value for key, value in values.items() if key in allowed})

    @staticmethod
    def _numeric_columns(rows: tuple[tuple[str, ...], ...], start: int, width: int) -> list[int]:
        result = []
        headers = rows[start - 1] if start > 0 and start - 1 < len(rows) else ()
        for column in range(width):
            header = headers[column].strip().casefold() if column < len(headers) else ""
            if any(token in header for token in ("detection pval", "detection p-value", "detection_pval", "pvalue", "p-value")):
                continue
            if PreparationService._is_numeric_annotation_header(header):
                continue
            values = [row[column].strip() for row in rows[start:start + 20] if column < len(row) and row[column].strip()]
            numeric = sum(PreparationService._is_number(value) for value in values)
            if values and numeric / len(values) >= 0.7:
                result.append(column)
        return result

    @staticmethod
    def _is_numeric_annotation_header(header: str) -> bool:
        """识别少量公认数值注释名；宽松匹配常见分隔符，不匹配样本名。"""
        normalized = re.sub(r"[^a-z0-9]+", "_", header.strip().casefold()).strip("_")
        return normalized in PreparationService._NUMERIC_ANNOTATION_HEADERS

    @staticmethod
    def _feature_id_column(rows: tuple[tuple[str, ...], ...], start: int, width: int, samples: list[int]) -> int:
        for column in range(width):
            if column in samples:
                continue
            values = [row[column].strip() for row in rows[start:start + 20] if column < len(row) and row[column].strip()]
            if values and len(set(values)) / len(values) >= 0.8:
                return column
        return 0

    @staticmethod
    def _is_number(value: str) -> bool:
        try:
            return math.isfinite(float(value))
        except ValueError:
            return False

    @staticmethod
    def _feature_id_type(feature_ids: list[str]) -> str:
        nonempty = [value for value in feature_ids if value]
        if not nonempty:
            return "CUSTOM_ORIGINAL"
        if sum(value.upper().split(".", 1)[0].startswith("ENSG") for value in nonempty) / len(nonempty) >= 0.8:
            return "ENSEMBL_GENE"
        if sum(value.isdigit() for value in nonempty) / len(nonempty) >= 0.8:
            return "ENTREZ_OR_NUMERIC"
        if sum(value.upper().startswith("GSM") for value in nonempty) / len(nonempty) >= 0.8:
            return "GEO_SAMPLE_ID"
        return "CUSTOM_ORIGINAL"

    @staticmethod
    def _dedupe_issues(issues: list[Issue]) -> list[Issue]:
        seen: set[tuple[str, str]] = set()
        result = []
        for issue in issues:
            key = (issue.code, issue.message_zh)
            if key not in seen:
                seen.add(key)
                result.append(issue)
        return result
