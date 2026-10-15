# GSE10361 软件结果流程核验（2026-10-04）

## 范围与结论

本次只核对软件的数据流、保存参数、统计输出、图表和导出文件之间是否一致；不作基因或生物学解释。原始文件、已保存项目和软件输出均只读，未重跑 GUI、未改项目、未覆盖输出。

**结论：软件产物之间的结构及数值传递一致；但当前分析设定与输入数据事实存在冲突，故这只能证明“软件按已保存选择完成了流程”，不能据此认定本次结果可作为有效表达差异结果。**

## 复核补充（2026-10-04）

- 对当前磁盘上的项目再次只读核对：Excel 仍为单工作表五列，22,283 行与内部 JSON 一一匹配；将导出中 `NA` 与 JSON `null` 按缺失值等价后，五列逐格不一致数均为 0。项目摘要、六样本绘图矩阵和五张图仍存在。
- 实际查看五张 PNG 时发现 p 值直方图的横轴为 `Raw p-value`，但副标题错误地带有表达矩阵转换说明 `log2(x+1)`。p 值本身没有经过这个变换。这是可复现的图注错误，不影响已保存的 p 值数值，但会误导读图。
- 已在 `PlotService._pvalue_histogram` 移除此转换标签并增加回归测试。定向绘图测试 **7 passed**，本轮完整回归 **194 passed、1 skipped（43.61 秒）**。隔离新候选 `/private/tmp/rnaseq-helper-pvalue-fix.9nMdW4/RNA-Seq Helper.app` 的内置 Python 实际生成了仅标注有效 p 值数量的测试图；bundle 自检 `ready=true`、limma/DESeq2 微型验证及严格 ad-hoc 签名通过，包内 Python 源码与工作区一致。
- 为保护旧证据，真实用户项目内的旧 p 值图未覆盖，仍带原错误副标题；没有重跑差异分析。新候选没有 GUI 实屏验收，也没有替换 `/Applications/RNA-Seq Helper.app`。新候选可供后续桌面验收，安装版仍为旧版本。
- 输入尺度/转换公式的直接依据仍缺失，旧项目保存的手动 FPKM/LINEAR 选择与其 GEO array 来源线索冲突。因而旧分析结果仍不能通过输入事实核验；本轮不作生物学解释或尺度猜测。

## 核验对象

- 项目：`/Users/additionlee/Documents/RNA-Seq Helper Projects/GSE10361_series_matrix.txt-58d06b3f`
- 保存矩阵：`prepared/expression_matrix.tsv`，22,283 个 feature × 9 个样本。
- 分析计划：`analysis/analysis-plan.json`。
- 内部结果：`analysis/deg-result.json`。
- 用户可读导出：`reports/deg-results.xlsx`、`reports/analysis-report.html`、`reports/interpretation-zh.txt`。
- 图：`figures/` 中 PCA、样本相关性、p 值分布、火山图、热图共五张。

## 已核验：软件流程和文件一致性

1. **导出 Excel**：只含一个工作表；列名和顺序准确为 `feature_key`、`gene_symbol`、`log2FoldChange`、`pvalue`、`padj`。22,283 行与 JSON 结果一一对应；这五列所有行逐格一致（数值容差 `1e-12`，本次 0 处不一致）。没有改成七列。
2. **过滤和绘图输入**：按计划所存条件，在六个入选样本中至少三个值 `x≥1`，独立重建得到 22,275 个 feature，与结果中的 `plot_matrix` 行数及顺序完全相同。样本 ID 顺序一致；对 133,650 个绘图数值逐个套用 `log2(x+1)`，与保存的绘图矩阵最大绝对差为 0。
3. **组别交接**：保存计划指定 `test` 为 GSM261914、GSM261913、GSM261581，`control` 为 GSM261580、GSM261575、GSM261573；GSM260542、GSM260541、GSM260537 标为 excluded。统计矩阵和图表仅使用上述六个所选样本；三个排除样本没有进入 `plot_matrix`。
4. **结果计数**：22,283 个总 feature；22,275 个参与检验、8 个被过滤、0 个退化、0 个无效；有效 p 值 22,275 个，残差自由度均为 4。保存的 BH、FDR `<0.05`、效应绝对值 `≥1` 规则下，结果 JSON、HTML 和软件摘要一致地记录 94 个（正向 13、负向 81）。p 值范围为 `2.44388625e-09` 至 `0.9999751461`。
5. **独立 R 复算**：子代理使用 R 4.6.0、limma 3.68.4 对保存矩阵按原计划重跑过滤、`log2(x+1)`、`test-control`、经验贝叶斯和 BH。22,275 个检验行及掩码与内部 JSON 一致；最大绝对差异：LFC `5.33e-15`、p 值 `7.77e-15`、padj `8.10e-15`；BH `<0.05` 为 94 行，且同时满足 `|LFC|≥1` 也是 94 行。此项验证可重现性，不验证输入单位或实验设计。
6. **图表/报告**：五张图文件均存在；报告记录的矩阵哈希与项目保存的矩阵哈希相同。图表使用的过滤后矩阵与变换已按上文逐值核对。HTML 的方法、过滤、统计计数与内部结果一致。实际视觉检查发现 p 值直方图副标题误标了表达矩阵转换；源码已修复并通过回归，但旧项目中的 PNG 保持原样，不能算已更新。
7. **gene symbol**：本项目没有保存注释参考表（`reference_result=null`）；Excel 的 `gene_symbol` 因而为 `NA`，feature ID 保留为原 probe ID。这是当前项目缺少映射输入的结果，不是 Excel 行错位。

## 存在问题：输入事实未能支持当前方法标签

- 保存计划把数值选择为 `FPKM`、尺度为 `LINEAR`，且使用者确认状态没有对应的原文证据；报告因此写成“已确认的 FPKM 线性表达量”，并运行 `LIMMA_ON_LOG2_FPKM`、先 `x≥1` 过滤、再 `log2(x+1)`。
- 项目已有的 GSE10361 来源核查文档记录：该矩阵来源于 GPL96 芯片，GEO 样本页把对应数值标为芯片 SIGNAL；而当前 Series Matrix 导出值是否为线性、log 底数及确切公式未由直接证据确认。芯片 SIGNAL 与 FPKM 不是可互换的单位标签。
- 因此，统计文件与图表的内部一致性通过，但“FPKM/线性”的选择缺乏支持且与来源类型冲突。**94 及方向计数只是该保存设定下的程序输出，不能作为本次有效差异分析的可信结论。**本报告不对任何 feature 作生物学解释。

## 尚缺的确认

1. 当前这份 Series Matrix 导出值的确切数值尺度及转换公式，需要与该文件/导出对应的来源说明；不得按数值外观猜测。
2. 若要把分析作为有效比较，需先更正或确认输入事实，并由用户明确本次比较和样本纳入方案。此处仅记录软件保存的组别标签和排除项，不解释组别生物学含义。
3. 如需 gene symbol，须提供或选择能与当前平台 probe ID 对应且来源明确的注释表；这不是差异检验本身的必需输入。

## 后续建议与边界

- 先不要把当前输出用于生物学结论；保留现有项目以供审计，不要直接覆盖。
- 补齐输入尺度/公式与比较方案后，在软件中另存并重新运行，再对新项目重复同样的文件一致性检查。
- **本轮源码修复**：GEO `!Series_type = Expression profiling by array` 现在作为明确来源元数据保留；整理校验和分析规划均阻断将此类输入标为 raw count、TPM、FPKM、RPKM 或 CPM，同时保留“其他连续表达值”路径。没有明确 array `Series_type` 的 GEO 项目不受该门禁影响。来源平台类别写入项目清单、分析计划、HTML/manifest。
- **来源措辞修复**：用户手动选择但没有关联来源文字时，保存为 `manual_without_direct_text`；计划描述使用“当前选择”，报告不再写成来源已确认。五列 Excel 实现未改。
- 当前既有项目、HTML、XLSX 和图均保持原样；它们是旧运行产物，仍标记 FPKM，不能作为已修复结果。源码补丁尚未同步到候选 `.app` 或 `/Applications` 安装版，也未在真实 GUI 中重新导入该项目。
- 直接使用本地原始 GSE10361（只读）重走导入校验：识别到 `GPL96` 与 `Expression profiling by array`，数值单位/尺度候选仍是 UNKNOWN；强制选 FPKM/LINEAR 被 `GEO_ARRAY_MEASUREMENT_CONFLICT` 阻断；改选通用连续表达值后整理校验通过，允许进入后续步骤，但未擅自选定真实尺度或执行分析。
- 定向测试 **43 passed**；完整回归 **193 passed、1 skipped（41.11 秒）**。隔离候选 `/private/tmp/rnaseq-helper-result-audit.G1cGvP/RNA-Seq Helper.app` 已同步全部六个改动模块，源码目录 `diff` 无差异、ad-hoc 严格签名通过、`verify_bundle.py` 返回 `ready=true`，内置 R/limma/DESeq2 检查通过。没有 GUI 实屏验收。
- 再直接用隔离候选自己的 `Contents/MacOS/python`（Python 3.14.7）对真实 GSE 文件重走扫描/整理门禁：22,283×9；FPKM/LINEAR 被阻断；OTHER_NORMALIZED 整理校验通过。没有执行差异分析或推断尺度。
- 旧结果摘要保持未变：XLSX SHA256 `538a63513b46cbd9803268140085c0600971ab5dd4dc1a6e3fd53b6ba3bed0b6`；HTML `b548272d2180b1f2fd5c20abac614e9ec0eda9cf4b385665054c96c16416a1aa`；内部 JSON `d39829325482b049282056aa8d51026de874b55e64d034ef2f4958b5a081a90d`。
- 原先用户项目/HTML/XLSX/图均保持原样；其中 FPKM 结果仍是旧产物，尚无证据尺度的新结果没有生成。旧 HADQ06 候选和 `/Applications` 安装版均未替换。AI 自动化相关 Python 退出未重查。
- 本审查文档尚未登记至 MySQL：既有交接明确连接凭据轮换未确认，本轮未读取或使用凭据。恢复可信连接后再按项目规则登记，不能将未登记写成已完成。
