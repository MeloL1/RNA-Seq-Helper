from __future__ import annotations

import csv
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping

from rnaseq_helper.analysis.planning import PlanningService
from rnaseq_helper.domain.models import ExpressionMatrix, JobContext, ResultFilterConfig, sha256_file
from rnaseq_helper.services.project_lock import project_directory_lock


class AnnotationService:
    """Apply identifier-to-symbol labels to saved results without refitting a model."""

    def apply(
        self,
        matrix: ExpressionMatrix,
        plan_data: Mapping[str, Any],
        mapping: Mapping[str, str],
        context: JobContext,
    ) -> dict[str, Any]:
        from rnaseq_helper.analysis.service import AnalysisService, OutputPublishRollbackError
        from rnaseq_helper.analysis.result_filter import summarize_result
        from rnaseq_helper.services.plot_service import PlotService
        from rnaseq_helper.services.report_service import ReportService

        plan = PlanningService().restore(plan_data)
        project_dir = matrix.values.path.parent.parent.resolve(strict=True)
        clean_mapping = {
            str(key).strip(): str(value).strip()
            for key, value in mapping.items()
            if str(key).strip() and str(value).strip()
        }
        if not clean_mapping:
            raise ValueError("没有可应用的 Gene ID 与 Gene Symbol 映射。")
        with project_directory_lock(project_dir):
            if sha256_file(matrix.values.path) != plan.matrix_hash:
                raise ValueError("表达矩阵已变化，不能对旧结果补充注释。")
            analysis_dir = project_dir / "analysis"
            result_path = analysis_dir / "deg-result.json"
            plan_path = analysis_dir / "analysis-plan.json"
            report_manifest_path = project_dir / "reports" / "analysis-manifest.json"
            for path in (result_path, plan_path, report_manifest_path):
                if path.is_symlink() or not path.is_file():
                    raise ValueError("项目缺少完整的已保存分析结果；没有修改项目。")
            report_manifest = self._read_json(report_manifest_path)
            if (
                report_manifest.get("analysis_plan_hash") != sha256_file(plan_path)
                or report_manifest.get("deg_result_hash") != sha256_file(result_path)
            ):
                raise ValueError("现有分析结果完整性核验失败；没有修改项目。")
            result = self._read_json(result_path)
            rows = result.get("table")
            if not isinstance(rows, list) or not rows:
                raise ValueError("保存的差异结果表为空或格式无效。")
            prior_path = analysis_dir / "gene-annotations.tsv"
            combined = AnalysisService._read_gene_annotation_overlay(prior_path) if prior_path.is_file() else {}
            combined.update(clean_mapping)
            matched_ids: set[str] = set()
            for row in rows:
                if not isinstance(row, dict):
                    continue
                key = str(row.get("feature_key") or row.get("original_id") or "")
                if key in combined:
                    row["gene_symbol"] = combined[key]
                if key in clean_mapping:
                    matched_ids.add(key)
            staging = Path(tempfile.mkdtemp(prefix=".annotation-staging-", dir=project_dir))
            preserve = False
            try:
                AnalysisService._write_transaction_journal(
                    staging, AnalysisService._new_transaction_journal(project_dir, phase="preparing"),
                )
                for relative in AnalysisService.OUTPUT_RELATIVE_PATHS:
                    source = project_dir / relative
                    target = staging / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if source.is_file() and not source.is_symlink():
                        shutil.copy2(source, target)
                    elif relative.as_posix() == "analysis/gene-annotations.tsv":
                        target.write_text("feature_key\tgene_symbol\n", encoding="utf-8")
                    else:
                        raise FileNotFoundError(f"项目缺少结果产物：{relative}")
                overlay = staging / "analysis" / "gene-annotations.tsv"
                with overlay.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
                    writer.writerow(("feature_key", "gene_symbol"))
                    writer.writerows(sorted(combined.items()))
                filter_path = staging / "analysis" / "result-filter.json"
                try:
                    active_filter = json.loads(filter_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    active_filter = plan.result_filter.as_dict()
                active_config = ResultFilterConfig.from_mapping(active_filter)
                result["active_result_filter"] = active_config.as_dict()
                result["display_summary"] = summarize_result(rows, active_config)
                AnalysisService._write_result(staging, plan, result)
                active_plan = PlanningService().restore({**dict(plan_data), "result_filter": active_filter})
                context.emit("annotation", None, "正在更新基因标签、相关图表、Excel 与 HTML；不会重跑统计模型")
                figures = PlotService.refresh_filter_dependent(
                    matrix, active_plan, result, staging / "figures",
                )
                ReportService().build(
                    matrix, active_plan, result, figures=figures,
                    output_dir=staging / "reports", project_dir=project_dir,
                    analysis_artifact_dir=staging / "analysis",
                )
                context.emit("publish", None, "正在安全发布注释更新")
                AnalysisService._publish_outputs(project_dir, staging, context.cancelled)
            except OutputPublishRollbackError:
                preserve = True
                raise
            finally:
                if not preserve and staging.exists():
                    shutil.rmtree(staging)
            return {
                "result": result,
                "matched_count": len(matched_ids),
                "unmatched_count": max(0, len(rows) - len(matched_ids)),
                "annotation_path": str(project_dir / "analysis" / "gene-annotations.tsv"),
            }

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"无法读取 {path.name}：{exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path.name} 格式无效。")
        return value
