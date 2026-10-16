from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from rnaseq_helper.analysis.planning import PlanningService
from rnaseq_helper.analysis.result_filter import summarize_result
from rnaseq_helper.domain.models import ExpressionMatrix, JobContext, ResultFilterConfig, sha256_file
from rnaseq_helper.services.project_lock import project_directory_lock


class ResultFilterService:
    """Refresh report and filter-dependent figures from saved results without invoking R."""

    def refresh(
        self,
        matrix: ExpressionMatrix,
        plan_data: dict[str, Any],
        config: ResultFilterConfig,
        context: JobContext,
    ) -> dict[str, Any]:
        from rnaseq_helper.analysis.service import AnalysisService, OutputPublishRollbackError
        from rnaseq_helper.services.plot_service import PlotService
        from rnaseq_helper.services.report_service import ReportService

        plan = PlanningService().restore(plan_data)
        project_dir = matrix.values.path.parent.parent.resolve(strict=True)
        with project_directory_lock(project_dir):
            if sha256_file(matrix.values.path) != plan.matrix_hash:
                raise ValueError("表达矩阵已变化，不能用旧结果刷新筛选")
            plan_path = project_dir / "analysis" / "analysis-plan.json"
            result_path = project_dir / "analysis" / "deg-result.json"
            report_manifest_path = project_dir / "reports" / "analysis-manifest.json"
            for path in (plan_path, result_path, report_manifest_path):
                if path.is_symlink() or not path.is_file():
                    raise ValueError("项目缺少完整的已保存分析结果，未更新筛选显示")
            manifest = self._read_json(report_manifest_path)
            if (
                manifest.get("analysis_plan_hash") != sha256_file(plan_path)
                or manifest.get("deg_result_hash") != sha256_file(result_path)
            ):
                raise ValueError("项目分析文件校验未通过；为保护现有结果，没有更新筛选")
            expected_filter_hash = manifest.get("result_filter_hash")
            saved_filter_path = project_dir / "analysis" / "result-filter.json"
            if expected_filter_hash is not None and (
                saved_filter_path.is_symlink()
                or not saved_filter_path.is_file()
                or sha256_file(saved_filter_path) != str(expected_filter_hash)
            ):
                raise ValueError("项目当前筛选设置校验未通过；为保护现有结果，没有更新筛选")
            saved_result = self._read_json(result_path)
            rows = saved_result.get("table")
            if not isinstance(rows, list) or not rows:
                raise ValueError("已保存结果表为空或无法读取")
            active_plan = replace(plan, result_filter=config)
            saved_result["active_result_filter"] = config.as_dict()
            saved_result["display_summary"] = summarize_result(rows, config)

            staging = Path(tempfile.mkdtemp(prefix=".result-filter-staging-", dir=project_dir))
            preserve_staging = False
            try:
                AnalysisService._write_transaction_journal(
                    staging,
                    AnalysisService._new_transaction_journal(project_dir, phase="preparing"),
                )
                for relative in AnalysisService.OUTPUT_RELATIVE_PATHS:
                    source = project_dir / relative
                    target = staging / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if source.is_file() and not source.is_symlink():
                        shutil.copy2(source, target)
                    elif relative.as_posix() == "analysis/result-filter.json":
                        target.write_text(json.dumps(config.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    elif relative.as_posix() == "analysis/gene-annotations.tsv":
                        target.write_text("feature_key\tgene_symbol\n", encoding="utf-8")
                    else:
                        raise FileNotFoundError(f"项目缺少结果产物：{relative}")
                (staging / "analysis" / "result-filter.json").write_text(
                    json.dumps(config.as_dict(), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                context.emit("filter", None, "正在按新筛选条件刷新结果摘要、火山图和报告；不会重跑统计模型")
                figures = PlotService.refresh_filter_dependent(
                    matrix, active_plan, saved_result, staging / "figures",
                )
                ReportService().build(
                    matrix,
                    active_plan,
                    saved_result,
                    figures=figures,
                    output_dir=staging / "reports",
                    project_dir=project_dir,
                    analysis_artifact_dir=staging / "analysis",
                )
                context.emit("publish", None, "正在安全更新筛选视图与报告")
                AnalysisService._publish_outputs(project_dir, staging, context.cancelled)
            except OutputPublishRollbackError:
                preserve_staging = True
                raise
            finally:
                if not preserve_staging and staging.exists():
                    shutil.rmtree(staging)
            return {
                "result_filter": config.as_dict(),
                "summary": saved_result["display_summary"],
                "report_path": str(project_dir / "reports" / "analysis-report.html"),
            }

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"无法读取项目文件 {path.name}：{exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"项目文件 {path.name} 格式不正确")
        return value
