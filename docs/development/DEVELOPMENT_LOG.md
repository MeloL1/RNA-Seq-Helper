# 开发日志

## 2026-10-04 · 结果图注复核与隔离候选补丁

再次只读检查当前 GSE10361 项目。XLSX 为单工作表五列，22,283 行与 JSON 按 `NA`/`null` 缺失等价后逐格一致。视觉查看五张输出 PNG 发现 p 值直方图横轴标明原始 p 值，但副标题错误继承 `log2(x+1)` 表达矩阵变换说明。

已从 `PlotService._pvalue_histogram` 删除与 p 值无关的转换标签，补充测试验证副标题只报告有效 p 值数量。定向绘图测试 7 passed；完整测试 `194 passed, 1 skipped（43.61 秒）`。保留原候选 `/private/tmp/rnaseq-helper-result-audit.G1cGvP/RNA-Seq Helper.app`，复制创建并更新独立候选 `/private/tmp/rnaseq-helper-pvalue-fix.9nMdW4/RNA-Seq Helper.app`；工作区与包内 Python 源码一致，内置 R/limma/DESeq2 bundle 自检、limma/DESeq2 微型验证、实际调用包内 PlotService 的图注 smoke test 及严格 ad-hoc 签名通过。

原项目 Excel/HTML/图未改写，旧 p 值图仍含错误副标题，未重跑分析。新候选没有 GUI 实屏验收，安装版未更新。旧项目的 FPKM/LINEAR 输入事实仍缺直接来源证据，因此旧分析不能视作输入事实核验通过。本次没有 MySQL 操作或生物学解释。

## 2026-10-04 · GSE10361 结果复核、来源冲突阻断及隔离候选验证

用户要求只核验软件流程，不作生物学解释。复用实际已保存项目，不重跑用户 GUI/分析。结果 Excel 五列 22,283 行逐格匹配内部 JSON；过滤后 `plot_matrix` 22,275×6，样本次序和 `log2(x+1)` 逐值一致；HTML/五图计数一致。Luna/MAX 代理以 R4.6.0、limma3.68.4独立复算，LFC/p/padj最大误差分别 `5.33e-15/7.77e-15/8.10e-15`。核对发现原项目无直接来源文字却选 FPKM/LINEAR；原文件 `!Series_type=Expression profiling by array`、GPL96，旧 HTML 却称“已确认 FPKM”。当前旧结果保持不动，来源尺度未确认，不作可信结果结论。

最小源码修正：GEO reader 读取 `Series_type`；scanner 结构化保留 array 来源证据；PreparationService 对明确 array 系列阻断 raw count/TPM/FPKM/RPKM/CPM；ExpressionMatrix/AnalysisPlan 传递 `source_modality`，planner 再阻断一次；项目清单/HTML/manifest记录该类别。仅用户手动选择且无直接来源文字时，measurement provenance 显示 `manual_without_direct_text`，方法说明改为“当前选择”，不宣称来源确认。没有声明 array 类型的 GEO 工作流仍正常。五列 XLSX未改。

用只读原始 GSE10361文件真实校验：FPKM/LINEAR触发 `GEO_ARRAY_MEASUREMENT_CONFLICT`；改为 OTHER_NORMALIZED 后整理校验通过，尺度依然UNKNOWN需来源说明确认。随后直接通过新候选自带 Python3.14.7 重复该真实文件门禁，结果一致；未运行差异分析或写项目。旧 XLSX/HTML/JSON摘要分别为 `538a6351…bed0b6`、`b548272d…16a1aa`、`d3982932…081a90d`。新增 `tests/test_geo_array_measurement_gate.py`。定向43 passed；完整回归 **193 passed、1 skipped（41.11秒）**。

从旧HADQ06复制到隔离 `/private/tmp/rnaseq-helper-result-audit.G1cGvP/RNA-Seq Helper.app`，同步6个模块并编译字节码；`diff -qr --exclude=__pycache__` 源包无差异，严格ad-hoc签名通过，`packaging/verify_bundle.py --app` 返回ready=true，bundle内Python/R/limma/statmod/DESeq2可用且两个CLI微型profile通过。清理副本扩展属性遇只读 `liblzma.5.dylib` 权限报错；对新副本重新签名和strict验证成功。候选未打开GUI、未覆盖安装版；旧用户结果与五列Excel不变。MySQL未登记（凭据轮换未确认），Python自动操作崩溃未重新追查。审查文档：`RESULT-AUDIT-2026-10-04.md`。

## 2026-10-04 · 重复说明纠错及用户手动真实GSE验收证据

用户截图证明手动GSE10361扫描候选、结构预览和数值页切换成功；不证明完整整理/分析或崩溃修好，截图附带AX快照也不能当作完全无AX对照。修改ImportPage，把整理页全量重复文本拆为简短摘要/必要问题与独立滚动证据（max180）。原文候选默认展开且只有展开时一键确认可用；未知默认折叠，不自动填单位/尺度。增加content_layout末尾stretch避免空余空间分配给问题页。新增两个UI合同、调整count推荐说明应在证据区域的断言。源码恢复点 `/private/tmp/rnaseq-helper-compact-evidence.E3xjng/import_page.py`。

定向35 passed；稳定后完整176 passed、1 skipped（47.81秒）。两尺寸离屏页面几何检查默认折叠时1024×768预览可见、820×560可以滚动，不当作主窗口实屏证明。复用运行时新隔离副本HADQ06，未覆盖用户正在运行的Hx6JkY PID37964。源码比对/严格签名已通过，ImportPage SHA256 `07e961323e333b9a23452824faefd5b4157cb8f04c13209642e31a0e594a2c2f`；bundle自检ready=true、limma/DESeq2 CLI微型验证通过。统计源码与R worker未改、安装版未改、MySQL未访问。

## 2026-10-04 · 崩溃改用子进程生命周期探针

最新候选PID36715发生可归属的Qt Cocoa/AX SIGSEGV；只读崩溃报告及模块反汇编定位到选中接口isValid虚函数调用，详细证据见 `CRASH-2026-10-04.md`。停止桌面AX操作。子代理Hooke因用量限制失败，无结果。主流程新增 `tests/test_qt_lifecycle_subprocess.py`：辅助功能激活后50轮表格选中/重置/GC、20轮ImportPage DeferredDelete销毁/GC，独立子进程15秒上限，2 passed（1.14秒）。未激活对照的无效缓存不能视作产品复现；原生Cocoa问题仍未复现/修复。没有改产品源码、重跑全量、重打包或更新安装版，最近全量172/1不变。MySQL未访问。

## 2026-10-04 · sidecar 表关联纠错与 172 项回归

静态复核发现 `name_is_linked` 错误查询 sidecar 自身名字。多表 README 自称可能错套 TPM/log2；明确指名 a.tsv 又不能关联。新增两个测试先红测（2 failed），保留修改前 scanner 到 `/private/tmp/rnaseq-helper-sidecar-link-fix.wq9TNr/scanner.py`，再改为 path.name/长 stem 的带边界匹配。四个新增测试覆盖自称、短名、其他文件名子串与句尾句点；这些是文字合同，不是合成生物数据准确率测试。

研判文字证据/确认账本/自动判断/UI 定向 34 passed；全量一次 172 passed、1 skipped（47.35 秒）。复用 Hx6JkY 同一候选，更新 scanner 与 py_compile 字节码，重新 ad-hoc 签名；全包 Python 源码 diff 一致、严格签名通过、verify_bundle ready=true 且 limma/DESeq2 CLI profile 通过。源码/包内 scanner SHA256 均为 `83666d61762e00c5bc420622eb9f1d7dd34b1d0964a3b90cd78a8c61977c521d`；ImportPage 与 R worker 未改。没有重建 runtime、覆盖安装版、重复真实 GSE 基准或访问 MySQL。先前桌面和组件证据属于 scanner 更新前版本，当前 GUI 验收仍缺失。

## 2026-10-04 01:55 CST · GSE10474 受限组件读取证据

没有重复既有 GSE10361 基准。使用主机 `.venv/bin/python` 启动一个 15 秒硬限额子进程，断言 scanner 和 preparation 组件来源均为 Hx6JkY 包内源码，并禁止字节码写入。真实 GSE10474（2,124,974 B）完成扫描、40×35 预览、完整读取/校验，得到 22,277×34、757,418 数值单元格；UNKNOWN_MEASUREMENT/UNKNOWN_SCALE 正确阻断，无矩阵或分析结果输出。原文件前后 SHA256 `3cbf46e72f45f39da53f89c9c49aad0d24e83ea70c60f48135d7cccbc6976ee4` 一致，临时项目空目录自动清理。约 0.1778 秒、RSS 峰值 103.33 MiB，仅报告本次组件诊断，不作吞吐或稳定性推广。

此调用不是 `.app` 可执行文件进程，运行/访问上下文不同，输入也不同；不能代替 GSE10361 GUI 打开问题定位，更不能代替实屏验收。中断前 tccd 查询句柄 26917 已缺失，进程核对无残留，没有重跑该查询或声称它成功完成。产品代码/候选/回归结果不变，安装版未改，MySQL 未访问。证据详见 `CANDIDATE-ACCEPTANCE-2026-10-04.md`。


## 2026-10-04 01:50 CST · 最小 chooser 缓解与候选 Hx6JkY

- Luna/MAX 完成三个 chooser 的非 native 统一配置：文件名输入框无 completer，QFileSystemModel 使用 DontWatchForChanges。只改 `ui/pages/import_page.py`，新增 `tests/test_file_dialog_safety.py`。真实 Qt 输入/Open/Cancel 契约 6 passed（0.48 秒）；主流程稳定后一次全量 **168 passed、1 skipped（46.63 秒）**。
- 基于既有 UtT843 的 bundle，用 ditto 创建 `/private/tmp/rnaseq-helper-chooser-candidate.Hx6JkY/clean/RNA-Seq Helper.app`，更新唯一变更的产品源文件，并 py_compile 其对应字节码，重新 ad-hoc 签名。不重新 py2app 或重新嵌入依赖。全 Python 源码目录 diff 一致；ImportPage 源码/包内 SHA256 `fa8fedb322317102e6a4ff47aac423c8bcc0facbf6d66b9f93aa82e0f76496aa`，worker 未改。清理 xattr 有一条 liblzma permission denied；签名、严格验证、bundle 自检 ready=true 和两个 CLI profile 均通过，GUI 启动后严格签名复验也通过。
- Hx6JkY PID 35379 的同一真实 GSE10361 路径输入组合调用 1.19 秒正常返回，主窗显示文件名及正在检查；未再卡在旧主线程目录补全。然而没有观察到扫描结果。一次一秒 sample 显示主线程正常等事件、后台 Python 文件打开处于 `__open`；工具随后确认 Mac 自动锁屏，未反复解锁/截图。未据此断言 TCC 或文件服务原因，相关 tccd PID 日志查询无条目。核对 PID 后 TERM 结束无结果测试，非正常关窗/协作取消验收。
- 真实 GSE 源摘要仍为 `46f02f0ee04be5ba349d46061ee26c697f8be5b37a04b55a4accf32adce80746`。主流程核对 GSE10361/GSE10474 的矩阵文件分别 1,645,548 B/2,124,974 B，后者处理头 GCRMA 与本地 RMA 重处理脚本必须区分，不能混用说明确认单位或 log 底数。
- 两份 obwEZq/qDAcnT 更早 app 经 lsof 无占用核验后移入废纸篓，约 3.4 GiB，可恢复，未清空；强制递归删除工具拒绝后采用可恢复移除，不宣称释放空间。qDAcnT 的 20,179,066 B 取消 TSV 保留且摘要一致；删除已空旧父目录与四个空微型工作目录。必要 UtT843 故障对照、两个采样和源码快照保留。
- 两位代理已完成并关闭。安装版/桌面入口未改，MySQL 未访问。新候选、逐项待验与最短续接见 `CANDIDATE-ACCEPTANCE-2026-10-04.md`；不要重建或重跑通过的基线。


## 2026-10-04 01:22–01:34 CST · 候选 GUI R 验证与新的路径输入卡顿

本次直接使用现有 `/tmp/rnaseq-helper-r2-release-candidate.UtT843/clean/RNA-Seq Helper.app`，主进程 PID 33700（01:22:21 启动）。没有先重建或重跑全量测试。

- 主流程通过桌面工具进入“工具→环境与验证…”，先后点击 limma 和 DESeq2；分别观察到运行中按钮禁用/取消可用，再观察到“limma 微型验证通过。”“DESeq2 微型验证通过。”和运行按钮恢复。这是当前候选的 GUI 启动及结果回传证据，不再只有 CLI。
- GUI 取消第一次尝试时，任务在点击前已完成，不记作取消通过；第二次把启动、运行状态观察、立即取消放在同一工具调用中，观察到“验证失败：任务已取消”，运行按钮恢复、取消禁用。它只证明微型 R 任务取消信号，不能替代完整整理阶段取消/关闭。
- 截图在本轮对话工具输出中，未保存为项目图片文件；没有按指定双尺寸验收。成功的 GUI 微型输入仅为固定 runtime 验证，不能当作真实生物学数据测试。
- Finder 已定位并选中本地真实 GSE10361。随后只进行一次候选文件选择器键盘路径输入尝试，活动选择器期间没有主动调用 AX 树读取或 `setValue`；该组合调用与一次仅截图观察均返回 `timeoutReached`。不能确认整段输入执行到了哪一步，不计入导入通过。
- Finder 状态仍可正常读取，候选 PID 33700 存在、无独立 R 子进程；对应诊断目录没有本轮新 Python/app `.ips`。对该 PID 做一次 2 秒进程采样，记录到 `/private/tmp/rnaseq-helper-candidate-33700-20261004.sample.txt`。主线程全部 183 个样本停在 `QDialog::exec → QCompleter::eventFilter → QLineEdit::keyPressEvent → QFileSystemModel::fetchMore → QFileInfoGatherer::watchPaths → QFileSystemWatcher::addPaths → QDirIterator → __opendir2 → __open_nocancel`。这是路径补全/目录监视阶段阻塞的具体证据，**没有 AX 崩溃栈**，也不能据此说明所有既往退出都已定位。
- 因该候选停在文件选择器、尚未整理保存用户项目且无 R 任务，核对 PID/path 后向 33700 发送 SIGTERM 结束此次无响应测试进程；未用 SIGKILL、未删除用户数据。它不构成正常 GUI 关窗验收。
- 已分发 Luna/MAX 的最小 chooser 修复（禁用逐字目录补全及目录监视）与独立只读 GSE/清理盘点。新源码测试和新候选未完成前，旧候选仍保留作本次故障证据，不覆盖安装版。
- 当前候选严格 ad-hoc 签名复核成功；README 600 秒和唯一 JobContext 默认值/bridge 计时一致。本次四个 GUI 微型任务的空临时工作目录经 lsof 确认无占用后用 rmdir 清理。无凭据轮换确认，未访问 MySQL。


## 2026-10-03 17:04 CST · AI 审查整改、全量回归与最终候选

根据 Luna/MAX 子代理对首轮文字证据功能的两轮只读审查，修复后再次请求最终窄范围复核并获“通过、未发现新 P1/P2”。代理只做静态审查，没有代跑测试、启动 GUI 或连接数据库；测试和 bundle 验证由主流程执行。

- 隐私与项目记录：若证据句、来源位置或明确标识的路径包含患者/样本/临床身份上下文，则整句短摘录隐藏；证据序列化隐藏来源/位置，`DataAsset`、`PreparationRecipe`、项目 manifest 和参考请求序列化对明确标签的来源路径作脱敏，并留 `*_redacted` 标记。覆盖 `patient001`、`sample 01`、`样本-001`、`标本 02` 等路径形式。无身份标签的自然人姓名无法可靠自动识别；应用仍在本地分析项目保存用户所选的样本列信息，不承诺临床匿名化。
- sidecar 完整性：关联 README/说明/交付 `.md/.txt` 的硬上限为 4 份、256 KiB/份、512 KiB 合计、3000 行、单行 8192 字符。若目录枚举/读取/解码失败或任何上限导致不完整，则整批说明候选不参与单位/尺度共识，发出 `sidecar_scan_incomplete` 并禁用“一键采用”；不再因排序只读取前几份后把部分结果误认成完整证据。完整范围内按事实候选去重但不丢弃后续冲突值。
- 转换与界面：常见英文/中文否定 log2 表述不会作为正证据；同一行或多行出现不同安全公式时保留最多两种作为冲突证据，公式字段使用白名单，任意变量名不被写入 `reported_transform`。摘要优先展示将要采用的候选；证据去重键区分脱敏与非脱敏项；一键按钮只接受已展示、未脱敏的来源证据。对不完整扫描、隐私摘录和冲突给出各自提示。
- 通用 log2 门禁衔接：`PreparationService` 只从明确的逐项用户确认账本生成 `user-confirmed value_scale=LOG2` provenance；规划器同时要求 `matrix.value_scale == LOG2`。未知变换、无确认及评分/残差门禁保持阻断；有效确认的 `OTHER_NORMALIZED + LOG2` 可进入既有 limma profile。
- 定向回归 **35 passed**；最终完整 `.venv/bin/pytest -p no:cacheprovider -q` **162 passed、1 skipped（62.02 秒）**。新测试用于文本识别、边界、隐私和序列化契约，不把合成文字/矩阵用作真实自动研判准确率证据。
- 用本机真实 GSE10361 Series Matrix（1,645,548 B，未写入）只读重扫：`GEO_SERIES_MATRIX`、`UNKNOWN/UNKNOWN`、0 条事实候选；未运行独立 R 分析。
- 打包当前源码到隔离候选 `/tmp/rnaseq-helper-r2-release-candidate.UtT843/clean/RNA-Seq Helper.app`。`verify_bundle.py --app`=`ready=true`，arm64，独立 R 4.6、75 包，limma/DESeq2 两个微型 CLI profile 正常；`codesign --verify --deep --strict` 成功（本机 ad-hoc）。models.py `0ee5003e3f6264f8b5b24f4511754ca328ddbee6c53c5828fd89b75a8a26b75a`、scanner.py `224bec2597403c8d4fd171fa1ef7d1437c89f33d0709beb4c39975f2353490a8`、import_page.py `abb41263d356e7fa615d84c44fb2efce8ce0284000396153e7801ecf7b91f21d`、preparation/service.py `615d788931669873c0a0086cb740ef8cd86a400e38e34821d08680382092cf4f`、planning.py `95ea2895d3cdb783867329485ba111deb60a853d85b4fef7f5ed94d6bbca145d`、background_jobs.py `16d89339d7cd3658f35451460f4913bb0835abd97e319bee0756580987259a62`、`worker.R` `22cd26e83d92d0f7ede7b50839ee98dcc6dca3bdb009956434582ff051e4839e` 的源码/包内摘要逐项一致。
- 最终候选通过 bundle 验证后，删除了前两份过时临时候选、被中止构建的临时目录，以及可再生 `packaging/build`、`packaging/dist`；最终候选保留。安装版和桌面 alias 未改动。无 GUI 截图/AX/鼠标验证，因此普通选文件、拖放、布局、实屏取消/关闭和 GUI R 按钮仍待人工验收；不能用 CLI 自检替代。
- MySQL 元数据没有同步或复核：本轮曾发生凭据意外回显，随后未连接或执行 SQL。先等用户轮换凭据，之后再安全同步，不重读凭据规则文件或复用泄露值。

## 2026-10-03 16:14 CST · 自动研判原文证据与确认记录首版

按 R2 未完成项补上明确文字证据链，不改统计 profile、数值转换、plot matrix/XLSX 契约或 UNKNOWN 门禁：

- `Evidence` 新增 fact key/value、来源位置、短摘录、证据等级、摘录脱敏标记及单独的已报告变换公式。表格证据只检查预览前 8 行、最多 80 列的非数值文本；记录 CSV/TSV 表格记录行列或 Excel 工作表单元格，直接保留原文片段。引用超过长度上限时以省略号标示；患者/样本编号、访问号、路径、邮箱及公式以外的独立数字做隐藏。
- 新增同目录说明文本受限读取：仅 `.md/.txt`、文件名含 README/说明/交付等标记、最多 4 个、单个 256 KiB、总量 512 KiB；不解压、不联网、不跟随符号链接。说明须明确包含当前表文件名，或该目录只有一张表达表；多 sheet 时还须包含所选 sheet 名。关联不明的 sidecar 仅告知“未用于判断”；跨文件/表冲突保留 UNKNOWN。
- 事实页增加“确认并采用文件原文候选”；仅填入唯一无冲突的支持字段，其他字段继续 UNKNOWN。用户逐项状态和引用随 `fact_confirmations` 写入 `preparation-recipe.json` 和 `project.json`。无冲突且用户选择与候选一致时，完整 `log2(...)` 原式可记入 `reported_transform`；公式缺失/冲突时留空，不写成分析使用的 `input_transform`，也不反推伪计数。
- 新增 `tests/test_recognition_text_evidence.py` 与 `tests/test_fact_confirmation_ledger.py`；适配既有自动研判 UI 断言。定向回归 **49 passed**；全量 `.venv/bin/pytest -p no:cacheprovider -q` 为 **146 passed、1 skipped（57.99 秒）**。这组单元用例只核验 parser/账本契约，不代表真实数据分类准确率。
- 使用已在本机且只读的真实 GSE10361 Series Matrix（1,645,548 B）复核：识别为 GEO Series Matrix，单位和尺度均 UNKNOWN、没有事实文字候选；没有独立 R 分析、数据写入或新产物。
- 重新构建 clean 隔离候选 `/tmp/rnaseq-helper-r2-evidence.im2GgT/clean/RNA-Seq Helper.app`（约 1.7 GiB）。`verify_bundle.py --app` 返回 `ready=true` 并执行 limma/DESeq2 微型验证；R 4.6、75 个包；本机 ad-hoc `codesign --verify --deep --strict` 通过。`models.py`、`scanner.py`、`import_page.py`、`preparation/service.py`、`background_jobs.py`、`worker.R` 源码/包内摘要逐一相同。
- 新 clean 候选验真后，删除本轮生成的 `packaging/build`、`packaging/dist` 和已被替代的旧临时候选应用（均未被进程占用，均可从源码重建）；保留新候选。未启动 GUI、未操作屏幕/AX；桌面布局、人工选文件/拖放、GUI 微型验证按钮、实屏取消/关闭均未验证，`/Applications/RNA-Seq Helper.app` 未修改。

**安全事项：**读取 MySQL 连接规则时，本轮用于过滤凭据的命令未覆盖文件中的实际格式，工具结果意外回显了凭据值。之后停止数据库访问；未执行 SQL、未写入/传播该值到项目文件。MySQL 元数据未同步或复核。需要用户先轮换本机凭据，再按连接规则安全同步元数据；本日志不包含凭据本身。

## 2026-10-03 15:34 CST · R2 续接提示词与当前候选状态同步

复核发现 `NEXT-DEVELOPMENT-PROMPT-2026-10-03-R2.md` 的候选路径仍指向被替代的 10/03 临时包，并保留“README 120 秒尚未修复”“先写规格/先跑真实数据”的过期命令。已在提示词顶部新增续接实况，将当前目标改为 `/tmp/rnaseq-helper-r2-final-candidate.PI00wN/clean/RNA-Seq Helper.app`，列出四个源码/候选 SHA256，注明实屏验收仍待人工；把超时说明、短规格/首个低风险迭代、真实输入核验和参考盘点标为已完成，并明确参考联网下载/cache read 仍未实现。

这是交接文档同步，不改产品源码、候选、统计或安装版，不需重跑测试/重建 bundle。下一轮应复用人工验收清单中的当前候选路径，未获实屏输入时按无人值守规则保留待验项并继续其他安全工作。

## 2026-10-03 15:29 CST · R worker 超时边界复核

按 R2 核查默认值、调用覆盖与计时起止：`JobContext.timeout_seconds` 唯一默认值为 600 秒；源码没有调用点传入另一超时值。`RBridgeClient` 在子进程已启动、JSON 请求写入并关闭 stdin 后启动 monotonic 等待计时；在 `communicate(timeout=0.25)` 轮询中检查取消和超时，收到 worker EOF/响应后停止等待，再执行 JSON 解码和 Python 后续处理。因此该数字只描述 R worker 响应等待，不是进程启动、请求准备、结果解码、导入校验、绘图、报告或整个分析流程的硬总时限。

README 现准确说明计时起点与不包含的阶段，保留 600 秒默认，不更改产品行为。此为纯文档修改，不需重跑测试或重建 1.7 GiB 候选；当前候选源码未变化，既有候选与源码摘要核对继续有效。

## 2026-10-03 15:15–15:26 CST · 真实 GEO 导入/取消性能核验与参考闭环审计

按 R2 要求使用本地真实数据，通过当前源码 `ImportPage` 的后台扫描、有限预览、全量读取及验证路径做一次离屏导入核验；没有绕过软件改用独立 R 分析。数据来自 Codex's House 的只读原始目录：`/Users/additionlee/Desktop/Master.nosync/agent/Codex's House/SEALI_ALI/0_Raw/GSE10361_series_matrix.txt.gz`，文件 1,645,548 B（远低于 1 GB），SHA256 `46f02f0ee04be5ba349d46061ee26c697f8be5b37a04b55a4accf32adce80746`。扫描识别为 `GEO_SERIES_MATRIX`，扫描约 0.002 秒，有限预览约 0.0065 秒，展示 40×10；完整读取与逐项验证约 0.0961 秒，得到 22,283 特征、9 个样本。文件内没有足以确认数值单位/变换的明确证据，校验返回 `UNKNOWN_MEASUREMENT` 和 `UNKNOWN_SCALE`，没有把未知表达值猜作 count/TPM，也未写矩阵、项目 manifest 或其他产物。临时项目目录退出时为空，源文件字节保持只读。

取消探针在真实解析/验证进度达 2,000 行后调用 `ImportTaskWorker.request_cancel()`，从请求至 worker 退出约 0.001 秒，本轮取消任务总时长约 0.0041 秒。为观察离屏响应，用 10 ms Qt timer 记录到 6 个心跳，最大事件循环间隔 46.728 ms、P95 15.755 ms。macOS `resource.getrusage(RUSAGE_SELF).ru_maxrss` 峰值为 172,244,992 B（约 164.3 MiB）。这些短小一次性测量受缓存、调度和机器状态影响；仅证明该 1.6 MB 文件在当前离屏路径上能快速预览/验证并迅速协作取消，不能外推为大文件容量上限、实屏流畅度、鼠标取消、跨机器性能或长期稳定性。没有进行完整全量测试套件或重复构建，因为源码和候选包没有改动。

参考资源经独立 Luna/MAX 只读复核，并结合本机元数据核对：用户级 `~/Library/Application Support/RNA-Seq Helper/reference-cache/` 只有一个 335 B JSON，含 checksum/source/species/platform/mapping 字段、2 个 mapping key，但 species/platform 都为 null；未读取映射值或缓存 source 路径。系统 R 有 `AnnotationDbi 1.74.0`、`org.Hs.eg.db 3.23.1`，没有 `org.Mm.eg.db`、`org.Rn.eg.db`；最终候选的内置 R 库共 75 个一级包目录，但不含 `AnnotationDbi`、上述三种 OrgDb 或 GEOquery，因此系统 R 有人类 OrgDb 不能证明候选 bundle 可离线映射。

本地文件盘点仅核对小型表头/文件元数据：`SEALI_ALI/0_Raw/GPL6947_HumanHT-12_V3_0_R1_11283641_A.bgx`（24,023,491 B）及 `GSE32707_RAW/GPL10558_HumanHT-12_V4_0_R1_15002873_B.txt.gz`（13,716,199 B）、`...R2...txt.gz`（13,721,073 B）列名含 `Probe_Id` 与 `Symbol`，符合 GPL reader 的列名契约；没有对其做全量映射。`GSE69063_RAW/GPL19983_hugene21st_Hs_ENTREZG_desc.annot.txt.gz` 为 120,916 B，但其首行是两列数据而非现有 reader 要求的编号/symbol 表头，当前不算可用参考。另有 6,038,451,838 B 的 `GPL13667_family.soft.gz`，本轮仅查看文件元数据，未解压/读取；归档区另有 `GPL13667_annot.tsv`，内容未核验。TCR/BCR contig annotations 不属于 gene-symbol GPL 表。

代码边界：`ReferenceService` 可读用户给的表/GPL，运行时对指定 ID 类型尝试当前 R 环境已安装的 OrgDb，解析后写入用户 cache；无 cache read/hit 路径，无自动下载或完整物种、平台、release 匹配；cache 缺少相应字段时也没有拒绝复用逻辑，写入不是原子替换且无同资源并发锁。GPL reader 对 gzip 文件整包读入内存，尚无压缩/解压尺寸上限。一个未命中读取路径且 species/platform 未填写的 JSON 不构成缓存闭环。

参考闭环是后续独立任务，本轮只记方案、不联网下载、不装注释包、不改缓存/原始数据：

- 芯片探针映射的首选来源是用户明确提供或由**准确 GPL accession**定位的 NCBI GEO 平台记录/SOFT family 文件。NCBI 官方列出按平台 accession 取 SOFT 的路径形式，并说明 GPL 是平台实体；其 SOFT 规范要求平台表 ID 与样本表 ID_REF 对应，需同时核对具体平台和物种，不能仅凭 `ILMN_`/`Probe_Id` 外观猜测。见 [NCBI GEO programmatic access](https://www.ncbi.nlm.nih.gov/geo/info/geo_paccess.html)、[GEO SOFT format](https://www.ncbi.nlm.nih.gov/geo/info/soft.html)。
- Ensembl/Entrez 等基因编号转 SYMBOL 可选 Bioconductor 官方 `org.Hs.eg.db`、`org.Mm.eg.db`、`org.Rn.eg.db`，并固定与内置 R 匹配的 Bioconductor release/package version；从 `AnnotationDbi::keytypes()` 验证输入类型，以 `select()` 查询映射，记录包元数据的 source URL/date。见 [AnnotationDbi 官方手册](https://bioconductor.org/packages/release/bioc/manuals/AnnotationDbi/man/AnnotationDbi.pdf) 及 [AnnotationHub 官方手册](https://bioconductor.org/packages/release/bioc/manuals/AnnotationHub/man/AnnotationHub.pdf)（仅作为将来可选的数据资源目录/缓存方案，不代表项目已依赖它）。
- 每份缓存需绑定 provider/source URL、准确平台 accession（如适用）、NCBI taxid、keytype、release/package version、下载时间、字节数、映射 schema 版本、SHA-256、官方校验值（若该来源提供）、映射覆盖率/歧义/未映射计数。用匹配这些字段的完整缓存键；旧缓存缺关键信息时不复用。先下载到同文件系统的临时位置，检查 HTTPS allowlist、大小上限、gzip/表头/平台/物种与 hash，再原子替换；同资源加锁，取消/损坏不得破坏最后一份有效缓存。
- 读取顺序建议为：用户明确指定的本地参考 → 精确匹配且 hash 有效的缓存 → 当前运行环境已安装且匹配的 OrgDb → 用户触发联网获取并明确确认。离线且无精确缓存、物种/平台不匹配或 checksum/结构校验失败时，说明原因与可执行的“选本地参考/稍后重试”步骤，保留原 feature key，不阻断表达差异分析，也绝不上传表达矩阵。
- 完成标准：覆盖人/鼠/大鼠的允许 ID 类型及 exact GPL、同名不同平台和版本不匹配；验证映射一对多不复制统计行；包含 cache hit、旧/损坏/错物种/错平台、断网、取消、并发、原子替换回滚、超大压缩文件限制；联网记录只传输公共参考包/文件，不发送表达值。仍待产品决策：是否把常见 OrgDb 作为可选随包组件（离线更可靠但会增大 bundle），还是第一次映射时由用户授权下载到 app 私有缓存并保存后续离线可用。

本次没有修改产品源码、统计行为或候选；安装版及隔离候选未更动。实屏 picker/Finder 拖放、事实与列角色页面布局、GUI 微型 R 验证、实屏取消/关闭仍未验证。最新状态见 `STATUS.md` 顶部和 `MANUAL-ACCEPTANCE-2026-10-03.md`。

## 2026-10-03 15:01 CST · 自动研判提示迭代与隔离候选重建

子代理只读审查指出，现有导入提示有候选与 UNKNOWN 门禁，但将依据压成概述，未呈现来源范围，也会一次让新手面对多个未确认事实。按 R2 规格仅修改提示呈现与证据定位：候选、软件线索/核查范围、当前优先确认的一项分开；单位选择后转到尺度问题；尺度选择后显示已选状态。扫描器对正文文字线索记录文件名、工作表（如有）及实际检查范围“前 8 行、最多 80 列”。界面明确说明这是软件核查范围而非原文摘录。没有改变判断规则、未知值门禁、分析 profile、统计输入或图表/XLSX 契约。

README 单次 R worker 超时已按代码默认 600 秒修正；仅限 R 子进程等待，不代表整个导入、绘图和报告流程时限。自动研判及 10x 隔离目录定向回归 **11 passed（0.45 秒）**。首次全量回归的既有 10x UI 用例尝试把 manifest 写进默认 `~/Documents`，当前受限环境不允许该写入；将该测试的项目输出根改为 pytest 临时目录后，单项通过。最终源码状态全量回归 `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider -q` → **141 passed、1 skipped（81.09 秒）**。

最终候选 `/tmp/rnaseq-helper-r2-final-candidate.PI00wN/clean/RNA-Seq Helper.app`，未覆盖旧候选、`/Applications` 安装版或桌面入口。py2app、内置 R 4.6（75 个包、105 项动态依赖重写、90 个组件签名）和 clean-copy 均成功；`codesign --verify --deep --strict` 通过；`verify_bundle.py --app` 返回 `ready=true`，limma/DESeq2 profile 可用。源码与候选完全一致的 SHA256：`import_page.py` `3d465451675cd7742933efe35175405c2b48d6f5c1a93a1a1f14aa9b49f233c1`；`scanner.py` `6466d7d941f20920a94f05519f86123de6e8cec41b92eb93d4006530b9e3f2c6`；`worker.R` `22cd26e83d92d0f7ede7b50839ee98dcc6dca3bdb009956434582ff051e4839e`。`release_check.py --app` 正确报告 `ready_for_formal_release=false`：当前为有效 ad-hoc 签名，缺 Developer ID/公证及干净 Mac 验收；另提示扩展属性警告。

未启动新候选 GUI、未做截图/AX/鼠标验收；用户无人值守时保持实屏项未验证，不循环尝试。候选待人工实屏验收；安装版未更新。自动研判的原文摘录、读取旁侧交付说明、证据确认账本仍未实现。最终 clean bundle 完整验证后，本轮原始 dist（1.7 GiB）和 build 中间产物（65 MiB）已删除；上一版临时 clean 候选因被最终源码取代也已清理，仅保留最终 clean 候选。依 R2 保留仅含本次修改前 `import_page.py` 与 `scanner.py` 的临时源码快照 `/tmp/rnaseq-r2-snapshot.eYZYsQ/`，不含用户数据或凭据。

README 与自动研判规格已新增到 `bioinformatics_overview.result_assets`；既有开发日志/状态记录仅更新文件大小与更新时间，未把表达矩阵、患者数据或凭据写入数据库。

## 2026-10-03 13:50 CST · 新候选 GUI 启动冒烟

因桌面无人值守，不执行截图/AX/鼠标验收；但为确认新 clean bundle 能初始化，使用 `open -g -n "/tmp/rnaseq-helper-candidate-20261003-obwEZq/clean/RNA-Seq Helper.app"` 启动一次。命令退出码 0；PID 5720 于 13:50:59 CST 运行 40 秒、13:52:56 运行 2:37、13:54:57 运行 4:38，执行路径为新候选，`lsof` 显示其从该包加载 Python/Qt 与资源文件。修复前旧候选 PID 1256 也仍在运行，因此本轮不执行操作输入，避免把两个同名实例混淆。证据仅覆盖启动与初始资源加载，不证明窗口可读、可操作、完整导入、布局、取消/关闭或长期稳定性。

## 2026-10-03 13:18 CST · 关闭守卫生命周期修复与新候选重建

把“真实导入后台验证期间关闭宿主窗口”集成到回归后，发现旧关闭守卫即使让所有测试断言通过，Qt 仍在父窗体销毁阶段报告 Python `eventFilter` 属性错误及 slot 错误。原因是为单窗口安装的 `BackgroundJobCloseGuard` 同时注册为 `QApplication` 和窗口事件过滤器；安全 Close/Quit 完成后未主动注销，过滤器可能越过自己的窗口生命周期。现于无活动任务放行 Close/Quit 时移除两处过滤器；任务结束后重放窗口关闭或应用退出前也注销应用级过滤器。移除了会在 PySide 清理对象属性后才触发的 `destroyed` Python 回调。

新增的真实 ImportPage 关窗测试确认：`PreparationService.validate()` 在真实 `QThread` 中已完成至少 128 行检查，宿主窗体收到 Close 后先保持可见并请求取消；释放测试同步点后验证线程先退出、窗口随后关闭，未交付矩阵、未产生整理项目、输入 SHA256 不变。修复后定向组（新取消、新关窗、既有 Close 与应用 Quit）**4 passed**，Qt 输出无事件过滤器异常。最新全量回归 `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider -q` → **141 passed、1 skipped（39.28 秒）**。新测试为受控离屏集成，不取代人工桌面取消/关闭。

因产品源码变动，将修复打入新隔离候选 `/tmp/rnaseq-helper-candidate-20261003-obwEZq/clean/RNA-Seq Helper.app`，未覆盖先前候选或 `/Applications`。构建命令使用 py2app `--dist-dir`/`--bdist-base` 指向该独立临时根目录：py2app 退出码 0，但原始包含已知 `liblzma` 严格签名警告；`embed_r_runtime.py` 退出码 0（R 4.6、75 个包、105 项 Mach-O 路径重写、90 个组件签名）；`prepare_clean_bundle.py` 退出码 0；clean 包 `codesign --verify --deep --strict` 通过；`verify_bundle.py --app` 退出码 0、`ready=true`，含 arm64/Python 3.14.7/PySide6 6.10.3/Qt 6.10.3、R.framework、limma/DESeq2/jsonlite/statmod 及两个微型 profile。源码与包内 `background_jobs.py` SHA256 均为 `16d89339d7cd3658f35451460f4913bb0835abd97e319bee0756580987259a62`；源码与包内 `worker.R` 均为 `22cd26e83d92d0f7ede7b50839ee98dcc6dca3bdb009956434582ff051e4839e`。

新候选 `release_check.py --app` 退出码 1，`ready_for_formal_release=false`：签名为有效 ad-hoc，但缺 Developer ID/公证/干净 Mac 验收，并报告扩展属性警告。新候选 GUI 未启动；旧 PID 1256 于 13:17:28 仍运行且路径指向修复前的 `/tmp/rnaseq-helper-candidate.qDAcnT/`，不作为新包启动证据。`/Applications/RNA-Seq Helper.app` 修改时间仍是 2026-09-22 23:56:47 CST，严格签名校验通过且未修改。新构建的原始 `dist/` 与 `build/` 中间产物已移入废纸篓，可恢复；新 clean 候选保留。未进行截图、AX 或实屏输入。

同步修正 `README.md` 中过期的 v25/“当前源码尚未重打包”说明，现指向新候选及人工验收清单，并明确旧安装版与正式发行的边界。

## 2026-10-03 13:04 CST · 真实整理服务取消集成回归

检查发现既有 `test_import_page_keeps_cancel_available_during_validation` 将整个 `PreparationService.validate()` 替换为测试等待循环；直接服务测试虽覆盖取消回调，但 UI 与真实整理循环此前未由同一用例贯通。新增 `test_import_page_cancels_real_validation_in_background`：在 pytest 临时目录生成 80,000 行取消专用表，正常经 `ImportPage` 扫描、预览和确认 raw count/linear，由真实后台 `QThread` 完成全量读取并执行真实 `PreparationService.validate()`；测试同步点设在真实验证已报告 128 行后，通过整理页取消按钮发出请求。断言线程结束、没有 `matrixReady`、没有整理项目结果、原始文件 SHA256 前后一致。此小型合成表只测协作取消路径，不评价自动研判、差异分析或生物学结果；也不替代 500,000×6 的人工取消/关窗实屏步骤。

定向回归 `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider -q tests/test_preparation_cancellation.py::test_import_page_cancels_real_validation_in_background` → **1 passed（0.71 秒）**。随后唯一一次完整回归 `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider -q` → **140 passed、1 skipped（40.81 秒）**。改动仅在测试，不含产品源码；未启动新 GUI、未截图或操作 AX，候选包和安装版均未改变。真实 Finder 拖放、人工选文件、布局、实屏取消/关闭仍待验收。

## 2026-10-03 13:00 CST · 候选包状态复核

13:00 CST 复核当前源码环境为 Python 3.14.7、PySide6/Qt 6.10.3；只读 fixture `tests/fixtures/company_counts.tsv` SHA256 仍为 `4d363bea15f4e742dee076182668ca7e1d69613eb649a95b05eb5c8e6dbce41f`。隔离候选 `codesign --verify --deep --strict` 成功，`packaging/verify_bundle.py --app ...` 退出码 0 并返回 `ready=true`，确认 arm64、内置 R.framework/Rscript、jsonlite/limma/statmod/DESeq2 与 limma/DESeq2 微型 profile 可用；源码及候选 `worker.R` SHA256 均为 `22cd26e83d92d0f7ede7b50839ee98dcc6dca3bdb009956434582ff051e4839e`。同一候选 GUI PID 1256 于 13:00:32 仍存活 10:53，状态为睡眠等待。未进行截图、AX、鼠标操作或测试套件重跑；本次复核不增加人工桌面验收证据。

## 2026-10-03 12:56 CST · 候选进程只读续查

12:56:48 CST 只读检查显示隔离候选 GUI PID 1256 仍存活，启动后约 7 分 09 秒；进程可执行文件仍位于 `/tmp/rnaseq-helper-candidate.qDAcnT/clean/RNA-Seq Helper.app`。仅在用户 DiagnosticReports 目录按 `Python-*.ips` 和 12:49:30 之后的修改时间做定向查找，没有匹配报告。该证据只说明候选进程在空闲条件下持续存活、该目录未出现对应的新 Python 崩溃报告；不证明窗口可交互、导入成功、布局正确或稳定性修复。没有截图、AX 查询、鼠标输入、代码修改或测试重跑。

## 2026-10-03 12:49 CST · 隔离候选 GUI 启动基线

确认本机当前没有活动 RNA-Seq Helper 进程后，以 `open -g -n "/tmp/rnaseq-helper-candidate.qDAcnT/clean/RNA-Seq Helper.app"` 后台启动 clean 候选，未抢前台。PID 1256 于 12:49:39 CST 启动；12:50:42 只读复查时仍存活 1:03，执行文件路径位于该 clean 候选；`lsof` 显示 Python.framework 与多个打包二进制从候选路径加载。12:49:30 后未见新 Python `.ips`。没有窗口 AX 查询、截图或鼠标输入。此证据只支持“候选 GUI 启动成功且短时仍存活”，不能证明导入、Cocoa picker、布局、长时稳定性或取消/关闭通过。当前源码 GUI 没有新启动。

## 2026-10-03 12:48 CST · 准备取消/关闭负载文件

为后续人工实屏观察取消和关闭时的协作线程退出，临时生成 `/tmp/rnaseq-helper-candidate.qDAcnT/cancel-screen-test-only.tsv`：500,000 个合成特征×6 个整数样本列，20,179,066 B，SHA256 `6dafd7a24d5b6ccd8d7bfd1f1464ed7c6735766b468855f537febac02dd1aec9`。它只用于让后台读取/校验持续足够长，未用于自动研判评估、差异分析或生物解释；不放入源码目录或 MySQL。4×6 的 `company_counts.tsv` 仍只用于导入/交接契约，不用来冒充取消负载测试。

本轮未在缺少人工桌面操作时点取消/关窗，也没有声称这项通过。后续按 `MANUAL-ACCEPTANCE-2026-10-03.md` 两轮分别验证取消按钮和关闭窗口，等待任务/线程自然退出，不强杀。

## 2026-10-03 12:45 CST · 安装版与候选版只读对照

续接后重新确认候选与已安装状态：隔离 clean 候选仍在 `/tmp/rnaseq-helper-candidate.qDAcnT/clean/RNA-Seq Helper.app`，`codesign --verify --deep --strict` 再次通过；候选 bundle 没有被清理。`/Applications/RNA-Seq Helper.app` 也仍存在，目录修改时间为 2026-09-22，内置 PySide6/QtCore 均为 6.11.2；候选内是 6.10.3。两包均含 `Contents/Frameworks/R.framework`，worker SHA256 均为 `22cd26e83d92d0f7ede7b50839ee98dcc6dca3bdb009956434582ff051e4839e`。安装版严格签名校验通过，但这不表示其代码等于当前源码或候选。

只读查找未发现 `/Users/additionlee/Desktop/RNA-Seq Helper（双击启动）.app` 桌面 alias，也未发现 `/Users/additionlee/Applications/RNA-Seq Helper.app`。未创建替代入口、未覆盖 `/Applications` 包；此动作继续受候选人工实屏验收门槛约束。未进行截图、AX 查询或用户鼠标操作。

## 2026-10-03 · 拖拽契约、Cocoa chooser 定位与隔离候选包

开始续接时读取 10/03 提示词、README、STATUS、导入向导设计以及 10/03/9/25 日志。当前源码环境 Python 3.14.7、PySide6 6.10.3、Qt 6.10.3；只读输入 `tests/fixtures/company_counts.tsv` 为 291 B，SHA256 `4d363bea15f4e742dee076182668ca7e1d69613eb649a95b05eb5c8e6dbce41f`。本轮未启动常驻的正常源码主 GUI，也未操作桌面/AX；因此当前源码主窗口、窗口尺寸、人工 picker/拖放、候选 GUI 均仍待实屏验收。

一个 Luna、中推理代理只新增 `tests/test_import_drag_drop.py`，未改产品源码或既有文件。测试通过 Qt `QDragEnterEvent/QDropEvent` 把本地 URL 真正送入 `ImportPage` 的事件处理器；覆盖单文件加目录的混合候选、混入非本地 URL、纯非本地 URL 被忽略、未知数值事实阻断、人工确认 RAW_COUNT/LINEAR 后完整读取/校验/保存，以及现有 `AnalysisPage` 收到恰好一次形状 4×6 的 `ExpressionMatrix`。测试使用 SHA256 和字节比对证明仓库 fixture 未改写，并标明事件自动化不等于 Finder 人工拖拽。子代理定向组报告 39 passed；主线复核新文件 2 passed；之后本轮唯一一次完整回归 `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider -q` 为 **139 passed、1 skipped**（40.36 秒）。

Cocoa chooser 在隔离进程进行有限定位。先运行旧端到端用例 `QT_QPA_PLATFORM=cocoa PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider -q tests/test_import_ui_state.py::test_file_picker_path_completes_import_and_updates_group_page`，13.69 秒后以 pytest 退出码 1 失败，位置为候选扫描完成断言；该用例只检查对话框选项，`selectFile()` 后立即 `accept()`，没有验证 `selectedFiles()` 或 `exec()` 返回 Accepted。约 02:11 CST 的独立诊断 Python PID 90868（shell PID 90866）确认 `ImportPage` 可见、对话框可见且 parent 正是该页、`DontUseNativeDialog=True`、`ExistingFiles=True`、fixture 路径可读；执行 `selectFile(绝对路径)` 后立即及 2.5 秒有限轮询中 `selectedFiles()` 均为空，遂拒绝对话框，没有扫描、没有发出成功信号，fixture 字节未变。该结果定位到自动化选择步骤，不证明普通鼠标选择失败。

随后仅做一次不同的目录切换选择探针；诊断脚本在对话框退出后误将 `ImportPage.choose_file()` 的 `None` 返回值转成整数，约 02:12:39 抛出普通 `TypeError`，没有输出该次所选文件状态。它是探针代码错误，不是应用 SIGSEGV；遵守“每个假设最多两次”后不再尝试 Cocoa 自动选择，也没有更改产品 chooser。对应时段（02:08 后）诊断目录未见新 `Python-*.ips`，本轮未做整批历史报告或统一日志扫描。一般“Python 意外退出”仍未归属；9/25 PID 12456/Qt 6.10.3 的 AXCopyHierarchy→NSAccessibility/libqcocoa SIGSEGV 是已证实的特定 AX 触发案例，不归因于普通点击或所有历史通知。此前应用 Quit / QThread 守卫回归纳入本次全量通过，但不覆盖 SIGSEGV。

候选构建输出独立放在 `/tmp/rnaseq-helper-candidate.qDAcnT/`，没有使用或覆盖项目 `packaging/dist/`、`/Applications/RNA-Seq Helper.app`、用户 Applications 包或桌面入口。py2app 命令退出码 0；未经清理的原始 bundle 首次严格签名检查失败，日志含 liblzma 与资源封印提示。使用既有 `packaging/prepare_clean_bundle.py` 从原包生成独立 clean 候选后，该工具内置及再次执行的 `codesign --verify --deep --strict` 均退出码 0。clean 候选路径 `/tmp/rnaseq-helper-candidate.qDAcnT/clean/RNA-Seq Helper.app`，约 1.7 GiB。其 `packaging/verify_bundle.py --app ...` 退出码 0、`ready=true`，arm64、Python 3.14.7、PySide6 6.10.3（bundle `PySide6/__init__.py` 元数据）、QtCore 当前版本 6.10.3（bundle extension 的 Mach-O 依赖）、内置 R 4.6.0 与 jsonlite/limma/statmod/DESeq2 均核验；两种 R 微型分析分别返回 `LIMMA_ON_LOG_EXPRESSION` 和 `DESEQ2`。`worker.R` 与源码 SHA256 均为 `22cd26e83d92d0f7ede7b50839ee98dcc6dca3bdb009956434582ff051e4839e`。这只是构建、本机自检、ad-hoc 签名和 R 子进程验证，不等同启动 GUI、人工实屏导入、Developer ID/公证或干净 Mac 验收。

本轮结论属于 **② 候选构建通过、待人工验收**。未更新安装版。详细人工步骤见 `MANUAL-ACCEPTANCE-2026-10-03.md`；未验证项见 `STATUS.md` 顶部验收表。

## 2026-10-03 01:44–01:59 无人值守续查 Python 异常退出（历史快照）

本节记录的是当时的状态快照；12:49 之后的拖拽回归、候选构建及 GUI 启动进度，以本日志较新的条目和 `STATUS.md` 顶部为准。

按用户要求在其不值守电脑时继续可离线完成的检查，不以截图/等待解锁作为继续条件；没有对目标 Qt 窗口读取辅助功能树，也没有改系统权限。开始时间约 01:44 CST。源码 GUI 命令 `.venv/bin/python -m rnaseq_helper.app`，PID 87742 于 01:47:04 启动，执行文件 `/opt/homebrew/Cellar/python@3.14/3.14.7/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python`，Python 3.14.7、PySide6/Qt 6.10.3。只读测试输入 `/Users/additionlee/Desktop/Master.nosync/agent/RNA-Seq Helper/tests/fixtures/company_counts.tsv`，SHA256 `4d363bea15f4e742dee076182668ca7e1d69613eb649a95b05eb5c8e6dbce41f`；屏幕物理分辨率 3024×1964，未测窗口尺寸。Codex Computer Use 只读应用清单，没有对 RNA-Seq Helper 做截图、控件操作或 AX 扫描。

在 01:48–01:59 复核时 PID 87742 仍存活（约 12 分），且启动后没有发现新 `.ips`。只读并行检查覆盖用户目录与系统级 DiagnosticReports、对应时段统一日志；没有可归属的新报告/事件，也没有项目自身日志。故本轮不能分类为 `AX/libqcocoa/SIGSEGV` 或 `QThread/SIGABRT`，更不能声称已修复；只记录源码进程在空闲观察条件下未复现。

为不调用 AX 或依赖截图，另以 `QT_QPA_PLATFORM=cocoa` 运行现有 chooser 端到端测试一次成功（`1 passed in 0.76s`）：可见 `ImportPage` 上的 Qt 非原生文件选择器由测试定时选择仓库 fixture，随后扫描、单位/尺度门禁、整理保存，并由现有 `AnalysisPage` 接收一次 `matrixReady(ExpressionMatrix)`。这证明一次 Cocoa Qt 运行的自动化流程通过，不是人工鼠标验收或视觉布局截图。后续同平台短测在文件选择阶段未能稳定选中 fixture；具体原因未明，期间没有新崩溃报告。离屏稳定回归保留原测试方式，没有把不稳定的 Cocoa 选择时序留在测试夹具里。实屏拖拽、截图、窄窗和受控崩溃对照仍未完成。

定向命令 `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider -q tests/test_app_shutdown_contract.py tests/test_import_ui_state.py tests/test_background_job_close.py` → **16 passed（最终复核 0.76 秒）**。全量命令 `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider -q` → **137 passed、1 skipped（最终复核 41.77 秒）**。整条离屏导入测试用只读 fixture 证明未知单位/尺度会阻断、明确确认后完成读取/验证/保存，`matrixReady(ExpressionMatrix)` 恰好一次到达现有 `AnalysisPage`；这与上面一次 Cocoa 自动化通过均不能替代人工实屏/布局验收。关闭守卫的只读复核表明其可处理窗口 Close / 应用 Quit 时的合作式线程取消和等待，不覆盖 SIGSEGV、强制终止或所有 Python 崩溃。

本轮没有改代码、构建候选或替换安装版。用户上次看到的“Python 意外退出”仍无本轮可归属诊断报告；下次若再出现，需记录准确时间并保留对应 PID 与新生成的 `.ips`，才能区别 Qt Cocoa/AX 与 QThread 退出问题。此前“运行 R 微型验证”停在 R worker 是独立的 R 子进程现象，不能当作这次 GUI Python 崩溃证据。当前仍 **不能打包**；源码实屏 `matrixReady`、窄窗、关闭/取消以及候选包门槛未完成。

## 2026-09-25 · 非原生文件选择器离屏回归与锁屏基线

按当前目标重新读取 README、STATUS、9/24–9/25 开发日志、导入向导设计、完整 `import_page.py` 和 `test_import_ui_state.py`。02:02 CST 基线：命令 `.venv/bin/python -m rnaseq_helper.app`；PID 13908，自 01:05:54 运行，执行文件 `/opt/homebrew/Cellar/python@3.14/3.14.7/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python`；Python/PySide6/Qt 为 3.14.7/6.10.3/6.10.3。测试输入 `/Users/additionlee/Desktop/Master.nosync/agent/RNA-Seq Helper/tests/fixtures/company_counts.tsv`，291 B，SHA256 `4d363bea15f4e742dee076182668ca7e1d69613eb649a95b05eb5c8e6dbce41f`，测试比较前后字节相同。Codex Computer Use 仅调用一次 `getState`，返回 Mac 已锁定；没有触发控件、截图或 AX。`system_profiler SPDisplaysDataType` 读到当前内屏物理尺寸 3024×1964；锁屏时没有取得当前应用逻辑几何。本轮没有读取历史 crash 日志，只按 PID 启动时间列查启动后新生成的 `.ips`：截至 02:11 没有匹配项；PID 仍存活 65:07，然而它加载的是本轮修改前代码，不能作为修复验收。

因真实 QFileDialog 屏幕路径仍待解锁，新增离屏回归 `test_file_picker_path_completes_import_and_updates_group_page`：通过 `choose_file()` 打开当前非原生 QFileDialog，核验 ExistingFiles/DontUseNativeDialog，选择仓库的只读 `company_counts.tsv`；随后走候选扫描、未知单位/尺度阻断、显式确认 raw count/linear、完整后台读取/验证/保存。测试把 `matrixReady` 接到现有 `AnalysisPage.set_matrix`，确认只发一次、载荷为 `ExpressionMatrix`、尺寸 4×6，现有分组页生成 6 个样本行，源文件字节前后一致。该端到端 Qt 回归仅是离屏证据，不能标为实屏 picker/拖拽或桌面验收，也不能覆盖 AX/Cocoa 崩溃。端到端用例连续额外复跑 5 次均 **1 passed**；定向 `test_import_ui_state.py` + Quit/关闭测试组 **16 passed**；最终全量命令 `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider -q` **137 passed、1 skipped**。

本轮没有尝试屏幕操作或等待解锁；没有构建候选包、替换 `/Applications/RNA-Seq Helper.app` 或改桌面入口。Picker 实屏点击、拖拽主流程、事实确认和成功交接的本轮截图、列角色修复实屏和窄窗、关闭/取消桌面复现、AX/SIGSEGV 归属及候选 bundle 验收均仍未完成，因此发布闸门维持关闭。

## 2026-09-25 · 应用级 Quit 请求等待后台线程结束

复核主窗口接线后发现 `BackgroundJobCloseGuard` 只安装在主窗口上，仅拦截 `QEvent.Close`；用户经菜单或快捷键调用 `QApplication.quit()` 时，Qt 另发应用级 `QEvent.Quit`。根据 Qt 官方 [`QCoreApplication::quit`](https://doc.qt.io/qt-6/qcoreapplication.html#quit) 说明，应用可处理该事件以中断退出。此前这条路径未受守卫，线程仍运行时存在直接退出事件循环并析构活动 `QThread` 的风险。

`src/rnaseq_helper/ui/background_jobs.py` 现在让同一守卫也监听 `QCoreApplication`。若 Quit 到来时仍有活动线程，忽略该请求、调用既有协作取消回调，并在所有线程结束后重新投递 `QCoreApplication.quit`；普通窗口关闭仍在线程结束后调用 `window.close()`。该逻辑仅处置线程生命周期，不处理 `AXCopyHierarchy`/Cocoa accessibility `SIGSEGV`。

Luna 子代理新增 `tests/test_app_shutdown_contract.py`，以真实 `QThread`、受界限的 `QApplication.exec()` 验证应用退出。主线强化测试：设置 `quitOnLastWindowClosed(False)` 并要求迅速退出，从而证明守卫会恢复显式 Quit 请求，而非依赖关闭末窗口的默认行为。命令 `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider -q tests/test_app_shutdown_contract.py tests/test_background_job_close.py` 为 **3 passed**；新应用退出测试单测再连续运行 5 次，均 **1 passed**。全量命令 `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider -q` 为 **136 passed、1 skipped**。另以短时 Qt 事件循环验证守卫在线程退出后正常放行退出请求。

本轮再次只读检查正常源码进程 PID 13908：仍运行，命令 `.venv/bin/python -m rnaseq_helper.app`，启动时间 01:05:54 CST，Python 3.14.7/PySide6/Qt 6.10.3；该实例早于本轮代码修改，不能作为新代码桌面验证。02:00 CST 时该 PID 已运行 54 分 37 秒，仍存活；没有发现其启动后新生成的 Python `.ips`。锁屏后没有截图或鼠标/AX操作，也没有声称屏幕验收通过。未打包或替换安装版；应用级 Quit/关闭回归已离屏覆盖，但正常 Finder 用户关闭、导入取消、实屏窄窗与布局、Picker/拖拽，以及 AX 崩溃是否复现仍未闭环。

## 2026-09-25 · 列角色页紧凑布局修正与锁屏续验

重新核对 README、STATUS、9/24–9/25 开发日志、导入向导设计、当前 `import_page.py` 与 `test_import_ui_state.py`。续验开始于 01:37 CST：正常源码 GUI PID 13908 自 01:05:54 运行，命令 `.venv/bin/python -m rnaseq_helper.app`，可执行文件 `/opt/homebrew/Cellar/python@3.14/3.14.7/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python`，Python 3.14.7、PySide6/Qt 6.10.3；输入为只读 `tests/fixtures/company_counts.tsv`（291 B，SHA256 `4d363bea15f4e742dee076182668ca7e1d69613eb649a95b05eb5c8e6dbce41f`）。屏幕 3024×1964 物理像素/1512×982 逻辑点，源码窗口内容 1024×768、外框 1024×800。此轮未使用 Codex Computer Use 或 Accessibility/AX；一次低层 Quartz 鼠标事件执行前发现 `loginwindow` 已在前台、PID 13908 非 active，事件未送达应用，故未测试文件选择器且未重试。进程仍存活；截至 01:50 未发现其启动后新的 Python `.ips`。

Luna 子代理按列角色页实屏截图 `source-columns-page-1024x800-2026-09-25.png` 修正已发现的提示与表格挤压：换行标签改用自然最小高度，列角色/预览内容放入可纵横滚动区，页脚保留在外层。新增离屏几何用例覆盖 1024×768、820×560 下提示不重叠、列角色表有滚动范围、主按钮可见。主线补充导入契约断言：`matrixReady` 恰好发射一次，载荷为 `ExpressionMatrix`。代理定向回归 12 passed；本轮主线 `.venv/bin/pytest -p no:cacheprovider -q` 实际结果 **135 passed、1 skipped**，类型/次数定向用例 1 passed。只改当前导入布局及其测试；无 R worker、统计方法、阈值或结果字段修改。

复核发现 `loginwindow` 前台后停止真实桌面操作；未伪称文件选择器或拖拽通过。既有 1024×768 实屏成功分组页仍证明此前该条件的整理交接；但新布局没有实屏复验，820×560 仅有离屏布局回归，运行中关闭/取消仍缺实际桌面路径。尝试的隔离 Qt/QThread 事件循环探针没有在预期时间返回，测试子进程经 SIGTERM 结束；它不是应用 UI/worker 实际复现，无新崩溃报告，不作为产品崩溃证据。无 AX 普通导入的 PID 13908 此前走到分组页且本轮仍存活，但不据此宣称通用崩溃已解决。没有新建候选包或替换 `/Applications` 安装版；文件选择器普通点击、实际拖拽、修复后实屏窄窗、运行中关闭/取消和候选包验收仍是明确门槛。

## 2026-09-25 · 源码窗口文件选择器与本轮 Python 崩溃归属

本轮实屏基线（2026-09-25，CST）：源码运行命令为 `.venv/bin/python -c 'from pathlib import Path; from functools import partial; import rnaseq_helper.ui.pages as p; p.ImportPage=partial(p.ImportPage,project_root=Path("/tmp/rnaseq-helper-gui-test.H7kySY")); import rnaseq_helper.app as a; raise SystemExit(a._gui())'`；进程 PID 12456，Homebrew Python 3.14.7，可执行文件为 `/opt/homebrew/Cellar/python@3.14/3.14.7/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python`，PySide6/Qt 均为 6.10.3。测试输入计划为只读仓库 fixture `tests/fixtures/company_counts.tsv`（SHA256 `4d363bea15f4e742dee076182668ca7e1d69613eb649a95b05eb5c8e6dbce41f`）；崩溃发生前尚未选择或读取该文件。内置 Retina 屏为 3024×1964 物理像素；Qt 窗口内容几何为 1024×768，macOS 窗口框（含标题栏）为 1024×800。初始空状态窗口截图为 `docs/development/evidence/source-empty-window-1024x800-2026-09-25.png`。本轮使用了 Codex Computer Use；最初目标 Python 窗口不在前台（前台为 ChatGPT PID 79228），因此此前点击不能算作应用按钮收到。将 Python 窗口置前后，真实 `QFileDialog` 成功打开。

随后对 QFileDialog 文件名控件执行 Computer Use 辅助功能输入并请求更新状态，目标 Python 进程在 2026-09-25 01:02:51 CST 退出。新报告 [`Python-2026-09-25-010251.ips`](/Users/additionlee/Library/Logs/DiagnosticReports/Python-2026-09-25-010251.ips) 中 PID=12456、父进程 `codex` PID 79269、责任进程 `ChatGPT` PID 79228；异常为 `EXC_BAD_ACCESS / SIGSEGV`。faulting thread 0 的栈包含 `NSAccessibilityAttributeAccessorInfo`、`AXCopyHierarchy`、`_AXXMIGCopyHierarchy`；报告确认进程加载 PySide 6.10 与 `libqcocoa.dylib`。本次可归属的触发条件是对活动 Qt 文件选择器进行 macOS Accessibility/AX 树查询及值操作；具体是 `setValue` 还是随后的状态刷新先触发失效无法由该次工具返回区分。该进程没有读取输入、没有启动导入 worker，也没有 `QThread::~QThread/SIGABRT` 证据。此结果证明 Qt/PySide 6.10.3 在这次 AX 交互下仍会崩溃，不能视为版本回退修复；也不能外推为普通鼠标/键盘使用必崩或解释所有历史弹窗。后续对本应用停止 AX 树交互，只保留像素截图与用户实际桌面输入；不更改系统辅助功能权限。

文件选择器本身已由前台 Qt AX 状态观察证实打开，尚未选文件；还没有 picker 窗口级 PNG。正式导入、事实门禁、列角色、`matrixReady` 到分组页、窄窗及关闭/取消均未验证。源码进程使用了临时项目根注入，仅能作为空状态/picker 探针，不能作为成功整理验收；完整路径应从无注入的 `.venv/bin/python -m rnaseq_helper.app` 重新开始。上一轮 **134 passed、1 skipped** 仍只是历史基线，本轮未重跑测试、未修改运行时代码、未打包或替换安装版。

重新以无测试注入的命令 `.venv/bin/python -m rnaseq_helper.app` 启动当前源码，PID 13908，启动时间 2026-09-25 01:05:54 CST；Qt 内容尺寸 1024×768、macOS 窗框 1024×800，初始空态截图 `docs/development/evidence/source-clean-launch-empty-1024x800-2026-09-25.png`。随后通过普通鼠标事件完成只读 291 B fixture `tests/fixtures/company_counts.tsv` 的候选选择、结构检查、数值事实确认、列角色确认及后台全量读取/校验/保存，进入分组页；全过程未查询 AX 树。事实未知门禁、确认 raw count/linear 的截图分别为 `source-facts-page-unknown-1024x800-2026-09-25.png`、`source-facts-confirmed-raw-linear-1024x800-2026-09-25.png`；列角色页截图 `source-columns-page-1024x800-2026-09-25.png` 显示说明文字被表格挤压/遮挡；结果分组页截图 `source-import-after-confirm-1024x800-2026-09-25.png` 显示矩阵 4 特征×6 样本，control 3、test 3、排除 0。项目 `~/Documents/RNA-Seq Helper Projects/company_counts-817d2e29/` 中的 manifest 标记 validation passed，24 个数值单元；准备矩阵、特征元数据、样本元数据及配方文件均已生成。源文件 SHA256 前后一致。将完整导入契约测试加强为 `len(matrixReady emissions) == 1`；定向测试通过，完整源码回归 **134 passed、1 skipped**。PID 13908 在本次检查期间仍运行；未发现该启动后新生成的 Python `.ips` 报告。这只说明本次无 AX 的鼠标导入链路没有复现崩溃，不能证明所有崩溃已修复，也不能归属先前无法匹配进程的通知。代码最小内容尺寸为 820×560，但系统级窗口拖动未成功，窄窗实屏仍未验收。未运行 R/差异分析、未触碰正式安装包。

## 2026-09-25 · 导入安全修复验收与 Python 崩溃再归因

完成并复核三个入口可靠性修正：扫描进度不再在文件数停留于 25 后对每个空目录重复发信号；列头明确为 `length/start/end/GC` 等的数值注释不会自动成为表达样本，界面解释排除原因、展开可编辑列角色且允许用户覆盖；扫描结果即使同时含可用候选与失效路径，也会显示错误路径与恢复说明，不丢弃可用候选。子代理负责的两个文件与测试经人工检查；扫描器由主线独立修改。新增回归纳入现有用例，最终完整 `.venv/bin/pytest -q` 为 **134 passed、1 skipped**。

继续排查“Python 意外退出”：本机 9 份 `.ips` 均运行于 Homebrew Python 3.14.7 + Qt 6.11，父进程 `codex`、责任进程 `ChatGPT`；8 份为 `AXCopyHierarchy → Qt Cocoa accessibility bridge` 的 `SIGSEGV`，1 份为 `QThread::~QThread` 的 `SIGABRT`。Python 和 Qt 版本与本项目此前运行环境吻合，因此报告可能涉及被 Codex 启动/观察的 RNA-Seq Helper，现有脱敏路径不足以排除或确认应用归属。Codex Computer Use 的公开 issue #41374/#42666 有相似 AX/Qt 崩溃模式。源码环境已回退到 PySide6/Qt 6.10.3，但官方相似问题横跨不同 Qt 版本；不能宣称此版本回退已修复。关闭 Codex Computer Use 会影响屏幕自动操作，已征求用户明确选择；在收到授权前不修改系统辅助功能权限。

截至 2026-09-25 最新诊断报告仍停留在 2026-09-23；没有同条件复测，故“之后无新日志”不作为稳定性证明。本轮未重打包或替换 `/Applications/RNA-Seq Helper.app`，未做桌面点击验收。当前无活动 RNA-Seq Helper 进程；下一步在确认屏幕辅助功能处理后，以当前源码启动、用像素截图和非 AX 交互验证 1024×768 与窄窗口，并完成导入到 `matrixReady` 的真实流程。

## 2026-09-24 · 扫描目录进度事件限频回归

修改 `src/rnaseq_helper/recognition/scanner.py`：目录扫描进度现在按已遍历目录项每 25 项发送，而不是依赖已发现文件数的模 25。旧逻辑在累计 25 个文件后遇到连续空目录时，每个空目录都会重复发送同一条事件，容易堵塞 Qt 主线程的排队信号。新增确定性测试构造 25 个说明文件后接 50 个空目录；新测试先证实旧代码发出 51 条 discovery 事件，修复后限制为 3 条。命令 `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -q -p no:cacheprovider tests/test_import_scan_reliability.py` 结果 **23 passed**。

本轮建立源码回退快照 `/tmp/rnaseq-helper-baseline-tPQbUE/project`（1.4 MB），排除 `.venv/` 与 `packaging/dist/`；项目内测试数据均为小型 fixture，未复制用户原始实验数据。项目没有 Git 仓库；指定的 `REVIEW-AND-ROADMAP-2026-09-23.md` 当前缺失，现以 `RNA-Seq Helper 最终规划.md`、`IMPORT-WIZARD-DESIGN-2026-09-23.md`、`STATUS.md` 和当前接口为准。下一步验证混合导入错误提示与数值注释列角色，再运行完整测试；当前源码 GUI 手动点击验收和是否重新打包仍未完成。

## 2026-09-24 · 崩溃报告归属复核

只读复核当天 9 份 Python 崩溃报告，并由 Luna 子代理交叉检查：8 份为 `AXCopyHierarchy`/Qt Cocoa bridge `SIGSEGV`，另 1 份为 `QThread::~QThread` `SIGABRT`。最新两份进程为 Homebrew Python 3.14.7，父进程 `codex`（PID 79269），责任进程 `ChatGPT`（PID 79228）；报告中的 `/Users/USER/Desktop/*` Qt 动态库路径已脱敏，不能据此认定为 RNA-Seq Helper。当前诊断目录无 `RNA-Seq Helper` 命名的崩溃报告，已安装版与 6.10.3 临时候选 bundle 进程均仍运行。

因此，前一条日志中的 PySide6 6.10.3 版本约束仅保留为保守候选，不能宣称已修复用户所说的弹窗；安装版未覆盖。停止读取 Qt 辅助功能树，后续 GUI 验收仅用像素截图与普通交互。还需依据用户是否在 Finder 独立启动时遇到相同弹窗确定实际故障归属。

本轮 `.venv/bin/pytest -q -p no:cacheprovider` 重跑为 **130 passed、1 skipped**。候选版实屏窗口内容为 1024×768，并保存窗口级截图 `evidence/import-window-1024x768-2026-09-24.png`；选择器可见，证明按钮能打开对话框，但未选入样本。为避免继续误操作其他前台应用，鼠标/键盘 GUI 输入已停止；没有读取辅助功能树，没有更改用户文档、发送消息或触碰原始数据。窄屏实屏、真实 GEO 导入、整理事实门禁的屏幕流程及 `matrixReady` 到分组页的实屏交接均未完成；本轮未重新打包或覆盖安装版。

为补充窄屏视觉核查，使用 Qt offscreen platform、当前源码和只读真实 `GSE10361_series_matrix.txt.gz` 生成 `evidence/organize-page-820x560-offscreen.png`。扫描/整理层载入 40×10 有界预览；截图显示 facts 页面需要确认单位与对数变换、未确认时主按钮禁用，窄视口保留纵向滚动。此图不是实际桌面窗口，不能替代 820×560 实屏检查；真实输入文件未修改。

随后直接经项目 `AssetScanner` + `PreparationService.start(preview_only=True) → complete_read → validate` 完成同一真实 GEO 表的导入与整理校验：有限预览 40×10、全量 22,284×10，唯一阻断原因是单位与 log 尺度都未知；输入文件 SHA256 前后一致。没有启动 R worker 或差异分析，未写入导入结果。

## 2026-09-23 · 阶段 5 · Python 异常退出调查与 Qt 版本回退候选

复核当天 9 份 `Python-*.ips`：8 份 `EXC_BAD_ACCESS/SIGSEGV` 的主线程栈为 macOS `NSAccessibility`/`AXCopyHierarchy`，经 Qt Cocoa accessibility bridge；与 Codex Computer Use 已公开的 Qt macOS 辅助功能扫描崩溃签名一致（[issue #41374](https://github.com/openai/codex/issues/41374)、[issue #42666](https://github.com/openai/codex/issues/42666)）。这些记录的发生时点与本轮请求 Qt 界面辅助功能树相符，不能据此认定 RNA 导入或分析代码崩溃。本轮停止对 Qt 窗口做 AX 树读取；不通过关闭辅助功能来绕过。

另有 1 份 `EXC_CRASH/SIGABRT` 报告，调用栈含 `QThread::~QThread → QWidget::~QWidget → PySide::destroyQCoreApplication`，属于线程退出生命周期，与 AX 崩溃是两类问题。源码已有 `BackgroundJobCloseGuard`，在窗口关闭时先协作取消并等待 GUI 微型验证、导入和正式分析线程；对应假线程及真实 `QThread` 回归通过。

崩溃报告加载 PySide6/Qt 6.11 系列；将项目依赖限制为 `PySide6>=6.10.3,<6.11`，并把本项目 `.venv` 切换到 6.10.3，没有关闭本应用或系统辅助功能。该环境下 `pip check` 通过，完整回归 **130 passed、1 skipped**。独立 clean 候选包构建于 `/tmp/rnaseq-helper-crash-fix-7M4Fry/RNA-Seq Helper-clean.app`：内置 R/limma/DESeq2 自检通过，严格 ad-hoc 签名校验通过，打包版 limma 与 DESeq2 微型验证均通过。

版本回退尚未在解锁的 macOS 桌面做实际窗口及 AX 对照，因此目前只能称为已验证可运行的缓解候选，不能声称 8 次 AX/SIGSEGV 已彻底消除。唯一安装包 `/Applications/RNA-Seq Helper.app`（0.1.0）仍在运行，包内为 PySide6 6.11 系列；本轮没有覆盖它。实屏导入流程、AX 稳定性对照和窄窗口截图继续待解锁后验收。

## 2026-09-23 · 导入向导简洁确认迭代

在清楚矩阵上，工作表/表头/方向设置与逐列角色编辑器改为按需展开；软件识别建议和原表预览常驻，用户仍需主动确认，数值单位/尺度仍为 UNKNOWN 时不能继续。多工作表、结构不明确、重复或空样本名、特征编号/列角色不明确时自动展开编辑器。逐步按钮文案改为描述当前动作；主提示使用“基因编号、样本数值”等新手用语。没有修改 `PreparationService` 校验、分析方法、R worker、阈值、结果 schema 或 `ExpressionMatrix`/`matrixReady` 接口。

回归新增清晰矩阵折叠/展开、歧义矩阵自动展开、未确认单位/尺度阻断，以及 1024×768 / 820×560 下前两步主按钮保持在视口内的检查。定向 UI 回归 **24 passed**；完整 `.venv/bin/pytest -q` **130 passed、1 skipped**。源码回退快照 `/tmp/rnaseq-helper-source-snapshot-JUhWCU` 排除真实数据、`.venv`、`packaging/dist/` 和凭据；校验模式对比仅显示快照后预期修改的 `import_page.py`、2 个测试和 3 份开发文档，其余纳入源码一致。当前桌面会话在实屏验收时再次锁定；系统截图仅显示锁屏背景，未冒充 GUI 截图。源码窗口已退出，没有对仍运行的安装包做替换。当前源码的真实文件 picker、导入点击和 1024×768/窄窗实屏截图仍待桌面解锁后补验；本轮未重打包。

## 2026-09-23 · 阶段 5 · 导入与整理 A+B 首轮修正

以 `IMPORT-WIZARD-DESIGN-2026-09-23.md` 为准继续改造，只改导入入口/表格整理，不改 R worker、统计方法、过滤阈值或结果 schema。主导航移除占位宽度的“环境与验证”按钮并放入“工具”菜单；导入文件清单页增加纵向滚动保护和内置表格横向滚动，最小主窗口高度调至 560（保持 820 px 最小宽度，以免未经本轮检查的分析页被挤压）；加入按“特征 × 样本”展示的结构估算、表头/方向与列角色的可展开原因说明、count 优先建议理由，以及 PDF 作为交付说明保留但不读取成表达矩阵的文案。

修正自动研判边界：单位/尺度候选只读取表格中的文字线索，不再从文件名或数值外观推断；GEO 等没有充分文本线索的数据保持 `UNKNOWN` 并指向交付说明。表格和 GEO Series Matrix 的后台完整读取现在支持逐行取消、约每千行报告进度；`WizardSession` 暂存 GEO 元数据，避免准备步骤重复解析同一个 GEO 文件。输入文件仍只读，整理输出契约未变。

新增混合目录（`a.pdf`、`b_counts.tsv`、`sample.fastq.gz`）、工作簿 count/TPM 建议、同级候选不默认选择、解释展开、特征×样本文案、仅文件名不能确认单位/尺度、普通表格/GEO 读取取消与进度的回归。基线 `99 passed, 1 skipped`；本轮完整源码回归 `.venv/bin/pytest -q` 为 `108 passed, 1 skipped`。用 Codex's House 中真实只读文件 `GSE10361_series_matrix.txt.gz`（1,645,548 bytes，远小于 1GB）扫描得到 GEO Series Matrix、22,284 × 10、GPL96；单位和尺度候选均为 UNKNOWN，符合“不靠名称或数值猜事实”。

本轮未重新打包。将源码运行窗口按 Python.app 可执行路径绑定后，984×768 实屏截图中导入首屏无明显遮挡；“工具 → 环境与验证…”入口可见。键盘焦点从当前步骤进入“选择文件”“选择 10x 文件夹”和文件表格，再返回步骤栏。窄窗拖动两次均未改变尺寸，因此窄屏尚未实测。文件选择器曾定位到真实 GSE10361 文件（1.57 MiB），但自动化双击时 Python/QT 进程以 139 退出并记录 invalid accessibility object；故真实导入预览及 `matrixReady` 交接仍未验收，且本轮未重试。另有旧安装版 `/Applications/RNA-Seq Helper.app` 同时运行，显示旧式标签页；该安装版未重打包。归档清单、10x 大文件校验/哈希等取消粒度仍需后续检查；`REVIEW-AND-ROADMAP-2026-09-23.md` 在当前项目中不存在，本轮据现有向导设计文档和最终规划继续。

## 2026-09-23 · 阶段 5 · A+B 迭代 2：有限预览、推荐证据与交接验证

把 `RawTable.is_complete` 作为预览/全表的显式标记；`TableReader` 与 `GeoSeriesMatrixReader` 可限制首轮行列数，`AssetScanner` 只读最多 40×80 的 GEO/普通表预览。GUI 通过 `PreparationService.start(preview_only=True)` 建立预览会话；用户确认后由 worker 调用 `complete_read()` 读取全表，再校验和保存。GEO 样本元数据随前缀预览保留，完成读取后的 GEO 解析对象复用，不再重复解析。若未展示的方向轴上还存在其他列/行，最终校验会阻断，防止样本静默遗漏；全量验证阶段明确隐藏取消按钮，避免在写入中途制造半成品。

推荐规则不再把同级工作表按文件顺序静默选第一张：同级候选保留给用户决定。工作簿名称线索可以明确建议优先查看 count 表，但不会据此确认单位；界面解释推荐理由并保持实际数值单位/尺度为 UNKNOWN。初学者界面隐藏 `RAW_COUNT` 等内部枚举及数值密度分数。新增普通表格/GEO 有界预览、延迟读取、样本轴完整性阻断、全量读取取消、混合目录识别、count/TPM 建议、同级候选以及有限预览至 `matrixReady` 交接测试。全量回归 `.venv/bin/pytest -q` 为 **116 passed, 1 skipped**；另有 1,500 特征矩阵在离屏 GUI 中经过预览、确认、后台全量读取/验证/保存，交接形状为 1,500×2。未改统计方法、R worker、过滤阈值、结果字段或 `ExpressionMatrix`/`matrixReady` 契约。

真实 GUI 最终导入验收仍待完成：Mac 当时处于锁屏，不能核验当前源码窗口中的实际交互；也尚未完成窄窗口重排验收。此次不重新打包，不把上一轮旧 bundle 当作当前源码验收结果。

后续复核进程时间发现，仍在运行的源码 GUI 于 17:25 启动；`import_page.py`/扫描器于 17:48 更新，`table_reader.py` 与导入页于 18:16 更新，因此该进程载入的是本轮修改前代码，不能作为当前版本的 GUI 验收对象。桌面控制接口在收到用户“已解锁”后仍报告系统锁屏；实际点击验收必须待接口确认可用后，从新启动的源码进程开始。

## 2026-09-23 · 阶段 5 · A+B 迭代 3：混合 10x 交付、校验取消与错误提示

修正多文件扫描中 10x 特判吞并同目录其他文件的问题：现在只把准确匹配 Matrix Market 三件套的文件并入 10x 资产；完整和缺件目录中的普通表达表、PDF 说明、FASTQ 均保留为独立候选/忽略/不支持项。新增完整和不完整 10x 混合交付扫描回归。

完整读取后的逐行校验现在接受协作取消与进度回调，按批检查矩阵生成和数值遍历；取消不写项目产物、不发 `matrixReady`。进入写矩阵和 manifest 阶段后仍禁用取消，避免产生半成品。worker 异常首屏使用按权限、路径缺失、压缩/格式损坏、编码、磁盘空间分类的恢复提示；原异常仅放状态悬停详情。新增校验取消/进度、GUI 取消按钮可见、源文件保持原文、未发布半成品及错误路径不出现在主提示的回归。

Excel 有界预览再增加资源边界：源工作表列数超过 80 时，首轮 `openpyxl` 读取使用 `max_col=80`，同时将读取内容标记为不完整；`RawTable.column_count` 保持已物化的预览列数，避免破坏准备服务的“首屏展示宽度 vs 完整文件样本轴”比较。新增 101 列工作簿预览/完整读取对照测试。

最新完整源码回归 `.venv/bin/pytest -q`：**125 passed, 1 skipped**；含扫描、取消及 UI 状态在内的定向组为 **36 passed**。离屏 Qt 检查导入页 1024×768 和 820×560 几何，主按钮均位于视口内且内容区收缩保留滚动；该结果不替代屏幕截图。文本预览现限制单物理行约 1 Mi 字符、保留文本 2 百万字符，超限时以可恢复错误阻断；完整读取不设该预览上限，极端单行仍可能占用较多内存并延迟协作取消。桌面控制接口在用户回复已解锁后仍检测到锁屏；现有源码 GUI 进程早于本轮改动（最后相关源码修改 18:16），实屏导入和窄屏截图必须由新源码进程验收。README 已标明 v25 是旧候选包，当前安装版未重打包。

## 2026-09-22 · 阶段 5 · 旧式 XLS 导入无反馈修复

修复 `.xls` 选择后界面不继续的问题。原因是资产扫描器在表格分支前会尝试 GEO Series Matrix 文本嗅探，二进制 Excel 不应进入该路径；现在只对文本表格执行 GEO 内容识别，`.xls/.xlsx/.xlsm` 直接交给 `TableReader`，并在 GEO 读取器中增加二进制 Excel 的防御性跳过。新增回归断言，真实 `.xls` 可列出工作表、读取数值并完成资产扫描。重新打包并安装后，用真实 6 KB `.xls` 实际点击验证已进入“2 整理并确认”。验证结果：`86 passed, 1 skipped`；bundle `ready=true`；严格 ad-hoc 签名校验通过。

## 2026-09-15 · 阶段 5 · 分组可读性与自动研判规则修正

分组页增加样本/注释筛选、点击表头排序、对可见行批量设置分组，并将 GEO 编号、sample title、平台和其他来源注释分列展示；新增配对个体和批次的通俗说明。自动研判修复 `normalized_counts` 被误识别为 raw count 的问题，并阻断 raw count 与 log2/其他转换的矛盾组合。版本命名统一为未发布开发版 `v0.30`。源码回归：`82 passed, 1 skipped`；v0.30 clean bundle 自检和严格签名校验通过。

整理页进一步拆分为“确认数据事实”和“设置列角色与预览”两个独立页签，避免单位/尺度设置与列角色表格争抢空间；新版 v0.30 已重新覆盖本机应用并通过内置 R 与严格签名校验。

## 2026-09-15 · 阶段 5 · 小白提示滚动与真实数据核验

小白提示改为独立滚动区域，垂直滑块始终可见；内容覆盖单位、原始/线性尺度、log2(x)/log2(x+1)、normalized/expression/signal intensity、ln/log10、z-score、残差及“不能靠猜”。自动研判改为强制输出可执行建议：没有明确线索时默认“其他连续表达值 + 原始/线性尺度”，不再输出“未确认/研判失败”。放大窗口实屏核验通过。完整回归：`82 passed, 1 skipped`；v0.30 clean bundle 自检和严格签名校验通过。使用 Codex's House 中 1GB 内真实文件核验时，发现 83.5MB 文本表的同步导入仍可能让界面等待较久，留作后续修复。v0.30 仍是未发布开发版本。

## 2026-09-14 · 阶段 5 · 面向新手的导入自动研判

导入页新增简洁的“小白提示”，用提供方常见写法说明如何判断单位、尺度和 log2 公式；同时在文件载入后自动根据文件名、可读性和数值内容生成单位/尺度候选。候选会自动填入下拉框但仍可修改，并明确标注“不是最终确认”；证据不足时保持“未确认”，避免把整数/小数外观当成单位判断。新增离屏回归覆盖 company count 自动候选。

验证：`.venv/bin/pytest -q` → `79 passed, 1 skipped`。v26 clean candidate 已通过 bundle 自检、limma/DESeq2 微型验证和 `codesign --verify --deep --strict`；两次全新屏幕核验通过：company count TSV 显示自动候选，GEO Series Matrix 示例显示证据不足并保持单位/尺度“未确认”。本轮未读取、修改或下载用户原始数据。

## 2026-09-13 · 阶段 2–4 · 统计链路、输入安全和结果交付

新增 PlanningService、AnalysisService 和 AnalysisPage。计划按已确认数据单位/尺度选择 DESeq2 或固定 `normalized-log-limma-trend-v1`，保存方法理由、设计、对比、过滤和矩阵哈希；R worker 新增通用 limma/DESeq2 方法，结果统一保留 feature_key、效应、pvalue、padj、tested 和 reason_not_tested，并区分独立过滤、全零和异常/不可估计原因。normalized 路径在 R 前执行 500 特征、50 个 Amean 值、组内退化比例不超过 5% 门禁；结果自动生成离线 HTML、XLSX 和 manifest。

同时新增 GEO Series Matrix 表段读取、10x 三件套稀疏元信息检查，以及 zip/tar 安全清单和受限展开。压缩路径逃逸、符号链接、异常压缩比、成员/总大小/路径层级均拒绝。验证命令为 `.venv/bin/python -m pytest -q`，结果 19 passed，1 skipped；额外通过 600 特征 TPM→limma 和 count→DESeq2 真实 R 回归及离屏 GUI 分组运行。尚未完成：GEO/10x 全部 GUI 分支、GPL/OrgDb 参考映射、PCA/相关/火山/热图、完整报告中文解读和正式签名公证。

## 2026-09-13 · 阶段 1 · 导入页阻断提示修复

屏幕复现了用户点击“应用整理并验证”后的失败：原始表格本身可读取，但“数值单位”和“数值尺度”仍是“未确认”，因此验证按设计阻断。为避免用户先点击才看到弹窗，导入页现在在这两个事实确认前禁用继续按钮，并显示内联提示；表头变化时同步刷新列角色标签。离屏 UI 回归确认：未确认时按钮禁用，选择“原始 count”和“原始/线性尺度”后可完成整理并写入独立 `prepared/` 目录。测试结果：10 passed，1 skipped。

## 2026-09-13 · 阶段 0 · 已实现并部分验证

新增 `pyproject.toml`、Python 包骨架、独立 `resources/r/worker.R`、阶段 0 CLI 自检/微型 limma/DESeq2 验证、最小 Qt worker、测试和 py2app 配置。R worker 采用单请求单进程 JSON Lines 边界，固定记录 R/limma/statmod 版本；DESeq2 不可用时直接报错。验证命令为 `PYTHONPATH=src python3 -m rnaseq_helper.app --self-check`、`PYTHONPATH=src python3 -m rnaseq_helper.app --micro-test` 和 `PYTHONPATH=src python3 -m unittest discover -s tests -v`。当前环境 R 侧 limma 路径可用，PySide6/rpy2/DESeq2 缺失，GUI 与正式 standalone 尚未验证；DESeq2 runner 已实现但待依赖安装后验证。下一步安装固定 GUI 构建依赖后检查 QThread 取消和 py2app 收集情况。

## 2026-09-13 · 阶段 0 · 依赖补齐与验证

在项目 `.venv` 中安装 PySide6 6.11.2、pytest、py2app 0.28.10 和 editable 包；在 R 4.6.0/Bioconductor 3.23 中安装 DESeq2 1.52.0。首次 DESeq2 微型 fixture 因 3 个基因的离散度过于接近而失败，扩展为固定 120 基因并加入可重复的基因间噪声后通过。验证命令为 `.venv/bin/python -m rnaseq_helper.app --self-check`、`--micro-test`、`--micro-deseq2`、`.venv/bin/python -m pytest -q` 和 QThread smoke test；结果分别为运行时全通过、limma 通过、DESeq2 通过、5 passed/1 skipped、QThread OK。已实现/已验证：独立 R worker、两条微型分析路径、Qt worker 通信。未验证：取消、standalone 产物、签名公证和干净 Mac。

## 2026-09-13 · 阶段 0 · UI 卡住修复

用户反馈点击后长期停留在“R worker 运行中……”。复现时 R 子进程已退出且 QThread 进入空闲事件循环，定位为打包环境下结果信号到 UI 处理器的自动连接不够明确。将 worker 启动信号和完成/失败回调全部指定 `Qt.ConnectionType.QueuedConnection`，确保控件只在主线程更新。修复后需重新打开最新 bundle，并验证成功和失败两条 UI 状态。

## 2026-09-13 · 阶段 0 · worker 生命周期修复

进一步用 PySide6 + QMainWindow 复现发现：`RuntimeWorker` 仅由 `start()` 局部变量持有；函数返回后 Python wrapper 被回收，QThread 留在空闲事件循环，完成信号因此无法更新 UI。新增 `active_jobs` 持有活动 thread/worker，在线程 finished 后释放；保留显式 QueuedConnection。此前仅有命令行/QThread 级测试不足以覆盖该生命周期问题，需以打包 GUI 实际点击作为验收。

## 2026-09-13 · 阶段 0 · Finder Rscript 路径修复

实际屏幕复测显示 bundle 从 Finder 启动后报 `No such file or directory: 'Rscript'`。终端环境中 `/usr/local/bin/Rscript` 可用，但 Finder 不保证继承 shell PATH。新增统一 `resolve_rscript()`，按用户覆盖变量、当前 PATH、R.framework、Homebrew 路径依次解析；分析客户端和环境自检共用该解析逻辑。需重新构建 bundle 后验证 Finder 点击。

重新构建后通过真实 Finder bundle 复测：点击按钮后界面显示“微型 limma 验证通过”，Rscript 路径解析修复生效。无 shell PATH 的命令行测试、自检、limma/DESeq2 bundle 测试和自动测试均保持通过。

## 2026-09-13 · 阶段 0 · standalone 构建

首次从项目根目录运行 py2app 时，py2app 0.28.10 因读取 `pyproject.toml` 的 `install_requires` 拒绝构建；改为从 `packaging/` 目录运行，并在打包专用 setup 中显式清空安装依赖后成功生成 standalone `.app`。bundle 约 1.2 GB，包含完整 PySide6 Qt runtime；体积优化留待后续。bundle 内 `--self-check`、`--micro-test`、`--micro-deseq2` 均返回 0，worker 资源路径正确。工作区 FinderInfo/provenance xattr 使本地严格 codesign 校验报资源错误；使用 `ditto --norsrc --noextattr` 复制品后 `codesign --verify --deep --strict` 返回 0。已验证构建和本机运行，未完成开发者证书签名、公证与跨机器验证。
## 2026-09-13 · 阶段 5 · 四图、报告和运行环境复核

具体变更：`services/plot_service.py` 增加 PCA（最多 2,000 个高变异特征）、Pearson 样本相关性、FDR 火山图和 Top 特征行 Z-score/Ward.D2-equivalent 热图，并在图中标记转换尺度；空热图选择退化时提供单行兜底。`services/report_service.py` 在离线 HTML 中嵌入四图预览，继续输出 XLSX、manifest、方法和诊断页。`app.py` 和 README 更新为阶段 5。由于本次会话原开发环境路径失效，在项目内新建隔离 `.venv`，依赖仅来自 `pyproject.toml`。

接口/参数决策：火山图只绘制有有限 padj 的特征，纵轴统一为 `-log10(FDR)`；DESeq2 仍保留未收缩模型效应，明确记录为后续 profile 工作，不引入未经固定的隐式 shrinkage。原始输入目录未写入、未下载、未删除。

验证：`.venv/bin/pytest -q` → `19 passed, 1 skipped`；阶段 2 的真实 R limma/DESeq2 fixture 同时生成 `analysis/`、`figures/`、`reports/` 产物。最新 standalone bundle 已重建，bundle `--self-check`、`--micro-test`、`--micro-deseq2` 均通过；屏幕监视两次确认阶段 5 主界面与“结果与报告”页可见。已实现/已验证：四图文件、figure-manifest、HTML/XLSX、结果页和运行时错误回传。未验证：干净 Mac、签名公证和正式发布包。下一步：补足参考文件映射、GEO/10x GUI 分支与完整中文解读，然后再做发布前验收。
## 2026-09-13 · 阶段 5 · 精度门禁与本地参考降级

具体变更：`analysis/planning.py` 增加连续表达低精度启发式，按固定容差检查低表达格点和低复杂度行，仅生成可继续的精度告警；`grouping/service.py` 对只有两对完整配对的设计增加残差自由度阻断。新增 `domain.models.ReferenceRequest/ReferenceResult` 与 `services/reference_service.py`，支持用户本地 CSV/TSV/XLSX 编号映射，保留一对多、不复制统计行、计算 coverage/ambiguous/unmapped/checksum，并在 `~/Library/Application Support/RNA-Seq Helper/reference-cache/` 写入可审计缓存。未访问网络、未下载参考或表达数据。

验证：`.venv/bin/pytest -q` → `23 passed, 1 skipped`。新增两对配对设计阻断、低精度告警和参考表部分覆盖测试；R worker 解析及前一轮 bundle 验证仍通过。已实现/已验证：门禁不把普通精度告警误当阻断，参考失败保留原编号。未实现：参考服务尚未由 GUI 配置入口调用，GEO/GPL 在线获取保持后续离线降级工作。
## 2026-09-13 · 阶段 5 · 取消任务与报告解释

具体变更：`AnalysisPage` 新增取消按钮，把同一 `JobContext` 的取消令牌传入分析 worker；`RBridgeClient` 已有轮询取消逻辑，取消时终止独立 Rscript 并回传可读状态。`ReportService` 新增离线 `interpretation-zh.txt` 和 XLSX Interpretation 页，HTML 同时展示该模板、实际参数、运行版本、样本安排、诊断和告警。结果表继续保留 NA 与 reason_not_tested。

验证：`.venv/bin/pytest -q` → `24 passed, 1 skipped`，离屏 UI 导入 `AnalysisPage`/`ResultsPage` 成功；最新 bundle 已重新构建，bundle 自检、limma 微型验证、DESeq2 微型验证通过。未完成：因 macOS 锁屏，新增代码后的两次屏幕监测尚缺，不能把源码测试代替 GUI 验收。下一步：解锁后启动最新 app，分别检查导入页、运行时页和结果页，再更新状态。
## 2026-09-13 · 阶段 5 · GEO gzip 与压缩导入边界

具体变更：修复 gzip GEO Series Matrix 进入整理向导时仍调用普通表格 `list_sheets()` 的问题；GEO 对 `.gz` 现在统一视为单一文本对象，可读取平台/样本元数据和表段。普通压缩包由 `ArchiveService` 先安全检查再受限展开，候选对象不唯一时不自动猜选；10x 结果给出细胞级数据不能直接进 bulk 的提示。

验证：新增 gzip GEO 扫描和整理测试后，`.venv/bin/pytest -q` → `25 passed, 1 skipped`。原始数据目录未修改，未联网下载 GEO 或参考文件。由于 Mac 仍锁屏，本轮最新改动的屏幕监测尚未执行；bundle 需要在解锁后重新启动并连续监视两次。
## 2026-09-13 · 阶段 5 · worker 进度与 10x 目录入口

具体变更：分析 worker 将 `JobContext.on_progress` 转为 Qt 信号，分析页显示独立 R worker 的阶段消息，并提供取消按钮；导入页增加选择 10x 目录的原生文件夹对话框，识别后明确提示细胞级矩阵不能当作 bulk 重复。这样长任务有可见状态，异常和取消不会永久停在单一文案。

验证：`.venv/bin/pytest -q` → `25 passed, 1 skipped`；离屏实例化分析页确认“取消当前任务”控件存在。最新源码改动后需重新构建 bundle；屏幕监测仍受 Mac 锁屏阻断，不能用离屏实例化替代两次真实界面检查。
## 2026-09-13 · 阶段 5 · GPL/SOFT 本地参考读取

具体变更：新增 `readers/gpl_reader.py`，读取用户本地 GPL SOFT/annot 平台表，识别平台编号、编号列和 gene symbol 列；同一探针对应多个符号时保留列表，不复制统计行。`ReferenceService` 对 `.soft/.annot` 走该读取器，扫描器把可识别参考文件标记为 REFERENCE，避免把参考表误送表达矩阵 runner。

验证：新增 GPL 一对多映射与扫描测试后，`.venv/bin/pytest -q` → `26 passed, 1 skipped`。未联网、未下载外部注释，原始输入保持只读。仍待：GUI 参考文件选择/物种确认入口和最新 bundle 屏幕监测（Mac 锁屏）。
## 2026-09-13 · 阶段 5 · 注释列与统一结果字段

具体变更：整理服务将非数值注释列完整写入 `prepared/feature_metadata.tsv`，但不进入表达矩阵；分析服务读取其中的 `gene_symbol`，通过 JSON Lines 传给 R worker，结果表保留 `feature_key/original_id/gene_symbol`，一对多参考关系仍不复制统计行。

验证：`.venv/bin/pytest -q` → `26 passed, 1 skipped`；R worker 解析、bundle 自检、limma 和 DESeq2 微型验证通过。最新 bundle 屏幕监测仍需解锁 Mac 后完成两次，不能以命令行或离屏测试替代。

## 2026-09-13 · 阶段 5 · 本地参考表 GUI 链路

具体变更：导入页新增可选的本地参考表选择入口，支持 CSV/TSV/TXT/XLSX/SOFT/annot；整理完成时通过 `ReferenceService` 生成编号到 gene symbol 的映射，保留一对多关系，将参考结果写入 `references/reference-result.json`，并在没有现有 gene symbol 注释列时追加到 `prepared/feature_metadata.tsv`。表达矩阵的统计行数保持不变。

验证：`.venv/bin/pytest -q` → `27 passed, 1 skipped`；bundle 内自检、limma 微型验证、DESeq2 微型验证均通过。由于 macOS 当前锁屏，新增代码后的两次真实屏幕监测尚未执行。

## 2026-09-13 · 阶段 5 · 最终 bundle 验证与导入边界

具体变更：补充项目对象的来源/平台/参考审计字段，GEO accession、title 和平台信息随 `sample_metadata.tsv` 保存；扫描器记录内容 fingerprint，支持错误扩展名但内容为 GEO 的识别。导入页支持文件拖放、压缩包多候选对象选择，并防止特征编号列重复进入样本列。运行时页拆分环境、limma、DESeq2 三项检查；新增 `packaging/verify_bundle.py` 作为离线 bundle 验证入口。

验证：`.venv/bin/pytest -q` → `28 passed, 1 skipped`；R worker 解析、源码微型 limma/DESeq2、最新 standalone bundle 验证均通过，临时去除 Finder 扩展属性副本的 Apple Silicon 严格签名校验通过。最终两次真实屏幕监测仍因 macOS 锁屏未执行。

## 2026-09-13 · 阶段 5 · v2 分组设计与真实屏幕验收

具体变更：分组页增加逐样本配对个体和批次字段，部分填写、完全混杂和不足自由度会阻断；运行时页与导入页的前一版改动保留。最新 bundle 重新构建后由 CUA 真实启动，未使用离屏实例代替屏幕检查。

验证：`29 passed, 1 skipped`；`packaging/verify_bundle.py` 通过。两次屏幕监测分别确认导入页和分组页，随后实际点击 limma 验证，界面显示“limma 微型验证通过”。

## 2026-09-13 · 阶段 5 · 参考失败降级与 v3 验收状态

具体变更：本地参考表发生编码错误、损坏或缓存目录无写权限时，服务返回可审计的 UNAVAILABLE/降级结果，保留原始编号并记录 checksum，不让 GUI 直接退出；新增 clean bundle 复制与验证脚本及常见提示文档。

验证：`30 passed, 1 skipped`，最新 bundle 自动验证通过。v2 两次真实屏幕监测已确认导入页、分组页和 limma 微型验证完成；v3 启动后的两次屏幕监测因 macOS 再次锁屏未完成。clean 副本严格签名检查明确暴露 `liblzma.5.dylib` 子组件签名问题，未将 ad-hoc bundle 宣称为正式发布包。

## 2026-09-13 · 阶段 5 · v5 启动修复、离线 OrgDb 与真实屏幕验收

具体变更：`ReferenceService` 增加已安装离线 OrgDb 的可选编号映射，仍以用户本地参考表优先；移除 `RBridgeClient` 与 `services` 包之间的循环导入，修复 v4 bundle 启动时的 py2app “Launch error”。整理配方现在保存注释/忽略列，项目 manifest 保存来源资产与 fingerprint，GEO sample metadata 保存平台字段；worker 资源同步更新。

验证：源码 `.venv/bin/pytest -q` → `32 passed, 1 skipped`；`packaging/verify_bundle.py` → `ready: true`，Apple Silicon、Rscript、limma、DESeq2 均通过；clean bundle 副本的 `codesign --verify --deep --strict` 通过。v5 启动后完成两次独立真实屏幕监测，分别确认导入页和分组/分析页；未读取用户原始数据、未联网下载参考。未验证：干净 Mac 和开发者证书签名/公证。

## 2026-09-13 · 阶段 5 · 压缩包安全边界与 v6 屏幕验收

具体变更：压缩包检查增加 zip 符号链接、tar 特殊文件和整体展开/压缩比限制，继续拒绝路径穿越；补充对应反例测试。v6 standalone 重新打包，保留前一版本的本地参考、离线 OrgDb 和 GUI 启动修复。

验证：`.venv/bin/pytest -q` → `35 passed, 1 skipped`；`packaging/verify_bundle.py` → `ready: true`；v6 完成两次独立真实屏幕监测，导入页和分组/分析页均正常；运行时页此前已真实点击 limma、DESeq2 并分别显示“微型验证通过”。clean bundle 副本严格签名校验通过。未验证：干净 Mac、正式开发者证书签名和公证。

## 2026-09-13 · 阶段 5 · v8 压缩候选对象树验收

具体变更：压缩包内多个表达候选由简化下拉选择升级为带对象类型、用途、尺寸和来源的树形对话框；候选对象保留 parent_asset_id 与 archive_member_paths，10x 仍明确禁止作为独立 bulk 样本进入分析。

验证：`.venv/bin/pytest -q` → `35 passed, 1 skipped`；`packaging/verify_bundle.py` → `ready: true`。v8 启动后完成两次独立真实屏幕监测，导入页和分组/分析页均正常显示。未验证：通过真实压缩包触发 GUI 对象树、干净 Mac、正式开发者证书签名和公证。

## 2026-09-13 · 阶段 5 · v9 10x 稀疏预览验收

具体变更：10x 入口在拒绝进入 bulk runner 前，展示矩阵维度、非零条目和 feature type 行数；仍不稠密化、不把细胞当独立重复。新增 feature type 计数测试。

验证：`.venv/bin/pytest -q` → `35 passed, 1 skipped`；`packaging/verify_bundle.py` → `ready: true`。v9 完成两次独立真实屏幕监测，导入页和分组/分析页正常。未验证：真实用户压缩包/10x 通过 GUI 选择器的完整交互、干净 Mac、正式开发者证书签名和公证。

## 2026-09-13 · 阶段 5 · v7 最终回归与交付说明

具体变更：增加 Rscript 环境检查超时，报告 Summary 直接记录真实来源文件和参考结果；重新打包 v7，并同步修正文档中过期的“OrgDb 未实现”描述。当前交付仍明确区分本机 clean 自签检查与正式开发者证书签名/公证。

验证：`.venv/bin/pytest -q` → `35 passed, 1 skipped`；`packaging/verify_bundle.py` → `ready: true`，Apple Silicon、Rscript、limma、DESeq2 均通过；clean bundle 的 `codesign --verify --deep --strict` 通过。v7 两次独立真实屏幕监测确认导入页和分组/分析页正常；运行时页真实点击 limma、DESeq2 均显示“微型验证通过”。未验证：干净 Mac、正式开发者证书签名和公证。

## 2026-09-13 · 阶段 5 · v10 极小矩阵 DESeq2 降级路径与真实 GUI 全链路

具体变更：针对极小的本地 smoke-test 矩阵，DESeq2 的离散度趋势拟合失败时，按 DESeq2 文档改用逐基因离散度继续使用同一 count model；结果的 `parameters.dispersion_estimation` 和 `issues` 明确记录该降级及正式分析复核提示。其他 DESeq2 错误仍原样失败，不切换到 limma。

验证：`.venv/bin/pytest -q` → `36 passed, 1 skipped`；极小 4 特征矩阵已通过独立 R worker 验证并返回 warning；`packaging/verify_bundle.py` → `ready: true`；clean bundle 副本的 `codesign --verify --deep --strict` 通过。v10 完成两次独立真实屏幕监测，并通过打包应用实际完成：选择本地 TSV、确认原始 count/线性尺度、生成 DESeq2 计划、运行 R worker、生成离线 HTML/XLSX/四张图，结果页显示“分析完成”；同一包的运行时 limma、DESeq2 微型验证均显示“通过”。未验证：干净 Mac、正式开发者证书签名和公证。

## 2026-09-13 · 阶段 5 · v11 转置整理修复、公式安全门禁与发布检查

具体变更：修复转置预览中错误的元组/整数索引，切换方向时按新视图重新推导特征列、样本列和注释列；Excel 公式无缓存值时明确阻断，仍不执行公式；修复发布检查器面对非 UTF-8 FinderInfo 输出时崩溃的问题。结果包继续保留五张离线图、原始 p 值直方图和 worker 告警字段。

验证：`.venv/bin/pytest -q` → `42 passed, 1 skipped`；`packaging/verify_bundle.py` → `ready: true`，Apple Silicon、Rscript、limma、statmod、DESeq2 和 worker 资源均通过；clean v11 副本 `codesign --verify --deep --strict` 通过；v11 完成两次独立真实屏幕监测，导入页和运行时页均正常，重新点击 limma 与 DESeq2 微型验证均显示“通过”。新增 QThread/R worker 完成信号回归。发布检查器正确报告当前仍缺 Developer ID、内置 R.framework、公证和干净 Mac 验收，未伪造正式发布状态。

## 2026-09-13 · 阶段 5 · v13 R worker 完成信号与进度显示修复

具体变更：运行时页将 R worker 进度改由主线程 `QObject` 槽接收，避免匿名 queued lambda 导致 Rscript 已退出而完成信号未更新界面；保留 120 秒超时和显式失败信息。新增 QThread 级回归测试，覆盖独立 R worker 的完成信号。

验证：`.venv/bin/pytest -q` → `42 passed, 1 skipped`；`packaging/verify_bundle.py` → `ready: true`；clean v13 副本 `codesign --verify --deep --strict` 通过。v13 完成两次独立真实屏幕监测，实际观察到“R worker：正在等待独立 R worker 返回”后回到“limma 微型验证通过”；随后 DESeq2 微型验证也显示“通过”。此前 v12 复现出的“Rscript 已退出但界面仍等待”已修复。发布检查器仍明确报告 Developer ID、内置 R.framework、公证和干净 Mac 是正式发布前置条件。

## 2026-09-13 · 阶段 5 · v14 精度门禁、合成 mock 与递归容器

具体变更：标准化表达分析计划新增按固定容差计算的 Q(1)、Q(0.1)、低复杂度比例 L 和模型残差退化比例 Z；普通低精度只记录可继续告警，严重舍入组合在 R worker 前阻断，并把完整诊断写入 `preprocessing.precision_diagnostics`。新增临时目录 mock 工厂，覆盖 GEO 2000×8、公司 count 3000×12、10x 1000×600、TPM/FPKM regular、低精度边界和 10x 非稠密语义。`ArchiveService` 增加逐层清单检查的嵌套 zip/tar 展开；普通 GEO `.txt.gz` 不会被误当成 tar 容器。

验证：`.venv/bin/pytest -q` → `50 passed, 1 skipped`；定向 mock 与容器测试通过；本轮只使用本地合成数据，未下载或改写用户原始文件。源码门禁、mock 结构、递归安全边界均已验证；v14 standalone 已完成两次独立真实屏幕监测，第二次从本地公司 count TSV 走完单位/尺度确认、整理、分组、DESeq2 R worker 和结果页，生成 HTML/XLSX/5 张图。仍待正式签名、公证、内置 R.framework 和干净 Mac 验收。

## 2026-09-13 · 阶段 5 · v15 显式列角色与 standalone 双屏验收

具体变更：导入整理页将原先的样本勾选改为逐列角色表，显式区分特征编号、样本表达、说明/注释和忽略；每列显示原列名、角色、前三个数据示例，特征编号角色保持唯一，至少一列特征编号和两列样本表达才允许继续。配方继续保存 annotation/ignored 列，不读取或改写源文件。

验证：新增 GUI 角色约束回归；`.venv/bin/pytest -q` → `50 passed, 1 skipped`（定向 UI → `2 passed`）；v15 standalone 重建后 `packaging/verify_bundle.py` 返回 `ready: true`，Apple Silicon、Rscript、limma、statmod、DESeq2 均可用；clean 副本 `codesign --verify --deep --strict` 通过。v15 完成两次独立真实屏幕监测，均从公司 count TSV 完成列角色/单位/尺度确认、整理、分组、DESeq2 R worker 与结果页，未留下 Rscript 进程。仍待完整多 sheet/GEO/10x 向导交互、正式 Developer ID 签名、公证、内置 R.framework 和干净 Mac 验收。

## 2026-09-13 · 阶段 5 · v16 多工作表预览与 standalone 双屏验收

具体变更：导入整理页增加 Excel 多工作表逐张导航，展示当前工作表的行列规模、前 40 行数值密度和候选表头行，并明确提示不同用途的工作表不会自动拼接；继续保留逐列显式角色、唯一特征编号和至少两列样本表达约束。新增多工作表 GUI 回归和本地合成多 sheet fixture；未读取或改写用户原始数据。

验证：`.venv/bin/pytest -q` → `52 passed, 1 skipped`；v16 standalone 重建后 `packaging/verify_bundle.py` 返回 `ready: true`，Apple Silicon、Rscript、limma、statmod、DESeq2 均可用；clean 副本 `codesign --verify --deep --strict` 通过。v16 完成两次独立真实屏幕监测：第一次加载多工作表 Excel，分别观察说明页和表达矩阵页；第二次从本地公司 count TSV 完成单位/尺度确认、显式列角色、整理、分组、DESeq2 R worker 和结果页，并生成离线 HTML/XLSX/5 张图。仍待完整 GEO/10x 向导交互、正式 Developer ID 签名、公证、内置 R.framework 和干净 Mac 验收。

## 2026-09-13 · 阶段 5 · v17 GEO 样本注释分组建议与 standalone 双屏验收

具体变更：分组服务现在可读取整理阶段保存的 `sample_title` 等样本元数据，先将空格和标点规范为安全词边界，再生成 control/treated 等候选；分组页增加“来源/样本注释（只读）”列。GSM 编号本身仍不会被当作实验分组依据，建议始终显示为待人工确认；新增注释驱动分组回归测试。

验证：`.venv/bin/pytest -q` → `53 passed, 1 skipped`；v17 standalone 重建后 `packaging/verify_bundle.py` 返回 `ready: true`，Apple Silicon、Rscript、limma、statmod、DESeq2 均可用；`prepare_clean_bundle.py` 生成副本并通过 `codesign --verify --deep --strict`。v17 完成两次独立真实屏幕监测：第一次加载本地合成 GEO Series Matrix，分组页显示 GSM、sample_title 并给出“同时参考了样本注释”的建议；第二次从本地公司 count TSV 完成表头/列角色、单位/尺度、整理、分组、DESeq2 R worker 和结果页，并生成离线 HTML/XLSX/5 张图。正式 Developer ID 签名、公证、内置 R.framework 和干净 Mac 验收仍需发布环境。
## 2026-09-13 · 阶段 5 · v18 10x 稀疏校验与 R worker 等待反馈

具体变更：10x Matrix Market 导入增加流式稀疏条目校验，拒绝越界坐标、Inf/NaN、格式错误和声明/实际条目数不一致；`TenXBundle` 保存稀疏度，导入页展示矩阵维度、非零条目、稀疏度和 feature type 计数，同时继续阻止细胞级对象进入 bulk 分析。R bridge 在等待独立 R worker 时每 2 秒向 GUI 报告已等待时间，并保留 120 秒超时和子进程回收逻辑，解决用户看到长时间“运行中”时无法判断是否仍在工作的问题。

验证：源码回归 `55 passed, 1 skipped`；v18 bundle `verify_bundle.py` ready；clean 副本严格自签验证通过。两次真实屏幕监测均通过：10x 稀疏预览和 company count → DESeq2 → 离线 HTML/XLSX/五张图完整链路。当前仍不宣称正式发布，Developer ID、公证、内置 R.framework 和干净 Mac 验收留待发布环境。

## 2026-09-13 · 阶段 5 · v19 10x 三步向导与独立 R 基准

具体变更：新增 `TenXWizardDialog`，将 10x 的“数据事实、特征构成、分析边界”拆成三步可审查页面，并保留已写出的只读 manifest；新增 `tests/test_independent_r_baseline.py`，不经过应用 worker，而是直接调用 limma/DESeq2，与 worker 结果逐项比较关键统计量。

验证：`.venv/bin/pytest -q` → `57 passed, 1 skipped`；v19 standalone `verify_bundle.py` ready；clean 副本严格自签验证通过。v19 完成两次全新真实屏幕监测：10x 三步向导逐步显示 1000×600、3000 个非零条目、99.50% 稀疏度、950 Gene Expression/50 Antibody Capture 及 pseudobulk 边界；company count 全链路完成并进入结果页，未留下 Rscript 进程。正式发布仍受 Developer ID、公证、内置 R.framework 和干净 Mac 条件限制。

## 2026-09-13 · 阶段 5 · v20 GEO 三步向导、压缩候选树与最终双屏验收

具体变更：GEO Series Matrix 新增“数据与平台事实→样本注释来源→分析含义确认”三步导入向导，展示平台、GSM、sample title，并明确本地离线、人工确认和不自动上传/猜分组边界。压缩包候选对象改为层级目录树，分别展示类型/用途、形状与文件大小、完整性，并保留来源路径提示；同时修正 py2app 构建配置，避免新 setuptools 将项目依赖误传给 py2app。

验证：源码回归 `.venv/bin/pytest -q` → `59 passed, 1 skipped`；v20 standalone `packaging/verify_bundle.py` 返回 `ready: true`，Apple Silicon、Rscript、jsonlite、limma、statmod、DESeq2 和 worker 资源均通过；clean 副本 `codesign --verify --deep --strict` 通过。最终 bundle 完成两次全新真实屏幕监测：第一次从 GEO 测试 Series Matrix 逐步走完三页并看到 4 个 GSM、sample title 和 GPLV20；第二次从公司 count TSV 完成表头/列角色、原始 count/线性尺度、整理、分组、DESeq2 R worker 和结果页，等待期间显示已等待秒数，完成后生成离线 HTML/XLSX/5 张图，未留下 Rscript 进程。正式 Developer ID 签名、公证、内置 R.framework 和干净 Mac 验收仍需发布环境。

## 2026-09-13 · 阶段 5 · v21 标准化表达敏感性验证

具体变更：新增 `tests/test_normalized_sensitivity.py`，在不调用应用自身转换、规划或 R 适配代码的前提下，用独立 limma 实现 36 个组合：过滤阈值 0.5/1/2、伪计数 0.1/0.5/1、robust TRUE/FALSE、均衡/不均衡深度。测试固定合成底层表达和预指定 200 个强效应特征，记录测试数、显著数和方向一致率；默认 profile 仍由产品约定固定，不按显著数最大化选择。

验证：`PYTHONPATH=src .venv/bin/pytest -q` → `60 passed, 1 skipped`；36 个敏感性组合全部执行，均衡深度下预指定强效应方向一致率达到 95% 门槛。本轮只使用本地合成数据，未下载实验数据或改写用户原始文件。v20 standalone 双屏验收结果保持有效；正式 Developer ID 签名、公证、内置 R.framework 和干净 Mac 验收仍需发布环境。

## 2026-09-13 · 阶段 5 · v22 R worker 取消与最终微型验证屏幕验收

具体变更：新增慢 worker 取消回归，使用独立等待进程确认取消令牌会终止子进程，而不是只更新界面按钮。此前 macOS 锁屏导致的最终包运行时页验收已在解锁后补做。

验证：`PYTHONPATH=src .venv/bin/pytest -q` → `61 passed, 1 skipped`；最终 standalone 包中实际点击“运行 limma 微型验证”，画面先显示“R worker：正在等待独立 R worker 返回（已等待 2 秒）”，随后显示“limma 微型验证通过”；DESeq2 微型验证同样显示通过。检查进程列表无残留 Rscript/worker。未读取或修改用户原始数据。正式 Developer ID 签名、公证、内置 R.framework 和干净 Mac 验收仍需发布环境。

## 2026-09-13 · 阶段 6 审计 · 当前包的正式发布缺口

离线运行 `packaging/release_check.py` 对当前 `packaging/dist/RNA-Seq Helper.app` 做发布审计。结果明确为未就绪：原始 bundle 的严格签名检查未通过，当前没有可用开发者签名身份，包未内置 `R.framework` 而依赖本机 `/usr/local/bin/Rscript`；clean 副本的 ad-hoc 严格自签只能证明本机副本完整，不等同 Developer ID 或公证。干净 Mac、中文/空格路径、断网、权限和休眠恢复仍需发布环境验证。

## 2026-09-13 · 阶段 6 候选 · v23 内置 R runtime

具体变更：`packaging/embed_r_runtime.py` 将系统 R.framework 的最小可用子集复制到 app 内，包含 R 4.6.0、base/recommended 包以及 DESeq2、limma、jsonlite、statmod 的递归依赖；只读系统 R，不下载、不覆盖系统文件。由于官方 Rscript 的 Mach-O 启动器内含安装时绝对 R_HOME，候选包使用 app 内 wrapper 将脚本调用转发到 app 内 exec/R；同时重写 R 组件的绝对动态库依赖并做本机 ad-hoc 签名。`runtime_paths` 优先解析冻结 app 内 Rscript，RBridge 对内置 runtime 清空用户 R 包库。

验证：源码 `.venv/bin/pytest -q` → `62 passed, 1 skipped`；`packaging/verify_bundle.py` 返回 `ready: true`，直接检查到 R.home 位于 app 内，limma/DESeq2/jsonlite 均为 TRUE，limma/DESeq2 微型验证通过；clean 副本 `codesign --verify --deep --strict` 通过。Developer ID、公证、干净 Mac、断网/休眠/权限和安装器验证仍待发布环境。屏幕验收需在 Mac 解锁后补做两次。

补充：`verify_bundle.py` 现在支持 `--app`，已对 clean v23 副本再次运行 bundle 自检、limma 和 DESeq2 微型验证，Rscript 路径均位于对应 app 内 `Contents/Frameworks/R.framework`，未发现残留 Rscript 进程。

## 2026-09-13 · 阶段 6 候选 · v24 运行时取消与导入缩略图

具体变更：运行时验证页新增“取消当前验证”，取消令牌直接作用于当前 RuntimeWorker；limma/DESeq2 结果与失败信号分别关闭对应线程，避免全局线程引用在快速重复点击时误关旧任务。导入页新增当前表和转置表的离线 Qt 缩略图，用于方向/表头审查；压缩包候选树保留参考文件但将其标记为不能作为表达矩阵，表达候选与参考用途不再混淆。安全展开前增加目标卷剩余空间检查。

验证：定向 UI/运行时/路径回归 `9 passed`，完整源码回归 `.venv/bin/pytest -q` → `63 passed, 1 skipped`；v24 standalone 重建后 `packaging/verify_bundle.py --app` 返回 `ready: true`，Rscript 位于 app 内 `Contents/Frameworks/R.framework`，四个核心 R 包可加载；clean 副本 `codesign --verify --deep --strict` 通过，`release_check.py` 仅保留 ad-hoc 签名阻断。v24 的真实屏幕复验目前被 macOS 锁屏阻断，不能用命令行结果冒充屏幕证据；未读取或修改用户原始数据。正式 Developer ID、公证、干净 Mac 和安装器仍待发布环境。

## 2026-09-13 · 阶段 6 候选 · v25 设计字段与原始输入提示

具体变更：修正 `AnalysisService` 到 R worker 的设计协议，除保留 `paired_subjects` 审计字段外，按 worker 约定显式传递 `subject`，避免配对信息在 R 端被静默忽略；批次字段继续显式传递。导入页对 FASTQ/BAM/SAM、GPL/SOFT/annot、辅助文件和未知文件给出对应中文下一步，不再统一显示为无意义的“不是表达表格”。

验证：批次/配对 payload 捕获回归、导入页缩略图/参考候选/原始测序指引和运行时回归后，完整源码回归 `.venv/bin/pytest -q` → `65 passed, 1 skipped`。v25 standalone 重建后 clean 副本 bundle 自检 `ready: true`，R 4.6.0、jsonlite、limma、statmod、DESeq2 均从 app 内加载；limma/DESeq2 直接微型请求均通过，进程列表无残留 Rscript。屏幕监测仍被 macOS 锁屏阻断，未以命令行结果替代屏幕证据；未读取或修改用户原始数据。正式 Developer ID、公证、干净 Mac 和安装器仍待发布环境。

## 2026-09-13 · 阶段 6 候选 · v25 解锁后双屏验收完成

验证：macOS 解锁后对 v25 clean bundle 完成两轮真实屏幕监测。第一轮在“运行时验证”页点击环境检查、limma 微型验证和 DESeq2 微型验证，界面分别显示内置 Rscript 路径、limma 通过和 DESeq2 通过，等待期间取消按钮正常启用并在结束后恢复禁用。第二轮使用 `company_counts.tsv`，屏幕显示表头第 3 行、数据第 4 行、原始 count/原始线性尺度、当前/转置离线缩略图、control/test 各 3 个样本；确认计划后启动独立 DESeq2 worker，结果页显示分析完成、离线 HTML、`reports/deg-results.xlsx` 和 `figures/` 五张图。结果 HTML/XLSX 同时保留“小于最小基因数”的告警，说明这是 4 基因合成 fixture 的预期限制，不冒充真实数据无告警。进程检查仅见 GUI/CUA 进程，无残留 Rscript 或 worker。未读取或修改用户原始数据。正式 Developer ID、公证、干净 Mac 和安装器仍待发布环境。
