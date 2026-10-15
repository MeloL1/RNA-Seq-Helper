from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from rnaseq_helper.domain.models import JobContext
from rnaseq_helper.r_bridge.client import RBridgeClient
from rnaseq_helper.ui.workers.runtime_worker import _micro_payload


DIRECT_LIMMA = r'''
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
fit <- lmFit(m, design)
fit <- contrasts.fit(fit, makeContrasts(treated - control, levels = design))
fit <- eBayes(fit, trend = TRUE, robust = TRUE,
              winsor.tail.p = c(0.05, 0.10), proportion = 0.01,
              stdev.coef.lim = c(0.1, 4))
out <- data.frame(
  coefficient = as.numeric(fit$coefficients[, 1]),
  moderated_t = as.numeric(fit$t[, 1]),
  pvalue = as.numeric(fit$p.value[, 1]),
  stringsAsFactors = FALSE
)
cat(toJSON(out, dataframe = "rows", auto_unbox = TRUE, digits = 17, na = "null"))
'''


DIRECT_DESEQ2 = r'''
suppressPackageStartupMessages({
  library(jsonlite)
  library(DESeq2)
})
p <- fromJSON(commandArgs(trailingOnly = TRUE)[1], simplifyVector = FALSE)
m <- do.call(rbind, p$counts)
storage.mode(m) <- "integer"
features <- as.character(unlist(p$feature_ids))
samples <- as.character(unlist(p$sample_ids))
rownames(m) <- features
colnames(m) <- samples
groups <- factor(as.character(unlist(p$groups)), levels = c(p$control, p$test))
col_data <- data.frame(group = groups, row.names = samples)
dds <- DESeqDataSetFromMatrix(countData = m, colData = col_data, design = ~ group)
dds <- DESeq(dds, quiet = TRUE)
res <- results(dds, contrast = c("group", p$test, p$control), independentFiltering = FALSE)
out <- data.frame(
  feature_id = rownames(res),
  log2FoldChange = as.numeric(res$log2FoldChange),
  stat = as.numeric(res$stat),
  pvalue = as.numeric(res$pvalue),
  stringsAsFactors = FALSE
)
cat(toJSON(out, dataframe = "rows", auto_unbox = TRUE, digits = 17, na = "null"))
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


def _direct(rscript: str, code: str, payload: dict[str, object]) -> list[dict[str, object]]:
    with tempfile.TemporaryDirectory(prefix="rnaseq-helper-r-baseline-") as workdir:
        payload_path = Path(workdir) / "payload.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run(
            [rscript, "--vanilla", "-e", code, str(payload_path)],
            capture_output=True,
            text=True,
            check=False,
        )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _assert_close(actual: object, expected: object) -> None:
    if actual is None or expected is None:
        assert actual is expected
        return
    assert float(actual) == pytest.approx(float(expected), rel=1e-10, abs=1e-12)


def test_limma_worker_matches_independent_direct_r_baseline() -> None:
    rscript = _rscript()
    if not _has_package(rscript, "limma") or not _has_package(rscript, "jsonlite"):
        pytest.skip("limma/jsonlite 未安装")
    payload = _micro_payload()
    expected = _direct(rscript, DIRECT_LIMMA, payload)
    actual = RBridgeClient(rscript=rscript).run(
        "micro_limma", payload, JobContext(Path.cwd())
    ).result["table"]
    assert len(actual) == len(expected)
    for actual_row, expected_row in zip(actual, expected):
        for key in ("coefficient", "moderated_t", "pvalue"):
            _assert_close(actual_row[key], expected_row[key])


def test_deseq2_worker_matches_independent_direct_r_baseline() -> None:
    rscript = _rscript()
    if not _has_package(rscript, "DESeq2") or not _has_package(rscript, "jsonlite"):
        pytest.skip("DESeq2/jsonlite 未安装")
    payload = _micro_payload()
    expected = _direct(rscript, DIRECT_DESEQ2, payload)
    actual = RBridgeClient(rscript=rscript).run(
        "micro_deseq2", payload, JobContext(Path.cwd())
    ).result["table"]
    assert len(actual) == len(expected)
    for actual_row, expected_row in zip(actual, expected):
        assert actual_row["feature_id"] == expected_row["feature_id"]
        for key in ("log2FoldChange", "stat", "pvalue"):
            _assert_close(actual_row[key], expected_row[key])
