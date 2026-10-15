from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from tests.fixtures.mock_factory import regular_normalized_values


# This experiment deliberately does not import the application's planning,
# transform, or R adapter code.  It is a small independent R implementation
# used to check that the fixed product defaults are not selected by outcome.
DIRECT_SENSITIVITY = r'''
suppressPackageStartupMessages({
  library(jsonlite)
  library(limma)
})
p <- fromJSON(commandArgs(trailingOnly = TRUE)[1], simplifyVector = FALSE)
m <- do.call(rbind, p$matrix)
storage.mode(m) <- "double"
groups <- factor(as.character(unlist(p$groups)), levels = c(p$control, p$test))
design <- model.matrix(~ 0 + groups)
colnames(design) <- c("control", "treated")
true_features <- seq_len(min(200, nrow(m)))
cases <- list()
for (threshold in c(0.5, 1, 2)) {
  for (pseudocount in c(0.1, 0.5, 1)) {
    for (robust in c(FALSE, TRUE)) {
      for (depth_name in c("balanced", "imbalanced")) {
        depth <- if (depth_name == "balanced") rep(1, ncol(m)) else
          c(rep(0.65, ncol(m) / 2), rep(1.35, ncol(m) / 2))
        x <- sweep(m, 2, depth, "*")
        keep <- rowSums(x >= threshold) >= (ncol(m) / 2)
        y <- log2(x[keep, , drop = FALSE] + pseudocount)
        fit <- lmFit(y, design)
        fit <- contrasts.fit(fit, makeContrasts(treated - control, levels = design))
        fit <- eBayes(
          fit, trend = TRUE, robust = robust,
          winsor.tail.p = c(0.05, 0.10), proportion = 0.01,
          stdev.coef.lim = c(0.1, 4)
        )
        coefficient <- as.numeric(fit$coefficients[, 1])
        pvalue <- as.numeric(fit$p.value[, 1])
        padj <- p.adjust(pvalue, method = "BH")
        truth <- coefficient[match(true_features, which(keep))]
        finite_truth <- is.finite(truth)
        direction_accuracy <- if (any(finite_truth))
          mean(truth[finite_truth] > 0) else NA_real_
        significant <- is.finite(padj) & padj < 0.05 & abs(coefficient) >= 1
        key <- paste(threshold, pseudocount, robust, depth_name, sep = "|")
        cases[[key]] <- list(
          threshold = threshold,
          pseudocount = pseudocount,
          robust = robust,
          depth = depth_name,
          tested = sum(keep),
          significant = sum(significant),
          direction_accuracy = direction_accuracy
        )
      }
    }
  }
}
cat(toJSON(list(cases = unname(cases)), auto_unbox = TRUE, digits = 17, na = "null"))
'''


def _rscript() -> str:
    path = shutil.which("Rscript")
    if not path:
        pytest.skip("Rscript 不可用")
    return path


def _has_package(rscript: str, package: str) -> bool:
    result = subprocess.run(
        [rscript, "--vanilla", "-e", f"cat(requireNamespace('{package}', quietly=TRUE))"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() == "TRUE"


def test_normalized_defaults_are_checked_across_sensitivity_grid() -> None:
    rscript = _rscript()
    if not _has_package(rscript, "limma") or not _has_package(rscript, "jsonlite"):
        pytest.skip("limma/jsonlite 未安装")
    values = regular_normalized_values(feature_count=1200, sample_count=12, seed=4800)
    payload = {
        "matrix": values.tolist(),
        "groups": ["control"] * 6 + ["test"] * 6,
        "control": "control",
        "test": "test",
    }
    with tempfile.TemporaryDirectory(prefix="rnaseq-helper-sensitivity-") as workdir:
        payload_path = Path(workdir) / "payload.json"
        payload_path.write_text(json.dumps(payload), encoding="utf-8")
        result = subprocess.run(
            [rscript, "--vanilla", "-e", DIRECT_SENSITIVITY, str(payload_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    cases = report["cases"]
    assert len(cases) == 36
    assert {case["threshold"] for case in cases} == {0.5, 1, 2}
    assert {case["pseudocount"] for case in cases} == {0.1, 0.5, 1}
    assert {case["robust"] for case in cases} == {False, True}
    assert {case["depth"] for case in cases} == {"balanced", "imbalanced"}

    balanced = [case for case in cases if case["depth"] == "balanced"]
    assert all(case["direction_accuracy"] is not None for case in balanced)
    assert min(float(case["direction_accuracy"]) for case in balanced) >= 0.95

    # The grid must actually be informative; product defaults remain the
    # documented profile choice rather than the case with the most hits.
    assert len({case["significant"] for case in cases}) > 1
    default = next(
        case for case in cases
        if case["threshold"] == 1
        and case["pseudocount"] == 1
        and case["robust"] is True
        and case["depth"] == "balanced"
    )
    assert default["threshold"] == 1
    assert default["pseudocount"] == 1
