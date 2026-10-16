from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
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


DIRECT_DESEQ2_BATCH_ANALYSIS = r'''
suppressPackageStartupMessages({ library(jsonlite); library(DESeq2) })
p <- fromJSON(commandArgs(trailingOnly = TRUE)[1], simplifyVector = FALSE)
m <- do.call(rbind, p$counts)
storage.mode(m) <- "integer"
samples <- as.character(unlist(p$sample_ids))
features <- as.character(unlist(p$feature_ids))
rownames(m) <- features
colnames(m) <- samples
groups <- factor(as.character(unlist(p$groups)), levels = c(p$control, p$test))
batch_map <- unlist(p$batch)
col_data <- data.frame(batch = factor(as.character(batch_map[samples])), group = groups, row.names = samples)
dds <- DESeqDataSetFromMatrix(countData = m, colData = col_data, design = ~ 0 + batch + group)
dds <- DESeq(
  dds, test = "Wald", fitType = "parametric", sfType = "ratio",
  betaPrior = FALSE, minReplicatesForReplace = 7, useT = FALSE,
  minmu = 0.5, parallel = FALSE, quiet = TRUE
)
res <- results(
  dds, contrast = c("group", p$test, p$control), alpha = p$fdr_threshold,
  cooksCutoff = TRUE, independentFiltering = TRUE, pAdjustMethod = "BH"
)
out <- data.frame(feature_key = rownames(res), log2FoldChange = as.numeric(res$log2FoldChange),
                  stat = as.numeric(res$stat), pvalue = as.numeric(res$pvalue),
                  padj = as.numeric(res$padj), stringsAsFactors = FALSE)
cat(toJSON(out, dataframe = "rows", auto_unbox = TRUE, digits = 17, na = "null"))
'''


DIRECT_DESEQ2_PAIRED_BATCH_ANALYSIS = r'''
suppressPackageStartupMessages({ library(jsonlite); library(DESeq2) })
p <- fromJSON(commandArgs(trailingOnly = TRUE)[1], simplifyVector = FALSE)
m <- do.call(rbind, p$counts)
storage.mode(m) <- "integer"
samples <- as.character(unlist(p$sample_ids))
features <- as.character(unlist(p$feature_ids))
rownames(m) <- features
colnames(m) <- samples
groups <- factor(as.character(unlist(p$groups)), levels = c(p$control, p$test))
batch_map <- unlist(p$batch)
subject_map <- unlist(p$subject)
col_data <- data.frame(
  batch = factor(as.character(batch_map[samples])),
  subject = factor(as.character(subject_map[samples])),
  group = groups,
  row.names = samples
)
dds <- DESeqDataSetFromMatrix(countData = m, colData = col_data,
                              design = ~ 0 + batch + subject + group)
dds <- DESeq(
  dds, test = "Wald", fitType = "parametric", sfType = "ratio",
  betaPrior = FALSE, minReplicatesForReplace = 7, useT = FALSE,
  minmu = 0.5, parallel = FALSE, quiet = TRUE
)
res <- results(
  dds, contrast = c("group", p$test, p$control), alpha = p$fdr_threshold,
  cooksCutoff = TRUE, independentFiltering = TRUE, pAdjustMethod = "BH"
)
out <- data.frame(feature_key = rownames(res), log2FoldChange = as.numeric(res$log2FoldChange),
                  stat = as.numeric(res$stat), pvalue = as.numeric(res$pvalue),
                  padj = as.numeric(res$padj), stringsAsFactors = FALSE)
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
dds <- DESeq(
  dds, test = "Wald", fitType = "parametric", sfType = "ratio",
  betaPrior = FALSE, minReplicatesForReplace = 7, useT = FALSE,
  minmu = 0.5, parallel = FALSE, quiet = TRUE
)
res <- results(
  dds, contrast = c("group", p$test, p$control), cooksCutoff = TRUE,
  independentFiltering = FALSE, pAdjustMethod = "BH"
)
out <- data.frame(
  feature_id = rownames(res),
  log2FoldChange = as.numeric(res$log2FoldChange),
  stat = as.numeric(res$stat),
  pvalue = as.numeric(res$pvalue),
  stringsAsFactors = FALSE
)
cat(toJSON(out, dataframe = "rows", auto_unbox = TRUE, digits = 17, na = "null"))
'''


DIRECT_DESEQ2_ANALYSIS = r'''
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
dds <- DESeqDataSetFromMatrix(countData = m, colData = col_data, design = ~ 0 + group)
dds <- DESeq(
  dds, test = "Wald", fitType = "parametric", sfType = "ratio",
  betaPrior = FALSE, minReplicatesForReplace = 7, useT = FALSE,
  minmu = 0.5, parallel = FALSE, quiet = TRUE
)
res <- results(dds, contrast = c("group", p$test, p$control), alpha = p$fdr_threshold,
               cooksCutoff = TRUE, independentFiltering = TRUE,
               pAdjustMethod = "BH")
out <- data.frame(
  feature_key = rownames(res),
  log2FoldChange = as.numeric(res$log2FoldChange),
  stat = as.numeric(res$stat),
  pvalue = as.numeric(res$pvalue),
  padj = as.numeric(res$padj),
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


def test_formal_deseq2_worker_matches_independent_filtering_baseline() -> None:
    rscript = _rscript()
    if not _has_package(rscript, "DESeq2") or not _has_package(rscript, "jsonlite"):
        pytest.skip("DESeq2/jsonlite 未安装")
    rng = np.random.default_rng(20261015)
    means = np.geomspace(10.0, 1200.0, 600)
    counts = rng.poisson(means[:, None] * np.asarray([1, 1, 1, 1.35, 1.35, 1.35]))
    counts[:25, 3:] = rng.poisson(means[:25, None] * 2.5, size=(25, 3))
    samples = ["C1", "C2", "C3", "T1", "T2", "T3"]
    payload = {
        "counts": counts.tolist(),
        "feature_ids": [f"gene_{index:04d}" for index in range(len(counts))],
        "sample_ids": samples,
        "groups": ["control"] * 3 + ["test"] * 3,
        "control": "control",
        "test": "test",
        "fdr_threshold": 0.05,
        "lfc_threshold": 1.0,
    }
    expected = _direct(rscript, DIRECT_DESEQ2_ANALYSIS, payload)
    actual = RBridgeClient(rscript=rscript).run(
        "analyze_deseq2", payload, JobContext(Path.cwd()), "deseq2-count-v1",
    ).result["table"]
    assert len(actual) == len(expected) == len(counts)
    for actual_row, expected_row in zip(actual, expected):
        assert actual_row["feature_key"] == expected_row["feature_key"]
        for key in ("log2FoldChange", "stat", "pvalue", "padj"):
            _assert_close(actual_row[key], expected_row[key])


def test_formal_deseq2_batch_design_matches_independent_direct_baseline() -> None:
    rscript = _rscript()
    if not _has_package(rscript, "DESeq2") or not _has_package(rscript, "jsonlite"):
        pytest.skip("DESeq2/jsonlite 未安装")
    rng = np.random.default_rng(20261015)
    samples = []
    groups = []
    batch = {}
    for group in ("control", "test"):
        for batch_name in ("B1", "B2", "B3"):
            for replicate in range(1, 4):
                sample = f"{group}_{batch_name}_{replicate}"
                samples.append(sample)
                groups.append(group)
                batch[sample] = batch_name
    base_means = np.geomspace(15.0, 900.0, 320)
    size = 1.0 / 0.12
    counts = np.empty((len(base_means), len(samples)), dtype=int)
    for sample_index, group in enumerate(groups):
        mean = base_means * (1.8 if group == "test" else 1.0)
        counts[:, sample_index] = rng.negative_binomial(size, size / (size + mean))
    payload = {
        "counts": counts.tolist(),
        "feature_ids": [f"gene_{index:04d}" for index in range(len(counts))],
        "sample_ids": samples,
        "groups": groups,
        "batch": batch,
        "control": "control",
        "test": "test",
        "fdr_threshold": 0.05,
        "lfc_threshold": 1.0,
    }
    expected = _direct(rscript, DIRECT_DESEQ2_BATCH_ANALYSIS, payload)
    actual = RBridgeClient(rscript=rscript).run(
        "analyze_deseq2", payload, JobContext(Path.cwd()), "deseq2-count-v1",
    ).result["table"]

    assert len(actual) == len(expected) == len(counts)
    for actual_row, expected_row in zip(actual, expected):
        assert actual_row["feature_key"] == expected_row["feature_key"]
        for key in ("log2FoldChange", "stat", "pvalue", "padj"):
            _assert_close(actual_row[key], expected_row[key])


def test_formal_deseq2_paired_batch_design_matches_independent_direct_baseline() -> None:
    rscript = _rscript()
    if not _has_package(rscript, "DESeq2") or not _has_package(rscript, "jsonlite"):
        pytest.skip("DESeq2/jsonlite 未安装")
    rng = np.random.default_rng(20261016)
    samples: list[str] = []
    groups: list[str] = []
    subjects: dict[str, str] = {}
    batches: dict[str, str] = {}
    subject_effects = rng.lognormal(0.0, 0.25, size=8)
    for subject_index in range(8):
        subject = f"subject_{subject_index + 1}"
        control_batch, test_batch = ("B1", "B2") if subject_index % 2 == 0 else ("B2", "B1")
        for group, batch_name in (("control", control_batch), ("test", test_batch)):
            sample = f"{subject}_{group}"
            samples.append(sample)
            groups.append(group)
            subjects[sample] = subject
            batches[sample] = batch_name
    base_means = np.geomspace(20.0, 700.0, 320)
    dispersion_size = 1.0 / 0.1
    counts = np.empty((len(base_means), len(samples)), dtype=int)
    for sample_index, (sample, group) in enumerate(zip(samples, groups)):
        subject_index = int(subjects[sample].split("_")[1]) - 1
        batch_multiplier = 1.25 if batches[sample] == "B2" else 1.0
        group_multiplier = 1.6 if group == "test" else 1.0
        mean = base_means * subject_effects[subject_index] * batch_multiplier * group_multiplier
        counts[:, sample_index] = rng.negative_binomial(
            dispersion_size, dispersion_size / (dispersion_size + mean),
        )
    payload = {
        "counts": counts.tolist(),
        "feature_ids": [f"gene_{index:04d}" for index in range(len(counts))],
        "sample_ids": samples,
        "groups": groups,
        "subject": subjects,
        "batch": batches,
        "control": "control",
        "test": "test",
        "fdr_threshold": 0.05,
        "lfc_threshold": 1.0,
    }
    expected = _direct(rscript, DIRECT_DESEQ2_PAIRED_BATCH_ANALYSIS, payload)
    actual = RBridgeClient(rscript=rscript).run(
        "analyze_deseq2", payload, JobContext(Path.cwd()), "deseq2-count-v1",
    ).result["table"]

    assert len(actual) == len(expected) == len(counts)
    for actual_row, expected_row in zip(actual, expected):
        assert actual_row["feature_key"] == expected_row["feature_key"]
        for key in ("log2FoldChange", "stat", "pvalue", "padj"):
            _assert_close(actual_row[key], expected_row[key])


@pytest.mark.parametrize("with_batch", [False, True])
def test_formal_deseq2_cooks_reason_matches_native_cooks_filter(with_batch: bool) -> None:
    rscript = _rscript()
    if not _has_package(rscript, "DESeq2") or not _has_package(rscript, "jsonlite"):
        pytest.skip("DESeq2/jsonlite 未安装")

    rng = np.random.default_rng(20261015)
    if with_batch:
        samples = [f"{group}_{batch}_{rep}" for group in ("C", "T")
                   for batch in ("A", "B") for rep in range(1, 4)]
        groups = ["control" if sample.startswith("C_") else "test" for sample in samples]
        batches = {sample: sample.split("_")[1] for sample in samples}
    else:
        samples = [f"C{index}" for index in range(1, 4)] + [f"T{index}" for index in range(1, 4)]
        groups = ["control"] * 3 + ["test"] * 3
        batches = None
    n_samples = len(samples)
    counts = rng.poisson(60, size=(400, n_samples))
    counts[:, np.asarray(groups) == "test"] = rng.poisson(
        75, size=(400, sum(group == "test" for group in groups)),
    )
    counts[0, 0] = 5000  # 单个样本的极端 count，专门触发 DESeq2 Cook's 过滤
    payload: dict[str, object] = {
        "counts": counts.tolist(),
        "feature_ids": [f"gene_{index:04d}" for index in range(len(counts))],
        "sample_ids": samples,
        "groups": groups,
        "control": "control",
        "test": "test",
        "fdr_threshold": 0.05,
        "lfc_threshold": 1.0,
    }
    if batches is not None:
        payload["batch"] = batches

    actual_result = RBridgeClient(rscript=rscript).run(
        "analyze_deseq2", payload, JobContext(Path.cwd()), "deseq2-count-v1",
    ).result
    actual = actual_result["table"]
    outlier = actual[0]
    assert outlier["pvalue"] is None
    assert outlier["padj"] is None
    assert outlier["tested"] is False
    assert outlier["reason_not_tested"] == "cooks_outlier"
    assert actual_result["diagnostics"]["outlier_or_unestimable"] == sum(
        row["reason_not_tested"] in {"cooks_outlier", "not_estimable"} for row in actual
    )
