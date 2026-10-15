#!/usr/bin/env Rscript

# 独立 R worker：JSON Lines 入/出，单请求单进程。
# 仅在明确执行安装脚本时使用网络；保留项目约定的清华 CRAN 镜像。
options(repos = c(CRAN = "https://mirrors.tuna.tsinghua.edu.cn/CRAN/"))
suppressPackageStartupMessages({
  library(jsonlite)
  library(limma)
})

emit <- function(request_id, ok, result = NULL, error = NULL) {
  out <- list(request_id = request_id, ok = ok)
  if (ok) out$result <- result else out$error <- error
  # Keep NA result fields as explicit JSON nulls; omitting them would make the
  # standardized DEG schema depend on whether a column happened to be all NA.
  cat(toJSON(out, auto_unbox = TRUE, null = "null", na = "null", dataframe = "rows", digits = 17), "\n", sep = "")
  flush.console()
}

run_micro_limma <- function(payload, profile_id) {
  matrix_data <- do.call(rbind, payload$matrix)
  storage.mode(matrix_data) <- "double"
  feature_ids <- as.character(unlist(payload$feature_ids))
  sample_ids <- as.character(unlist(payload$sample_ids))
  groups <- factor(as.character(unlist(payload$groups)), levels = c(payload$control, payload$test))
  if (nrow(matrix_data) != length(feature_ids) || ncol(matrix_data) != length(sample_ids)) stop("矩阵维度与 ID 数量不一致")
  if (any(!is.finite(matrix_data))) stop("矩阵含非有限值")
  design <- model.matrix(~ 0 + groups)
  colnames(design) <- c("control", "treated")
  fit <- lmFit(matrix_data, design)
  contrast <- makeContrasts(treated - control, levels = design)
  fit <- contrasts.fit(fit, contrast)
  fit <- eBayes(fit, trend = TRUE, robust = TRUE, winsor.tail.p = c(0.05, 0.10), proportion = 0.01, stdev.coef.lim = c(0.1, 4))
  table <- data.frame(
    feature_id = feature_ids,
    coefficient = as.numeric(fit$coefficients[, 1]),
    moderated_t = as.numeric(fit$t[, 1]),
    pvalue = as.numeric(fit$p.value[, 1]),
    padj = p.adjust(as.numeric(fit$p.value[, 1]), method = "BH"),
    stringsAsFactors = FALSE
  )
  list(
    profile_id = profile_id %||% "stage0-micro-v1",
    method = "LIMMA_ON_LOG_EXPRESSION",
    design = unname(design),
    contrast = "treated - control",
    table = table,
    fit = list(df_prior = as.numeric(fit$df.prior), s2_prior = as.numeric(fit$s2.prior)),
    runtime = list(R = R.version.string, limma = as.character(packageVersion("limma")), statmod = as.character(packageVersion("statmod")))
  )
}

run_micro_deseq2 <- function(payload, profile_id) {
  if (!requireNamespace("DESeq2", quietly = TRUE)) stop("DESeq2 未安装；本次没有静默改用其他方法")
  count_data <- do.call(rbind, payload$counts)
  storage.mode(count_data) <- "integer"
  feature_ids <- as.character(unlist(payload$feature_ids))
  sample_ids <- as.character(unlist(payload$sample_ids))
  groups <- factor(as.character(unlist(payload$groups)), levels = c(payload$control, payload$test))
  rownames(count_data) <- feature_ids
  colnames(count_data) <- sample_ids
  col_data <- data.frame(group = groups, row.names = sample_ids)
  dds <- DESeq2::DESeqDataSetFromMatrix(countData = count_data, colData = col_data, design = ~ group)
  dds <- DESeq2::DESeq(dds, quiet = TRUE)
  res <- DESeq2::results(dds, contrast = c("group", payload$test, payload$control), independentFiltering = FALSE)
  table <- data.frame(
    feature_id = rownames(res),
    baseMean = as.numeric(res$baseMean),
    log2FoldChange = as.numeric(res$log2FoldChange),
    lfcSE = as.numeric(res$lfcSE),
    stat = as.numeric(res$stat),
    pvalue = as.numeric(res$pvalue),
    padj = as.numeric(res$padj),
    stringsAsFactors = FALSE
  )
  list(
    profile_id = profile_id %||% "stage0-micro-v1",
    method = "DESEQ2",
    contrast = paste(payload$test, "-", payload$control),
    table = table,
    runtime = list(R = R.version.string, DESeq2 = as.character(packageVersion("DESeq2")))
  )
}

run_reference_orgdb <- function(payload, profile_id) {
  if (!requireNamespace("AnnotationDbi", quietly = TRUE)) {
    stop("AnnotationDbi 未安装；本次保留原始特征编号")
  }
  package_by_taxid <- c(`9606` = "org.Hs.eg.db", `10090` = "org.Mm.eg.db", `10116` = "org.Rn.eg.db")
  taxid <- as.character(payload$species_taxid %||% "")
  package_name <- unname(package_by_taxid[[taxid]])
  if (is.null(package_name) || !requireNamespace(package_name, quietly = TRUE)) {
    stop("当前物种的 OrgDb 未安装；本次保留原始特征编号")
  }
  package_object <- getExportedValue(package_name, package_name)
  ids <- unique(as.character(unlist(payload$feature_ids)))
  id_type <- as.character(payload$id_type %||% "")
  if (id_type == "ENSEMBL_GENE") {
    keytype <- "ENSEMBL"
    query_ids <- sub("\\..*$", "", ids)
  } else if (id_type == "ENTREZ_OR_NUMERIC") {
    keytype <- "ENTREZID"
    query_ids <- ids
  } else if (id_type == "SYMBOL") {
    keytype <- "SYMBOL"
    query_ids <- ids
  } else {
    stop("当前编号类型不适合 OrgDb 自动映射")
  }
  if (!length(query_ids)) return(list(mapping = list(), release = as.character(packageVersion(package_name)), package = package_name))
  selected <- AnnotationDbi::select(package_object, keys = query_ids, columns = "SYMBOL", keytype = keytype)
  mapping <- list()
  if (nrow(selected)) {
    for (row_index in seq_len(nrow(selected))) {
      query <- as.character(selected[[keytype]][row_index])
      symbol <- as.character(selected$SYMBOL[row_index])
      if (!is.na(query) && nzchar(query) && !is.na(symbol) && nzchar(symbol)) {
        original_ids <- ids[query_ids == query]
        for (original_id in original_ids) {
          mapping[[original_id]] <- unique(c(mapping[[original_id]], symbol))
        }
      }
    }
  }
  list(mapping = mapping, release = as.character(packageVersion(package_name)), package = package_name)
}

build_design <- function(payload) {
  sample_ids <- as.character(unlist(payload$sample_ids))
  groups <- factor(
    as.character(unlist(payload$groups)),
    levels = c(payload$control, payload$test)
  )
  design_data <- data.frame(group = groups, row.names = sample_ids)
  design_terms <- c()
  for (term_name in c("batch", "subject")) {
    values <- payload[[term_name]]
    if (!is.null(values) && length(values) > 0) {
      value_map <- unlist(values)
      design_data[[term_name]] <- factor(as.character(value_map[sample_ids]))
      design_terms <- c(design_terms, term_name)
    }
  }
  design_terms <- c(design_terms, "group")
  formula <- stats::as.formula(paste("~ 0 +", paste(design_terms, collapse = " + ")))
  # Build the two group indicators explicitly.  R's treatment contrasts can
  # silently drop the control indicator when subject/batch terms are added to
  # a no-intercept formula, even though the group contrast remains estimable.
  # Covariates use treatment coding with their intercept removed.
  design <- stats::model.matrix(~ 0 + group, data = design_data)
  group_columns <- grep("^group", colnames(design))
  if (length(group_columns) != 2) stop("设计矩阵中无法找到恰好两列组别效应")
  colnames(design)[group_columns] <- c("control", "test")
  for (term_name in c("batch", "subject")) {
    if (term_name %in% names(design_data)) {
      covariate <- stats::model.matrix(
        stats::as.formula(paste("~", term_name)),
        data = design_data
      )
      covariate <- covariate[, setdiff(colnames(covariate), "(Intercept)"), drop = FALSE]
      if (ncol(covariate)) design <- cbind(design, covariate)
    }
  }
  list(data = design_data, formula = formula, matrix = design)
}

row_means_by_group <- function(matrix_data, groups, control, test) {
  list(
    control = rowMeans(matrix_data[, groups == control, drop = FALSE]),
    test = rowMeans(matrix_data[, groups == test, drop = FALSE])
  )
}

fit_limma_profile <- function(fit) {
  # limma added the legacy switch after older bundled versions were released.
  # Detect the formal argument before calling eBayes so an older runtime is not
  # given an argument that it cannot understand.  The profile itself fixes the
  # value to TRUE whenever the installed version supports it.
  ebayes_args <- list(
    fit = fit,
    trend = TRUE,
    robust = TRUE,
    winsor.tail.p = c(0.05, 0.10),
    proportion = 0.01,
    stdev.coef.lim = c(0.1, 4)
  )
  legacy_supported <- "legacy" %in% names(formals(limma::eBayes))
  if (legacy_supported) ebayes_args$legacy <- TRUE
  fit <- do.call(limma::eBayes, ebayes_args)

  positive_finite <- function(values, label) {
    if (!length(values) || any(!is.finite(values) | values <= 0)) {
      stop(paste0("limma ", label, " 必须全部为有限正数"))
    }
  }
  positive_finite(fit$s2.prior, "s2.prior")
  positive_finite(fit$s2.post, "s2.post")
  if (!length(fit$df.prior) || any(
    (!is.finite(fit$df.prior) & !is.infinite(fit$df.prior)) |
      fit$df.prior < 0
  )) {
    stop("limma df.prior 必须为非负数或 Inf")
  }
  list(
    fit = fit,
    legacy_supported = legacy_supported,
    legacy = if (legacy_supported) TRUE else NULL
  )
}

as_plot_matrix <- function(values, feature_ids, sample_ids, transform) {
  if (!length(feature_ids) || nrow(values) != length(feature_ids) ||
      ncol(values) != length(sample_ids) || any(!is.finite(values))) {
    stop("绘图矩阵必须为非空且全部为有限数值")
  }
  list(
    feature_ids = as.list(as.character(feature_ids)),
    sample_ids = as.list(as.character(sample_ids)),
    values = lapply(seq_len(nrow(values)), function(index) {
      as.list(as.numeric(values[index, , drop = TRUE]))
    }),
    transform = as.character(transform)
  )
}

result_summary <- function(table, fdr_threshold, lfc_threshold) {
  tested <- table$tested %in% TRUE
  significant <- tested & !is.na(table$padj) & table$padj < fdr_threshold
  magnitude <- significant & !is.na(table$log2FoldChange) &
    abs(table$log2FoldChange) >= lfc_threshold
  list(
    feature_count = nrow(table),
    tested_count = sum(tested),
    not_tested_count = sum(!tested),
    significant_count = sum(significant),
    significant_magnitude_count = sum(magnitude),
    up_count = sum(magnitude & table$log2FoldChange > 0, na.rm = TRUE),
    down_count = sum(magnitude & table$log2FoldChange < 0, na.rm = TRUE),
    fdr_threshold = fdr_threshold,
    lfc_threshold = lfc_threshold
  )
}

run_analyze_limma <- function(payload, profile_id) {
  matrix_data <- do.call(rbind, payload$matrix)
  storage.mode(matrix_data) <- "double"
  feature_ids <- as.character(unlist(payload$feature_ids))
  sample_ids <- as.character(unlist(payload$sample_ids))
  if (nrow(matrix_data) != length(feature_ids) ||
      ncol(matrix_data) != length(sample_ids)) {
    stop("矩阵维度与 ID 数量不一致")
  }
  if (any(!is.finite(matrix_data))) stop("矩阵含非有限值")
  design_info <- build_design(payload)
  design <- design_info$matrix
  groups <- as.character(unlist(payload$groups))
  control <- as.character(payload$control)
  test <- as.character(payload$test)
  fdr_threshold <- as.numeric(payload$fdr_threshold %||% 0.05)
  lfc_threshold <- as.numeric(payload$lfc_threshold %||% 1)
  method_name <- as.character(payload$method %||% "LIMMA_ON_LOG2_EXPRESSION")
  gene_symbols <- normalize_symbols(payload$gene_symbols, length(feature_ids))
  transform <- as.character(payload$transform %||% "already_log2")
  min_samples <- as.integer(payload$min_samples %||% 0)
  if (transform == "log2(x+1)") {
    threshold <- as.numeric(payload$filter_threshold %||% 1)
    keep <- rowSums(matrix_data >= threshold) >= min_samples
    analysis_matrix <- log2(matrix_data[keep, , drop = FALSE] + 1)
  } else {
    keep <- rep(TRUE, nrow(matrix_data))
    analysis_matrix <- matrix_data
  }
  if (sum(keep) < 1) stop("过滤后没有可拟合特征")
  if (any(!is.finite(analysis_matrix))) {
    stop("转换后的 limma 矩阵含非有限值")
  }
  fit_model <- limma::lmFit(analysis_matrix, design)
  fit_model <- limma::contrasts.fit(
    fit_model,
    limma::makeContrasts(test - control, levels = design)
  )
  means <- row_means_by_group(analysis_matrix, groups, control, test)
  coefficient <- rep(NA_real_, nrow(matrix_data))
  moderated_t <- rep(NA_real_, nrow(matrix_data))
  pvalue <- rep(NA_real_, nrow(matrix_data))
  padj <- rep(NA_real_, nrow(matrix_data))
  mean_control <- rep(NA_real_, nrow(matrix_data))
  mean_test <- rep(NA_real_, nrow(matrix_data))
  coefficient[keep] <- as.numeric(fit_model$coefficients[, 1])
  mean_control[keep] <- means$control
  mean_test[keep] <- means$test

  # Use the residual variance from the fitted, full design.  This includes
  # batch and subject terms and therefore does not reimplement the design with
  # a group-only within-group calculation.  The scale follows the product
  # specification exactly: s2 <= 1e-12 * max(1, mean(y^2)).
  residual_variance <- as.numeric(fit_model$sigma)^2
  expression_scale <- pmax(1, rowMeans(analysis_matrix^2))
  degenerate_kept <- rep(FALSE, nrow(matrix_data))
  degenerate_kept[keep] <- residual_variance <= 1e-12 * expression_scale
  nondegenerate_kept <- keep & !degenerate_kept
  limma_profile <- NULL
  if (any(nondegenerate_kept)) {
    valid_fit <- fit_limma_profile(fit_model[!degenerate_kept[keep], , drop = FALSE])
    limma_profile <- valid_fit
    valid_indices <- which(nondegenerate_kept)
    moderated_t[valid_indices] <- as.numeric(valid_fit$fit$t[, 1])
    pvalue[valid_indices] <- as.numeric(valid_fit$fit$p.value[, 1])
  } else {
    legacy_supported <- "legacy" %in% names(formals(limma::eBayes))
    limma_profile <- list(
      legacy_supported = legacy_supported,
      legacy = if (legacy_supported) TRUE else NULL
    )
  }
  finite_limma <- keep & is.finite(coefficient) & is.finite(pvalue)
  valid <- finite_limma & !degenerate_kept
  pvalue[degenerate_kept] <- NA_real_
  padj[valid] <- p.adjust(pvalue[valid], method = "BH")
  reasons <- rep("below_expression_filter", nrow(matrix_data))
  reasons[valid] <- ""
  reasons[degenerate_kept] <- "degenerate_residual_variance"
  reasons[keep & !degenerate_kept & !finite_limma] <- "invalid_or_degenerate_variance"
  tested <- valid
  table <- data.frame(
    feature_key = feature_ids,
    original_id = feature_ids,
    gene_symbol = gene_symbols,
    log2FoldChange = coefficient,
    pvalue = pvalue,
    padj = padj,
    direction = ifelse(coefficient > 0, "up", ifelse(coefficient < 0, "down", "flat")),
    tested = tested,
    reason_not_tested = reasons,
    mean_control_expression = mean_control,
    mean_treated_expression = mean_test,
    analysis_method = method_name,
    analysis_basis = "normalized_expression",
    effect_scale = "log2_expression",
    mean_expression_unit = as.character(payload$measurement_type %||% "normalized_expression"),
    moderated_t = moderated_t,
    stringsAsFactors = FALSE
  )
  list(
    profile_id = profile_id,
    method = method_name,
    analysis_basis = "normalized_expression",
    effect_scale = "log2_expression",
    table = table,
    excluded_features = feature_ids[!keep],
    filter_summary = list(
      threshold = ifelse(transform == "log2(x+1)", as.numeric(payload$filter_threshold %||% 1), NA),
      min_samples = min_samples,
      excluded_count = sum(!keep)
    ),
    issues = list(),
    summary = result_summary(table, fdr_threshold, lfc_threshold),
    diagnostics = list(
      filtered_count = sum(!keep),
      degenerate_count = sum(degenerate_kept),
      degenerate_fraction = sum(degenerate_kept) / sum(keep),
      invalid_count = sum(keep & !degenerate_kept & !finite_limma),
      residual_df = fit_model$df.residual,
      pvalue_count = sum(is.finite(pvalue))
    ),
    parameters = list(
      transform = transform,
      filter_threshold = ifelse(transform == "log2(x+1)", 1, NA),
      min_samples = min_samples,
      trend = TRUE,
      robust = TRUE,
      winsor.tail.p = c(0.05, 0.10),
      proportion = 0.01,
      stdev.coef.lim = c(0.1, 4),
      p_adjust_method = "BH",
      legacy_supported = limma_profile$legacy_supported,
      legacy = limma_profile$legacy
    ),
    plot_matrix = as_plot_matrix(
      analysis_matrix,
      feature_ids[keep],
      sample_ids,
      transform
    ),
    runtime = list(
      R = R.version.string,
      limma = as.character(packageVersion("limma")),
      statmod = as.character(packageVersion("statmod"))
    )
  )
}

run_analyze_deseq2 <- function(payload, profile_id) {
  if (!requireNamespace("DESeq2", quietly = TRUE)) {
    stop("DESeq2 未安装；本次没有静默改用其他方法")
  }
  count_data <- do.call(rbind, payload$counts)
  storage.mode(count_data) <- "double"
  if (any(!is.finite(count_data)) || any(count_data < 0) ||
      any(count_data != floor(count_data))) {
    stop("DESeq2 输入必须是有限的非负整数 count")
  }
  count_data <- matrix(as.integer(count_data), nrow = nrow(count_data))
  feature_ids <- as.character(unlist(payload$feature_ids))
  sample_ids <- as.character(unlist(payload$sample_ids))
  rownames(count_data) <- feature_ids
  colnames(count_data) <- sample_ids
  design_info <- build_design(payload)
  fit_keep <- rowSums(count_data) > 0
  if (!any(fit_keep)) stop("没有非零 count 可用于 DESeq2 拟合")
  fit_count_data <- count_data[fit_keep, , drop = FALSE]
  dds <- DESeq2::DESeqDataSetFromMatrix(
    countData = fit_count_data,
    colData = design_info$data,
    design = design_info$formula
  )
  dispersion_fallback <- FALSE
  dds <- tryCatch(
    DESeq2::DESeq(dds, quiet = TRUE),
    error = function(error) {
      message <- conditionMessage(error)
      if (!grepl("all gene-wise dispersion estimates", message, fixed = TRUE)) {
        stop(error)
      }
      # DESeq2 documents this path for designs where the dispersion trend
      # cannot be fitted (for example, a tiny synthetic smoke-test matrix).
      # Keep the DESeq2 count model and make the downgrade explicit in output.
      fallback <- DESeq2::estimateSizeFactors(dds)
      fallback <- DESeq2::estimateDispersionsGeneEst(fallback, quiet = TRUE)
      gene_dispersion <- S4Vectors::mcols(fallback)$dispGeneEst
      if (any(!is.finite(gene_dispersion) | gene_dispersion <= 0)) {
        stop(error)
      }
      DESeq2::dispersions(fallback) <- gene_dispersion
      dispersion_fallback <<- TRUE
      DESeq2::nbinomWaldTest(fallback, quiet = TRUE)
    }
  )
  fdr_threshold <- as.numeric(payload$fdr_threshold %||% 0.05)
  lfc_threshold <- as.numeric(payload$lfc_threshold %||% 1)
  gene_symbols <- normalize_symbols(payload$gene_symbols, length(feature_ids))
  res <- DESeq2::results(
    dds,
    contrast = c("group", as.character(payload$test), as.character(payload$control)),
    alpha = fdr_threshold
  )
  groups <- as.character(unlist(payload$groups))
  means <- row_means_by_group(count_data, groups, payload$control, payload$test)
  cooks <- tryCatch(DESeq2::assays(dds)[["cooks"]], error = function(e) NULL)
  base_mean <- rep(NA_real_, length(feature_ids))
  pvalue <- rep(NA_real_, length(feature_ids))
  padj <- rep(NA_real_, length(feature_ids))
  log2_fold_change <- rep(NA_real_, length(feature_ids))
  lfc_se <- rep(NA_real_, length(feature_ids))
  statistic <- rep(NA_real_, length(feature_ids))
  res_indices <- which(fit_keep)
  base_mean[res_indices] <- as.numeric(res$baseMean)
  pvalue[res_indices] <- as.numeric(res$pvalue)
  padj[res_indices] <- as.numeric(res$padj)
  log2_fold_change[res_indices] <- as.numeric(res$log2FoldChange)
  lfc_se[res_indices] <- as.numeric(res$lfcSE)
  statistic[res_indices] <- as.numeric(res$stat)
  reasons <- rep("all_zero", length(feature_ids))
  reasons[fit_keep] <- ""
  reasons[fit_keep & is.na(padj) & is.finite(pvalue)] <- "independent_filtering"
  outlier <- fit_keep & is.na(padj) & is.na(pvalue) & base_mean > 0
  if (!is.null(cooks)) {
    outlier_rows_fit <- apply(cooks, 1, function(values) any(is.finite(values) & values > stats::qf(0.99, 1, max(1, ncol(count_data) - 2))))
    outlier_rows <- rep(FALSE, length(feature_ids))
    outlier_rows[fit_keep] <- outlier_rows_fit
    reasons[outlier & outlier_rows] <- "cooks_outlier_or_unestimable"
  }
  reasons[fit_keep & is.na(padj) & reasons == ""] <- "not_estimable"
  tested <- is.finite(pvalue)
  plot_keep <- fit_keep
  plot_dds <- dds
  plot_transform <- "DESeq2::varianceStabilizingTransformation(blind=FALSE)"
  plot_issue <- NULL
  plot_values <- tryCatch(
    as.matrix(SummarizedExperiment::assay(
      DESeq2::varianceStabilizingTransformation(plot_dds, blind = FALSE)
    )),
    error = function(error) {
      # Very small synthetic fixtures may not support the VST dispersion
      # trend.  Keep the count path explicit and use normalized counts only;
      # never expose raw counts as plotting data.
      plot_issue <<- list(
        code = "DESEQ2_PLOT_VST_FALLBACK",
        severity = "WARNING",
        message_zh = paste0(
          "绘图的 VST 在当前矩阵上不可用，已明确回退到",
          " DESeq2 size-factor normalized count 的 log2(x+1)。",
          "正式统计结果不受此绘图回退影响。"
        ),
        detail = conditionMessage(error)
      )
      plot_transform <<- "log2(DESeq2_normalized_count+1;VST_fallback)"
      normalized <- DESeq2::counts(plot_dds, normalized = TRUE)
      log2(normalized + 1)
    }
  )
  if (any(!is.finite(plot_values))) stop("DESeq2 绘图变换产生非有限值")
  plot_issues <- if (is.null(plot_issue)) list() else list(plot_issue)
  table <- data.frame(
    feature_key = feature_ids,
    original_id = feature_ids,
    gene_symbol = gene_symbols,
    log2FoldChange = log2_fold_change,
    pvalue = pvalue,
    padj = padj,
    direction = ifelse(log2_fold_change > 0, "up", ifelse(log2_fold_change < 0, "down", "flat")),
    tested = tested,
    reason_not_tested = reasons,
    mean_control_expression = means$control,
    mean_treated_expression = means$test,
    analysis_method = "DESEQ2",
    analysis_basis = "raw_count",
    effect_scale = "log2_count_model",
    mean_expression_unit = "RAW_COUNT",
    baseMean = base_mean,
    lfcSE = lfc_se,
    stat = statistic,
    stringsAsFactors = FALSE
  )
  rownames(table) <- NULL
  list(
    profile_id = profile_id,
    method = "DESEQ2",
    analysis_basis = "raw_count",
    effect_scale = "log2_count_model",
    table = table,
    excluded_features = feature_ids[reasons != ""],
    filter_summary = list(
      independent_filtering = TRUE,
      excluded_count = sum(reasons != ""),
      excluded_reasons = as.list(base::table(table$reason_not_tested))
    ),
    issues = c(if (dispersion_fallback) list(list(
      code = "DESEQ2_GENEWISE_DISPERSION_FALLBACK",
      severity = "WARNING",
      message_zh = "基因数量过少，无法拟合 DESeq2 的离散度趋势；已按 DESeq2 文档使用逐基因离散度继续计算。正式结果仍需使用完整表达矩阵复核。"
    )) else list(), plot_issues),
    summary = result_summary(table, fdr_threshold, lfc_threshold),
    diagnostics = list(
      independent_filtering_na = sum(reasons == "independent_filtering"),
      all_zero = sum(reasons == "all_zero"),
      outlier_or_unestimable = sum(grepl("outlier|unestimable", reasons)),
      pvalue_count = sum(is.finite(pvalue))
    ),
    parameters = list(
      p_adjust_method = "BH",
      independent_filtering = TRUE,
      dispersion_estimation = if (dispersion_fallback) "gene-wise-fallback" else "trend",
      alpha = fdr_threshold,
      design = deparse(design_info$formula),
      plot_transform = plot_transform,
      plot_zero_rows_removed = sum(!plot_keep),
      plot_vst_fallback = !is.null(plot_issue)
    ),
    plot_matrix = as_plot_matrix(
      plot_values,
      feature_ids[plot_keep],
      sample_ids,
      plot_transform
    ),
    runtime = list(
      R = R.version.string,
      DESeq2 = as.character(packageVersion("DESeq2"))
    )
  )
}

`%||%` <- function(x, y) if (is.null(x)) y else x

normalize_symbols <- function(value, n) {
  if (is.null(value)) return(rep(NA_character_, n))
  output <- vapply(value, function(item) {
    if (is.null(item) || length(item) == 0) NA_character_ else as.character(item[[1]])
  }, character(1))
  if (length(output) < n) output <- c(output, rep(NA_character_, n - length(output)))
  output[seq_len(n)]
}

line <- readLines(file("stdin"), n = 1, warn = FALSE)
if (length(line) == 0 || !nzchar(line)) quit(status = 2)
request <- tryCatch(fromJSON(line, simplifyVector = FALSE), error = function(e) e)
if (inherits(request, "error")) {
  emit("unknown", FALSE, error = list(code = "INVALID_REQUEST", message = conditionMessage(request)))
} else {
  request_id <- as.character(request$request_id)
  tryCatch({
    if (request$method == "ping") {
      emit(request_id, TRUE, list(status = "ready", runtime = R.version.string, limma = as.character(packageVersion("limma"))))
    } else if (request$method == "micro_limma") {
      emit(request_id, TRUE, run_micro_limma(request$payload, request$profile_id))
    } else if (request$method == "micro_deseq2") {
      emit(request_id, TRUE, run_micro_deseq2(request$payload, request$profile_id))
    } else if (request$method == "reference_orgdb") {
      emit(request_id, TRUE, run_reference_orgdb(request$payload, request$profile_id))
    } else if (request$method == "analyze_limma") {
      emit(request_id, TRUE, run_analyze_limma(request$payload, request$profile_id))
    } else if (request$method == "analyze_deseq2") {
      emit(request_id, TRUE, run_analyze_deseq2(request$payload, request$profile_id))
    } else {
      stop(paste0("未知方法：", request$method))
    }
  }, error = function(e) emit(request_id, FALSE, error = list(code = "R_JOB_FAILED", message = conditionMessage(e))))
}
