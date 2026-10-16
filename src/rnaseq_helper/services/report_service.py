from __future__ import annotations

import html
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from rnaseq_helper.domain.models import AnalysisPlan, ExpressionMatrix, sha256_file


class ReportService:
    """生成不依赖网络的 HTML 和 XLSX 结果包。"""

    RESULT_EXPORT_COLUMNS = (
        "feature_key",
        "gene_symbol",
        "log2FoldChange",
        "pvalue",
        "padj",
    )
    MISSING_VALUE = "NA"

    def build(
        self,
        matrix: ExpressionMatrix,
        plan: AnalysisPlan,
        result: dict[str, Any],
        figures: dict[str, Path] | None = None,
        output_dir: Path | None = None,
        project_dir: Path | None = None,
        analysis_artifact_dir: Path | None = None,
    ) -> dict[str, Path]:
        project_dir = Path(project_dir) if project_dir is not None else matrix.values.path.parent.parent
        report_dir = Path(output_dir) if output_dir is not None else project_dir / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        html_path = report_dir / "analysis-report.html"
        xlsx_path = report_dir / "deg-results.xlsx"
        manifest_path = report_dir / "analysis-manifest.json"
        interpretation_path = report_dir / "interpretation-zh.txt"
        interpretation = self._interpretation(matrix, plan, result)
        project_manifest = self._read_json(project_dir / "project.json")
        analysis_artifact_dir = (
            Path(analysis_artifact_dir)
            if analysis_artifact_dir is not None
            else project_dir / "analysis"
        )
        self._write_html(html_path, matrix, plan, result, figures or {}, interpretation, project_manifest)
        self._write_xlsx(xlsx_path, matrix, plan, result, interpretation, project_manifest)
        interpretation_path.write_text(interpretation + "\n", encoding="utf-8")
        figure_hashes = {
            path.name: sha256_file(path)
            for path in (figures or {}).values()
        }
        figure_manifest_path = (
            next(iter((figures or {}).values())).parent / "figure-manifest.json"
            if figures else None
        )
        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "html": "reports/" + html_path.name,
            "xlsx": "reports/" + xlsx_path.name,
            "interpretation_zh": "reports/" + interpretation_path.name,
            "analysis_plan": "analysis/analysis-plan.json",
            "preparation_recipe": "preparation-recipe.json",
            "method_profile_id": plan.method_profile_id,
            "source_modality": matrix.source_modality or project_manifest.get("source_modality"),
            "matrix_hash": matrix.content_hash,
            "feature_metadata_hash": sha256_file(matrix.feature_metadata.path),
            "sample_metadata_hash": sha256_file(matrix.sample_metadata.path),
            "preparation_recipe_hash": (
                sha256_file(project_dir / "preparation-recipe.json")
                if (project_dir / "preparation-recipe.json").is_file() else None
            ),
            "analysis_plan_hash": sha256_file(analysis_artifact_dir / "analysis-plan.json"),
            "deg_result_hash": sha256_file(analysis_artifact_dir / "deg-result.json"),
            "html_hash": sha256_file(html_path),
            "xlsx_hash": sha256_file(xlsx_path),
            "figure_manifest_hash": (
                sha256_file(figure_manifest_path)
                if figure_manifest_path is not None and figure_manifest_path.is_file()
                else None
            ),
            "figure_hashes": figure_hashes,
            "source_path": project_manifest.get("source_path"),
            "platform_id": matrix.platform_id or project_manifest.get("platform_id"),
            "reference_result": project_manifest.get("reference_result"),
            "measurement_provenance": matrix.measurement_provenance,
            "figures": {
                key: "figures/" + path.name
                for key, path in (figures or {}).items()
            },
            "result_issues": result.get("issues", []),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"html": html_path, "xlsx": xlsx_path, "interpretation_zh": interpretation_path, "manifest": manifest_path}

    @staticmethod
    def _write_html(path: Path, matrix: ExpressionMatrix, plan: AnalysisPlan, result: dict[str, Any], figures: dict[str, Path], interpretation: str, project_manifest: dict[str, Any]) -> None:
        summary = result.get("summary", {})
        rows = result.get("table", [])
        headers = list(rows[0].keys()) if rows else []
        body_rows = []
        for row in rows:
            body_rows.append(
                "<tr>"
                + "".join(
                    f"<td>{ReportService._html_result_value(row.get(header))}</td>"
                    for header in headers
                )
                + "</tr>"
            )
        summary_items = "".join(
            f"<li>{html.escape(str(key))}: {html.escape(str(value))}</li>"
            for key, value in summary.items()
        )
        limitations = "".join(f"<li>{html.escape(item)}</li>" for item in plan.limitations_zh)
        warnings = "".join(f"<li>{html.escape(item)}</li>" for item in plan.warnings) or "<li>无额外告警</li>"
        result_issues = "".join(
            f"<li>{html.escape(str(issue.get('severity', 'WARNING')))}：{html.escape(str(issue.get('message_zh', issue)))}</li>"
            if isinstance(issue, dict) else f"<li>{html.escape(str(issue))}</li>"
            for issue in result.get("issues", [])
        ) or "<li>worker 未返回额外告警</li>"
        parameter_items = "".join(
            f"<li>{html.escape(str(key))}: {html.escape(json.dumps(value, ensure_ascii=False, default=str) if isinstance(value, (dict, list, tuple)) else str(value))}</li>"
            for key, value in result.get("parameters", {}).items()
        ) or "<li>worker 未返回参数</li>"
        diagnostic_items = "".join(
            f"<li>{html.escape(ReportService._diagnostic_label(key))}: {html.escape(ReportService._format_diagnostic_value(key, value))}</li>"
            for key, value in result.get("diagnostics", {}).items()
        ) or "<li>worker 未返回诊断</li>"
        runtime_items = "".join(
            f"<li>{html.escape(str(key))}: {html.escape(str(value))}</li>"
            for key, value in result.get("runtime", {}).items()
        ) or "<li>worker 未返回版本信息</li>"
        contrast = plan.contrast if isinstance(plan.contrast, dict) else {}
        control_group = str(contrast.get("control", "")).strip()
        test_group = str(contrast.get("test", "")).strip()
        contrast_description = (
            f"对比方向：{test_group} − {control_group}（正值表示测试组在模型尺度上高于对照组）"
            if control_group and test_group
            else "对比方向：分析计划未记录完整的测试组与对照组，无法从报告确认"
        )
        transform_description = ReportService._transform_description(plan, project_manifest)
        assignments = plan.design.get("assignments", {})
        subjects = plan.design.get("paired_subjects", {})
        batches = plan.design.get("batch", {})
        subject_aliases = ReportService._factor_aliases(subjects, "个体")
        batch_aliases = ReportService._factor_aliases(batches, "批次")
        assignment_items = "".join(
            "<li>" + html.escape(str(sample)) + ": " + html.escape(str(group))
            + (f"；配对个体 {html.escape(subject_aliases[subjects[sample]])}"
               if sample in subjects and str(subjects[sample]).strip() else "")
            + (f"；{html.escape(batch_aliases[batches[sample]])}"
               if sample in batches and str(batches[sample]).strip() else "")
            + "</li>"
            for sample, group in assignments.items()
        ) or "<li>无样本分组记录</li>"
        replicate_structure_labels = {
            "independent": "已确认不同个体/独立生物样本",
            "paired": "已确认同一对象的配对/重复测量",
            "cell": "细胞/细胞核级（当前版本不支持直接分析）",
            "unknown": "未知或未确认",
        }
        replicate_structure = replicate_structure_labels.get(
            str(plan.design.get("replicate_structure", "")), "旧计划未记录样本独立性/配对确认",
        )
        factor_privacy_note = (
            "<p>报告中的配对个体与批次已用匿名序号替代原标签；相同原标签仍对应相同序号。</p>"
            if subject_aliases or batch_aliases else ""
        )
        contrast_groups = tuple(
            group for group in (plan.contrast.get("control"), plan.contrast.get("test"))
            if group not in (None, "")
        )
        included_counts = {
            group: sum(assigned_group == group for assigned_group in assignments.values())
            for group in contrast_groups
        }
        if assignments and contrast_groups:
            analyzed_samples = sum(included_counts.values())
            sample_usage = (
                f"分析纳入样本：{analyzed_samples}（"
                + "；".join(f"{html.escape(str(group))} {count}" for group, count in included_counts.items())
                + "）；未纳入的样本不参与本次统计。"
            )
        else:
            sample_usage = "分析纳入样本：无法从保存的分组计划确认。"
        figure_links = "".join(
            f"<li><a href=\"../figures/{html.escape(figure_path.name)}\">{html.escape(key)}</a>"
            f"<br><img src=\"../figures/{html.escape(figure_path.name)}\" alt=\"{html.escape(key)}\" style=\"max-width:760px;width:100%;height:auto\"></li>"
            for key, figure_path in figures.items()
        )
        provenance_items = "".join(
            f"<li>{html.escape(str(key))}: {html.escape(str(value))}</li>"
            for key, value in {
                "来源文件": project_manifest.get("source_path", ""),
                "平台": matrix.platform_id or project_manifest.get("platform_id", ""),
                "来源平台类别": matrix.source_modality or project_manifest.get("source_modality", ""),
                "参考结果": project_manifest.get("reference_result", "未使用本地参考表"),
                "单位/尺度选择记录": matrix.measurement_provenance or "未记录来源证据",
            }.items()
            if value
        )
        validation = project_manifest.get("validation", {})
        validation_items = "".join(
            f"<li>{html.escape(str(issue.get('severity', 'INFO')))}：{html.escape(str(issue.get('message_zh', issue)))}</li>"
            if isinstance(issue, dict) else f"<li>{html.escape(str(issue))}</li>"
            for issue in validation.get("issues", [])
        ) or "<li>整理验证无额外记录</li>"
        document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>RNA-Seq Helper 分析报告</title>
<style>body{{font-family:-apple-system,BlinkMacSystemFont,"Helvetica Neue",Arial,sans-serif;color:#111;max-width:1400px;margin:32px auto;padding:0 24px}}h1{{font-size:24px}}h2{{font-size:17px;margin-top:28px;border-bottom:1px solid #bbb;padding-bottom:6px}}table{{border-collapse:collapse;width:100%;font-size:12px}}th{{background:#243b53;color:#fff;text-align:left;position:sticky;top:0}}th,td{{padding:5px 7px;border-bottom:1px solid #ddd;white-space:nowrap}}.note{{background:#fff7d6;padding:10px;border-left:4px solid #c28a00}}</style></head>
<body><h1>RNA-Seq Helper 分析报告</h1>
<p>本报告基于本地项目中的已整理表达矩阵，HTML 不依赖远程脚本或网络资源。</p>
<h2>本次分析</h2><ul><li>方法：{html.escape(plan.method)}</li><li>Profile：{html.escape(plan.method_profile_id)}</li><li>{html.escape(contrast_description)}</li><li>样本关系：{html.escape(replicate_structure)}</li><li>完整矩阵：{matrix.values.shape[0]} 个特征 × {matrix.values.shape[1]} 个样本列</li><li>{sample_usage}</li><li>矩阵哈希：{html.escape(matrix.content_hash)}</li></ul>
<h2>结果摘要</h2><ul>{summary_items}</ul>
<div class="note">模型效应是组间模型尺度差异，不等同于原尺度算术均值之比。NA 保留，并在 reason_not_tested 中记录原因。</div>
<h2>方法与限制</h2><p>{html.escape(plan.method_reason_zh)}</p><p>{html.escape(transform_description)}</p><ul>{limitations}</ul>
<h2>来源与参考</h2><ul>{provenance_items or "<li>未记录额外来源信息</li>"}</ul>
<h2>整理验证</h2><ul>{validation_items}</ul>
<h2>中文解读（审计模板）</h2><pre>{html.escape(interpretation)}</pre>
<h2>样本安排</h2><ul>{assignment_items}</ul>
{factor_privacy_note}
<h2>实际参数与运行版本</h2><ul>{parameter_items}</ul><ul>{runtime_items}</ul>
<h2>质量诊断与告警</h2><ul>{diagnostic_items}</ul><ul>{warnings}</ul><ul>{result_issues}</ul>
<h2>图表</h2><ul>{figure_links}</ul>
<h2>完整结果表</h2><table><thead><tr>{"".join(f"<th>{html.escape(header)}</th>" for header in headers)}</tr></thead><tbody>{"".join(body_rows)}</tbody></table>
</body></html>"""
        path.write_text(document, encoding="utf-8")

    @staticmethod
    def _write_xlsx(path: Path, matrix: ExpressionMatrix, plan: AnalysisPlan, result: dict[str, Any], interpretation: str, project_manifest: dict[str, Any]) -> None:
        workbook = Workbook()
        result_sheet = workbook.active
        result_sheet.title = "DEG Results"
        rows = result.get("table", [])
        result_sheet.append(list(ReportService.RESULT_EXPORT_COLUMNS))
        for row in rows:
            result_sheet.append([
                ReportService._export_result_value(row.get(column))
                for column in ReportService.RESULT_EXPORT_COLUMNS
            ])
        result_sheet.freeze_panes = "A2"
        result_sheet.auto_filter.ref = result_sheet.dimensions

        result_sheet.sheet_view.showGridLines = False
        header_fill = PatternFill("solid", fgColor="243B53")
        for cell in result_sheet[1]:
            cell.fill = header_fill
            cell.font = Font(color="FFFFFF", bold=True)
            cell.alignment = Alignment(horizontal="center", vertical="center")
        for column_cells in result_sheet.columns:
            width = min(48, max(12, max(len(str(cell.value or "")) for cell in column_cells) + 2))
            result_sheet.column_dimensions[get_column_letter(column_cells[0].column)].width = width
        workbook.save(path)

    @classmethod
    def _export_result_value(cls, value: Any) -> Any:
        """将结果表中的缺失值写成可读的 NA，而不是空单元格。"""
        if value is None:
            return cls.MISSING_VALUE
        if isinstance(value, (int, float)) and not isinstance(value, bool) and not math.isfinite(value):
            return cls.MISSING_VALUE
        if isinstance(value, str) and not value.strip():
            return cls.MISSING_VALUE
        return value

    @classmethod
    def _html_result_value(cls, value: Any) -> str:
        """HTML 与 XLSX 对缺失值使用同一呈现规则，并进行 HTML 转义。"""
        return html.escape(str(cls._export_result_value(value)))

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _diagnostic_label(key: str) -> str:
        return {
            "residual_df": "残差自由度（每个特征）",
        }.get(key, key)

    @staticmethod
    def _factor_aliases(values: Any, prefix: str) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for value in values.values() if isinstance(values, dict) else ():
            key = str(value).strip()
            if key and key not in aliases:
                aliases[key] = f"{prefix}{len(aliases) + 1}"
        return aliases

    @staticmethod
    def _format_diagnostic_value(key: str, value: Any) -> str:
        if key == "residual_df" and isinstance(value, (list, tuple)) and value:
            unique = list(dict.fromkeys(value))
            if len(unique) == 1:
                return f"{unique[0]}（所有特征相同）"
        if isinstance(value, (dict, list, tuple)):
            return json.dumps(value, ensure_ascii=False, default=str)
        return str(value)

    @staticmethod
    def _interpretation(matrix: ExpressionMatrix, plan: AnalysisPlan, result: dict[str, Any]) -> str:
        summary = result.get("summary", {})
        significant = int(summary.get("significant_magnitude_count", 0) or 0)
        tested = int(summary.get("tested_count", 0) or 0)
        direction = f"上调 {summary.get('up_count', 0)} 个、下调 {summary.get('down_count', 0)} 个"
        if significant:
            finding = f"在预设 FDR<{plan.config.fdr_threshold} 且 |模型效应|≥{plan.config.lfc_threshold} 的规则下，共有 {significant} 个特征达到筛选条件（{direction}）。"
        else:
            finding = f"在预设 FDR<{plan.config.fdr_threshold} 且 |模型效应|≥{plan.config.lfc_threshold} 的规则下，没有特征同时达到筛选条件。"
        basis = "原始 count 计数模型（DESeq2）" if plan.analysis_basis == "raw_count" else "标准化表达值的 log 表达模型（limma-trend）"
        contrast = plan.contrast if isinstance(plan.contrast, dict) else {}
        control_group = str(contrast.get("control", "")).strip()
        test_group = str(contrast.get("test", "")).strip()
        contrast_direction = (
            f"对比方向：{test_group} − {control_group}；正值表示测试组在模型尺度上高于对照组。"
            if control_group and test_group
            else "对比方向：分析计划未记录完整的测试组与对照组，方向无法核实。"
        )
        limitation = "本分析基于标准化值，未使用原始计数中的测序深度和计数精度信息。" if plan.analysis_basis != "raw_count" else "结果依赖原始 count 的实验设计、独立重复和异常值处理；NA 保留其未检验原因。"
        worker_warnings = [
            str(issue.get("message_zh", issue)) if isinstance(issue, dict) else str(issue)
            for issue in result.get("issues", [])
        ]
        warning_line = f"运行告警：{'；'.join(worker_warnings)}" if worker_warnings else "运行告警：无"
        return "\n".join([
            "本段为软件生成的可审计中文解读模板，不替代实验或临床判断。",
            f"分析基础：{basis}；本次有效检验特征数：{tested}。",
            contrast_direction,
            finding,
            "模型效应表示对比方向上的模型尺度差异，不直接等同于原尺度算术均值之比，也不证明因果关系。",
            limitation,
            warning_line,
            "建议结合 PCA、样本相关性、热图、实验设计和独立验证共同解释；软件不会因图形分离不明显而自动删除样本。",
        ])

    @staticmethod
    def _transform_description(plan: AnalysisPlan, project_manifest: dict[str, Any]) -> str:
        plan_preprocessing = getattr(plan, "preprocessing", {})
        preprocessing = plan_preprocessing if isinstance(plan_preprocessing, dict) else {}
        transform = str(preprocessing.get("transform", "")).strip()
        if transform == "log2(x+1)":
            threshold = preprocessing.get("filter_threshold")
            if threshold is None:
                return "软件本次对线性输入执行 log2(x+1) 变换；计划未记录过滤阈值。"
            return f"软件本次对线性输入先按 x≥{threshold} 过滤，再执行 log2(x+1)；未做额外重新标准化。"
        if transform == "already_log2":
            reported = str(project_manifest.get("reported_transform", "")).strip()
            if reported:
                return f"软件本次未再次取对数，直接拟合用户确认的 log2 尺度输入；来源文字记录的原始公式为：{reported}。"
            return "软件本次未再次取对数，直接拟合用户确认的 log2 尺度输入；项目未记录可核实的原文件公式，不能据此判断是否含伪计数。"
        if transform in {"none", ""} and plan.method == "DESEQ2":
            return "软件未对原始 count 做 log 变换；DESeq2 在计数模型中使用 size factor 处理样本测序深度差异。"
        if transform in {"none", ""}:
            return "软件本次未追加表达值变换；来源文件此前采用的变换公式未在此处推断。"
        return f"分析计划记录的变换标记为 {transform}；该标记不证明来源文件此前使用的具体公式。"
