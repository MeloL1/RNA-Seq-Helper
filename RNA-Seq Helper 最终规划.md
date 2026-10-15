# RNA-Seq Helper 最终规划

版本：1.0；日期：2026-09-13。本文是开发规格，不包含程序实现。整合原架构及 TPM/FPKM 修订，以本文作为后续开发和审查依据。

## 1. 产品定位与核心原则

面向完全不懂生信的科研人员、研究生和临床医生，提供本地 GEO2R 式两组差异表达分析体验。GEO2R 依赖 GEO 的文件结构与元数据，本软件承担本地文件的识别、显式整理与有效性验证。

核心流程：拖入文件 → 扫描和人话说明 → 按需整理向导 → 可视化确认分组与对照 → 准备参考 → 确认自动生成的计划 → 分析、绘图、报告。

核心约束：

- 识别宽容，整理显式；不承诺任意文件自动可分析。
- 原始文件只读，整理结果写入独立项目目录；保存可重放的整理配方。
- 文件可读、单位已知、方法适用、实验设计可估计是不同检查，不能合并成一个置信度。
- 数据事实不明时请用户核实；方法已明确时由软件选择，不要求小白选择统计工具。
- 联网仅获取参考，不上传表达矩阵；参考获取失败不必然阻断按原编号分析。
- 未支持的统计设计和无效数据不能通过风险勾选绕过。

## 2. v1 范围

| 输入 | 支持范围 | 限制 |
|---|---|---|
| 公司 CSV/TSV/Excel | 整理、预览、分析；包括多 sheet、非首行表头、说明列 | 必须确认数值单位、尺度与样本身份 |
| GEO Series Matrix | 识别、整理、样本注释读取和适用方法分析 | 多平台分开；不假定全部 GEO 表均为已标准化芯片值 |
| GPL SOFT/annot | 作为参考文件读取和匹配 | 不作为表达矩阵计算 |
| TPM/FPKM | 正式支持 log 表达 limma-trend 路径 | 明确局限；不直接输入 DESeq2 或 voom |
| CPM/RPKM、其他已知 log 表达 | 根据独立单位和尺度标记进入适用连续表达路径 | 通用路径需通过第 8 节门禁 |
| 10x 三件套 | 组合识别、完整性检查、稀疏导入、预览 | v1 不把细胞当独立 bulk 样本做两组差异 |
| tar/tar.gz/zip | 安全递归展开和逻辑对象选择 | 展开限额、目录逃逸防护 |
| FASTQ/BAM | 识别并提供友好指引 | 不做比对、定量 |
| 无关文件 | 已知无关文件标注忽略 | 未识别文件单独标记，不武断归为无关 |

统计设计：两组独立样本和明确的简单配对设计；可支持可估计的简单批次协变量。每组至少 2 个独立生物学样本，建议至少 3 个；完整配对至少 2 对且残差自由度须通过检查。复杂重复测量、未知独立性和完全混杂设计暂停。

芯片默认以探针作为统计单位，结果称“差异探针”；名称映射不能把一个探针复制成多个独立发现。count 的 Ensembl/Entrez 编号可以直接计算，翻译名称通常是非阻断增强功能。

## 3. 项目结构与运行存储

```text
RNA-Seq Helper/
├── pyproject.toml
├── README.md
├── docs/                       # 产品、接口、识别与向导规范
├── src/rnaseq_helper/
│   ├── app.py
│   ├── domain/                 # dataclass、枚举、验证、事件、错误
│   ├── ui/
│   │   ├── pages/              # 导入、整理、分组、计划、运行、结果
│   │   ├── widgets/            # 预览、样本卡片、步骤条
│   │   ├── controllers/
│   │   └── workers/            # QObject worker + QThread
│   ├── services/               # 导入、项目、参考、计划、分析、绘图、报告、自检
│   ├── recognition/            # 扫描、探测器注册、证据、压缩识别
│   ├── readers/                # 分隔文本、Excel、GEO、10x
│   ├── preparation/            # 向导引擎、配方、预览、转换、矩阵校验
│   ├── grouping/               # 分组建议与设计验证
│   ├── references/             # 缓存、providers、映射校验
│   ├── r_bridge/               # 客户端、独立 worker、协议、转换、固定 R 入口
│   └── resources/              # 图标、术语、图文指引、离线参考、报告模板
├── packaging/                  # py2app、Info.plist、运行时清单、签名
└── tests/                      # fixtures、识别、整理、分析、打包
```

只有 ui 依赖 Qt；领域、识别、整理引擎与服务不持有窗口对象。

运行缓存：`~/Library/Application Support/RNA-Seq Helper/reference-cache/`；日志：`~/Library/Logs/RNA-Seq Helper/`。用户项目保存 project.json、preparation-recipe.json、prepared/、analysis/、figures/、references/、reports/。签名后的 .app 内不写缓存或结果。

## 4. 领域对象与接口契约

对象默认不可变，大矩阵使用存储引用。MatrixStoreRef 包含路径、dense/sparse、dtype、shape、哈希；TableStoreRef 包含路径和 schema；ArtifactRef 包含路径、格式、哈希与用途。Evidence 包含依据、来源位置与分数；Issue 包含编码、严重程度、中文解释与操作。

| dataclass | 字段规格 |
|---|---|
| DataAsset | asset_id、source_paths、parent_asset_id、archive_member_paths、content_fingerprint、kind、role、reader_key、confidence、evidence、shape_hint、species_hint、platform_ids、measurement_hint、scale_hint、各维度置信度、related_asset_ids、issues |
| ExpressionMatrix | matrix_id、values: MatrixStoreRef、feature_metadata: TableStoreRef、sample_metadata: TableStoreRef、observation_unit、measurement_type、value_scale、input_transform、measurement_provenance、feature_id_type、species_taxid、platform_id、source_asset_ids、recipe_id、validation、content_hash |
| AnalysisPlan | plan_id、matrix_hash、method、method_reason_zh、analysis_basis、method_profile_id、resolved_method_parameters、design、contrast、preprocessing、reference_request、reference_required_for_fit、config、limitations_zh、input_selection_reason_zh、warnings、blockers、confirmation_digest |
| DEGConfig | control_group、test_group、fdr_threshold=0.05、lfc_threshold=1、count_filter、expression_filter: ExpressionFilterSpec、paired_subject_column、batch_column、lfc_shrinkage、top_heatmap_features=30、random_seed |
| DEGResult | result_id、plan_digest、table、summary、diagnostics、plot_matrix、excluded_features、analysis_basis、method_profile_id、effect_scale、resolved_method_parameters、filter_summary、runtime_versions、issues |
| ReferenceResult | request、status: READY/PARTIAL/UNAVAILABLE/NOT_NEEDED、mapping、provider、species_taxid、platform_id、release、retrieved_at、checksum、coverage、ambiguous_count、unmapped_count、guide |
| ReportBundle | bundle_id、html、result_xlsx、figures、analysis_manifest、preparation_recipe、reproduction_artifacts、warnings |

辅助对象：PreparationRecipe、WizardSession、WizardStep、PreviewPage、GroupingSuggestion、DesignSpec、ContrastSpec、TransformSpec、ExpressionFilterSpec、MethodProfile、ReferenceRequest、ProgressEvent、UserFacingError、JobContext。

TransformSpec：底数、伪计数、原尺度、是否已经转换、转换公式与证据。ExpressionFilterSpec：尺度、阈值、单位、样本数量规则、解析出的 N。MethodProfile 包含 profile_id、版本、全部参数和诊断阈值，禁止通过修改 profile 悄悄改变旧分析。

ExpressionMatrix 不变量：

- 特征表顺序与矩阵行一致，样本表顺序与列一致；内部 feature_key/sample_id 唯一。
- 原始编号按字符串保留，展示名称可重复。
- 注释列不进入数值矩阵；重复、缺失、异常处理进入配方。
- 不静默填零、合并重复编号、修复日期化基因名或四舍五入小数为 count。
- count 是有限非负整数，且数据来源确认是可用原始计数；整数外观不是充分证据。
- observation_unit=CELL 禁止进入 bulk runner。
- 翻译基因名称不改变统计矩阵行数。

### 核心服务签名

| 类 | 签名 |
|---|---|
| AssetScanner | scan(paths: Sequence[Path], context: JobContext) -> ScanResult |
| AssetDetector | detect(probe: FileProbe, siblings: Sequence[FileProbe]) -> DetectionResult |
| ArchiveService | inspect(asset, limits) -> ArchiveManifest；extract(manifest, context) -> Sequence[DataAsset] |
| PreparationService | start(asset) -> WizardSession；preview(session, patch, window) -> PreviewPage；apply(session, decision) -> WizardSession；finish(session) -> ExpressionMatrix |
| GroupingService | suggest(matrix) -> Sequence[GroupingSuggestion]；validate(matrix, assignments, design) -> ValidationSummary |
| ReferenceService | resolve(request, context) -> ReferenceResult |
| PlanningService | build(matrix, design, config) -> AnalysisPlan；confirm(plan, decisions) -> AnalysisPlan |
| AnalysisService | run(matrix, plan, reference, context) -> DEGResult |
| NormalizedExpressionRunner | run(matrix, confirmed_plan, context) -> DEGResult |
| RBridgeClient | submit(request: RJobRequest, context) -> RJobResponse；cancel(job_id) -> CancelOutcome |
| PlotService | build(result, matrix, context) -> Sequence[FigureArtifact] |
| ReportService | build(result, figures, provenance, context) -> ReportBundle |
| EnvironmentService | check(context) -> EnvironmentStatus |

JobContext 仅包含取消令牌、事件回调、工作目录与任务标识，不依赖 Qt。

UI 命令：importRequested(paths)、previewRequested(session_id, revision, patch, window)、wizardDecisionSubmitted(session_id, revision, decision)、groupsConfirmed(matrix_id, assignments, design)、planConfirmed(plan_id, digest)、runRequested(plan_id)、cancelRequested(job_id)。

worker 输出：assetsDiscovered、previewReady、wizardUpdated、planReady、progressChanged、failed、completed、cancelled。事件带任务标识；预览带 revision，丢弃过期响应。传递不可变 DTO/存储引用，不共享可变 DataFrame。数据、分组、尺度、参数变化使旧计划确认失效。

取消用线程安全令牌；不能仅依赖忙碌 worker 的 queued slot。无法估计进度时使用活动进度，不制造百分比。

## 5. 整理向导

向导只展示未解决的问题。每页包含为什么需要本步的一句话、原表与整理后预览、建议依据、返回、下一步、使用建议并跳过、暂时跳过稍后处理。必要问题未解决可退出，不能直接运行。

| 场景 | 交互与确认 |
|---|---|
| 多 sheet | sheet 卡片显示名称、尺寸、数值密度、缩略图；逐张点击分页预览；使用这张表；不默认拼接 |
| 非首行表头 | 展示前 30 行和候选表头；点击行即时更新样本名与尺寸；表头和数据起始行分别可选 |
| 列名混乱 | 原列名、数值摘要、待分组/对照/另一组卡片区；拖拽、多选或键盘分配；颜色同步到表格 |
| 行列相反 | 展示当前和转置后缩略图，说明每行基因每列样本；一键转置可撤销 |
| 编号列与样本列 | 编号/样本数值/说明/忽略四种角色；点击列头改角色；指定样本列后才推断分组 |
| 包内多个候选 | 逻辑对象目录树、用途、尺寸、完整性；10x 三件套一张卡片；表达矩阵和参考分开 |
| 单位/尺度不明 | 读取交付说明并给出示例；用户确认原始计数、TPM/FPKM/其他，是否已取 log；不要求选方法 |

解释分别采用“这个文件有几张表，需要找到各样本表达量的那张”“请确认没有把说明文字当数据”“请按实验安排把样本放好”“需要把基因放行上、样本放列上”等中文。

Excel 多级合并表头可建议组合名称并显示来源；数值区合并单元格暂停，不向下填成重复测量。不执行宏、公式或外部链接；公式缺缓存值引导打开 Excel 保存或导出纯数值。

最终页展示矩阵尺寸、所选表头、排除行列、转置、重复与缺失、单位尺度、物种、分组、配对关系和全部变更。全量验证通过后生成标准对象，抽样预览不能替代验证。

## 6. 识别决策与分组规范

文件清单 → 内容探测 → gzip 内部类别/安全容器展开 → 同目录组合 → GEO/平台标记 → Excel sheet → 文本编码分隔符 → 表头/方向/列角色 → 单位与尺度 → 可分析性。

原始 FASTQ/BAM 优先识别不进入分析；MTX+features/genes+barcodes 合成逻辑对象。已知图片、PDF、说明文档归辅助/无关；未知保留未识别类别。扩展名与内容冲突按内容识别并说明；编码不明给候选预览，不替换乱码。

压缩限制覆盖体积、成员数、压缩比、递归深度、磁盘空间；拒绝目录穿越和链接逃逸，只展开到工作目录。

置信度按格式、方向、列角色、单位、尺度、物种、分组分别记录：≥0.90 展示建议可跳过结构整理；0.60–0.90 强制相应预览确认；<0.60 给多个候选。是待真实数据校准的工程分数，不是准确概率；实验含义始终需要确认。

measurement_type：RAW_COUNT/TPM/FPKM/RPKM/CPM/OTHER_NORMALIZED/UNKNOWN；value_scale：LINEAR/LOG2/OTHER_TRANSFORM/UNKNOWN；观察单位独立记录。

单位证据顺序：结构化元数据/交付说明 → sheet/表头 → 文件名 → 数值分布。列总和接近一百万仅提示 TPM/CPM 候选，不能区分二者；子集 TPM 不必总和一百万。

分组建议：

| 模式 | 建议与限制 |
|---|---|
| Ctrl/Control vs Treat | 对照/处理，词边界匹配 |
| Normal vs Tumor | 正常/肿瘤，询问是否配对 |
| WT vs KO | WT/KO，建议 WT 对照 |
| Vehicle vs Drug | 溶剂/用药 |
| Sham vs Model | 假手术/模型，仍核实实验含义 |
| Healthy vs Disease | 健康/疾病 |
| NC/OE/KD | 保留原名，NC 含义需核实 |
| A1–A6 vs B1–B6 | A/B，不决定对照 |
| Patient01_Pre/Post | 前后组与个体配对候选，逐项核实 |
| 条件×时间 | 多因素候选，不能简单折成两组 |
| GSM 编号 | 查样本注释，编号自身不含组别 |
| S1–S12/纯数字 | 未分组，不猜前 6 对后 6 |
| batch1/batch2 | 批次候选，不当实验组 |
| 10x 条形码 | 细胞编号，不推断实验组 |

来源优先：明确样本表 → 结构化样本注释 → 列名 → 文件名。连接样本表用唯一 ID，不按行硬配。分组和对照每次都确认。

## 7. TPM/FPKM 分析分支

### 默认 profile

profile_id：normalized-log-limma-trend-v1。

| 环节 | 固定默认 |
|---|---|
| 输入 | 同实验、同单位、同定量流程的 bulk TPM/FPKM |
| 过滤 | 线性尺度 x≥1，至少 N 个入选样本达标；N 为较小组独立样本数，配对为完整配对数 |
| 转换 | log2(x+1)；已知已经转换则不再次转换 |
| 再标准化 | 不做 quantile/TMM/总和缩放/中位数校正 |
| 模型 | lmFit 普通最小二乘，contrasts.fit 指定方向 |
| 方差 | eBayes(trend=TRUE, robust=TRUE) |
| winsor.tail.p | c(0.05,0.10)，是 limma 默认值，显式传入只为可复现，非自定义调优 |
| 版本行为 | 支持 legacy 参数的固定发布版本显式 legacy=TRUE，沿用传统稳健估计；不支持时由版本 profile 定义，不盲传 |
| 其他参数 | proportion=0.01、stdev.coef.lim=c(0.1,4)；其他实际参数及依赖版本全部记录 |
| 校正 | 当前对比全部有效检验 BH |
| 筛选 | padj<0.05 且模型效应绝对值≥1；分别说明两种条件 |

新增说明：winsor.tail.p 在采用相应稳健估计算法时生效；现代 limma 不同 legacy 路径可能处理不同。显式参数不等于跨版本自动一致，必须固定版本和实际算法。它处理方差估计的尾部，不截尾 TPM 数值。

过滤是产品启发式，不是通用最优阈值。达标数量在全部样本计数，不要求两组都达标、不只看处理组。全零特征排除，保留原因。count 仍用原计数预过滤，不能将表达量过滤冒充 count 过滤。

选择 +1 为零值定义明确、易解释、能缓和低表达变化。+0.1/+0.5 用于开发敏感性验证，不按显著基因数自动挑伪计数。已知其他 log 公式使用独立 profile/实际标记；不可强写 plus_1。

trend 在平均表达与方差相关时合理；robust 保护经验贝叶斯超参数，不是稳健回归、不自动修复离群样本。零值位置不必比 count 更多，交付舍入和不同定量可能改变零比例。

不对零值加抖动、不填虚构表达。执行过滤后检查残差方差与均值—方差诊断；无法估计的特征单独标记，广泛异常按第 8–9 节暂停。

### 方法枚举与调度

DESEQ2；LIMMA（芯片）；LIMMA_ON_LOG2_TPM；LIMMA_ON_LOG2_FPKM；LIMMA_ON_LOG2_RPKM；LIMMA_ON_LOG2_CPM；LIMMA_ON_LOG_EXPRESSION；BLOCKED。

可信原始 count 优先 DESeq2；芯片确认 log 尺度后 limma；TPM/FPKM 自动上述 profile。不得直接 TPM→voom 或 DESeq2、不得随意反推整数 count。完整 Salmon/RSEM 结果经 tximport 为后续独立输入类型，不与只有 TPM 表格混同。普通 limma/vooma 等只作后续评估。

TPM 和 FPKM 共用 runner，分开单位、方法枚举和报告。TPM 完整标准定义列总和约一百万，FPKM 不恒定；默认阈值同为 1 只是实用默认，不表明单位等价。不自动 FPKM→TPM，交付表可能不完整，重新归一化会改变含义。

可信 count 与 TPM 同实验、同特征层级且样本对应时优先 count，告知“我们优先用原始计数，因为它保留更多统计建模所需信息”。样本/物种/层级冲突时展示差异请选数据。

线性 TPM/FPKM 负值暂停核实，不能裁零；已知中心化 log 表达负值可能合法。非有限值阻断。TPM 明显超过一百万且不属于舍入容差时单位核实；FPKM 不用此上限。高值只按原值、log 值和同基因跨样本预览核实，不自动截尾。

## 8. LIMMA_ON_LOG_EXPRESSION 门禁与诊断

此通用入口不能是未知数据的兜底垃圾桶。允许“确认为可比较的连续 log 表达值，原单位不详”，不允许“看起来像 log 所以试算”。以下阈值是版本化产品保守策略，不是 limma 的普遍数学限制。

### 通过条件和阻断文案

| 检查 | 通过 | 不通过与提示 |
|---|---|---|
| 数据含义 | 有交付说明/用户核实：每项是特征表达值，同一定量流程、可跨样本比较 | UNKNOWN_SCALE：“还不能确认这些数字是表达量、计数还是其他分数。请查看交付说明，或向提供方确认单位和转换方式。” |
| 尺度 | log2 已知，或其他明确对数底数可按已知规则换底；中心化方式已知且未消除待比较效应 | INVALID_TRANSFORM：“这张表可能已经被再次标准化或换成评分。当前无法确定组间变化的含义，请提供转换说明或未转换表达表。” |
| 排除类型 | 非 Z-score、非百分位/秩、非比值到未知参照、非残差表达、不含混合单位 | NON_EXPRESSION_SCORE：“这些值是评分或校正残差，不能沿用表达量的差异分析和倍数解释。请提供原表达矩阵。” |
| 观察单位 | 独立 bulk 样本，或明确简单配对 | INVALID_REPLICATES：“目前无法确认这些列代表独立样本。技术重复或细胞不能直接当作不同个体，请补充样本说明。” |
| 数值与标识 | 所选数值全部有限、样本 ID 唯一、元数据匹配 | INVALID_VALUES：“部分单元格不是有效数字，或样本名称重复。请回到预览修正标出的项目。” |
| 设计 | 满秩、对比可估计；n-rank(design)≥2；每组≥2；配对≥2 完整对 | NON_ESTIMABLE：“当前样本安排无法可靠区分组别影响。可能样本不足或组别与批次完全重合，请补充或调整实验信息。” |
| 可用特征 | 无单位时仅排除全局常量/不可用行；至少 500 个可拟合特征，Amean 至少 50 个不同值（1e-8 量化精度） | INSUFFICIENT_TREND_DATA：“可用于估计表达量与波动关系的数据太少，本版本无法可靠完成自动分析。请提供完整表达表或采用专门流程。” |
| 残差方差 | 无效方差特征比例≤5%；剩余仍满足规模门禁 | DEGENERATE_VARIANCE：“较多基因在每组内几乎没有波动，可能数值被舍入、复制或列并非独立样本。请索取更高精度数据并核实样本。” |
| 方差拟合 | eBayes 成功，先验与后验方差有限且为正，统计量/p 值有效；df.prior=Inf 本身允许 | FAILED_VARIANCE_FIT：“软件无法稳定估计这些表达值的波动，已停止输出显著性结果。请检查数据精度、样本安排和数据处理说明。” |
| 舍入质量 | 第 9 节未达到严重异常组合条件 | 使用第 9 节文案 |

残差数值零判据：在模型尺度 y 上，s²≤1e-12×max(1,mean(y²)) 视为数值退化。退化行不参与正式检验；比例按过滤后可拟合行计算。该判据和 5% 阈值需以 mock 与真实交付数据校准，写入 profile。

已 log 的 TPM/FPKM 可用等价单位阈值过滤。原单位不详时不能假设“log≥1”等于 TPM≥1；只按上述可用性排除，不编造原尺度阈值。单位完全未知也不一定阻断，前提是表达含义、log 尺度和可比性得到证实。

### 仅提示、不阻断的诊断

样本 PCA 分离不明显、离群样本候选、样本相关性偏低、plotSA 曲线较平、p 值直方图不均匀、单个 Shapiro 正态性检验不通过，均不单独作为阻断规则。它们不能证明方法失效或通过。趋势诊断用于查看平均表达与残差方差，不以“有明显趋势”作为运行的必要条件。

PCA/相关性报告提示核实质量与批次；不自动删样本，不用风险勾选代替修复。统计 QC 通过只意味着未发现门禁问题，不宣称所有模型假设已被证明。

## 9. 过度四舍五入/低精度检测规范

目的：识别可能因交付精度损失导致的退化，不从矩阵外观认定数据提供方一定舍入。启发式只适用于非 count 连续表达路径，整数 count 禁用此规则。

### 指标定义

对入选数据按固定种子均匀抽取最多 100,000 个有限非零值用于早期预览；最终用全量或确定性流式统计确认。零值不参与格点占比，避免真实零表达制造误报；非零值少于 1,000 个标记证据不足，不触发格点单项诊断。

对线性 TPM/FPKM：取 0<x≤10 的低表达值；对直接输入的 log 表达：取全部非零值。若线性低表达值不足 1,000 个，不计算低表达格点告警。

定义格点比例 Q(q)：距最近 q 倍数不超过 1e-6×q 的值所占比例。线性尺度测试 q=1、0.1；log 尺度测试 q=0.1。log 值近整数≥95% 也报告。容差用于二进制表示误差，不是扩大舍入判断范围。

定义 L：过滤后非恒定特征中，使用全部所选样本，值经 1e-8 数值容差归并后不同值数量≤3 的特征比例。已知线性输入还计算低表达段全零/开关比例，但不单独定性为舍入。

定义 Z：模型拟合后数值退化残差方差比例，判据见第 8 节。重复样本列按完整数值列和原样本信息检查，单独报告，不能靠格点检查替代。

### 分级与动作

| 条件 | 动作与中文提示 |
|---|---|
| 线性低表达 Q(1)≥95%；或 log Q(0.1)≥95% | 精度告警，允许继续：“很多表达值只保留了整数或较少小数，低表达基因的变化可能被压缩。软件会继续分析并记录此限制；如能获取更多小数位的数据，结果通常更稳妥。” |
| 线性 Q(0.1)≥95% 且 L≥20% | 同类告警；一位小数格点本身不单独称过度舍入 |
| 以上任一格点告警成立，且 L≥50% 且 Z>5% | 暂停：“数据精度可能不足：超过一半的可用基因只有不超过 3 种数值，且较多基因无法估计组内波动。请向提供方索取未取整或保留更多小数的数据，并核实是否包含复制或技术重复。” |
| Z>5%，无格点证据 | 方差退化门禁暂停，但不声称舍入：“较多基因无法估计组内波动，请核实数据处理和独立样本信息。” |

建议索取保留至少 3–4 位小数或完整数值精度的文件；增加显示小数位不会恢复丢失精度。以上 95%/20%/50%/5% 是起始产品阈值，必须覆盖误报测试并根据真实数据校准。三样本/组、开关表达和严重生物学一致性可产生少量离散值，故格点或 L 单项不阻断。

## 10. 执行、效应解释、图表与报告

执行：验证 → 单位过滤 → 尺度转换 → 设计拟合 → 残差门禁 → 固定 eBayes → BH → 字段适配 → QC → 图表 → 报告。R job 携带 profile 与全部参数，回传实际参数，服务核对一致性。失败不得静默换方法。

统一表字段：feature_key、original_id、gene_symbol、log2FoldChange、pvalue、padj、direction、tested、reason_not_tested；新增 analysis_method、analysis_basis、effect_scale、mean_control_expression、mean_treated_expression、mean_expression_unit。方法专属统计字段另存，完整参数放结果级元数据与 Excel 方法页。

兼容 log2FoldChange 字段，但标准化表达路径界面称“模型估计的组间变化”。简单两组系数是 mean(log2(x+1)) 的处理组减对照组；不是 log2(原尺度算术均值之比)。1→2 TPM 对应约 0.585，不能把系数≥1直接称“原始 TPM 翻倍”。有协变量时是调整后的效应。NA 保留原因，不改为零。

| 图 | 默认数据与标签 |
|---|---|
| PCA | 过滤后 log2(x+1)，最多 2,000 高变异特征；按基因中心化，不按方差缩放；副标题标尺度和选取规则 |
| 样本相关性 | 过滤后 log2(x+1)，Pearson；不使用行 Z-score；图注标尺度 |
| 火山图 | 模型系数与 -log10(padj)；横轴组间变化（log2表达尺度），副标题标 log2(TPM+1)/实际公式 |
| Top 热图 | 先用同一 log 矩阵，展示前按行 Z-score；图例标每个基因内标准化颜色，图注标原尺度 |

log 缓和原始 TPM 的动态范围，避免少数高值主导；不是 count VST，不保证完全同方差。PCA 不按显著性选基因。无显著结果改为高变异特征热图并改名；离群只建议核实，不自动删。

计划页正文：“这份数据提供的是 TPM 标准化表达量。软件将先取 log2，再用 limma-trend 比较两组差异。该方法适用于缺少原始计数的情况，但无法利用原始计数中的测序深度和精度信息；结果需结合实验设计及后续验证解释。”

不增加接受标准化分析勾选或二次确认，只用统一开始分析按钮。方法在运行前可见，结果页持续显示“本次分析基于标准化值；论文中请说明方法”。不只在报告末尾告知；未知数据事实仍需核实。

报告方法段记录来源、特征层级、单位、阈值与 N、实际 log 公式、limma/R版本、设计与对比、eBayes全部参数、BH集合、筛选规则、实际排除原因。说明 eBayes 检验非零效应，展示幅度筛选不等于对超过该幅度的假设控制 FDR。

局限段：“本分析基于标准化表达量，未使用原始计数中的测序深度和计数精度信息。标准化值可能受表达组成、定量流程及有效长度变化影响。伪计数会改变低表达区域效应，模型效应不严格等于原尺度倍数变化。结果需结合实验设计与独立验证；如获可信 count，可补充计数模型分析。”

HTML 离线可打开、无远程脚本依赖；完整表 xlsx；包含图注、样本安排、整理配方、参考版本、参数、QC、局限与运行清单。中文解读使用可审计模板，v1 不依赖在线大模型。

## 11. 参考文件与失败降级

名称翻译优先用户参考/本地缓存。芯片识别 GPL → GEOparse 获取 → 必要时独立 R worker GEOquery → 手动导入或保留探针。换解析库不解决共同网络不可达，使用有限重试和超时。

编号检测：ENSG 人、ENSMUSG 小鼠、ENSRNOG 大鼠只是物种建议；Entrez 纯数字不能推断物种；Symbol 可跳过翻译；混合/自定义展示示例请核实。物种决定字典，须确认。Ensembl 版本后缀仅调整查表键，保留原 ID。

映射优先离线版本化表/OrgDb（人、小鼠、大鼠），其次 biomaRt 官方镜像和已知参考版本，再手动导入/原 ID 输出。一对多保留列表，未映射和歧义覆盖率进入报告；不复制统计行。预置参考记录来源、许可、版本、日期、checksum。

ManualGuide 含直接平台页面/当前验证下载 URL、版本截图和实际按钮（例如 Download family/SOFT）、下载内容、项目 references/ 保存建议、拖回应用与重新检查。不同平台不保证相同 annot 按钮；网页变动可退文字步骤。count 字典引导 Ensembl BioMart 指定物种、版本与编号/名称列。

## 12. 验证与 mock

独立 R 基准不调用应用自己的转换/适配模块。固定 fixture、过滤集合、N、转换、设计、对比、lmFit、eBayes trend/robust/winsor.tail.p/legacy与全部参数、零方差规则、BH集合、R/limma/statmod版本。比较矩阵、系数、残差、moderated t、p/padj、NA位置和排除原因；浮点容差不要求跨架构字节一致。交换对照后系数反号，双侧 p/padj 不变。

验证显式默认 winsor.tail.p 与相同版本/算法省略该参数结果一致；现代参数路径是否实际使用它须记录，不能以显式传参掩盖算法变化。

| mock | 设计 |
|---|---|
| GEO 芯片 | 合成 Series Matrix，2,000探针×8样本，log2值、样本注释、测试平台；配套 SOFT/annot；内部测试平台禁止触发真实下载 |
| 公司 count | 3,000基因×12样本，负二项 count；Excel说明/raw_counts/TPM，表头第4行、注释列、Ensembl编号 |
| 10x | 稀疏三件套，1,000基因×600细胞，含非Gene Expression特征，各样本目录与样本表；验证不稠密化、不进bulk |
| TPM regular | 8,000基因，control/treated各6；合理均值/方差和右偏分布；双向2倍变化各200，另有预指定4倍强效应 |
| FPKM regular | 同底层过程导出FPKM，验证同runner不同单位标记 |
| 低表达/组成变化 | 零值、开关表达、少数极高表达增加；验证过滤/诊断/组成局限 |
| 已log/不明尺度 | log2(TPM+1)、其他伪计数、中心化、Z-score、无说明；验证不重复转换与通用门禁 |
| 舍入精度 | 完整精度、4/3/2/1/0位小数、直接log按0.1格点、开关表达和复制列；覆盖告警、严重组合与误报 |
| 容器/失败 | 嵌套包、无关文件、损坏包、缺barcodes、错误扩展名、负值、Inf、错物种、混杂设计、count/TPM样本冲突 |

TPM 必须从完整组成/模拟定量过程生成，植入后重归一化。分别保存底层丰度、最终标准化尺度及 log(x+1) 尺度真值；不假定乘2后系数恰好1。测试用合成数据固定种子，不需下载原始实验文件。

方向验收使用预指定中高表达、低中噪声强效应子集，不事后按显著性选择：低噪声固定集方向全部正确；多种子模拟目标方向一致率≥95%并报告不确定性。检出率、经验FDR、空模型校准分别评估，不要求所有植入特征显著、不要求count与TPM结论一致。

敏感性验证阈值0.5/1/2、伪计数0.1/0.5/1、robust开关、深度差异；是开发实验，不按最多显著结果挑默认。通用门禁500特征/50均值/5%退化、舍入组合均需明确正反例与边界测试。

## 13. 路线图与 macOS 技术选择

| 阶段 | 交付与门槛 |
|---|---|
| 0 | PySide6空壳、独立R worker、py2app样包；干净Mac能完成微型DESeq2和robust trend分析，取消不拖垮GUI |
| 1 | 公司表格、配方、向导、单位尺度和count/TPM关联；原文件不变、重放一致、预览无过期响应 |
| 2 | DESeq2/芯片limma/TPM/FPKM、设计、QC门禁、最小结果表和方法说明；独立R基准通过 |
| 3 | GEO/参考/缓存/离线降级；错平台物种不误配，多平台不混合 |
| 4 | 安全压缩展开与10x稀疏导入；危险包拒绝，细胞不进bulk |
| 5 | 四图、中文解读、HTML/xlsx完整报告；NA与空结果正确，离线可打开 |
| 6 | 签名公证app；干净机、中文/空格路径、断网、权限、休眠、取消、只提供TPM场景测试 |

TPM/FPKM 前置阶段2，所需依赖阶段0验证，非后期补丁。每阶段观察真实小白完成任务，不能只检验按钮。

PySide6：成熟表格/拖拽/线程与Python复用；用系统字体、菜单、快捷键和原生文件对话框打磨macOS观感。SwiftUI更原生但增加Python/R边界工作；Electron增加Chromium/Node与Python/R多运行时包装。

rpy2用于成熟R生态，固定ABI和包版本。架构为Qt主线程→QThread worker→独立Python进程主线程→rpy2/R，R串行初始化执行；QThread负责通信等待，避免共享R和崩溃扩散。耗时扫描/预览/网络也放worker。

py2app正式standalone构建，不交付alias样包。正式版内置固定Python/R/核心包/常见离线参考，双击使用不要求安装R；首次安装引导是开发/损坏恢复路径。Apple Silicon优先，Intel独立匹配构建；检查Qt插件、R.framework、BLAS/Fortran和R动态库、子进程入口、签名公证与Gatekeeper；不可假设py2app自动收集所有R依赖。

首次自检：运行时、架构、包实际加载和小型计算、磁盘/缓存；网络可选，不阻断离线。错误为“发生什么+影响+下一步”，堆栈只留诊断日志。

FASTQ/BAM排除判断不变：涉及测序类型、链特异性、参考版本、工具、资源与质量验证，不应隐藏成v1一键。提示“本版本从表达矩阵开始，请索取每个基因在每个样本中的原始count表和分组说明；若只有TPM/FPKM，本软件也可分析并标记方法”。未来前处理独立模块。10x未来增加样本/供者/细胞类型信息和pseudobulk，不把细胞当重复。

## 14. Luna 开发与日志建议

以下为工作安排建议，不是模型额度承诺。按当前可用 gpt-5.6-luna 理解用户所称 luna。

- 默认 medium：按固定规格实现、常规测试与UI服务连接。
- high：阶段开始的接口梳理、R/Qt进程边界、分析正确性、通用门禁、压缩安全和打包难题；问题解决后下一个工作单元回 medium。
- low：明确且机械的文案、资源整理、小范围格式修改。不要为整个大项目持续使用xhigh/max，也不要因工作量大就全部low。
- 一次交付一个可验证的工作单元；先阶段0，勿一次要求全部成品。思考强度通常按任务/轮次设置，不假定代理能自动修改自己的设置。
- 授权自动并行开子代理；优先减少重复扫描、重复基准和巨大工具输出。

日志建议：每20–30分钟有效开发或完成一个可验证单元写一次（先发生者）；统计参数/接口变化、失败原因确认、转向、停止或交接立即写。不每分钟写长日志，不记录逐步私有思考链。

建议文件：docs/development/STATUS.md 保存最新状态；docs/development/DEVELOPMENT_LOG.md 追加事件；docs/development/DECISIONS.md 保存影响架构/方法的决策与理由。日志是开发产物，不写入Codex个人记忆目录。

每条日志包含时间/阶段、具体变更文件、接口或参数决策、验证命令及结果、已知问题、下一步、恢复所需环境/路径。标清“已实现/已验证/未验证”，不以自述替代测试；不写密码、密钥或用户原始数据内容。每条约200–500字即可，保留必要失败信息。

给审查者检查：每60–90分钟或每个阶段验收一次；阶段0、第一份DESeq2/TPM基准、通用门禁实现和正式打包必须检查。若同一问题两次无进展，立即整理失败证据请检查，不反复盲试。日志可先读，关键结论要抽查实际diff、命令结果及产物。

额度管理：每工作单元结束查看实际剩余额度（可用时）；低于20%主动写完整checkpoint，低于10%优先完成交接记录并结束当前边界清楚的单元。这是自定保留策略，不是平台硬阈值。五小时窗口不是五小时连续运行保证；不能从API价格推算Codex订阅额度或承诺某强度节省百分比。

建议交给Luna的第一项任务：“阅读本文，只完成阶段0运行时与打包验证，先输出任务清单再推进；默认medium，关键进程/打包问题建议high；按上述日志规范记录；不要下载实验数据、不要绕过统计门禁。阶段0验证后供审查，再继续下一阶段。”

## 15. 参考资料

- [NCBI GEO2R说明](https://www.ncbi.nlm.nih.gov/geo/info/geo2r.html)
- [limma官方手册：eBayes默认值与版本参数](https://bioconductor.org/packages/release/bioc/manuals/limma/man/limma.pdf)
- [Bioconductor FPKM log转换与limma-trend教学示例](https://bioconductor.org/help/course-materials/2014/BioC2014/Frazee.pdf)
- [voom原始论文](https://pmc.ncbi.nlm.nih.gov/articles/PMC4053721/)
- [TPM/FPKM等路径的项目比较研究](https://pmc.ncbi.nlm.nih.gov/articles/PMC10888899/)
- [tximport官方说明](https://new.bioconductor.org/packages/devel/bioc/vignettes/tximport/inst/doc/tximport.html)
- [10x MEX官方格式](https://www.10xgenomics.com/support/software/cell-ranger/8.0/analysis/cr-outputs-mex-matrices)
- [rpy2低层接口与线程注意事项](https://rpy2.github.io/doc/v3.5.x/html/rinterface.html)
- [Qt线程与QObject](https://doc.qt.io/qtforpython-6/overviews/qtdoc-threads-qobject.html)
- [py2app](https://py2app.readthedocs.io/en/stable/)
- [GPT-5.6 Luna官方模型说明](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
- [Codex计划与额度说明](https://learn.chatgpt.com/docs/pricing)

诊断启发式、日志频率和思考强度安排为本项目建议；以上来源不意味着它们是官方或普遍统计标准。
