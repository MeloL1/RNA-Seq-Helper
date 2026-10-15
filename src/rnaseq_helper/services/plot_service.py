from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.cluster.hierarchy import leaves_list, linkage

from rnaseq_helper.domain.models import AnalysisPlan, ExpressionMatrix


PALETTE = {"up": "#D55E00", "down": "#0072B2", "ns": "#999999"}


class PlotService:
    """按统一矩阵和固定阈值生成五张离线诊断/结果图。"""

    def build(self, matrix: ExpressionMatrix, plan: AnalysisPlan, result: dict[str, Any]) -> dict[str, Path]:
        project_dir = matrix.values.path.parent.parent
        figure_dir = project_dir / "figures"
        figure_dir.mkdir(parents=True, exist_ok=True)
        feature_ids, sample_ids, plot_values, plot_transform = self._plot_matrix(result)
        display_labels = self._display_labels(result, feature_ids)
        assignments = plan.design.get("assignments", {})
        groups = [str(assignments.get(sample_id, "unassigned")) for sample_id in sample_ids]
        figures = {
            "pca": self._pca(figure_dir / "pca.png", plot_values, sample_ids, groups, plan, plot_transform),
            "sample_correlation": self._correlation(figure_dir / "sample-correlation.png", plot_values, sample_ids, plot_transform),
            "pvalue_histogram": self._pvalue_histogram(figure_dir / "p-value-histogram.png", result),
            "volcano": self._volcano(figure_dir / "volcano.png", result, plan, display_labels),
            "top_heatmap": self._heatmap(
                figure_dir / "top-heatmap.png",
                plot_values,
                feature_ids,
                sample_ids,
                groups,
                result,
                plan,
                plot_transform,
                display_labels,
            ),
        }
        (figure_dir / "figure-manifest.json").write_text(
            json.dumps({key: str(path) for key, path in figures.items()}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return figures

    @staticmethod
    def _plot_matrix(result: dict[str, Any]) -> tuple[list[str], list[str], np.ndarray, str]:
        """读取 runner 生成的绘图矩阵；绘图绝不回退到原始输入矩阵。"""
        plot = result.get("plot_matrix") if isinstance(result, dict) else None
        if not isinstance(plot, dict):
            raise ValueError("R worker 未返回已变换的绘图矩阵")
        feature_ids = plot.get("feature_ids")
        sample_ids = plot.get("sample_ids")
        transform = plot.get("transform")
        values = plot.get("values")
        if not isinstance(feature_ids, list) or not feature_ids or any(not isinstance(value, str) for value in feature_ids):
            raise ValueError("绘图矩阵没有可用特征编号")
        if not isinstance(sample_ids, list) or not sample_ids or any(not isinstance(value, str) for value in sample_ids):
            raise ValueError("绘图矩阵没有可用样本编号")
        if len(set(feature_ids)) != len(feature_ids) or len(set(sample_ids)) != len(sample_ids):
            raise ValueError("绘图矩阵的特征或样本编号重复")
        if not isinstance(transform, str) or not transform.strip():
            raise ValueError("绘图矩阵缺少转换说明")
        if not isinstance(values, list) or len(values) != len(feature_ids):
            raise ValueError("绘图矩阵特征数与数值行数不一致")
        if any(not isinstance(row, list) or len(row) != len(sample_ids) for row in values):
            raise ValueError("绘图矩阵样本数与数值列数不一致")
        array = np.asarray(values, dtype=float)
        if not np.isfinite(array).all():
            raise ValueError("绘图矩阵含无效数值")
        return feature_ids, sample_ids, array, transform.strip()

    @staticmethod
    def _clean_gene_symbol(value: Any) -> str | None:
        """把结果表中的空/占位 gene symbol 统一视为未映射。"""
        if value is None:
            return None
        text = str(value).strip()
        if not text or text.casefold() in {"none", "nan", "na", "n/a", "null"}:
            return None
        return text

    @classmethod
    def _display_labels(cls, result: dict[str, Any], feature_ids: list[str]) -> dict[str, str]:
        """图中优先显示 gene symbol；无 symbol 时退回 feature ID。

        同一个 symbol 可能对应多个 feature。此时仍保留 symbol，但附加
        feature ID，避免热图/火山图的标签看起来像同一个基因而无法追溯。
        """
        symbol_by_feature: dict[str, str] = {}
        for row in result.get("table", []):
            if not isinstance(row, dict):
                continue
            feature_id = str(row.get("feature_key") or row.get("original_id") or "").strip()
            symbol = cls._clean_gene_symbol(row.get("gene_symbol"))
            if feature_id and symbol:
                symbol_by_feature[feature_id] = symbol

        candidates = [symbol_by_feature.get(feature_id, feature_id) for feature_id in feature_ids]
        symbol_counts = Counter(
            candidate
            for feature_id, candidate in zip(feature_ids, candidates)
            if candidate != feature_id and candidate
        )
        labels: dict[str, str] = {}
        for feature_id, candidate in zip(feature_ids, candidates):
            if candidate == feature_id or not candidate:
                labels[feature_id] = feature_id
            elif symbol_counts[candidate] > 1:
                labels[feature_id] = f"{candidate} ({feature_id})"
            else:
                labels[feature_id] = candidate
        return labels

    @staticmethod
    def _style() -> None:
        plt.rcParams.update({
            "font.family": ["PingFang SC", "Arial", "Helvetica", "DejaVu Sans", "sans-serif"],
            "font.size": 10,
            "axes.spines.right": False,
            "axes.spines.top": False,
            "axes.linewidth": 1.2,
            "legend.frameon": False,
            "svg.fonttype": "none",
        })

    @classmethod
    def _pca(
        cls,
        path: Path,
        values: np.ndarray,
        sample_ids: list[str],
        groups: list[str],
        plan: AnalysisPlan,
        plot_transform: str | None = None,
    ) -> Path:
        cls._style()
        if values.shape[0] > 2000:
            high_variance = np.argsort(np.var(values, axis=1))[::-1][:2000]
            values = values[high_variance, :]
        centered = values - np.mean(values, axis=1, keepdims=True)
        _, singular_values, components = np.linalg.svd(centered, full_matrices=False)
        coordinates = np.zeros((values.shape[1], 2), dtype=float)
        component_count = min(2, components.shape[0])
        coordinates[:, :component_count] = (
            components[:component_count, :] * singular_values[:component_count, None]
        ).T
        variance = np.zeros(2, dtype=float)
        raw_variance = singular_values ** 2
        if np.sum(raw_variance):
            variance[:component_count] = raw_variance[:component_count] / np.sum(raw_variance)
        fig, ax = plt.subplots(figsize=(6.2, 5.0), constrained_layout=True)
        for group in dict.fromkeys(groups):
            mask = np.asarray(groups) == group
            ax.scatter(coordinates[mask, 0], coordinates[mask, 1], s=42, label=group, alpha=0.85)
            for x_value, y_value, label in zip(coordinates[mask, 0], coordinates[mask, 1], np.asarray(sample_ids)[mask]):
                ax.text(x_value, y_value, label, fontsize=8, va="bottom", ha="left")
        ax.set_xlabel(f"PC1 ({variance[0]:.1%})")
        ax.set_ylabel(f"PC2 ({variance[1]:.1%})")
        ax.set_title("PCA of transformed expression")
        ax.text(
            0.02,
            0.98,
            f"{cls._transform_label(plan, plot_transform)}; top {min(values.shape[0], 2000):,} variable features",
            transform=ax.transAxes,
            va="top",
            fontsize=8,
            color="#4D4D4D",
        )
        ax.legend(title="Group")
        fig.savefig(path, dpi=300, bbox_inches="tight")
        plt.close(fig)
        return path

    @classmethod
    def _correlation(cls, path: Path, values: np.ndarray, sample_ids: list[str], plot_transform: str | None = None) -> Path:
        cls._style()
        # 零方差样本的 Pearson r 不可定义，保留为掩码空单元格，不能伪造为 0。
        correlation = cls._sample_correlation(values)
        fig, ax = plt.subplots(figsize=(6.2, 5.2), constrained_layout=True)
        image = ax.imshow(correlation, cmap="RdBu_r", vmin=-1, vmax=1)
        ax.set_xticks(range(len(sample_ids)), sample_ids, rotation=45, ha="right")
        ax.set_yticks(range(len(sample_ids)), sample_ids)
        ax.set_title("Sample Pearson correlation")
        if plot_transform:
            ax.text(0.02, 1.02, plot_transform, transform=ax.transAxes, va="bottom", fontsize=8, color="#4D4D4D")
        fig.colorbar(image, ax=ax, label="Pearson r", shrink=0.8)
        fig.savefig(path, dpi=300, bbox_inches="tight")
        plt.close(fig)
        return path

    @staticmethod
    def _sample_correlation(values: np.ndarray) -> np.ma.MaskedArray:
        """返回样本 Pearson 相关矩阵，并保留零方差导致的 NaN。"""
        centered = values.T - np.mean(values.T, axis=1, keepdims=True)
        numerator = centered @ centered.T
        sum_squares = np.sum(centered * centered, axis=1)
        denominator = np.sqrt(sum_squares[:, None] * sum_squares[None, :])
        correlation = np.full(numerator.shape, np.nan, dtype=float)
        np.divide(numerator, denominator, out=correlation, where=denominator > 0)
        return np.ma.masked_invalid(correlation)

    @classmethod
    def _pvalue_histogram(cls, path: Path, result: dict[str, Any]) -> Path:
        """保存原始 p 值分布，避免只凭火山图判断模型校准。"""
        cls._style()
        pvalues = np.asarray(
            [row.get("pvalue") for row in result.get("table", []) if isinstance(row.get("pvalue"), (int, float))],
            dtype=float,
        )
        pvalues = pvalues[np.isfinite(pvalues) & (pvalues >= 0) & (pvalues <= 1)]
        fig, ax = plt.subplots(figsize=(6.2, 4.6), constrained_layout=True)
        if pvalues.size:
            ax.hist(pvalues, bins=50, range=(0, 1), color="#4C78A8", edgecolor="white", linewidth=0.35)
            ax.set_xlim(0, 1)
            subtitle = f"{pvalues.size:,} finite p-values"
        else:
            ax.text(0.5, 0.5, "No finite p-values to plot", ha="center", va="center", transform=ax.transAxes)
            subtitle = "No finite p-values to plot"
        ax.set_xlabel("Raw p-value")
        ax.set_ylabel("Number of features")
        ax.set_title("Raw p-value distribution")
        ax.text(0.02, 0.98, subtitle, transform=ax.transAxes, va="top", fontsize=8, color="#4D4D4D")
        fig.savefig(path, dpi=300, bbox_inches="tight")
        plt.close(fig)
        return path

    @classmethod
    def _volcano(
        cls,
        path: Path,
        result: dict[str, Any],
        plan: AnalysisPlan,
        display_labels: dict[str, str] | None = None,
    ) -> Path:
        cls._style()
        rows = result.get("table", [])
        lfc_cutoff = plan.config.lfc_threshold
        fdr = plan.config.fdr_threshold
        points: list[tuple[float, float, str]] = []
        ranked: list[tuple[float, str, float, float]] = []
        for row in rows:
            lfc, padj = row.get("log2FoldChange"), row.get("padj")
            if not isinstance(lfc, (int, float)) or not np.isfinite(lfc):
                continue
            if not isinstance(padj, (int, float)) or not np.isfinite(padj):
                continue
            significant = padj < fdr
            y_value = -np.log10(max(float(padj), np.finfo(float).tiny))
            color = PALETTE["up"] if significant and lfc > lfc_cutoff else PALETTE["down"] if significant and lfc < -lfc_cutoff else PALETTE["ns"]
            points.append((float(lfc), float(y_value), color))
            if significant:
                feature_id = str(row.get("feature_key") or row.get("original_id") or "")
                label = (display_labels or {}).get(feature_id, feature_id)
                ranked.append((y_value * abs(float(lfc)), label, float(lfc), float(y_value)))
        fig, ax = plt.subplots(figsize=(6.2, 5.0), constrained_layout=True)
        if points:
            ax.scatter([item[0] for item in points], [item[1] for item in points], s=10, c=[item[2] for item in points], alpha=0.65, rasterized=len(points) > 5000)
        ax.axvline(-lfc_cutoff, color="#4D4D4D", linestyle="--", linewidth=0.8)
        ax.axvline(lfc_cutoff, color="#4D4D4D", linestyle="--", linewidth=0.8)
        ax.set_xlabel("Group difference (log2 expression scale)")
        ax.set_ylabel("−log10(FDR)")
        ax.set_title("Differential expression volcano")
        ax.text(0.02, 0.98, cls._transform_label(plan), transform=ax.transAxes, va="top", fontsize=8, color="#4D4D4D")
        for _, label, x_value, y_value in sorted(ranked, reverse=True)[:10]:
            ax.annotate(label, (x_value, y_value), xytext=(3, 3), textcoords="offset points", fontsize=7)
        fig.savefig(path, dpi=300, bbox_inches="tight")
        plt.close(fig)
        return path

    @classmethod
    def _heatmap(
        cls,
        path: Path,
        values: np.ndarray,
        feature_ids: list[str],
        sample_ids: list[str],
        groups: list[str],
        result: dict[str, Any],
        plan: AnalysisPlan,
        plot_transform: str | None = None,
        display_labels: dict[str, str] | None = None,
    ) -> Path:
        cls._style()
        rows = result.get("table", [])
        row_by_id = {str(row.get("feature_key")): row for row in rows}
        selected = []
        for feature_id in feature_ids:
            row = row_by_id.get(feature_id, {})
            if isinstance(row.get("padj"), (int, float)) and np.isfinite(row["padj"]) and row["padj"] < plan.config.fdr_threshold and isinstance(row.get("log2FoldChange"), (int, float)) and abs(row["log2FoldChange"]) >= plan.config.lfc_threshold:
                selected.append(feature_id)
        if not selected:
            selected = [feature_ids[index] for index in np.argsort(np.var(values, axis=1))[::-1][:plan.config.top_heatmap_features]]
        selected = selected[:plan.config.top_heatmap_features]
        indices = [feature_ids.index(feature_id) for feature_id in selected]
        data = values[indices, :]
        row_sd = np.std(data, axis=1, ddof=1)
        keep = np.isfinite(row_sd) & (row_sd > 0)
        data = data[keep]
        selected = [feature_id for feature_id, valid in zip(selected, keep) if valid]
        selected_labels = [
            (display_labels or {}).get(feature_id, feature_id)
            for feature_id in selected
        ]
        if data.shape[0] == 0:
            fig, ax = plt.subplots(figsize=(7.0, 4.0), constrained_layout=True)
            ax.text(0.5, 0.5, "No non-constant features to plot", ha="center", va="center", transform=ax.transAxes)
            ax.set_axis_off()
            if plot_transform:
                ax.text(0.02, 0.02, plot_transform, transform=ax.transAxes, fontsize=8, color="#4D4D4D")
            fig.savefig(path, dpi=300, bbox_inches="tight")
            plt.close(fig)
            return path
        if data.shape[0] > 1:
            order = leaves_list(linkage(data, method="ward", metric="euclidean"))
            data = data[order]
            selected = [selected[index] for index in order]
            selected_labels = [selected_labels[index] for index in order]
        z = (data - np.mean(data, axis=1, keepdims=True)) / np.std(data, axis=1, ddof=1, keepdims=True)
        bounds = max(float(np.nanquantile(np.abs(z), 0.99)) if z.size else 1.0, 1.0)
        column_order = np.argsort(np.asarray(groups))
        fig, ax = plt.subplots(figsize=(7.0, max(4.0, min(12.0, 2.5 + len(selected) * 0.18))), constrained_layout=True)
        image = ax.imshow(z[:, column_order], cmap="RdBu_r", vmin=-bounds, vmax=bounds, aspect="auto")
        ax.set_xticks(range(len(sample_ids)), np.asarray(sample_ids)[column_order], rotation=45, ha="right")
        ax.set_yticks(range(len(selected_labels)), selected_labels, fontsize=7)
        ax.set_title("Top features (row z-score; Ward.D2-equivalent)")
        if plot_transform:
            ax.text(0.02, 1.02, plot_transform, transform=ax.transAxes, va="bottom", fontsize=8, color="#4D4D4D")
        fig.colorbar(image, ax=ax, label="Within-feature z-score", shrink=0.65)
        fig.savefig(path, dpi=300, bbox_inches="tight")
        plt.close(fig)
        return path

    @staticmethod
    def _transform_label(plan: AnalysisPlan, plot_transform: str | None = None) -> str:
        if plot_transform:
            return plot_transform
        transform = str(plan.preprocessing.get("transform", ""))
        if transform == "log2(x+1)":
            return "log2(x+1)"
        if transform == "already_log2":
            return "confirmed log2 expression"
        return transform or "filtered expression"
