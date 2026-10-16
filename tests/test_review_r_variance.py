from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from rnaseq_helper.domain.models import JobContext
from rnaseq_helper.r_bridge.client import RBridgeClient


DIRECT_FORMAL_LIMMA = r'''
suppressPackageStartupMessages({
  library(jsonlite)
  library(limma)
})
p <- fromJSON(commandArgs(trailingOnly = TRUE)[1], simplifyVector = FALSE)
m <- do.call(rbind, p$matrix)
storage.mode(m) <- "double"
sample_ids <- as.character(unlist(p$sample_ids))
groups <- factor(as.character(unlist(p$groups)),
                 levels = c(p$control, p$test))
design_data <- data.frame(group = groups)
for (term_name in c("batch", "subject")) {
  values <- p[[term_name]]
  if (!is.null(values) && length(values) > 0) {
    value_map <- unlist(values)
    design_data[[term_name]] <- factor(as.character(value_map[sample_ids]))
  }
}
terms <- c(setdiff(names(design_data), "group"), "group")
design <- model.matrix(~ 0 + group, data = design_data)
group_columns <- grep("^group", colnames(design))
colnames(design)[group_columns] <- c("control", "test")
for (term_name in c("batch", "subject")) {
  if (term_name %in% names(design_data)) {
    covariate <- model.matrix(as.formula(paste("~", term_name)), data = design_data)
    covariate <- covariate[, setdiff(colnames(covariate), "(Intercept)"), drop = FALSE]
    if (ncol(covariate)) design <- cbind(design, covariate)
  }
}
fit_model <- lmFit(m, design)
fit_model <- contrasts.fit(fit_model, makeContrasts(test - control, levels = design))
scale <- pmax(1, rowMeans(m^2))
degenerate <- fit_model$sigma^2 <= 1e-12 * scale
fit <- fit_model[!degenerate, , drop = FALSE]
ebayes_args <- list(
  fit = fit,
  trend = TRUE,
  robust = TRUE,
  winsor.tail.p = c(0.05, 0.10),
  proportion = 0.01,
  stdev.coef.lim = c(0.1, 4)
)
if ("legacy" %in% names(formals(eBayes))) ebayes_args$legacy <- TRUE
fit <- do.call(eBayes, ebayes_args)
pvalue <- rep(NA_real_, nrow(m))
valid_indices <- which(!degenerate)
pvalue[valid_indices] <- as.numeric(fit$p.value[, 1])
pvalue[degenerate] <- NA_real_
valid <- !degenerate & is.finite(fit_model$coefficients[, 1]) & is.finite(pvalue)
padj <- rep(NA_real_, nrow(m))
padj[valid] <- p.adjust(pvalue[valid], method = "BH")
out <- list(
  coefficient = as.numeric(fit_model$coefficients[, 1]),
  pvalue = pvalue,
  padj = padj,
  degenerate = degenerate,
  residual_df = fit_model$df.residual,
  design_rank = qr(design)$rank
)
cat(toJSON(out, auto_unbox = TRUE, digits = 17, na = "null"))
'''


DIRECT_LINEAR_FILTERED_LIMMA = r'''
suppressPackageStartupMessages({ library(jsonlite); library(limma) })
p <- fromJSON(commandArgs(trailingOnly = TRUE)[1], simplifyVector = FALSE)
m <- do.call(rbind, p$matrix)
storage.mode(m) <- "double"
keep <- rowSums(m >= p$filter_threshold) >= p$min_samples
analysis_matrix <- log2(m[keep, , drop = FALSE] + 1)
groups <- factor(as.character(unlist(p$groups)), levels = c(p$control, p$test))
design <- model.matrix(~ 0 + groups)
colnames(design) <- c("control", "test")
fit_model <- contrasts.fit(lmFit(analysis_matrix, design), makeContrasts(test - control, levels = design))
scale <- pmax(1, rowMeans(analysis_matrix^2))
degenerate_kept <- fit_model$sigma^2 <= 1e-12 * scale
valid <- which(!degenerate_kept)
ebayes_args <- list(fit = fit_model[valid, , drop = FALSE], trend = TRUE, robust = TRUE,
                    winsor.tail.p = c(0.05, 0.10), proportion = 0.01,
                    stdev.coef.lim = c(0.1, 4))
if ("legacy" %in% names(formals(eBayes))) ebayes_args$legacy <- TRUE
ebayes_fit <- do.call(eBayes, ebayes_args)
coefficient <- rep(NA_real_, nrow(m))
pvalue <- rep(NA_real_, nrow(m))
padj <- rep(NA_real_, nrow(m))
coefficient[keep] <- as.numeric(fit_model$coefficients[, 1])
kept_indices <- which(keep)
valid_indices <- kept_indices[valid]
pvalue[valid_indices] <- as.numeric(ebayes_fit$p.value[, 1])
padj[valid_indices] <- p.adjust(pvalue[valid_indices], method = "BH")
degenerate <- rep(FALSE, nrow(m))
degenerate[kept_indices] <- degenerate_kept
cat(toJSON(list(keep = keep, coefficient = coefficient, pvalue = pvalue, padj = padj,
                degenerate = degenerate), auto_unbox = FALSE, digits = 17, na = "null"))
'''


def _rscript() -> str:
    path = shutil.which("Rscript")
    if not path:
        pytest.skip("Rscript 不可用")
    return path


def _has_package(rscript: str, package: str) -> bool:
    check = subprocess.run(
        [rscript, "--vanilla", "-e", f"cat(requireNamespace('{package}', quietly=TRUE))"],
        capture_output=True,
        text=True,
        check=False,
    )
    return check.stdout.strip() == "TRUE"


def _direct(rscript: str, code: str, payload: dict[str, object]) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="rnaseq-helper-r-variance-") as workdir:
        payload_path = Path(workdir) / "payload.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run(
            [rscript, "--vanilla", "-e", code, str(payload_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    assert result.returncode == 0, result.stderr
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return json.loads(lines[-1])


def _payload() -> dict[str, object]:
    return {
        "feature_ids": ["stable", "degenerate", "stable_2", "stable_3"],
        "sample_ids": ["C1", "C2", "C3", "C4", "T1", "T2", "T3", "T4"],
        "groups": ["control"] * 4 + ["treated"] * 4,
        "control": "control",
        "test": "treated",
        "fdr_threshold": 0.05,
        "lfc_threshold": 1,
        "measurement_type": "TPM",
        "transform": "already_log2",
        "method": "LIMMA_ON_LOG2_TPM",
        "min_samples": 0,
        "gene_symbols": [None] * 4,
        "matrix": [
            [2.0, 2.2, 1.8, 2.1, 4.0, 4.2, 3.8, 4.1],
            [2.0, 2.0, 2.0, 2.0, 5.0, 5.0, 5.0, 5.0],
            [1.0, 1.4, 0.8, 1.2, 1.6, 1.9, 1.3, 1.7],
            [5.0, 5.3, 4.7, 5.1, 5.4, 5.0, 5.8, 5.2],
        ],
    }


def _assert_close(actual: object, expected: object) -> None:
    if actual is None or expected is None:
        assert actual is expected
        return
    assert float(actual) == pytest.approx(float(expected), rel=1e-10, abs=1e-12)


def test_formal_limma_marks_degenerate_rows_and_uses_bh_on_valid_rows() -> None:
    rscript = _rscript()
    if not _has_package(rscript, "limma") or not _has_package(rscript, "jsonlite"):
        pytest.skip("limma/jsonlite 未安装")
    payload = _payload()
    expected = _direct(rscript, DIRECT_FORMAL_LIMMA, payload)
    actual = RBridgeClient(rscript=rscript).run(
        "analyze_limma",
        payload,
        JobContext(Path.cwd()),
        "normalized-log-limma-trend-v1",
    ).result
    table = actual["table"]
    assert len(table) == len(payload["feature_ids"])
    for index, row in enumerate(table):
        _assert_close(row["log2FoldChange"], expected["coefficient"][index])
        _assert_close(row["pvalue"], expected["pvalue"][index])
        _assert_close(row["padj"], expected["padj"][index])
        assert row["tested"] is (not expected["degenerate"][index])
    degenerate_row = table[1]
    assert degenerate_row["tested"] is False
    assert degenerate_row["reason_not_tested"] == "degenerate_residual_variance"
    assert degenerate_row["pvalue"] is None
    assert degenerate_row["padj"] is None
    assert degenerate_row["log2FoldChange"] == pytest.approx(3.0)
    assert actual["diagnostics"]["degenerate_count"] == 1
    assert actual["diagnostics"]["pvalue_count"] == 3
    assert actual["diagnostics"]["residual_df"] == expected["residual_df"]
    assert actual["parameters"]["p_adjust_method"] == "BH"
    assert actual["parameters"]["legacy_supported"] is True
    assert actual["parameters"]["legacy"] is True


def test_formal_limma_uses_actual_paired_batch_design_and_plot_subset() -> None:
    rscript = _rscript()
    if not _has_package(rscript, "limma") or not _has_package(rscript, "jsonlite"):
        pytest.skip("limma/jsonlite 未安装")
    payload = _payload()
    # Robust empirical Bayes needs more than a couple of non-degenerate rows
    # when subject and batch terms are present.
    for index in range(4, 12):
        payload["feature_ids"].append(f"stable_{index}")
        payload["gene_symbols"].append(None)
        payload["matrix"].append([
            float(index) + delta
            for delta in (0.0, 0.1, -0.1, 0.05, 0.8, 0.9, 1.0, 0.85)
        ])
    payload["subject"] = {
        "C1": "S1", "C2": "S2", "C3": "S3", "C4": "S4",
        "T1": "S1", "T2": "S2", "T3": "S3", "T4": "S4",
    }
    payload["batch"] = {
        "C1": "B1", "C2": "B1", "C3": "B2", "C4": "B2",
        "T1": "B1", "T2": "B1", "T3": "B2", "T4": "B2",
    }
    expected = _direct(rscript, DIRECT_FORMAL_LIMMA, payload)
    actual = RBridgeClient(rscript=rscript).run(
        "analyze_limma",
        payload,
        JobContext(Path.cwd()),
        "normalized-log-limma-trend-v1",
    ).result
    assert actual["diagnostics"]["residual_df"] == expected["residual_df"]
    assert actual["diagnostics"]["residual_df"][0] == 3
    assert actual["diagnostics"]["degenerate_count"] == 2
    assert len(actual["table"]) == len(expected["coefficient"])
    for index, row in enumerate(actual["table"]):
        _assert_close(row["log2FoldChange"], expected["coefficient"][index])
        _assert_close(row["pvalue"], expected["pvalue"][index])
        _assert_close(row["padj"], expected["padj"][index])
        assert row["tested"] is (not expected["degenerate"][index])
    plot = actual["plot_matrix"]
    assert plot["feature_ids"] == payload["feature_ids"]
    assert plot["sample_ids"] == payload["sample_ids"]
    assert plot["transform"] == "already_log2"
    assert plot["values"] == payload["matrix"]


def test_formal_linear_limma_matches_independent_filter_transform_and_bh_baseline() -> None:
    rscript = _rscript()
    if not _has_package(rscript, "limma") or not _has_package(rscript, "jsonlite"):
        pytest.skip("limma/jsonlite 未安装")
    sample_ids = ["C1", "C2", "C3", "T1", "T2", "T3"]
    matrix = []
    feature_ids = []
    for index in range(12):
        base = 4.0 + index * 2
        matrix.append([base, base + 2, base - 1, base + 3, base + 5, base + 1])
        feature_ids.append(f"stable_{index:02d}")
    matrix.extend([
        [1, 0, 1, 1, 0, 0],  # exactly min_samples cells meet the inclusive threshold
        [1, 0, 0, 0, 0, 0],  # below the filter threshold in sample count
        [1, 1, 1, 1, 1, 1],  # retained by filtering, then excluded as degenerate
    ])
    feature_ids.extend(["boundary", "filtered", "all_zero"])
    payload = {
        "matrix": matrix,
        "feature_ids": feature_ids,
        "sample_ids": sample_ids,
        "groups": ["control"] * 3 + ["treated"] * 3,
        "control": "control",
        "test": "treated",
        "fdr_threshold": 0.05,
        "lfc_threshold": 1.0,
        "measurement_type": "TPM",
        "transform": "log2(x+1)",
        "method": "LIMMA_ON_LOG2_TPM",
        "filter_threshold": 1.0,
        "min_samples": 3,
        "gene_symbols": [None] * len(feature_ids),
    }
    expected = _direct(rscript, DIRECT_LINEAR_FILTERED_LIMMA, payload)
    actual = RBridgeClient(rscript=rscript).run(
        "analyze_limma", payload, JobContext(Path.cwd()), "normalized-log-limma-trend-v1",
    ).result["table"]

    assert [row["feature_key"] for row in actual] == feature_ids
    assert expected["keep"][-3:] == [True, False, True]
    assert expected["degenerate"][-1] is True
    for index, row in enumerate(actual):
        _assert_close(row["log2FoldChange"], expected["coefficient"][index])
        _assert_close(row["pvalue"], expected["pvalue"][index])
        _assert_close(row["padj"], expected["padj"][index])
        assert row["tested"] is (expected["keep"][index] and not expected["degenerate"][index])
    assert actual[-3]["tested"] is True
    assert actual[-2]["reason_not_tested"] == "below_expression_filter"
    assert actual[-2]["log2FoldChange"] is None
    assert actual[-1]["reason_not_tested"] == "degenerate_residual_variance"
    assert actual[-1]["pvalue"] is None and actual[-1]["padj"] is None
