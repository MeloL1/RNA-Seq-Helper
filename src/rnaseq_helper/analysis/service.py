from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Callable
from uuid import uuid4

from rnaseq_helper.domain.models import AnalysisPlan, ExpressionMatrix, JobContext, sha256_file
from rnaseq_helper.r_bridge.client import RBridgeClient, RBridgeError
from rnaseq_helper.analysis.planning import PlanningService
from rnaseq_helper.services.project_lock import project_directory_lock


class OutputPublishRollbackError(RuntimeError):
    """输出替换及其回滚均失败；恢复材料已保留在项目目录中。"""


class AnalysisService:
    """读取标准化 prepared/ 文件并通过 RBridge 执行已确认计划。"""

    APPLICATION_ID = "org.rnaseqhelper.app"

    OUTPUT_RELATIVE_PATHS = (
        Path("analysis-plan.json"),
        Path("analysis/analysis-plan.json"), Path("analysis/deg-result.json"),
        Path("figures/figure-manifest.json"), Path("figures/pca.png"),
        Path("figures/sample-correlation.png"), Path("figures/p-value-histogram.png"),
        Path("figures/volcano.png"), Path("figures/top-heatmap.png"),
        Path("reports/analysis-report.html"), Path("reports/deg-results.xlsx"),
        Path("reports/interpretation-zh.txt"), Path("reports/analysis-manifest.json"),
    )

    def __init__(self, bridge: RBridgeClient | None = None) -> None:
        self.bridge = bridge or RBridgeClient()

    def run(self, matrix: ExpressionMatrix, plan: AnalysisPlan, context: JobContext) -> dict[str, Any]:
        project_dir = matrix.values.path.parent.parent.resolve(strict=True)
        with project_directory_lock(project_dir):
            return self._run_locked(matrix, plan, context, project_dir)

    def _run_locked(
        self,
        matrix: ExpressionMatrix,
        plan: AnalysisPlan,
        context: JobContext,
        project_dir: Path,
    ) -> dict[str, Any]:
        if not plan.runnable:
            raise ValueError("分析计划包含阻断问题，不能运行")
        current_matrix_hash = sha256_file(matrix.values.path)
        if plan.matrix_hash != matrix.content_hash or current_matrix_hash != plan.matrix_hash:
            raise ValueError("表达矩阵已变化，当前分析计划失效")
        if (
            plan.feature_metadata_hash is not None
            and sha256_file(matrix.feature_metadata.path) != plan.feature_metadata_hash
        ):
            raise ValueError("特征注释已变化，当前分析计划失效；请重新确认计划")
        self._raise_if_cancelled(context)
        feature_ids, sample_ids, values = self._read_matrix(matrix.values.path)
        if plan.method == "DESEQ2" and any(
            value > 2_147_483_647 for row in values for value in row
        ):
            raise ValueError("count 超出当前 DESeq2 运行时可安全处理的整数范围；未启动统计分析")
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
            "gene_symbols": self._read_gene_symbols(matrix.feature_metadata.path, feature_ids),
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
        self._raise_if_cancelled(context)
        result = dict(response.result or {})
        expected = {"method": plan.method, "profile_id": plan.method_profile_id}
        if result.get("method") != expected["method"] or result.get("profile_id") != expected["profile_id"]:
            raise ValueError("R worker 返回的方法或 profile 与分析计划不一致")
        parameters = result.get("parameters", {})
        self._validate_parameters(plan, parameters)
        self._validate_result_table(
            result.get("table"), feature_ids, plan, matrix.measurement_type.value, parameters,
        )
        self._validate_summary(result.get("summary"), result.get("table"), plan)
        self._validate_plot_matrix(result.get("plot_matrix"), feature_ids, sample_ids)
        from rnaseq_helper.services.plot_service import PlotService
        from rnaseq_helper.services.report_service import ReportService

        staging_dir = Path(tempfile.mkdtemp(prefix=".analysis-staging-", dir=project_dir))
        preserve_staging = False
        try:
            self._write_transaction_journal(
                staging_dir,
                self._new_transaction_journal(project_dir, phase="preparing"),
            )
            PlanningService.save(plan, staging_dir)
            self._write_result(staging_dir, plan, result)
            figures = PlotService().build(
                matrix, plan, result,
                output_dir=staging_dir / "figures",
                manifest_dir=project_dir / "figures",
            )
            self._raise_if_cancelled(context)
            ReportService().build(
                matrix, plan, result, figures,
                output_dir=staging_dir / "reports",
                project_dir=project_dir,
                analysis_artifact_dir=staging_dir / "analysis",
            )
            self._raise_if_cancelled(context)
            context.emit("publish", None, "正在保存分析结果；此阶段不可取消")
            self._publish_outputs(project_dir, staging_dir, context.cancelled)
        except OutputPublishRollbackError:
            # Even if moving the failed transaction to its recovery name fails,
            # never let temporary-directory cleanup delete the only old copies.
            preserve_staging = True
            raise
        finally:
            if not preserve_staging and staging_dir.exists():
                shutil.rmtree(staging_dir)
        return result

    @staticmethod
    def _publish_outputs(
        project_dir: Path,
        staging_dir: Path,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        """Replace only known analysis artifacts; roll back old files on publish errors."""
        project_dir = project_dir.resolve(strict=True)
        if Path(staging_dir).is_symlink():
            raise OSError("分析临时目录不能是符号链接")
        staging_dir = staging_dir.resolve(strict=True)
        if not staging_dir.is_relative_to(project_dir):
            raise OSError("分析临时产物必须位于当前项目目录内")
        relative_paths = AnalysisService.OUTPUT_RELATIVE_PATHS
        backup_dir = staging_dir / ".previous"
        backups: list[tuple[Path, Path]] = []
        installed: list[Path] = []
        journal_path = staging_dir / ".transaction.json"
        try:
            AnalysisService._check_cancelled(cancelled)
            expected_states: dict[str, dict[str, Any]] = {}
            for relative in relative_paths:
                staged = staging_dir / relative
                AnalysisService._assert_no_symlink_path(staging_dir, staged)
                if not staged.is_file():
                    raise FileNotFoundError(f"分析产物未完整生成：{relative}")
                file_descriptor = os.open(staged, os.O_RDONLY)
                try:
                    os.fsync(file_descriptor)
                finally:
                    os.close(file_descriptor)
                target = project_dir / relative
                parent = project_dir
                for part in relative.parent.parts:
                    parent = parent / part
                    if parent.is_symlink():
                        raise OSError(f"拒绝写入通过符号链接指向的结果目录：{relative.parent}")
                    parent.mkdir(exist_ok=True)
                    if not parent.resolve(strict=True).is_relative_to(project_dir):
                        raise OSError(f"结果目录超出当前项目范围：{relative.parent}")
                if target.is_symlink() or (target.exists() and not target.is_file()):
                    raise OSError(f"拒绝覆盖非普通文件的分析产物路径：{relative}")
                expected_states[relative.as_posix()] = {
                    "had_original": target.exists(),
                    "old_sha256": sha256_file(target) if target.exists() else None,
                    "new_sha256": sha256_file(staged),
                }
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            if (
                journal.get("application") != AnalysisService.APPLICATION_ID
                or journal.get("project_identity") != AnalysisService._project_identity(project_dir)
                or not isinstance(journal.get("transaction_id"), str)
                or not journal["transaction_id"]
            ):
                raise ValueError("分析事务日志不属于当前应用或项目")
            journal.update({"phase": "publishing", "outputs": expected_states})
            AnalysisService._write_transaction_journal(staging_dir, journal)

            for relative in relative_paths:
                AnalysisService._check_cancelled(cancelled)
                staged = staging_dir / relative
                target = project_dir / relative
                original = expected_states[relative.as_posix()]
                if target.is_symlink() or target.exists() != original["had_original"]:
                    raise OSError(f"分析发布期间文件状态发生变化，已停止覆盖：{relative}")
                if target.exists() and sha256_file(target) != original["old_sha256"]:
                    raise OSError(f"分析发布期间旧文件内容发生变化，已停止覆盖：{relative}")
                if target.exists():
                    backup = backup_dir / relative
                    AnalysisService._assert_no_symlink_path(staging_dir, backup)
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(target, backup)
                    backups.append((backup, target))
                    AnalysisService._fsync_directory(target.parent)
                    AnalysisService._fsync_directory(backup.parent)
                os.replace(staged, target)
                installed.append(target)
                AnalysisService._fsync_directory(staged.parent)
                AnalysisService._fsync_directory(target.parent)
            AnalysisService._check_cancelled(cancelled)
            journal["phase"] = "committed"
            AnalysisService._write_transaction_journal(staging_dir, journal)
            AnalysisService._check_cancelled(cancelled)
        except Exception as publish_error:
            rollback_errors: list[str] = []
            targets_with_backups = {target for _, target in backups}
            for backup, target in reversed(backups):
                target.parent.mkdir(parents=True, exist_ok=True)
                if backup.exists():
                    try:
                        os.replace(backup, target)
                        AnalysisService._fsync_directory(backup.parent)
                        AnalysisService._fsync_directory(target.parent)
                    except OSError as exc:
                        rollback_errors.append(f"恢复 {target.relative_to(project_dir)} 失败：{exc}")
            for target in reversed(installed):
                if target in targets_with_backups:
                    continue
                try:
                    target.unlink(missing_ok=True)
                    AnalysisService._fsync_directory(target.parent)
                except OSError as exc:
                    rollback_errors.append(f"移除新文件 {target.relative_to(project_dir)} 失败：{exc}")
            if rollback_errors:
                try:
                    journal = json.loads(journal_path.read_text(encoding="utf-8"))
                    journal["phase"] = "recovery_required"
                    AnalysisService._write_transaction_journal(staging_dir, journal)
                except Exception as exc:
                    rollback_errors.append(f"无法记录恢复状态：{exc}")
                recovery_dir = project_dir / f".analysis-recovery-{uuid4().hex}"
                try:
                    os.replace(staging_dir, recovery_dir)
                    recovery_note = f"恢复材料保留在：{recovery_dir}"
                except OSError as exc:
                    recovery_note = f"无法移动临时恢复材料（{staging_dir}）：{exc}"
                raise OutputPublishRollbackError(
                    "分析结果发布失败，且自动回滚未能完整完成。请勿删除项目中的恢复材料；"
                    + "；".join(rollback_errors)
                    + "；"
                    + recovery_note
                ) from publish_error
            raise

    @staticmethod
    def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
        if cancelled is not None and cancelled():
            raise RBridgeError("任务已取消；旧分析结果保持不变")

    @staticmethod
    def _raise_if_cancelled(context: JobContext) -> None:
        AnalysisService._check_cancelled(context.cancelled)

    @staticmethod
    def _write_transaction_journal(staging_dir: Path, journal: dict[str, Any]) -> None:
        path = staging_dir / ".transaction.json"
        temporary = staging_dir / ".transaction.json.tmp"
        AnalysisService._assert_no_symlink_path(staging_dir, path)
        AnalysisService._assert_no_symlink_path(staging_dir, temporary)
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(journal, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        AnalysisService._fsync_directory(staging_dir)

    @staticmethod
    def _assert_no_symlink_path(root: Path, path: Path) -> None:
        cursor = root
        try:
            parts = path.relative_to(root).parts
        except ValueError as exc:
            raise OSError(f"事务路径超出临时目录：{path}") from exc
        for part in parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise OSError(f"事务路径不能包含符号链接：{path}")

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        directory_fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    @staticmethod
    def recover_interrupted_outputs(project_dir: Path) -> tuple[str, ...]:
        """Recover or remove stale staging transactions before a project is loaded."""
        root = Path(project_dir).resolve(strict=True)
        messages: list[str] = []
        candidates = sorted(
            [*root.glob(".analysis-staging-*"), *root.glob(".analysis-recovery-*")]
        )
        for staging_dir in candidates:
            if staging_dir.is_symlink() or not staging_dir.is_dir():
                raise ValueError(f"发现无效的分析事务目录，未触碰：{staging_dir}")
            marker = staging_dir / ".recovery-complete"
            journal_path = staging_dir / ".transaction.json"
            backup_root = staging_dir / ".previous"
            try:
                for path in (marker, journal_path, backup_root):
                    AnalysisService._assert_no_symlink_path(staging_dir, path)
            except OSError as exc:
                raise ValueError(f"分析事务目录包含符号链接；项目未改动：{staging_dir}") from exc
            if marker.is_file():
                try:
                    marker_record = json.loads(marker.read_text(encoding="utf-8"))
                    journal = json.loads(journal_path.read_text(encoding="utf-8"))
                    if (
                        marker_record.get("application") != AnalysisService.APPLICATION_ID
                        or marker_record.get("project_identity") != AnalysisService._project_identity(root)
                        or marker_record.get("transaction_id") != journal.get("transaction_id")
                        or journal.get("application") != AnalysisService.APPLICATION_ID
                        or journal.get("project_identity") != AnalysisService._project_identity(root)
                        or journal.get("phase") != "rolled_back"
                    ):
                        raise ValueError("完成标记不属于当前应用或项目")
                except (OSError, UnicodeError, json.JSONDecodeError, AttributeError, ValueError) as exc:
                    raise ValueError(f"恢复完成标记无效；未删除目录：{staging_dir}") from exc
                shutil.rmtree(staging_dir)
                messages.append("已完成一次中断分析项目的恢复清理。")
                continue
            try:
                journal = json.loads(journal_path.read_text(encoding="utf-8"))
                if journal.get("version") != 1:
                    raise ValueError("事务记录版本不支持")
                if (
                    journal.get("application") != AnalysisService.APPLICATION_ID
                    or journal.get("project_identity") != AnalysisService._project_identity(root)
                    or not isinstance(journal.get("transaction_id"), str)
                    or not journal["transaction_id"]
                ):
                    raise ValueError("事务记录不属于当前应用或项目")
                phase = str(journal["phase"])
                outputs = journal["outputs"]
            except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"发现分析事务记录缺失或损坏；为保护旧结果，没有改动项目：{staging_dir}"
                ) from exc
            if phase in {"committed", "rolled_back"}:
                shutil.rmtree(staging_dir)
                messages.append("已清理已完成事务留下的临时文件。")
                continue
            if phase == "preparing":
                shutil.rmtree(staging_dir)
                messages.append("已清理未进入发布阶段的中断分析临时文件；旧结果未动。")
                continue
            if phase not in {"publishing", "recovery_required"} or not isinstance(outputs, dict):
                raise ValueError(f"分析事务记录状态无法识别；项目未改动：{staging_dir}")
            if set(outputs) != {path.as_posix() for path in AnalysisService.OUTPUT_RELATIVE_PATHS}:
                raise ValueError(f"分析事务清单不完整或包含未知文件；项目未改动：{staging_dir}")
            try:
                for relative in AnalysisService.OUTPUT_RELATIVE_PATHS:
                    name = relative.as_posix()
                    state = outputs[name]
                    if not isinstance(state, dict) or not isinstance(state.get("had_original"), bool):
                        raise ValueError(f"事务记录字段无效：{name}")
                    target = root / relative
                    parent = root
                    for part in relative.parent.parts:
                        parent = parent / part
                        if parent.is_symlink():
                            raise ValueError(f"拒绝沿符号链接恢复：{relative}")
                    if target.is_symlink():
                        raise ValueError(f"拒绝覆盖符号链接目标：{relative}")
                    backup = staging_dir / ".previous" / relative
                    staged = staging_dir / relative
                    AnalysisService._assert_no_symlink_path(staging_dir, backup)
                    AnalysisService._assert_no_symlink_path(staging_dir, staged)
                    if state["had_original"]:
                        old_hash = state.get("old_sha256")
                        if not isinstance(old_hash, str):
                            raise ValueError(f"原文件哈希缺失：{relative}")
                        if backup.is_file():
                            if sha256_file(backup) != old_hash:
                                raise ValueError(f"旧文件恢复副本哈希不匹配：{relative}")
                            if target.is_file():
                                target_hash = sha256_file(target)
                                if target_hash == old_hash:
                                    continue
                                if target_hash != state.get("new_sha256"):
                                    raise ValueError(f"文件在中断后被用户修改，拒绝覆盖：{relative}")
                            parent.mkdir(parents=True, exist_ok=True)
                            temporary = target.with_name(f".{target.name}.restore-{uuid4().hex}")
                            with backup.open("rb") as source, temporary.open("wb") as destination:
                                shutil.copyfileobj(source, destination)
                                destination.flush()
                                os.fsync(destination.fileno())
                            os.replace(temporary, target)
                            AnalysisService._fsync_directory(target.parent)
                        elif not target.is_file() or sha256_file(target) != old_hash:
                            raise ValueError(f"旧结果及其恢复副本都不可验证：{relative}")
                    else:
                        if staged.exists():
                            if not staged.is_file():
                                raise ValueError(f"新输出暂存内容不是普通文件，未处理：{relative}")
                            if target.exists():
                                raise ValueError(f"原本不存在的新输出目标在中断后被占用，拒绝覆盖或删除：{relative}")
                        elif target.is_file():
                            new_hash = state.get("new_sha256")
                            if not isinstance(new_hash, str) or sha256_file(target) != new_hash:
                                raise ValueError(f"新文件在中断后又被修改，未删除：{relative}")
                            target.unlink()
                            AnalysisService._fsync_directory(target.parent)
                        elif target.exists():
                            raise ValueError(f"新输出目标不是普通文件，未删除：{relative}")
                AnalysisService._write_transaction_journal(
                    staging_dir, {**journal, "phase": "rolled_back"},
                )
                marker_tmp = staging_dir / ".recovery-complete.tmp"
                marker_tmp.write_text(json.dumps({
                    "application": AnalysisService.APPLICATION_ID,
                    "project_identity": AnalysisService._project_identity(root),
                    "transaction_id": journal["transaction_id"],
                }), encoding="utf-8")
                with marker_tmp.open("rb") as handle:
                    os.fsync(handle.fileno())
                os.replace(marker_tmp, marker)
                AnalysisService._fsync_directory(staging_dir)
                shutil.rmtree(staging_dir)
                messages.append("检测到上次分析在发布期间中断；已恢复旧结果，未保留未完成的新结果。")
            except Exception as exc:
                raise ValueError(
                    f"分析事务自动恢复未完成；旧文件和恢复材料均保留，请勿手动删除：{staging_dir}（{exc}）"
                ) from exc
        return tuple(messages)

    @staticmethod
    def _project_identity(project_dir: Path) -> str:
        root = Path(project_dir).resolve(strict=True)
        manifest_path = root / "project.json"
        project_id = None
        if manifest_path.is_file() and not manifest_path.is_symlink():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                candidate = manifest.get("project_id") if isinstance(manifest, dict) else None
                project_id = str(candidate).strip() if candidate else None
            except (OSError, UnicodeError, json.JSONDecodeError):
                project_id = None
        identity = f"project_id:{project_id}" if project_id else f"path:{root}"
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    @classmethod
    def _new_transaction_journal(
        cls,
        project_dir: Path,
        phase: str,
        outputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "version": 1,
            "application": cls.APPLICATION_ID,
            "project_identity": cls._project_identity(project_dir),
            "transaction_id": uuid4().hex,
            "pid": os.getpid(),
            "phase": phase,
            "outputs": outputs or {},
        }

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
            fixed_profile = {
                "test": "Wald",
                "size_factor_type": "ratio",
                "dispersion_fit_type": "parametric",
                "beta_prior": False,
                "min_replicates_for_replace": 7,
                "use_t": False,
                "min_mu": 0.5,
                "parallel": False,
                "cooks_cutoff": True,
                "independent_filter_statistic": "baseMean",
                "p_adjust_method": "BH",
            }
            if parameters.get("independent_filtering") is not True:
                raise ValueError("DESeq2 worker 未明确返回独立过滤设置")
            if parameters.get("dispersion_estimation") not in {"trend", "gene-wise-fallback"}:
                raise ValueError("DESeq2 worker 返回了未知的离散度估计路径")
            if float(parameters.get("alpha", -1)) != float(plan.config.fdr_threshold):
                raise ValueError("DESeq2 worker 返回的 alpha 与分析计划不一致")
            for key in (
                "test", "size_factor_type", "beta_prior",
                "min_replicates_for_replace", "use_t", "min_mu", "parallel",
                "cooks_cutoff", "independent_filter_statistic",
            ):
                expected = plan.resolved_method_parameters.get(key, fixed_profile[key])
                if parameters.get(key) != expected:
                    raise ValueError(f"DESeq2 worker 返回的 {key} 与分析计划不一致")
            expected_adjust = plan.resolved_method_parameters.get(
                "p_adjust_method", fixed_profile["p_adjust_method"],
            )
            if parameters.get("p_adjust_method") != expected_adjust:
                raise ValueError("DESeq2 worker 返回的多重校正方法与分析计划不一致")
            returned_fit_type = parameters.get("dispersion_fit_type")
            if returned_fit_type != plan.resolved_method_parameters.get(
                "dispersion_fit_type", fixed_profile["dispersion_fit_type"],
            ):
                if not (
                    returned_fit_type == "gene-wise"
                    and parameters.get("dispersion_estimation") == "gene-wise-fallback"
                ):
                    raise ValueError("DESeq2 worker 返回的离散度拟合路径与分析计划不一致")
            threshold = parameters.get("independent_filter_threshold")
            if threshold is not None and (
                isinstance(threshold, bool)
                or not isinstance(threshold, (int, float))
                or not math.isfinite(threshold)
                or threshold < 0
            ):
                raise ValueError("DESeq2 worker 返回的独立过滤阈值无效")
        else:
            expected_transform = plan.preprocessing.get("transform")
            if parameters.get("transform") != expected_transform:
                raise ValueError("R worker 返回的转换方式与分析计划不一致")
            expected_filter_threshold = plan.preprocessing.get("filter_threshold")
            returned_filter_threshold = parameters.get("filter_threshold")
            if expected_filter_threshold is None:
                if returned_filter_threshold is not None:
                    raise ValueError("R worker 返回了分析计划中不存在的表达过滤阈值")
            elif (
                returned_filter_threshold is None
                or float(returned_filter_threshold) != float(expected_filter_threshold)
            ):
                raise ValueError("R worker 返回的表达过滤阈值与分析计划不一致")
            if parameters.get("trend") is not True or parameters.get("robust") is not True:
                raise ValueError("limma worker 未返回固定的 trend/robust 参数")
            expected_min_samples = int(plan.preprocessing.get("min_samples", 0))
            returned_min_samples = parameters.get("min_samples")
            if (
                isinstance(returned_min_samples, bool)
                or not isinstance(returned_min_samples, int)
                or returned_min_samples != expected_min_samples
            ):
                raise ValueError("limma worker 返回的 min_samples 与分析计划不一致")
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
    def _validate_result_table(
        table: Any,
        feature_ids: list[str],
        plan: AnalysisPlan,
        measurement_type: str,
        parameters: dict[str, Any] | None = None,
    ) -> None:
        required = {
            "feature_key", "original_id", "gene_symbol", "log2FoldChange", "pvalue", "padj",
            "direction", "tested", "reason_not_tested", "mean_control_expression",
            "mean_treated_expression", "analysis_method", "analysis_basis", "effect_scale",
            "mean_expression_unit",
        }
        if not isinstance(table, list) or len(table) != len(feature_ids):
            raise ValueError("R worker 返回的结果行数与输入特征数不一致")
        returned_ids: list[str] = []
        expected_effect_scale = "log2_count_model" if plan.method == "DESEQ2" else "log2_expression"
        expected_unit = "RAW_COUNT" if plan.method == "DESEQ2" else measurement_type
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
            if row["effect_scale"] != expected_effect_scale or row["mean_expression_unit"] != expected_unit:
                raise ValueError("R worker 返回的效应尺度或表达单位与分析计划不一致")
            for key in ("log2FoldChange", "pvalue", "padj"):
                value = row[key]
                if value is not None and (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                ):
                    raise ValueError(f"R worker 返回的 {key} 不是有限数值或 NA")
            for key in ("pvalue", "padj"):
                value = row[key]
                if value is not None and not 0.0 <= value <= 1.0:
                    raise ValueError(f"R worker 返回的 {key} 超出 0 到 1 的概率范围")
            if row["tested"] and row["pvalue"] is None:
                raise ValueError("R worker 将没有有效 pvalue 的结果标记为已检验")
            if not row["tested"] and row["pvalue"] is not None:
                raise ValueError("R worker 将有有效 pvalue 的结果标记为未检验")
            if plan.method != "DESEQ2" and row["tested"] and row["padj"] is None:
                raise ValueError("limma 已检验结果缺少 BH 校正值")
            if row["padj"] is not None and row["pvalue"] is None:
                raise ValueError("R worker 返回了 padj 但对应 pvalue 缺失")
            if not isinstance(row["reason_not_tested"], str):
                raise ValueError("R worker 返回的 reason_not_tested 不是文本")
            if not row["tested"] and not row["reason_not_tested"].strip():
                raise ValueError("R worker 未为未检验结果提供原因")
            effect = row["log2FoldChange"]
            if effect is not None:
                expected_direction = "up" if effect > 0 else "down" if effect < 0 else "flat"
                if row["direction"] != expected_direction:
                    raise ValueError("R worker 返回的 direction 与 log2FoldChange 符号不一致")
            elif row["direction"] is not None:
                raise ValueError("R worker 为缺失效应值返回了方向标签")
        if plan.method == "DESEQ2" and parameters is not None:
            threshold = parameters.get("independent_filter_threshold")
            family = []
            for row in table:
                base_mean = row.get("baseMean")
                if (
                    isinstance(base_mean, bool)
                    or not isinstance(base_mean, (int, float))
                    or not math.isfinite(base_mean)
                ):
                    continue
                if threshold is None or base_mean >= float(threshold):
                    family.append(row)
            adjustment_rows = [row for row in family if row["pvalue"] is not None]
            adjustment_row_ids = {id(row) for row in adjustment_rows}
            if any(
                (row["padj"] is not None) != (id(row) in adjustment_row_ids)
                for row in table
            ):
                raise ValueError("DESeq2 的 padj 有效行与独立过滤后的检验集合不一致")
            expected_padj = AnalysisService._bh_adjust(
                [float(row["pvalue"]) for row in adjustment_rows]
            )
        else:
            adjustment_rows = [row for row in table if row["padj"] is not None]
            expected_padj = AnalysisService._bh_adjust(
                [float(row["pvalue"]) for row in adjustment_rows]
            )
        for row, expected in zip(adjustment_rows, expected_padj):
            if not math.isclose(float(row["padj"]), expected, rel_tol=1e-10, abs_tol=1e-12):
                raise ValueError("R worker 返回的 padj 与对应检验集合的 BH 校正不一致")
        if returned_ids != [str(value) for value in feature_ids]:
            raise ValueError("R worker 返回的特征顺序或编号与输入不一致")

    @staticmethod
    def _bh_adjust(pvalues: list[float]) -> list[float]:
        """Benjamini-Hochberg adjusted p-values in original row order."""
        count = len(pvalues)
        if not count:
            return []
        order = sorted(range(count), key=lambda index: pvalues[index])
        adjusted = [1.0] * count
        running_min = 1.0
        for rank_index in range(count - 1, -1, -1):
            original_index = order[rank_index]
            rank = rank_index + 1
            candidate = min(1.0, pvalues[original_index] * count / rank)
            running_min = min(running_min, candidate)
            adjusted[original_index] = running_min
        return adjusted

    @staticmethod
    def _validate_summary(summary: Any, table: Any, plan: AnalysisPlan) -> None:
        if not isinstance(summary, dict) or not isinstance(table, list):
            raise ValueError("R worker 未返回可核对的结果摘要")
        tested = [row for row in table if row["tested"]]
        significant = [
            row for row in tested
            if row["padj"] is not None and row["padj"] < plan.config.fdr_threshold
        ]
        magnitude = [
            row for row in significant
            if row["log2FoldChange"] is not None
            and abs(row["log2FoldChange"]) >= plan.config.lfc_threshold
        ]
        expected = {
            "feature_count": len(table),
            "tested_count": len(tested),
            "not_tested_count": len(table) - len(tested),
            "significant_count": len(significant),
            "significant_magnitude_count": len(magnitude),
            "up_count": sum(row["log2FoldChange"] > 0 for row in magnitude),
            "down_count": sum(row["log2FoldChange"] < 0 for row in magnitude),
            "fdr_threshold": plan.config.fdr_threshold,
            "lfc_threshold": plan.config.lfc_threshold,
        }
        for key, value in expected.items():
            observed = summary.get(key)
            if isinstance(value, int):
                if isinstance(observed, bool) or not isinstance(observed, (int, float)) or observed != value:
                    raise ValueError(f"R worker 的结果摘要 {key} 与结果表不一致")
            elif (
                isinstance(observed, bool)
                or not isinstance(observed, (int, float))
                or not math.isfinite(observed)
                or not math.isclose(float(observed), float(value), rel_tol=0, abs_tol=1e-12)
            ):
                raise ValueError(f"R worker 的结果摘要 {key} 与分析计划不一致")

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
    def _read_gene_symbols(path: Path, feature_ids: list[str]) -> list[str | None]:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle, delimiter="\t"))
        if not rows:
            return [None] * len(feature_ids)
        headers = [value.strip().casefold() for value in rows[0]]
        feature_key_index = next((index for index, value in enumerate(headers) if value == "feature_key"), None)
        symbol_index = next((index for index, value in enumerate(headers) if value in {"gene_symbol", "gene symbol", "symbol", "gene"}), None)
        if feature_key_index is None or symbol_index is None:
            return [None] * len(feature_ids)
        symbols_by_feature: dict[str, str | None] = {}
        for row in rows[1:]:
            if max(feature_key_index, symbol_index) >= len(row):
                continue
            feature_key = row[feature_key_index].strip()
            symbol = row[symbol_index].strip() or None
            if not feature_key:
                continue
            if feature_key in symbols_by_feature and symbols_by_feature[feature_key] != symbol:
                # Conflicting labels are ambiguous; never attach one by row position.
                symbols_by_feature[feature_key] = None
            else:
                symbols_by_feature[feature_key] = symbol
        return [symbols_by_feature.get(str(feature_id)) for feature_id in feature_ids]

    @staticmethod
    def _write_result(project_dir: Path, plan: AnalysisPlan, result: dict[str, Any]) -> None:
        analysis_dir = project_dir / "analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)
        (analysis_dir / "analysis-plan.json").write_text(json.dumps(plan.as_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (analysis_dir / "deg-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
