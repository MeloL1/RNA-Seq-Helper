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

if (any(!is.finite(expression_values))) stop("输入表达矩阵包含非有限值")
preprocessing <- plan$preprocessing
transform <- as.character(preprocessing$transform %||% "already_log2")
filter_threshold <- as.numeric(preprocessing$filter_threshold %||% 1)
min_samples <- as.integer(preprocessing$min_samples %||% 0)
if (transform == "log2(x+1)") {
  keep <- rowSums(expression_values >= filter_threshold) >= min_samples
  model_values <- log2(expression_values[keep, , drop = FALSE] + 1)
} else if (transform == "already_log2") {
  keep <- rep(TRUE, nrow(expression_values))
  model_values <- expression_values
} else {
  stop("独立基准不支持计划中的转换：", transform)
}
if (!any(keep)) stop("按已保存计划过滤后没有可拟合特征")
fit <- lmFit(model_values, design)
fit <- contrasts.fit(fit, makeContrasts(test - control, levels = design))
degenerate <- as.numeric(fit$sigma)^2 <= 1e-12 * pmax(1, rowMeans(model_values^2))
valid <- !degenerate
if (!any(valid)) stop("过滤后没有可用于 limma 检验的非退化特征")
ebayes_args <- list(
  fit = fit[valid, , drop = FALSE],
  trend = TRUE,
  robust = TRUE,
  winsor.tail.p = c(0.05, 0.10),
  proportion = 0.01,
  stdev.coef.lim = c(0.1, 4)
)
if ("legacy" %in% names(formals(limma::eBayes))) {
  ebayes_args$legacy <- TRUE
}
if (any(valid)) fit_valid <- do.call(limma::eBayes, ebayes_args)

direct_lfc <- direct_t <- direct_p <- direct_padj <- rep(NA_real_, length(feature_ids))
direct_control <- direct_test <- rep(NA_real_, length(feature_ids))
kept_indices <- which(keep)
direct_lfc[kept_indices] <- as.numeric(fit$coefficients[, 1])
direct_control[kept_indices] <- rowMeans(model_values[, groups == plan$contrast$control, drop = FALSE])
direct_test[kept_indices] <- rowMeans(model_values[, groups == plan$contrast$test, drop = FALSE])
if (any(valid)) {
  valid_indices <- kept_indices[valid]
  direct_t[valid_indices] <- as.numeric(fit_valid$t[, 1])
  direct_p[valid_indices] <- as.numeric(fit_valid$p.value[, 1])
  direct_padj[valid_indices] <- p.adjust(direct_p[valid_indices], method = "BH")
}

direct <- data.frame(
  feature_key = feature_ids,
  tested = seq_along(feature_ids) %in% kept_indices[valid],
  log2FoldChange = direct_lfc,
  moderated_t = direct_t,
  pvalue = direct_p,
  padj = direct_padj,
  mean_control_expression = direct_control,
  mean_treated_expression = direct_test,
  stringsAsFactors = FALSE
)

tool_result <- fromJSON(result_path, simplifyVector = TRUE)
tool <- tool_result$table
if (nrow(tool) != length(feature_ids) || anyDuplicated(tool$feature_key)) {
  stop("软件结果的特征数不匹配或 feature_key 重复")
}
tool <- tool[match(feature_ids, tool$feature_key), , drop = FALSE]
if (anyNA(tool$feature_key) || !identical(as.character(tool$feature_key), feature_ids)) {
  stop("软件结果 feature_key 缺失或顺序无法匹配")
}

max_abs_difference <- function(left, right) {
  left <- as.numeric(left)
  right <- as.numeric(right)
  if (!identical(is.na(left), is.na(right))) return(Inf)
  if (!identical(is.finite(left), is.finite(right))) return(Inf)
  values <- abs(left - right)
  values <- values[is.finite(values)]
  if (!length(values)) return(0)
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
  transform = transform,
  filter_threshold = if (transform == "log2(x+1)") filter_threshold else NULL,
  min_samples = if (transform == "log2(x+1)") min_samples else NULL,
  limma_version = as.character(packageVersion("limma")),
  legacy_argument_used = "legacy" %in% names(formals(limma::eBayes)),
  tool_summary = tool_summary,
  direct_summary = list(
    tested_count = sum(direct$tested),
    significant_count = direct_significant,
    significant_magnitude_count = direct_magnitude
  ),
  max_abs_difference = list(
    tested = if (identical(as.logical(tool$tested), direct$tested)) 0 else Inf,
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
if (!comparison$identical_within_tolerance) {
  stop("独立基准与软件结果不一致；已输出差异摘要")
}
