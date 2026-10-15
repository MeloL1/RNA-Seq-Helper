from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any
from uuid import uuid4

from rnaseq_helper.domain.models import AnalysisPlan, ExpressionMatrix, JobContext
from rnaseq_helper.r_bridge.client import RBridgeClient
from rnaseq_helper.analysis.planning import PlanningService


class AnalysisService:
    """读取标准化 prepared/ 文件并通过 RBridge 执行已确认计划。"""

    def __init__(self, bridge: RBridgeClient | None = None) -> None:
        self.bridge = bridge or RBridgeClient()

    def run(self, matrix: ExpressionMatrix, plan: AnalysisPlan, context: JobContext) -> dict[str, Any]:
        if not plan.runnable:
            raise ValueError("分析计划包含阻断问题，不能运行")
        if plan.matrix_hash != matrix.content_hash:
            raise ValueError("表达矩阵已变化，当前分析计划失效")
        feature_ids, sample_ids, values = self._read_matrix(matrix.values.path)
        assignments = plan.design.get("assignments", {})
        active_indices = [
            index for index, sample_id in enumerate(sample_ids)
            if assignments.get(sample_id, "") in PlanningService.ACTIVE_GROUPS
        ]
        if len(active_indices) < 4:
            raise ValueError("纳入分析的样本少于 4 个；请至少保留两组、每组 2 个独立样本")
        sample_ids = [sample_ids[index] for index in active_indices]
        values = [[row[index] for index in active_indices] for row in values]
        groups = [assignments.get(sample_id, "") for sample_id in sample_ids]
        payload: dict[str, Any] = {
            "feature_ids": feature_ids,
            "sample_ids": sample_ids,
            "groups": groups,
            "control": plan.config.control_group,
            "test": plan.config.test_group,
            "fdr_threshold": plan.config.fdr_threshold,
            "lfc_threshold": plan.config.lfc_threshold,
            "method": plan.method,
            "measurement_type": matrix.measurement_type.value,
            "paired_subjects": plan.design.get("paired_subjects", {}),
            # R worker 的设计构造器使用 subject 这一项；保留上面的
            # paired_subjects 也便于协议/报告保留用户语义，但不能只传后者，
            # 否则配对信息会被静默忽略。
            "subject": plan.design.get("paired_subjects", {}),
            "batch": plan.design.get("batch", {}),
            "min_samples": plan.preprocessing.get("min_samples", 0),
            "gene_symbols": self._read_gene_symbols(matrix.feature_metadata.path, len(feature_ids)),
        }
        if plan.method == "DESEQ2":
            payload["counts"] = values
            method = "analyze_deseq2"
        else:
            payload["matrix"] = values
            payload["transform"] = plan.preprocessing.get("transform", "already_log2")
            payload["filter_threshold"] = plan.preprocessing.get("filter_threshold")
            method = "analyze_limma"
        response = self.bridge.run(method, payload, context, plan.method_profile_id)
        result = dict(response.result or {})
        expected = {"method": plan.method, "profile_id": plan.method_profile_id}
        if result.get("method") != expected["method"] or result.get("profile_id") != expected["profile_id"]:
            raise ValueError("R worker 返回的方法或 profile 与分析计划不一致")
        self._validate_parameters(plan, result.get("parameters", {}))
        self._validate_result_table(result.get("table"), feature_ids, plan)
        self._validate_plot_matrix(result.get("plot_matrix"), feature_ids, sample_ids)
        self._write_result(matrix.values.path.parent.parent, plan, result)
        from rnaseq_helper.services.plot_service import PlotService
        from rnaseq_helper.services.report_service import ReportService

        figures = PlotService().build(matrix, plan, result)
        ReportService().build(matrix, plan, result, figures)
        return result

    @staticmethod
    def _validate_plot_matrix(plot: Any, feature_ids: list[str], sample_ids: list[str]) -> None:
        """绘图输入由实际 runner 产生，不允许回退到原始计数。"""
        if not isinstance(plot, dict):
            raise ValueError("R worker 未返回已变换的绘图矩阵")
        returned_features = plot.get("feature_ids")
        if not isinstance(returned_features, list) or not returned_features:
            raise ValueError("绘图矩阵没有可用特征")
        known = set(feature_ids)
        if len(set(returned_features)) != len(returned_features) or any(value not in known for value in returned_features):
            raise ValueError("绘图矩阵特征编号重复或与输入不匹配")
        if plot.get("sample_ids") != sample_ids:
            raise ValueError("绘图矩阵样本顺序与输入不匹配")
        if not isinstance(plot.get("transform"), str) or not plot["transform"]:
            raise ValueError("绘图矩阵缺少转换说明")
        values = plot.get("values")
        if not isinstance(values, list) or len(values) != len(returned_features):
            raise ValueError("绘图矩阵特征数与数值行数不一致")
        for row in values:
            if not isinstance(row, list) or len(row) != len(sample_ids):
                raise ValueError("绘图矩阵样本数与数值列数不一致")
            if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) for value in row):
                raise ValueError("绘图矩阵含无效数值")

    @staticmethod
    def _validate_parameters(plan: AnalysisPlan, parameters: dict[str, Any]) -> None:
        if parameters.get("p_adjust_method") != "BH":
            raise ValueError("R worker 返回的多重校正方法与计划不一致")
        if plan.method == "DESEQ2":
            if parameters.get("independent_filtering") is not True:
                raise ValueError("DESeq2 worker 未明确返回独立过滤设置")
            if parameters.get("dispersion_estimation") not in {"trend", "gene-wise-fallback"}:
                raise ValueError("DESeq2 worker 返回了未知的离散度估计路径")
            if float(parameters.get("alpha", -1)) != float(plan.config.fdr_threshold):
                raise ValueError("DESeq2 worker 返回的 alpha 与分析计划不一致")
        else:
            expected_transform = plan.preprocessing.get("transform")
            if parameters.get("transform") != expected_transform:
                raise ValueError("R worker 返回的转换方式与分析计划不一致")
            if parameters.get("trend") is not True or parameters.get("robust") is not True:
                raise ValueError("limma worker 未返回固定的 trend/robust 参数")
            if parameters.get("winsor.tail.p") != [0.05, 0.1]:
                raise ValueError("limma worker 返回的 winsor.tail.p 与 profile 不一致")
            if float(parameters.get("proportion", -1)) != 0.01:
                raise ValueError("limma worker 返回的 proportion 与 profile 不一致")
            if parameters.get("stdev.coef.lim") != [0.1, 4]:
                raise ValueError("limma worker 返回的 stdev.coef.lim 与 profile 不一致")
            if not isinstance(parameters.get("legacy_supported"), bool):
                raise ValueError("limma worker 未返回版本算法兼容信息")
            if parameters["legacy_supported"] and parameters.get("legacy") is not True:
                raise ValueError("limma worker 未使用固定的 legacy 算法")

    @staticmethod
    def _validate_result_table(table: Any, feature_ids: list[str], plan: AnalysisPlan) -> None:
        required = {
            "feature_key", "original_id", "gene_symbol", "log2FoldChange", "pvalue", "padj",
            "direction", "tested", "reason_not_tested", "mean_control_expression",
            "mean_treated_expression", "analysis_method", "analysis_basis", "effect_scale",
            "mean_expression_unit",
        }
        if not isinstance(table, list) or len(table) != len(feature_ids):
            raise ValueError("R worker 返回的结果行数与输入特征数不一致")
        returned_ids: list[str] = []
        for row in table:
            if not isinstance(row, dict) or not required.issubset(row):
                raise ValueError("R worker 返回的结果表缺少统一字段")
            returned_ids.append(str(row["feature_key"]))
            if str(row["analysis_method"]) != plan.method:
                raise ValueError("R worker 返回的结果方法字段与分析计划不一致")
            if str(row["analysis_basis"]) != plan.analysis_basis:
                raise ValueError("R worker 返回的分析基础与分析计划不一致")
            if not isinstance(row["tested"], bool):
                raise ValueError("R worker 返回的 tested 字段不是布尔值")
        if returned_ids != [str(value) for value in feature_ids]:
            raise ValueError("R worker 返回的特征顺序或编号与输入不一致")

    @staticmethod
    def _read_matrix(path: Path) -> tuple[list[str], list[str], list[list[float]]]:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle, delimiter="\t"))
        if not rows or len(rows[0]) < 3:
            raise ValueError("表达矩阵至少需要一个特征列和两个样本列")
        sample_ids = rows[0][1:]
        feature_ids: list[str] = []
        values: list[list[float]] = []
        for row in rows[1:]:
            if not row:
                continue
            feature_ids.append(row[0])
            values.append([float(item) for item in row[1:]])
        if len({*feature_ids}) != len(feature_ids):
            raise ValueError("prepared 表中存在重复 feature_key")
        return feature_ids, sample_ids, values

    @staticmethod
    def _read_gene_symbols(path: Path, expected_count: int) -> list[str | None]:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle, delimiter="\t"))
        if not rows:
            return [None] * expected_count
        headers = [value.strip().casefold() for value in rows[0]]
        symbol_index = next((index for index, value in enumerate(headers) if value in {"gene_symbol", "gene symbol", "symbol", "gene"}), None)
        if symbol_index is None:
            return [None] * expected_count
        symbols: list[str | None] = []
        for row in rows[1:expected_count + 1]:
            value = row[symbol_index].strip() if symbol_index < len(row) else ""
            symbols.append(value or None)
        return symbols + [None] * max(0, expected_count - len(symbols))

    @staticmethod
    def _write_result(project_dir: Path, plan: AnalysisPlan, result: dict[str, Any]) -> None:
        analysis_dir = project_dir / "analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)
        (analysis_dir / "analysis-plan.json").write_text(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (analysis_dir / "deg-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
