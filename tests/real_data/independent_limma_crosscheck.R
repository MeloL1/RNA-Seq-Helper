#!/usr/bin/env Rscript

# Independently refit a saved RNA-Seq Helper TPM project and compare it with
# the user-facing XLSX export. This script does not read the app's DEG JSON.

suppressPackageStartupMessages({
  library(jsonlite)
  library(limma)
  library(readxl)
})

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1L) {
  stop("Usage: Rscript independent_limma_crosscheck.R <project-directory>")
}

project_dir <- normalizePath(args[[1]], mustWork = TRUE)
plan_path <- file.path(project_dir, "analysis", "analysis-plan.json")
matrix_path <- file.path(project_dir, "prepared", "expression_matrix.tsv")
xlsx_path <- file.path(project_dir, "reports", "deg-results.xlsx")

plan <- fromJSON(plan_path, simplifyVector = FALSE)
if (!identical(plan$method, "LIMMA_ON_LOG2_TPM")) {
  stop("Project method is not LIMMA_ON_LOG2_TPM")
}

assignments <- unlist(plan$design$assignments, use.names = TRUE)
active <- assignments[assignments %in% c("control", "test")]
sample_ids <- names(active)
group <- factor(unname(active), levels = c("control", "test"))

input <- read.delim(
  matrix_path,
  check.names = FALSE,
  stringsAsFactors = FALSE,
  quote = ""
)
feature_ids <- as.character(input[[1]])
expression <- as.matrix(input[, sample_ids, drop = FALSE])
storage.mode(expression) <- "double"
rownames(expression) <- feature_ids

threshold <- as.numeric(plan$preprocessing$filter_threshold)
min_samples <- as.integer(plan$preprocessing$min_samples)
keep <- rowSums(expression >= threshold) >= min_samples
log_expression <- log2(expression[keep, , drop = FALSE] + 1)

design <- model.matrix(~ 0 + group)
colnames(design) <- c("control", "test")
fit <- lmFit(log_expression, design)
contrast <- makeContrasts(test - control, levels = design)
fit <- contrasts.fit(fit, contrast)

ebayes_args <- list(
  fit = fit,
  trend = TRUE,
  robust = TRUE,
  winsor.tail.p = c(0.05, 0.10),
  proportion = 0.01,
  stdev.coef.lim = c(0.1, 4)
)
if ("legacy" %in% names(formals(eBayes))) {
  ebayes_args$legacy <- TRUE
}
fit <- do.call(eBayes, ebayes_args)

independent <- data.frame(
  feature_key = feature_ids[keep],
  log2FoldChange = as.numeric(fit$coefficients[, 1]),
  pvalue = as.numeric(fit$p.value[, 1]),
  padj = p.adjust(as.numeric(fit$p.value[, 1]), method = "BH"),
  stringsAsFactors = FALSE
)

export <- read_excel(
  xlsx_path,
  sheet = 1,
  col_types = rep("text", 5)
)
expected_columns <- c(
  "feature_key", "gene_symbol", "log2FoldChange", "pvalue", "padj"
)
if (!identical(names(export), expected_columns)) {
  stop("Exported XLSX columns differ from the expected five-column contract")
}
if (!identical(as.character(export$feature_key), feature_ids)) {
  stop("Exported XLSX feature order/IDs differ from the prepared matrix")
}

parse_export_numeric <- function(values, name) {
  missing <- is.na(values) | values == "NA"
  parsed <- suppressWarnings(as.numeric(values))
  if (any(is.na(parsed) & !missing)) {
    stop("Exported column contains a non-numeric value: ", name)
  }
  parsed[missing] <- NA_real_
  parsed
}

compare_numeric <- function(name, expected, observed, tolerance = 1e-10) {
  expected_na <- is.na(expected)
  observed_na <- is.na(observed)
  na_mismatch <- sum(expected_na != observed_na)
  jointly_finite <- !expected_na & !observed_na
  delta <- abs(expected[jointly_finite] - observed[jointly_finite])
  mismatch <- sum(delta > tolerance)
  max_delta <- if (length(delta)) max(delta) else 0
  data.frame(
    field = name,
    mismatches = mismatch + na_mismatch,
    max_absolute_difference = max_delta
  )
}

expected_lfc <- rep(NA_real_, length(feature_ids))
expected_pvalue <- rep(NA_real_, length(feature_ids))
expected_padj <- rep(NA_real_, length(feature_ids))
expected_lfc[keep] <- independent$log2FoldChange
expected_pvalue[keep] <- independent$pvalue
expected_padj[keep] <- independent$padj

comparison <- rbind(
  compare_numeric(
    "log2FoldChange",
    expected_lfc,
    parse_export_numeric(export$log2FoldChange, "log2FoldChange")
  ),
  compare_numeric(
    "pvalue",
    expected_pvalue,
    parse_export_numeric(export$pvalue, "pvalue")
  ),
  compare_numeric(
    "padj",
    expected_padj,
    parse_export_numeric(export$padj, "padj")
  )
)

cat("Project:", project_dir, "\n")
cat("R:", R.version.string, "\n")
cat("limma:", as.character(packageVersion("limma")), "\n")
cat("samples:", paste(sample_ids, collapse = ", "), "\n")
cat(
  "group sizes:",
  paste(names(table(group)), as.integer(table(group)), collapse = "; "),
  "\n"
)
cat("input features:", length(feature_ids), "\n")
cat("independently tested:", sum(keep), "\n")
cat("filtered:", sum(!keep), "\n")
cat("exported rows:", nrow(export), "\n")
print(comparison, row.names = FALSE, digits = 16)

if (any(comparison$mismatches != 0L)) {
  stop("Independent R results do not match the app XLSX within tolerance")
}

cat("PASS: all exported tested estimates match independent limma results.\n")
