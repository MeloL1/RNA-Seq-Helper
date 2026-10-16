from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

from rnaseq_helper.domain.models import ResultFilterConfig


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def selected_pvalue(row: Mapping[str, Any], config: ResultFilterConfig) -> float | None:
    key = "padj" if config.pvalue_mode == "fdr" else "pvalue"
    return _finite_number(row.get(key))


def is_pvalue_significant(row: Mapping[str, Any], config: ResultFilterConfig) -> bool:
    value = selected_pvalue(row, config)
    return value is not None and value < config.pvalue_threshold


def passes_result_filter(row: Mapping[str, Any], config: ResultFilterConfig) -> bool:
    if row.get("tested") is not True or not is_pvalue_significant(row, config):
        return False
    effect = _finite_number(row.get("log2FoldChange"))
    return effect is not None and abs(effect) >= config.log2fc_threshold


def filtered_rows(rows: Iterable[Mapping[str, Any]], config: ResultFilterConfig) -> list[Mapping[str, Any]]:
    return [row for row in rows if passes_result_filter(row, config)]


def summarize_result(rows: Iterable[Mapping[str, Any]], config: ResultFilterConfig) -> dict[str, Any]:
    materialized = [row for row in rows if isinstance(row, Mapping)]
    tested = [row for row in materialized if row.get("tested") is True]
    pvalue_significant = [row for row in tested if is_pvalue_significant(row, config)]
    selected = [row for row in pvalue_significant if passes_result_filter(row, config)]
    up = sum((_finite_number(row.get("log2FoldChange")) or 0.0) > 0 for row in selected)
    down = sum((_finite_number(row.get("log2FoldChange")) or 0.0) < 0 for row in selected)
    return {
        "feature_count": len(materialized),
        "tested_count": len(tested),
        "not_tested_count": len(materialized) - len(tested),
        "significant_count": len(pvalue_significant),
        "significant_magnitude_count": len(selected),
        "up_count": up,
        "down_count": down,
        **config.as_dict(),
        "uses_unadjusted_pvalue": config.pvalue_mode == "pvalue",
    }
