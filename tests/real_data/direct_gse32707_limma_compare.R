#!/usr/bin/env Rscript

# 独立基线：不调用 RNA-Seq Helper 的 worker，只复现已保存的 GSE32707
# normalized-expression limma 计划，并与工具结果逐行比较。
# 用法：Rscript --vanilla direct_gse32707_limma_compare.R <project_dir>

args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 1) {
  stop("需要一个项目目录参数")
}

project_dir <- normalizePath(args[[1]], mustWork = TRUE)
matrix_path <- file.path(project_dir, "prepared", "expression_matrix.tsv")
plan_path <- file.path(project_dir, "analysis", "analysis-plan.json")
result_path <- file.path(project_dir, "analysis", "deg-result.json")

suppressPackageStartupMessages({
  library(jsonlite)
  library(limma)
})

`%||%` <- function(left, right) {
  if (is.null(left)) right else left
}

matrix_table <- read.delim(
  matrix_path,
  check.names = FALSE,
  quote = "",
  comment.char = "",
  stringsAsFactors = FALSE
)
feature_ids <- as.character(matrix_table[[1]])
sample_ids <- names(matrix_table)[-1]
expression_values <- as.matrix(matrix_table[, -1, drop = FALSE])
storage.mode(expression_values) <- "double"

plan <- fromJSON(plan_path, simplifyVector = TRUE)
assignments <- plan$design$assignments
active <- vapply(
  sample_ids,
  function(sample_id) {
    group <- as.character(assignments[[sample_id]] %||% "")
    group %in% c(plan$contrast$control, plan$contrast$test)
  },
  logical(1)
)
if (!all(active)) {
  expression_values <- expression_values[, active, drop = FALSE]
  sample_ids <- sample_ids[active]
}

groups <- factor(
  vapply(sample_ids, function(sample_id) as.character(assignments[[sample_id]]), character(1)),
  levels = c(plan$contrast$control, plan$contrast$test)
)
design <- model.matrix(~ 0 + groups)
colnames(design) <- c("control", "test")

# 这是本项目保存的 GSE32707 计划：线性芯片表达值，先按固定规则取 log2(x+1)。
model_values <- log2(expression_values + 1)
fit <- lmFit(model_values, design)
fit <- contrasts.fit(fit, makeContrasts(test - control, levels = design))
ebayes_args <- list(
  fit = fit,
  trend = TRUE,
  robust = TRUE,
  winsor.tail.p = c(0.05, 0.10),
  proportion = 0.01,
  stdev.coef.lim = c(0.1, 4)
)
if ("legacy" %in% names(formals(limma::eBayes))) {
  ebayes_args$legacy <- TRUE
}
fit <- do.call(limma::eBayes, ebayes_args)

direct <- data.frame(
  feature_key = feature_ids,
  log2FoldChange = as.numeric(fit$coefficients[, 1]),
  moderated_t = as.numeric(fit$t[, 1]),
  pvalue = as.numeric(fit$p.value[, 1]),
  padj = p.adjust(as.numeric(fit$p.value[, 1]), method = "BH"),
  mean_control_expression = rowMeans(model_values[, groups == plan$contrast$control, drop = FALSE]),
  mean_treated_expression = rowMeans(model_values[, groups == plan$contrast$test, drop = FALSE]),
  stringsAsFactors = FALSE
)

tool_result <- fromJSON(result_path, simplifyVector = TRUE)
tool <- tool_result$table
tool <- tool[match(feature_ids, tool$feature_key), , drop = FALSE]

max_abs_difference <- function(left, right) {
  values <- abs(as.numeric(left) - as.numeric(right))
  values <- values[is.finite(values)]
  if (!length(values)) return(NA_real_)
  max(values)
}

tool_summary <- tool_result$summary
direct_significant <- sum(direct$padj < plan$config$fdr_threshold, na.rm = TRUE)
direct_magnitude <- sum(
  direct$padj < plan$config$fdr_threshold &
    abs(direct$log2FoldChange) >= plan$config$lfc_threshold,
  na.rm = TRUE
)

comparison <- list(
  project = project_dir,
  matrix_dimensions = c(features = nrow(expression_values), samples = ncol(expression_values)),
  active_samples = ncol(expression_values),
  group_counts = as.list(table(groups)),
  transform = "log2(x+1)",
  limma_version = as.character(packageVersion("limma")),
  legacy_argument_used = "legacy" %in% names(formals(limma::eBayes)),
  tool_summary = tool_summary,
  direct_summary = list(
    tested_count = nrow(direct),
    significant_count = direct_significant,
    significant_magnitude_count = direct_magnitude
  ),
  max_abs_difference = list(
    log2FoldChange = max_abs_difference(tool$log2FoldChange, direct$log2FoldChange),
    moderated_t = max_abs_difference(tool$moderated_t, direct$moderated_t),
    pvalue = max_abs_difference(tool$pvalue, direct$pvalue),
    padj = max_abs_difference(tool$padj, direct$padj),
    mean_control_expression = max_abs_difference(tool$mean_control_expression, direct$mean_control_expression),
    mean_treated_expression = max_abs_difference(tool$mean_treated_expression, direct$mean_treated_expression)
  )
)

comparison$identical_within_tolerance <- all(
  unlist(comparison$max_abs_difference) <= 1e-10
)
cat(toJSON(comparison, auto_unbox = TRUE, pretty = TRUE, digits = 17, na = "null"))
cat("\n")
