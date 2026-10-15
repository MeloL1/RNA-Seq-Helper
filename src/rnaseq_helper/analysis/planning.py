from __future__ import annotations

import hashlib
import json
import csv
from dataclasses import replace
from pathlib import Path
from typing import Mapping
from uuid import uuid4

import numpy as np

from rnaseq_helper.domain.models import (
    AnalysisPlan,
    DEGConfig,
    ExpressionFilterSpec,
    ExpressionMatrix,
    Issue,
    IssueSeverity,
    MeasurementType,
    ObservationUnit,
    ReferenceRequest,
    ValueScale,
)
from rnaseq_helper.grouping.service import GroupingService


class PlanningService:
    """把已确认的输入事实和分组转成可审查、可重放的分析计划。"""

    ACTIVE_GROUPS = frozenset({"control", "test"})

    PROFILES = {
        "DESEQ2": "deseq2-count-v1",
        "LIMMA_ON_LOG2_TPM": "normalized-log-limma-trend-v1",
        "LIMMA_ON_LOG2_FPKM": "normalized-log-limma-trend-v1",
        "LIMMA_ON_LOG2_RPKM": "normalized-log-limma-trend-v1",
        "LIMMA_ON_LOG2_CPM": "normalized-log-limma-trend-v1",
        "LIMMA_ON_LOG_EXPRESSION": "normalized-log-limma-trend-v1",
    }

    def build(
        self,
        matrix: ExpressionMatrix,
        assignments: Mapping[str, str],
        config: DEGConfig | None = None,
        paired_subjects: Mapping[str, str] | None = None,
        batch: Mapping[str, str] | None = None,
    ) -> AnalysisPlan:
        sample_ids = self._read_sample_ids(matrix)
        # 只有两组比较实际使用的样本才进入设计；缺失、空值、未确认和
        # 其他未定义组一律按排除处理，避免“没填分组”被误当成纳入。
        active_sample_ids = tuple(sample for sample in sample_ids if assignments.get(sample) in self.ACTIVE_GROUPS)
        control, test = self._groups(assignments, config)
        grouping = GroupingService().validate(
            assignments,
            sample_ids,
            paired_subjects=paired_subjects,
            batch=batch,
        )
        blockers = list(grouping.issues)
        blockers.extend(self._design_gate_issues(active_sample_ids, assignments, paired_subjects, batch))
        if matrix.observation_unit == ObservationUnit.CELL:
            blockers.append(Issue(
                "CELL_NOT_BULK",
                IssueSeverity.BLOCKING,
                "当前矩阵标记为细胞级数据，不能把细胞当作独立 bulk 样本。",
                "请提供供者级 pseudobulk，或暂缓本版本两组分析",
            ))
        if matrix.source_modality == "MICROARRAY" and matrix.measurement_type != MeasurementType.OTHER_NORMALIZED:
            blockers.append(Issue(
                "SOURCE_MODALITY_MEASUREMENT_CONFLICT",
                IssueSeverity.BLOCKING,
                "来源元数据标注为芯片阵列，当前数值类型却选择了 raw count、TPM、FPKM、RPKM 或 CPM。",
                "返回导入整理，将芯片表达值标为“其他连续表达值”；尺度仍须按来源说明确认。",
            ))
        if not matrix.validation.passed:
            blockers.extend(matrix.validation.blockers)
        method, reason, preprocessing, limitations = self._method_for(matrix, grouping, config)
        if method == "BLOCKED":
            blockers.append(Issue(
                "UNSUPPORTED_ANALYSIS_INPUT",
                IssueSeverity.BLOCKING,
                reason,
                "请确认单位、尺度和数据来源，或提供适合本版本的表达矩阵",
            ))
        selected_config = config or DEGConfig(control or "control", test or "test")
        if control and test and (selected_config.control_group != control or selected_config.test_group != test):
            selected_config = replace(selected_config, control_group=control, test_group=test)
        group_counts = {
            group: sum(value == group for value in assignments.values())
            for group in (control, test) if group
        }
        min_group_n = min(group_counts.values()) if group_counts else 0
        if self._is_normalized_limma(method) and matrix.value_scale == ValueScale.LINEAR:
            preprocessing["min_samples"] = min_group_n
            if selected_config.expression_filter is None:
                selected_config = replace(
                    selected_config,
                    expression_filter=ExpressionFilterSpec(
                        scale="LINEAR",
                        threshold=1.0,
                        unit=matrix.measurement_type.value,
                        min_samples=min_group_n,
                        reason_zh="至少 N 个所选样本达到线性表达量 x≥1；N 为较小组样本数。",
                    ),
                )
        normalized_warnings: list[str] = []
        if self._is_normalized_limma(method):
            if method == "LIMMA_ON_LOG_EXPRESSION" and preprocessing.get("transform") != "log2(x+1)":
                blockers.extend(self._generic_log_evidence_issues(matrix))
            blockers.extend(self._normalized_gate_issues(
                matrix,
                assignments,
                preprocessing,
                paired_subjects=paired_subjects,
                batch=batch,
            ))
            precision = self._normalized_precision_diagnostics(
                matrix,
                preprocessing,
                assignments,
                paired_subjects,
                batch,
            )
            preprocessing["precision_diagnostics"] = precision
            normalized_warnings.extend(self._precision_warning_messages(precision))
            blockers.extend(self._precision_gate_issues(precision))
        design = {
            "type": "paired" if paired_subjects else "independent_two_group",
            "assignments": dict(assignments),
            "paired_subjects": dict(paired_subjects or {}),
            "batch": dict(batch or {}),
        }
        contrast = {"test": test, "control": control, "direction": f"{test} - {control}"}
        profile_id = self.PROFILES.get(method, "blocked")
        parameters = {
            "fdr_threshold": selected_config.fdr_threshold,
            "lfc_threshold": selected_config.lfc_threshold,
            "p_adjust_method": "BH",
            "random_seed": selected_config.random_seed,
        }
        if self._is_normalized_limma(method):
            # 这些参数属于 profile 契约，写入计划供 runner/主服务逐项核对。
            parameters.update({
                "trend": True,
                "robust": True,
                "winsor.tail.p": [0.05, 0.10],
                "proportion": 0.01,
                "stdev.coef.lim": [0.1, 4],
                "legacy_requested": True,
            })
        if selected_config.expression_filter:
            parameters["expression_filter"] = selected_config.expression_filter.as_dict()
        plan = AnalysisPlan(
            plan_id=str(uuid4()),
            matrix_hash=matrix.content_hash,
            method=method,
            method_reason_zh=reason,
            analysis_basis=self._analysis_basis(matrix),
            method_profile_id=profile_id,
            resolved_method_parameters=parameters,
            design=design,
            contrast=contrast,
            preprocessing=preprocessing,
            config=selected_config,
            limitations_zh=tuple(limitations),
            input_selection_reason_zh=reason,
            warnings=tuple(
                [issue.message_zh for issue in grouping.issues if issue.severity != IssueSeverity.BLOCKING]
                + normalized_warnings
            ),
            blockers=tuple(self._dedupe(blockers)),
            reference_request=ReferenceRequest(
                tuple(self._read_feature_ids(matrix)),
                species_taxid=matrix.species_taxid,
                platform_id=matrix.platform_id,
                source_paths=(matrix.values.path.parent.parent / "references" / "reference-result.json",)
                if (matrix.values.path.parent.parent / "references" / "reference-result.json").exists() else (),
            ),
            reference_required_for_fit=False,
            source_modality=matrix.source_modality,
        )
        digest_payload = plan.as_dict()
        digest_payload["confirmation_digest"] = ""
        digest = hashlib.sha256(self._canonical(digest_payload).encode("utf-8")).hexdigest()
        return replace(plan, confirmation_digest=digest)

    def confirm(self, plan: AnalysisPlan, digest: str) -> AnalysisPlan:
        if digest != plan.confirmation_digest:
            raise ValueError("分析计划已变化，必须重新确认后才能运行")
        return plan

    @staticmethod
    def save(plan: AnalysisPlan, project_dir: Path) -> Path:
        path = project_dir / "analysis-plan.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    @staticmethod
    def _read_sample_ids(matrix: ExpressionMatrix) -> tuple[str, ...]:
        rows = matrix.sample_metadata.path.read_text(encoding="utf-8").splitlines()[1:]
        return tuple(row.split("\t", 1)[0] for row in rows if row.strip())

    @staticmethod
    def _read_feature_ids(matrix: ExpressionMatrix) -> tuple[str, ...]:
        rows = matrix.values.path.read_text(encoding="utf-8").splitlines()[1:]
        return tuple(row.split("\t", 1)[0] for row in rows if row.strip())

    @staticmethod
    def _groups(assignments: Mapping[str, str], config: DEGConfig | None) -> tuple[str | None, str | None]:
        if config:
            return config.control_group, config.test_group
        groups = list(dict.fromkeys(
            str(group) for group in assignments.values()
            if group and group != "excluded"
        ))
        return (groups[0], groups[1]) if len(groups) >= 2 else (None, None)

    @staticmethod
    def _is_normalized_limma(method: str) -> bool:
        return method in {
            "LIMMA_ON_LOG2_TPM",
            "LIMMA_ON_LOG2_FPKM",
            "LIMMA_ON_LOG2_RPKM",
            "LIMMA_ON_LOG2_CPM",
            "LIMMA_ON_LOG_EXPRESSION",
        }

    @staticmethod
    def _method_for(matrix: ExpressionMatrix, grouping, config: DEGConfig | None):
        if not grouping.passed:
            return "BLOCKED", "样本分组或设计尚未通过两组分析门禁。", {}, ()
        if matrix.source_modality == "MICROARRAY" and matrix.measurement_type != MeasurementType.OTHER_NORMALIZED:
            return (
                "BLOCKED",
                "来源元数据表明输入来自芯片阵列，与当前所选数值类型冲突。",
                {},
                (),
            )
        if matrix.measurement_type == MeasurementType.RAW_COUNT and matrix.value_scale != ValueScale.LINEAR:
            return (
                "BLOCKED",
                "原始 count 不能同时标记为已取 log 或其他转换；这会使 DESeq2 的计数模型失效。",
                {},
                (),
            )
        if matrix.measurement_type == MeasurementType.RAW_COUNT:
            return (
                "DESEQ2",
                "按当前选择的数值类型和尺度使用原始 count 模型；请确保选择与数据来源说明一致。",
                {"transform": "none", "renormalize": False},
                (),
            )
        if matrix.measurement_type == MeasurementType.OTHER_NORMALIZED and matrix.value_scale == ValueScale.LINEAR:
            return (
                "LIMMA_ON_LOG_EXPRESSION",
                "数据是连续表达/芯片信号的线性值；先按固定规则过滤并取 log2(x+1)，再使用 limma-trend。",
                {"transform": "log2(x+1)", "renormalize": False, "filter_threshold": 1.0},
                ("该路径适用于已跨样本可比的连续表达值，不使用 DESeq2 的原始计数模型。",),
            )
        normalized_methods = {
            MeasurementType.TPM: "LIMMA_ON_LOG2_TPM",
            MeasurementType.FPKM: "LIMMA_ON_LOG2_FPKM",
            MeasurementType.RPKM: "LIMMA_ON_LOG2_RPKM",
            MeasurementType.CPM: "LIMMA_ON_LOG2_CPM",
        }
        if matrix.measurement_type in normalized_methods:
            method = normalized_methods[matrix.measurement_type]
            if matrix.value_scale == ValueScale.LINEAR:
                return (
                    method,
                    f"当前选择为{matrix.measurement_type.value}线性表达值；按固定 profile 先做 x≥1 过滤，再取 log2(x+1) 并使用 limma-trend。请确保单位和尺度与数据来源说明一致。",
                    {"transform": "log2(x+1)", "renormalize": False, "filter_threshold": 1.0},
                    ("本分析基于标准化值，未使用原始计数中的测序深度和计数精度信息。",),
                )
            if matrix.value_scale == ValueScale.LOG2:
                return (
                    method,
                    f"当前选择为{matrix.measurement_type.value}的 log2 表达量；不再次取 log，不做重新标准化，直接使用 limma-trend。请确保选择与数据来源说明一致。",
                    {"transform": "already_log2", "renormalize": False},
                    ("本分析基于已转换的标准化值；请在论文中说明原始转换公式。",),
                )
        if matrix.measurement_type == MeasurementType.OTHER_NORMALIZED and matrix.value_scale == ValueScale.LOG2:
            return (
                "LIMMA_ON_LOG_EXPRESSION",
                "当前选择为可跨样本比较的 log2 表达值；使用通用 log-expression 门禁。请确保尺度和可比性与数据来源说明一致。",
                {"transform": "already_log2", "renormalize": False},
                ("原始单位未知，不能解释为 TPM/FPKM 或原尺度倍数。",),
            )
        return (
            "BLOCKED",
            "当前数据事实还没有对应的安全分析 profile。若这是 GSE 芯片信号或其他连续表达值，请在“导入与整理 → 确认数据事实”选择“其他连续表达值 + 原始/线性尺度”；若提供方明确写明已经取 log2，再选择“已取 log2”。未确认、ln/log10、z-score 或残差不能直接进入本版本分析。",
            {},
            (),
        )

    @staticmethod
    def _analysis_basis(matrix: ExpressionMatrix) -> str:
        return "raw_count" if matrix.measurement_type == MeasurementType.RAW_COUNT else "normalized_expression"

    @staticmethod
    def _normalized_gate_issues(
        matrix: ExpressionMatrix,
        assignments: Mapping[str, str],
        preprocessing: Mapping[str, object],
        paired_subjects: Mapping[str, str] | None = None,
        batch: Mapping[str, str] | None = None,
    ) -> list[Issue]:
        """在启动 R 前执行可解释的规模、信息量和退化门禁。"""
        with matrix.values.path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle, delimiter="\t"))
        if len(rows) < 2:
            return [Issue(
                "INSUFFICIENT_TREND_DATA",
                IssueSeverity.BLOCKING,
                "表达矩阵没有足够的特征用于趋势和波动估计。",
                "请提供完整表达表",
            )]
        all_sample_ids = rows[0][1:]
        keep_columns = [index for index, sample in enumerate(all_sample_ids) if assignments.get(sample) in PlanningService.ACTIVE_GROUPS]
        sample_ids = [all_sample_ids[index] for index in keep_columns]
        values = np.asarray(
            [[float(row[index + 1]) for index in keep_columns] for row in rows[1:]],
            dtype=float,
        )
        if preprocessing.get("transform") == "log2(x+1)":
            threshold = float(preprocessing.get("filter_threshold", 1.0))
            min_samples = int(preprocessing.get("min_samples", 0))
            keep = np.sum(values >= threshold, axis=1) >= min_samples
            model_values = np.log2(values[keep] + 1.0)
        else:
            keep = np.ones(values.shape[0], dtype=bool)
            model_values = values
        # limma 不能对全局常量行估计特征方差；它们不计入可拟合行，
        # 但若因此不足 500 行仍必须阻断。非有限行同样不参与后续门禁。
        finite = np.all(np.isfinite(model_values), axis=1)
        nonconstant = finite & (np.ptp(model_values, axis=1) > 1e-12)
        fitting_values = model_values[nonconstant]
        issues: list[Issue] = []
        if fitting_values.shape[0] < 500:
            issues.append(Issue(
                "INSUFFICIENT_TREND_DATA",
                IssueSeverity.BLOCKING,
                f"过滤后只有 {fitting_values.shape[0]} 个可拟合特征，少于本版本要求的 500 个。",
                "请提供完整表达表或采用专门的小面板分析流程",
            ))
        if fitting_values.size:
            distinct_amean = len(np.unique(np.round(np.mean(fitting_values, axis=1), 8)))
            if distinct_amean < 50:
                issues.append(Issue(
                    "INSUFFICIENT_TREND_DATA",
                    IssueSeverity.BLOCKING,
                    f"可用特征的 Amean 只有 {distinct_amean} 个不同值，少于本版本要求的 50 个。",
                    "请提供保留更多数值精度且特征更完整的表达表",
                ))
            design, _, residual_df = PlanningService._design_matrix(
                sample_ids, assignments, paired_subjects, batch,
            )
            if fitting_values.size and design.size and residual_df > 0:
                residual = PlanningService._residuals(fitting_values, design)
                s2 = np.sum(residual ** 2, axis=1) / residual_df
                scale = np.maximum(1.0, np.mean(fitting_values ** 2, axis=1))
                degenerate_fraction = float(np.mean(s2 <= 1e-12 * scale))
                if degenerate_fraction > 0.05:
                    issues.append(Issue(
                        "DEGENERATE_VARIANCE",
                        IssueSeverity.BLOCKING,
                        f"约 {degenerate_fraction:.1%} 的可拟合特征残差方差退化，超过 5% 门槛。",
                        "请索取更高精度数据并核实样本是否为独立生物学重复",
                    ))
        return issues

    @staticmethod
    def _generic_log_evidence_issues(matrix: ExpressionMatrix) -> list[Issue]:
        """通用 log 入口只接受有转换证据的表达值，不能作为未知分数兜底。"""
        transform = str(matrix.input_transform or "").strip().casefold()
        provenance = str(matrix.measurement_provenance or "").strip().casefold()
        combined = f"{transform} {provenance}"
        score_tokens = (
            "z-score", "zscore", "z score", "standardized score", "score matrix",
            "percentile", "rank", "residual",
            "残差", "评分", "分数", "百分位", "秩", "比值",
        )
        if any(token in combined for token in score_tokens):
            return [Issue(
                "NON_EXPRESSION_SCORE",
                IssueSeverity.BLOCKING,
                "这些值是评分或校正残差，不能沿用表达量的差异分析和倍数解释。",
                "请提供原表达矩阵",
            )]
        # 当前 runner 对通用入口按 already_log2 直接拟合；仅有明确 log2
        # 证据才可进入，ln/log 等其他底数不能被标签自动当作 log2。
        confirmed_scale = (
            matrix.value_scale == ValueScale.LOG2
            and "user-confirmed value_scale=log2" in provenance
        )
        known_log = confirmed_scale or "log2" in transform or "log_2" in transform or transform in {
            "already_log2", "已取 log2", "已取log2"
        }
        if not known_log:
            return [Issue(
                "INVALID_TRANSFORM",
                IssueSeverity.BLOCKING,
                "当前无法确认通用表达矩阵的对数转换公式，不能把未知转换当作 log2 表达量。",
                "请提供转换说明或未转换表达表",
            )]
        return []

    @staticmethod
    def _design_matrix(
        sample_ids: tuple[str, ...],
        assignments: Mapping[str, str],
        paired_subjects: Mapping[str, str] | None,
        batch: Mapping[str, str] | None,
    ) -> tuple[np.ndarray, int, int]:
        """复现 worker 的 ~0 + batch + subject + group 设计及其残差自由度。"""
        groups = tuple(dict.fromkeys(
            str(assignments.get(sample)) for sample in sample_ids
            if assignments.get(sample) in PlanningService.ACTIVE_GROUPS
        ))
        columns = [
            [1.0 if str(assignments.get(sample)) == group else 0.0 for sample in sample_ids]
            for group in groups
        ]
        for metadata in (batch, paired_subjects):
            if not metadata:
                continue
            levels = tuple(dict.fromkeys(
                str(metadata.get(sample)) for sample in sample_ids
                if metadata.get(sample) is not None
            ))
            columns.extend([
                [1.0 if str(metadata.get(sample)) == level else 0.0 for sample in sample_ids]
                for level in levels
            ])
        design = np.asarray(columns, dtype=float).T if columns else np.empty((len(sample_ids), 0))
        rank = int(np.linalg.matrix_rank(design)) if design.size else 0
        return design, rank, len(sample_ids) - rank

    @staticmethod
    def _residuals(values: np.ndarray, design: np.ndarray) -> np.ndarray:
        projection = design @ np.linalg.pinv(design)
        return values - values @ projection.T

    @staticmethod
    def _design_gate_issues(
        sample_ids: tuple[str, ...],
        assignments: Mapping[str, str],
        paired_subjects: Mapping[str, str] | None,
        batch: Mapping[str, str] | None,
    ) -> list[Issue]:
        """在交给 R 前用同一无截距分类结构检查秩和残差自由度。"""
        groups = tuple(dict.fromkeys(
            str(assignments.get(sample)) for sample in sample_ids
            if assignments.get(sample) in PlanningService.ACTIVE_GROUPS
        ))
        if len(groups) != 2:
            return []
        design, rank, residual_df = PlanningService._design_matrix(
            sample_ids, assignments, paired_subjects, batch,
        )
        if residual_df < 2:
            return [Issue(
                "NON_ESTIMABLE",
                IssueSeverity.BLOCKING,
                f"设计矩阵秩为 {rank}，残差自由度只有 {residual_df}，不足以稳定估计组内波动。",
                "请增加独立样本，或移除与分组完全重合的协变量",
            )]
        return []

    @staticmethod
    def _normalized_precision_diagnostics(
        matrix: ExpressionMatrix,
        preprocessing: Mapping[str, object],
        assignments: Mapping[str, str],
        paired_subjects: Mapping[str, str] | None,
        batch: Mapping[str, str] | None,
    ) -> dict[str, object]:
        """按规划定义计算连续表达精度诊断；只对非 count 路径调用。"""
        with matrix.values.path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle, delimiter="\t"))
        if len(rows) < 2:
            return {"evidence_sufficient": False, "reason": "empty_matrix"}
        all_sample_ids = rows[0][1:]
        keep_columns = [index for index, sample in enumerate(all_sample_ids) if assignments.get(sample) in PlanningService.ACTIVE_GROUPS]
        values = np.asarray(
            [[float(row[index + 1]) for index in keep_columns] for row in rows[1:]],
            dtype=float,
        )
        if preprocessing.get("transform") == "log2(x+1)":
            threshold = float(preprocessing.get("filter_threshold", 1.0))
            min_samples = int(preprocessing.get("min_samples", 0))
            keep = np.sum(values >= threshold, axis=1) >= min_samples
            observed = values[keep]
            low_values = observed[(observed > 0) & (observed <= 10)]
            grid_candidates = ((1.0, low_values), (0.1, low_values))
            grid_scope = "linear_low_expression"
        else:
            observed = values
            nonzero = observed[observed != 0]
            grid_candidates = ((0.1, nonzero),)
            low_values = np.asarray([], dtype=float)
            grid_scope = "log_nonzero"
        diagnostics: dict[str, object] = {
            "grid_scope": grid_scope,
            "observed_value_count": int(observed.size),
            "nonzero_value_count": int(np.count_nonzero(observed)),
            "low_expression_value_count": int(low_values.size),
            "evidence_sufficient": int(np.count_nonzero(observed)) >= 1000,
        }
        if observed.size == 0:
            diagnostics.update({"q_1": None, "q_0_1": None, "low_complexity_fraction": None, "z": None})
            return diagnostics

        finite_rows = observed[np.all(np.isfinite(observed), axis=1)]
        variable_rows = [row for row in finite_rows if np.ptp(row) > 1e-12]
        low_complexity_fraction = float(
            np.mean([len(np.unique(np.round(row, 8))) <= 3 for row in variable_rows])
        ) if variable_rows else 0.0
        diagnostics["variable_feature_count"] = len(variable_rows)
        diagnostics["low_complexity_fraction"] = low_complexity_fraction

        def grid_fraction(candidates: np.ndarray, quantum: float) -> float | None:
            if candidates.size < 1000:
                return None
            ratio = candidates / quantum
            return float(np.mean(np.abs(ratio - np.round(ratio)) <= 1e-6))

        q_values: dict[str, float | None] = {}
        for quantum, candidates in grid_candidates:
            q_values[f"q_{quantum:g}"] = grid_fraction(candidates, quantum)
        diagnostics.update(q_values)

        # 用与设计门禁一致的满秩投影估计 Z；它是规划期保守筛查，R
        # worker 返回的实际 fit 诊断仍会写入最终报告。
        # 诊断矩阵只包含本次纳入分析的样本；排除样本不能进入设计矩阵，
        # 否则表达值列数与设计矩阵行数不一致。
        sample_ids = [all_sample_ids[index] for index in keep_columns]
        design, _, residual_df = PlanningService._design_matrix(
            sample_ids, assignments, paired_subjects, batch,
        )
        z_fraction: float | None = None
        if design.size and variable_rows and residual_df > 0:
            variable_values = np.asarray(variable_rows, dtype=float)
            residual = PlanningService._residuals(variable_values, design)
            s2 = np.sum(residual ** 2, axis=1) / residual_df
            scale = np.maximum(1.0, np.mean(variable_values ** 2, axis=1))
            z_fraction = float(np.mean(s2 <= 1e-12 * scale))
            diagnostics["residual_df"] = residual_df
        diagnostics["z"] = z_fraction
        diagnostics["grid_warning"] = bool(
            (q_values.get("q_1") is not None and q_values["q_1"] >= 0.95)
            or (q_values.get("q_0.1") is not None and q_values["q_0.1"] >= 0.95)
            or (grid_scope == "log_nonzero" and low_complexity_fraction >= 0.5)
        )
        diagnostics["severe_rounding"] = bool(
            diagnostics["grid_warning"]
            and low_complexity_fraction >= 0.5
            and z_fraction is not None
            and z_fraction > 0.05
        )
        return diagnostics

    @staticmethod
    def _precision_warning_messages(diagnostics: Mapping[str, object]) -> list[str]:
        if diagnostics.get("grid_warning"):
            return [
                "数值精度告警：很多表达值只保留了整数或较少小数，低表达基因的变化可能被压缩。"
                "软件会继续分析并记录此限制；如能获取更多小数位的数据，结果通常更稳妥。"
            ]
        return []

    @staticmethod
    def _precision_gate_issues(diagnostics: Mapping[str, object]) -> list[Issue]:
        if not diagnostics.get("severe_rounding"):
            return []
        return [Issue(
            "ROUNDING_PRECISION_DEGENERATE",
            IssueSeverity.BLOCKING,
            "数据精度可能不足：超过一半的可用特征只有不超过 3 种数值，且较多特征无法估计组内波动。",
            "请索取未取整或保留更多小数的数据，并核实是否包含复制或技术重复",
        )]

    @staticmethod
    def _canonical(value) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))

    @staticmethod
    def _dedupe(issues: list[Issue]) -> list[Issue]:
        seen: set[tuple[str, str]] = set()
        result = []
        for issue in issues:
            key = (issue.code, issue.message_zh)
            if key not in seen:
                seen.add(key)
                result.append(issue)
        return result
