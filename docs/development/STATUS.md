# 开发状态

## 2026-10-05 · 按用户要求清理临时材料

- 已将 `docs/development/evidence/` 中 17 张历史验收/离屏截图移入废纸篓；相关文字记录保留，但这些截图路径不再可用，不能作为当前验收证据。
- 删除了可再生成的 pytest/Python 缓存、临时 p 值 smoke-test 图片及空临时目录；将一个已停止进程产生的 0 字节 fatal 日志移入废纸篓。
- 复查用户文档目录的运行产物后，将 75 个仅含 `tenx-manifest.json`、且来源均为 pytest 临时目录的 10x 测试项目，以及 8 个空项目目录移入废纸篓。保留真实 GSE10361 分析项目和有完整导入验收材料的 `company_counts-817d2e29` 项目。
- 合并了 6 份重复/已过时的交接总结与续接提示词为 `HANDOFF.md`；原件移入废纸篓以便恢复。规格、验收、结果审计和崩溃诊断等用途不同的记录继续单独保留。
- 保留 `tests/fixtures`、真实分析结果、尚有审计/回退用途的候选包和源码快照。清理不涉及应用安装版或用户项目。

## 2026-10-04 · 真实结果复核补充与 p 值图注修正

- 对现存 GSE10361 项目再次只读核对：单表五列 XLSX 与 JSON 22,283 行逐格一致（`NA`/`null` 按缺失值等价）；五张图文件齐全。旧项目中的 p 值直方图把表达转换 `log2(x+1)` 错标为 p 值图副标题，已在源码移除并补测试。
- 定向绘图测试 **7 passed**；完整回归 **194 passed、1 skipped（43.61 秒）**。新隔离候选 `/private/tmp/rnaseq-helper-pvalue-fix.9nMdW4/RNA-Seq Helper.app` 源码同步、内置 R bundle 自检、limma/DESeq2 CLI 微型验证、图注 smoke test 与严格 ad-hoc 签名通过。
- 旧项目图未覆盖、未重跑分析；候选未实屏验收；`/Applications/RNA-Seq Helper.app` 未更新。旧分析输入的 FPKM/LINEAR 仍无直接来源依据，分析结果的输入事实核验未通过。后续需补齐来源尺度/公式后在软件中重跑，才能生成完整更新的实际报告。

## 2026-10-04 · GSE10361 实际结果核验与来源冲突门禁

- 实际项目 `~/Documents/RNA-Seq Helper Projects/GSE10361_series_matrix.txt-58d06b3f` 的 JSON、HTML、五列单表 Excel 和五张图在内部计数/顺序/数值上吻合；Excel 全行逐格对比一致，独立 R/limma 复算误差 < `8.1e-15`。这只证明保存参数下流程可重现。
- 发现实际 recipe 在无关联来源文本下手动选择 FPKM/LINEAR；GEO 原文件却明示 `!Series_type=Expression profiling by array`、GPL96。原 HTML错误写成“已确认 FPKM”。用户要求仅审软件流程，本条不含生物学解释。详情见 `RESULT-AUDIT-2026-10-04.md`。
- 已修复：读取并持久化 GEO `Series_type`；在整理校验和分析规划两层阻断明确 array 来源与 raw count/TPM/FPKM/RPKM/CPM 标签冲突；保留通用连续表达值路线和未知尺度门禁。用户手动选值但没有来源文字时，记录和方法说明不再将其包装成来源已核实。五列 Excel 契约未动。
- 用本地 GSE10361 原文件（只读）验证：FPKM/LINEAR 被准确阻断；改成 OTHER_NORMALIZED 后数据整理通过，单位/尺度仍不由软件猜测。定向 43 passed；完整回归 **193 passed、1 skipped**。
- 隔离候选 `/private/tmp/rnaseq-helper-result-audit.G1cGvP/RNA-Seq Helper.app` 已同步修复，源码目录比较一致，ad-hoc 严格签名及 standalone R/limma/DESeq2 CLI 自检通过。未做 GUI 实屏/用户操作验收；未更新 `/Applications`；旧用户结果、Excel、图保持原样且仍不应视为通过事实核对的分析结果。MySQL 未登记（凭据轮换尚未确认）。
- 使用候选自己的 Python 3.14.7 对真实 GSE 输入复跑门禁：识别 GPL96/array，阻断 FPKM；通用连续表达值整理校验通过，未选尺度或运行分析。

## 2026-10-04 · 最新用户成功反馈与交接总结

- 用户确认已使用软件得到结果并找到Excel，随后撤回7列修改要求，明确维持现状；没有实施导出代码/文件修改。当前源码仍单工作表5列。
- 本次只读核对运行版本已是HADQ06 PID40930；同PID私有fatal日志已建立、0字节。此前“仍是旧候选/新版未运行”的状态过时，不再要求重复切换。当前候选源码全目录及Resources/app.py与源码一致。
- 用户本次具体输入、转换/分组、结果项目及输出尚未逐项核验；成功使用不等于原生崩溃根因已修复、完整科学/桌面验收通过。下一轮优先审查本次实际结果。
- 当前交接见 `HANDOFF.md`。本次仅生成总结和更新此状态，无产品改动、测试重跑、构建、屏幕操作、安装覆盖或MySQL访问；最近完整回归仍188/1。

## 2026-10-04 · 诊断入口最终启动降级保护

- Luna/MAX最终只读复核确认前述修正，又发现不可写stderr的警告输出边界；已保护None、关闭及OSError，定向13 passed，最终完整 **188 passed、1 skipped（48.43秒）**。
- HADQ06原路径只更新诊断模块/字节码并重签名，源码全目录一致、strict签名通过。diagnostics当前SHA256 `f4b0251d07410c8cc641aac0316565d2385bbc683de2b95224b91c0a18b08dbc`；下方185项与旧摘要属于此前修订。CLI/R分支未改，不重复其自检/profile。
- 无屏幕操作；Hx6JkY PID37964仍在运行，未覆盖安装版。README入口更新为HADQ06。600秒说明与默认值已核对一致；崩溃根因、新候选实屏/真实分析、安装版更新、正式发布仍未完成，不能标记目标完成。MySQL未访问。

## 2026-10-04 · GUI 致命信号线程栈留存（不是崩溃修复）

- GUI启动前启用私有faulthandler日志，句柄保留至进程退出，覆盖窗口返回后的清理阶段；CLI不启用，初始化失败不阻止启动，下一次启动仅清理已停止进程的空诊断文件。Luna/MAX只读审查发现的失败清理及描述符遗漏已修正。
- 定向10 passed；最终完整回归 **185 passed、1 skipped（47.90秒）**。真实非fatal线程栈退出测试经过main分支，但未启动实屏GUI或故意触发崩溃。
- HADQ06隔离候选原路径更新lib/app.py、crash_diagnostics及实际入口Resources/app.py/字节码，源码全目录/入口一致、严格ad-hoc签名及CLI自检ready=true通过；未重跑未改变的R微型profile。app SHA256 `d286772fe539ff1353e95d92075b5141e4cf128707ad2f5335cdf4f3e0266a97`，diagnostics SHA256 `aa04f33109d5f238c5561896e4c0546d5c517089dfef26739d4f442be89bd518`。
- 用户仍运行Hx6JkY PID37964，未操作/覆盖；安装版未改，原生崩溃未修复、新版布局/真实分析桌面验收仍待完成。详见 `CRASH-DIAGNOSTICS-2026-10-04.md`；MySQL未访问。

## 2026-10-04 · GSE10361 官方单位依据补齐，尺度仍待确认

- 只读核对本地头部与官方GSM260537数值列说明、示例值，确认是GPL96芯片SIGNAL，排除原始RNA-seq count/TPM。原论文说明人体PLIER及GeneSpring后续归一化，但不证明当前导出矩阵的log底数/公式；不代替用户确认尺度或放宽门禁。
- 本地三列0h、三列72h、三列CtrPlate及重复个体标记要求明确比较/配对，不能将全部列当独立疾病病例。证据与来源见 `GSE10361-FACTS-2026-10-04.md`。
- 未下载新矩阵、改产品、跑R/回归/构建或更新安装版；HADQ06桌面待验，原生崩溃未修复，MySQL未访问。

## 2026-10-04 · 用户手动导入证据与紧凑识别 UI

- 用户提供三张界面截图/应用快照：GSE10361出现已扫描候选，进入结构页显示真实ID_REF/GSM/表达值预览，再进入数值确认页；该段手动操作未报告崩溃。快照附带AX文本，不能称完全没有辅助功能访问，也不能推断之前Qt Cocoa崩溃已消失。当前进程核对为Hx6JkY PID37964，未操作/终止或覆盖用户窗口。
- 截图暴露重复整段说明挤占预览。已将整理页改为摘要＋当前必要问题，证据单独限高180px滚动显示，未知输入默认折叠；原文候选默认展开，折叠后禁用一键确认。统计/UNKNOWN门禁未改。内容底部增加伸缩空白，避免问题页占满空余高度。
- 定向35 passed；最终完整回归 **176 passed、1 skipped（47.81秒）**，包含此前两个生命周期探针和本次两个UI合同。离屏1024×768预览y242、高192、视口502，未溢出；820×560视口294，滚动范围151。属于无主窗口样式的Qt页面几何检查，不代替实屏/黑白模式验收。
- 新隔离UI候选 `/private/tmp/rnaseq-helper-compact-ui.HADQ06/RNA-Seq Helper.app`：复用Hx6JkY runtime，只更新ImportPage/字节码，源码全目录一致、严格ad-hoc签名通过；ImportPage SHA256 `07e961323e333b9a23452824faefd5b4157cb8f04c13209642e31a0e594a2c2f`。Bundle自检ready=true、limma/DESeq2 CLI微型验证通过。Hx6JkY保留供用户当前运行；未更新安装版、未访问MySQL。
- 崩溃仍未修复，不能用UI修订或用户这段成功操作宣布整个目标完成。下一步验收新候选布局，原生崩溃分型独立保留。

## 2026-10-04 · 有界生命周期测试，尚未复现 Cocoa 崩溃

- 新增两个独立进程生命周期测试，15秒硬限额，定向 **2 passed（1.14秒）**：激活辅助功能的表格选中/重置/GC50轮；产品ImportPage创建/DeferredDelete/GC20轮。
- 未激活辅助功能的缓存无效对照不是产品失败证据；激活后通知更新正常。未复现外部AX/Cocoa原生崩溃，不据此宣称修好或添加猜测补丁。
- 产品代码与候选未改，未重跑全量/构建。最近全量仍172/1；当前候选仍桌面验收失败。详情 `CRASH-2026-10-04.md`；下一步需要原生接口所属控件的有界最小复现，不能重复CUA AX查询。

## 2026-10-04 02:06 CST · 最新候选发生原生崩溃，切换诊断方法

- Hx6JkY 最新源码版本 PID36715 在真实 GSE10361 扫描期间退出，新的 RNA-Seq Helper-2026-10-04-020615.ips 明确归属该进程。主线程 SIGSEGV0x10，Qt Cocoa 的选中项辅助功能接口调用与 AXCopyHierarchy 栈；没有扫描完成证据。当前状态为**候选桌面验收失败**，不能以 CLI/172项回归通过覆盖此结果。
- 已只读分析报告、反汇编对应 PC 并核对 Qt6.10.3 官方源码。停止对候选读取 AX，不再重复点击/截图/构建。另有 PID34701 的 Shiboken/QWidgetItem GC 崩溃，归属尚不足，需独立分型，不能合并为同一原因。
- 下一步改为有界最小进程复现及原生接口/包装对象生命周期诊断；尚无修复补丁，安装版未改。Luna/MAX 审查因用量限制失败，无结果；MySQL 未访问。详见 `CRASH-2026-10-04.md`。

## 2026-10-04 · README 关联规则修复（最新源码基线）

- 发现 scanner 将 README 自身文件名误作表达表关联证据，可能在多表目录错用单位/尺度；短表达表名又会漏关联。先以两个失败测试复现，再改为当前表达表文件名/允许的长 stem 的边界匹配，避免其他文件名子串命中。新增四项文字合同测试，不作为真实生物数据识别准确率证据。
- 定向 **34 passed**；稳定后完整回归一次 **172 passed、1 skipped（47.35 秒）**。保留 UNKNOWN、冲突和多工作表门禁，未改变统计、转换或读取线程。
- 同一路径 Hx6JkY 候选已更新 scanner 源码/字节码并重新签名，没有重建 py2app/R runtime。全包 Python 源码比对一致，严格 ad-hoc 签名通过；bundle 自检 ready=true，limma/DESeq2 CLI 微型验证通过。scanner SHA256 `83666d61762e00c5bc420622eb9f1d7dd34b1d0964a3b90cd78a8c61977c521d`。
- 下方 GUI/GSE 组件证据均早于这次 scanner 更新，不能算新版本桌面通过。当前仍待完整扫描/预览、拖放、布局和取消/关闭验收；安装版未覆盖，MySQL 未连接。

## 2026-10-04 01:55 CST · 新真实 GSE 的受限组件验证

- 主机 Python 明确加载当前 Hx6JkY 包内 scanner/preparation 组件，15 秒子进程限额下只读 GSE10474：扫描、40×35 预览、完整读取/校验完成，22,277 个特征×34 个样本、757,418 数值单元格。
- 输入 2,124,974 B，SHA256 `3cbf46e72f45f39da53f89c9c49aad0d24e83ea70c60f48135d7cccbc6976ee4`，前后未改。单位/尺度 UNKNOWN，UNKNOWN_MEASUREMENT/UNKNOWN_SCALE 阻断，0 个项目输出，临时空项目自动清理。本次约 0.1778 秒、峰值 RSS 103.33 MiB，仅为组件单次诊断。
- **不代表 .app 或 GUI 通过。**运行上下文与卡住的桌面进程不同，输入也不是 GSE10361，原文件打开阻塞原因仍未确认；普通选文件/拖放、布局、正式分析及安装更新条件仍未满足。
- 没有重跑回归/构建或改产品代码。中断前 tccd 查询句柄已不存在，未重启查询，不能据缺失输出判定授权状态。详细范围见 `CANDIDATE-ACCEPTANCE-2026-10-04.md`；MySQL 仍未访问。


## 2026-10-04 01:50 CST · chooser 修复、168 项回归与真实路径复验

**当前结论：新候选自检通过；真实 GSE 路径输入卡顿已解除，GUI 扫描/整体验收仍未完成，安装版未更新。**

- Luna/MAX 仅修改 ImportPage 的三个 chooser：统一关闭 filename 自动补全和 QFileSystemModel 目录监视，保留打开/取消、多选、10x 目录和参考过滤。新增真实 Qt 控件测试，定向 **6 passed**；主流程一次全量回归 **168 passed、1 skipped（46.63 秒）**。
- 当前验收目标：`/private/tmp/rnaseq-helper-chooser-candidate.Hx6JkY/clean/RNA-Seq Helper.app`。复用 UtT843 验证过的 runtime，更新唯一改动产品文件与字节码、重新签名，未重跑 py2app/R 依赖构建。全 Python 源码目录比对一致，ImportPage SHA256 `fa8fedb322317102e6a4ff47aac423c8bcc0facbf6d66b9f93aa82e0f76496aa`；worker 未改。Bundle 自检 ready=true、limma/DESeq2 CLI profile 通过，启动后严格 ad-hoc 签名再次通过。
- 新候选 GUI 用相同真实 GSE10361 路径，1.19 秒组合输入调用正常返回，主窗口显示文件名与扫描中；没有旧 QCompleter 主线程卡顿。但尚未观察候选结果，后台停在文件打开调用，随后工具确认电脑自动锁屏。未复查截图/要求值守；核对 PID 35379 后 SIGTERM 结束未交付的测试任务。扫描完成、事实门禁和正式分析不能记为通过。
- UtT843 的 GUI 两个 R 微型验证及立即取消有本轮证据；新候选目前只有 CLI 和真实路径输入证据，不把旧包的 UI 结果当成新包完整桌面复验。双尺寸、Finder 拖放、整理取消/关闭仍待补。
- 独立核对 GSE10361/GSE10474 头：前者处理字段含糊，后者写 GCRMA；本地 RMA 重处理对象与提交矩阵不同，不能混用方法确认尺度。两份压缩矩阵分别 1,645,548 B 和 2,124,974 B，原始数据只读。
- 清理：两份更早 obwEZq/qDAcnT app 移入废纸篓，约 3.4 GiB，可恢复；未清空废纸篓、不宣称释放对应空间。保留 qDAcnT 取消负载且摘要一致，移除空旧入口及四个空微型任务目录。UtT843、源码快照和本次采样保留为必要故障对照。
- 详见 `CANDIDATE-ACCEPTANCE-2026-10-04.md`。MySQL 尚无轮换确认，未连接或登记新记录。


## 2026-10-04 01:34 CST · GUI R 信号验收通过，路径输入卡顿待修

**当前结论：候选未获整体验收通过；文件选择器键盘路径输入出现可定位卡顿，安装版未更新。**

- UtT843 候选 PID 33700 的 GUI limma、DESeq2 微型验证各显示“通过”，启动/进度/完成及按钮恢复已有当前实屏证据。立即取消运行中的独立 DESeq2 微型任务显示“任务已取消”，按钮恢复；首次点击时任务已结束的尝试不计为取消证据。完整整理取消/关闭仍待验证。
- GSE10361 的一次键盘路径输入尝试超时，未完成导入。2 秒 `sample` 显示主线程停在 `QCompleter → QFileSystemModel::fetchMore → QFileSystemWatcher::addPaths → __opendir2/__open_nocancel`，非 AX 崩溃栈；Finder 仍响应、无对应新退出报告。已核对 PID/path 后 SIGTERM 结束无响应测试进程；不是正常 GUI 关窗通过。
- Luna/MAX 正在做最小 chooser 修复和独立本地 GSE/冗余盘点。产品代码变化后需定向/全量回归和一个新候选，旧包暂保留作故障对照。详细证据见开发日志顶部。
- 已清理本轮四个微型任务的空临时目录；当前候选签名复核通过。没有访问 MySQL，也没有安装版更新。


## 2026-10-04 · 更新目标后的候选桌面初检

- 现有最终候选仍存在：`/tmp/rnaseq-helper-r2-release-candidate.UtT843/clean/RNA-Seq Helper.app`。整个包内 `rnaseq_helper` Python 源码目录与当前源码比对无差异（排除字节码缓存），R worker 摘要也相同；未重建、未重跑回归。
- 桌面工具已按候选完整路径打开主窗口并观察添加数据页，初始页可读；Finder 已定位 GSE10361 所在目录。尚未执行选文件、拖放、双尺寸布局或正式分析，不将启动观察算作完整桌面验收。
- 工具要求操作后读取 AX 状态，Qt 文件选择器有既往 AX 崩溃证据，故未打开选择器进行冒险探测。普通文件选择仍转人工；不循环等解锁。
- 修正人工验收清单中已删除的旧候选路径，并补入 GSE10361 真实验收步骤。现有 UNKNOWN/UNKNOWN 负例不能支撑完整分析通过，需真实处理说明及分组证据后才能继续正式统计。
- README 默认 600 秒与 models 一致；`packaging/build`、`packaging/dist` 仍不存在，本轮无新增可确认删除项。安装版未改，MySQL 仍因凭据事件暂停访问，尚无轮换确认。


## 2026-10-03 17:04 CST · AI 复核整改与最终隔离候选

**当前结论：② 隔离候选本机自检通过，待人工桌面验收；安装版未更新。**

- 当前唯一保留候选：`/tmp/rnaseq-helper-r2-release-candidate.UtT843/clean/RNA-Seq Helper.app`（约 1.7 GiB）。Bundle 自检 `ready=true`，内置 arm64、R 4.6/75 个包，limma 与 DESeq2 微型 CLI profile 均就绪；`codesign --verify --deep --strict` 通过（ad-hoc）。7 个关键产品文件源码/包内 SHA256 完全一致：models、scanner、ImportPage、preparation service、planning、background worker、`worker.R`。
- 本轮代码最终全量回归 **162 passed、1 skipped（62.02 秒）**；研判/账本/门禁定向组 **35 passed**。唯一 skip 是已安装 DESeq2 后不适用的缺包分支。
- 两轮 Luna/MAX 只读审查提出的边界均已处理：姓名/临床上下文整句隐藏；带明显患者/样本/中英文编号标记的来源路径、工作表名和归档成员路径在序列化时隐藏；公式采用变量白名单；同值证据去重但保留所有冲突候选及最多两种不同 log2 公式；英文/中文否定表述不当作 log2 正证据；候选证据优先展示，脱敏与安全摘录不会被重复项去重掉。
- sidecar 读取设有 4 份、256 KiB/份、512 KiB 合计、3000 行、8192 字符/行上限。枚举/读取/解码失败、超限或扫描不完整时，整批说明候选不参与判断并禁用一键确认；用户仍可人工对照原文逐项确认。无标签的人名无法可靠自动发现，样本列数据仍按分析流程存于用户本机项目中；不能把软件描述为临床数据匿名化工具。
- 已确认 `OTHER_NORMALIZED + LOG2` 的分析门禁：仅当整理账本有明确用户尺度确认时才生成 provenance 标记并放行；UNKNOWN 和无确认的 LOG2 仍被阻断。已补完整理→分析规划契约测试。
- 真实 GSE10361（1,645,548 B）只读复扫：GEO Series Matrix，单位/尺度仍 `UNKNOWN/UNKNOWN`、0 条文字事实候选；没有独立 R 分析、矩阵写出或项目结果。该负例只证明未知门禁保留，不代表识别准确率验证。其余新测试是字符串/序列化契约，不用于生物学判断。
- 清理了被替代的两份 1.7 GiB 临时候选、被中止构建的临时目录，以及重新生成并验证候选后的 `packaging/build`、`packaging/dist`；现在只保留最终候选。没有触碰 `/Applications/RNA-Seq Helper.app` 或桌面 alias。
- **仍待人工：**当前 GUI 的普通选文件、Finder 拖放、窗口缩放/黑白模式、事实/列角色/分组页布局、实屏取消/关闭，以及 GUI“运行 R 微型验证”信号链路均未验收。遵照无人值守指示，没有进行截图、AX 或鼠标操作；bundle 自检/CLI 不等于实屏通过。
- **MySQL 未同步/未复核。**先前读取规则时过滤失误造成凭据值出现在工具输出，之后没有连接数据库或执行 SQL。请先轮换本机 MySQL 凭据；未收到轮换完成证据前不再读凭据或连库。

具体审查意见、修复、测试和 bundle 路径见 `DEVELOPMENT_LOG.md` 顶部。下方 16:14 及更早记录为历史状态。

## 2026-10-03 16:14 CST · 文字证据、确认账本与新隔离候选

**当前结论：② 新隔离候选的本机自检通过，仍待人工实屏验收；安装版未更新。**

- 当前候选：`/tmp/rnaseq-helper-r2-evidence.im2GgT/clean/RNA-Seq Helper.app`，约 1.7 GiB。py2app 与 R 4.6（75 个包）内置完成；`verify_bundle.py --app` 返回 `ready=true`，包内 limma/DESeq2 微型验证均返回预期方法；`codesign --verify --deep --strict` 通过（本机 ad-hoc）。
- 本次代码改动后的全量回归：**146 passed、1 skipped（57.99 秒）**。定向组为 **49 passed**。真实 GSE10361（1,645,548 B）再次只读扫描，结果仍是单位/尺度均 `UNKNOWN`、无事实证据命中；没有创建分析矩阵或项目结果。文本模式测试只验证引用定位和门禁契约，不作为真实数据自动研判准确率证据。
- 新增文字证据结构：保留事实类别、候选值、文件/工作表单元格或说明文件行号、原文短摘录；截断有省略标志，标识与非公式数字做脱敏。仅扫描表格前 8 行×最多 80 列的文本单元格；不根据数值大小/整数性推断。
- 允许只读关联同目录 README/说明/交付文本，单个≤256 KiB、合计≤512 KiB、最多 4 份；不跟随符号链接、不解压不联网。多表目录需说明明确点名当前文件；多工作表工作簿还需点名当前 sheet。无法关联或事实冲突时不采纳候选，继续 UNKNOWN。
- 事实页新增“确认并采用文件原文候选”按钮；只填入当前表有无冲突的文字候选，缺项仍未知。整理配方与 `project.json` 分别记录每项候选、用户选择状态、关联证据；唯一无冲突的 `log2(...)` 公式单独记作 `reported_transform`，不写入分析用的 `input_transform`，不影响统计语义。UNKNOWN 整理/分析门禁保持不变。
- 源码与新候选的 `models.py`、`scanner.py`、`import_page.py`、`preparation/service.py`、`background_jobs.py`、`worker.R` SHA256 均一致。旧 1.7 GiB 临时候选及本次 `packaging/build`、`packaging/dist` 已在新候选验真后删除；新候选保留。桌面 GUI、选择器/拖放、页面布局、GUI R 按钮、实屏取消/关闭仍未验证；未通过屏幕证据前不更新 `/Applications/RNA-Seq Helper.app`。
- MySQL 元数据**本轮未同步/未复核**：读取连接规则时发生凭据不应回显的安全失误，之后未连接数据库或复用凭据。需用户先轮换本机 MySQL 凭据，再安全更新登记；不得把本状态误读为 MySQL 已同步。

具体实现与审查意见见 `DEVELOPMENT_LOG.md` 顶部；新候选路径替代下方历史候选。下方较早记录只作时间顺序证据。

## 2026-10-03 15:15–15:34 CST · R2 真实数据、超时边界与参考闭环核验

**当前结论：② 最新隔离候选仍待人工实屏验收；真实小型 GEO 输入的源码导入/取消契约已新增一组数据证据。**

- 只读测试了 Codex's House 中的真实 GEO Series Matrix：`/Users/additionlee/Desktop/Master.nosync/agent/Codex's House/SEALI_ALI/0_Raw/GSE10361_series_matrix.txt.gz`，1,645,548 B，SHA256 `46f02f0ee04be5ba349d46061ee26c697f8be5b37a04b55a4accf32adce80746`。未改写原文件，也没有下载数据。
- 当前源码导入器识别为 GEO Series Matrix；有限预览约 0.0065 秒、40×10；扫描约 0.002 秒；全量读取及验证约 0.0961 秒，解析到 22,283 个特征、9 个样本。输入本身未明确测量单位或变换，应用正确以 `UNKNOWN_MEASUREMENT`、`UNKNOWN_SCALE` 阻断，未保存矩阵或生成项目产物。
- 后台取消探针在验证进度 2,000 行后请求取消，约 0.001 秒 worker 退出；该短任务总计约 0.0041 秒。10 ms Qt 心跳的最大事件循环间隔约 46.7 ms、P95 约 15.8 ms。进程峰值 RSS 约 164.3 MiB（macOS `ru_maxrss`）。
- 以上是本机、离屏、一次性小文件实测，不代表大于此文件的吞吐、GUI 视觉/鼠标响应或长时稳定性；事件循环心跳不能替代屏幕验收。临时测试项目目录为空；候选和 `/Applications` 安装版均未更动。
- 对隔离候选做了不重建的源码比对：`background_jobs.py`、`worker.R`、`import_page.py`、`scanner.py` 四个文件均与当前源码 SHA256 一致，分别为 `16d89339d7cd3658f35451460f4913bb0835abd97e319bee0756580987259a62`、`22cd26e83d92d0f7ede7b50839ee98dcc6dca3bdb009956434582ff051e4839e`、`3d465451675cd7742933efe35175405c2b48d6f5c1a93a1a1f14aa9b49f233c1`、`6466d7d941f20920a94f05519f86123de6e8cec41b92eb93d4006530b9e3f2c6`。
- Luna/MAX 子代理只读核对：用户级缓存仅 1 个 335 B JSON，含 2 条映射，但 `species_taxid`、`platform_id` 为空，且源码没有缓存读取路径，因此不能作为已验证可复用缓存。系统 R 有 `AnnotationDbi 1.74.0`、`org.Hs.eg.db 3.23.1`，无小鼠/大鼠 OrgDb；候选 bundle 内置 R 库 75 个包，但缺 `AnnotationDbi` 和三种 OrgDb。
- 本地文件盘点：`GPL6947_HumanHT-12_V3_0_R1_11283641_A.bgx` 及 `GPL10558` 的 R1/R2 两份表头包含 `Probe_Id`、`Symbol`，与 GPL reader 列名契约兼容（尚未实跑完整映射）。`GPL19983...desc.annot.txt.gz` 首行不是该契约表头，不能按现有 reader 计作可用映射。另有 `GPL13667_family.soft.gz`，大小约 6.04 GB，仅核对文件元数据，未打开/导入；归档目录有 `GPL13667_annot.tsv`，内容尚未验证。TCR/BCR contig annotation 不计作 gene-symbol GPL 表。
- 超时复核：唯一默认 `JobContext.timeout_seconds=600`，未找到调用点覆盖；R bridge 在请求写入并关闭 worker stdin 后开始等待计时，约每 0.25 秒轮询，达到门槛后终止子进程。README 已明确不含 worker 启动/请求准备及响应后的 Python 处理，也不覆盖整个导入、绘图或报告流程。本轮只改文档，没有改产品代码或重跑测试。
- R2 续接提示词已同步成当前事实：旧候选路径不再作为验收目标，已明确最新隔离候选、超时修复、自动研判规格与真实数据/参考盘点均已完成；实屏 GUI 项保留为未验证，避免下一轮重复构建或误把命令行验收说成桌面通过。
- 现有逻辑只读用户参考文件、尝试运行时 OrgDb、并写缓存；没有缓存优先读取、自动下载、精确物种/平台/release 一致性校验或原子/并发安全缓存更新。参考闭环留作独立后续工作，设计与完成条件已记录在 `DEVELOPMENT_LOG.md`；不将现有本地映射/缓存写入描述成下载闭环。
- 隔离候选仍为 `/tmp/rnaseq-helper-r2-final-candidate.PI00wN/clean/RNA-Seq Helper.app`；未启动候选 GUI，也未替换 `/Applications/RNA-Seq Helper.app` 或桌面入口。手动屏幕验收仍待用户方便时执行；不因当前未值守而等待或反复探测。

真实输入与性能细节记于 `DEVELOPMENT_LOG.md` 顶部。此前 15:01 状态快照及更早记录保留作历史证据。

## 2026-10-03 15:01 CST · R2 续接最新状态

**当前结论：② 最新隔离候选本机自检通过，仍待人工实屏验收。**

- 最新候选：`/tmp/rnaseq-helper-r2-final-candidate.PI00wN/clean/RNA-Seq Helper.app`。py2app 与内置 R 构建通过；ad-hoc 严格签名检查通过；`verify_bundle.py --app` 为 `ready=true`，内置 R 4.6、limma、DESeq2 和两个微型 profile 可用。
- 源码—候选摘要已核对：`import_page.py` SHA256 `3d465451675cd7742933efe35175405c2b48d6f5c1a93a1a1f14aa9b49f233c1`；`scanner.py` `6466d7d941f20920a94f05519f86123de6e8cec41b92eb93d4006530b9e3f2c6`；`worker.R` `22cd26e83d92d0f7ede7b50839ee98dcc6dca3bdb009956434582ff051e4839e`。
- 最新全量源码回归：**141 passed、1 skipped（81.09 秒）**；自动研判及 10x 临时输出根定向组 **11 passed**。10x 用例使用 pytest 临时目录，避免在测试中写用户 Documents。
- README 已将 R worker 单次请求超时对齐为 **600 秒**；只覆盖 R 子进程等待，不是完整导入/绘图/报告流程总时限。
- 自动研判首个小迭代：呈现候选、软件核查范围，按“单位→尺度”一次问一项；未知门禁不变。核查范围不是原文摘录；提供方说明自动读取、实际匹配词定位、确认状态账本仍未做。
- 本轮未启动候选 GUI、未做截图/AX/鼠标验收（无人值守），所以 Cocoa 选择器、Finder 拖放、屏幕布局、GUI 微型验证、候选实屏导入/取消/关闭均未新增证据。
- `/Applications/RNA-Seq Helper.app` 和桌面入口未改动。`release_check.py` 仍为 `ready_for_formal_release=false`：目前只有 ad-hoc 签名，缺 Developer ID、公证和干净 Mac 验收；另报扩展属性警告。

文档详情见 `DEVELOPMENT_LOG.md` 顶部和 `AUTO-RECOGNITION-SPEC-2026-10-03.md`。下方较早“当前状态”为历史阶段记录，以此段为最新状态。

## 2026-10-03 续接验收：独立候选包通过，待人工实屏验收

本轮新增 Qt 拖拽事件回归及真实后台整理取消/关窗集成回归，并修正关闭守卫的事件过滤器生命周期。完整回归 `.venv/bin/pytest -p no:cacheprovider -q` 为 **141 passed、1 skipped**。新回归通过真实 `ImportPage`、`PreparationService.validate()` 和 `QThread` 执行：取消按钮用 80,000 行测试表，验证进度到 128 行后取消；关窗用 2,000 行表，在同一真实验证阶段关闭宿主窗口。两项均确认任务协作结束、无矩阵交付、无项目结果写出且源文件摘要不变；关窗测试确认窗口等待线程结束再关闭。合成表仅用于取消/线程契约，不用于自动研判、统计或生物学判断。所有这些都是 Qt 自动化，不能替代 Finder 拖放、人工关闭或实屏验收。

Cocoa 选择器没有形成稳定自动化证据：旧测试在 `selectFile()` 后立即 `accept()`，随后候选扫描未发生；单独诊断确认对话框属于本次 `ImportPage`、可见、非原生、`ExistingFiles`，源文件存在，但一次绝对路径 `selectFile()` 后 `selectedFiles()` 仍为空，因此没有 accept。第二次探针因诊断代码误把 `choose_file()`（无返回值）当作 `QDialog.exec()` 返回值，在记录阶段抛出 `TypeError`，不能当成产品故障或成功。遵照重试上限，没有第三次 Cocoa 选择尝试；未使用 AX、未改系统权限。检查对应时段没有新 `.ips`。9/25 PID 12456 的 `AXCopyHierarchy/NSAccessibility/libqcocoa` SIGSEGV 是已归属的 AX 触发案例；不外推至普通鼠标操作，也不解释全部历史弹窗。

在新的 `/tmp/rnaseq-helper-candidate-20261003-obwEZq/clean/RNA-Seq Helper.app` 隔离候选中打入最新源码。py2app 原始输出出现已知 `liblzma` 严格签名问题；既有 clean-copy 脚本生成新副本后 `codesign --verify --deep --strict` 通过。`verify_bundle.py --app ...` 退出码 0、`ready=true`，arm64、Python 3.14.7、PySide6/Qt 6.10.3、R 4.6.0，limma/DESeq2/jsonlite/statmod 及两个微型 profile 可用。源码与候选中的 `background_jobs.py` SHA256 均为 `16d89339d7cd3658f35451460f4913bb0835abd97e319bee0756580987259a62`，`worker.R` SHA256 均为 `22cd26e83d92d0f7ede7b50839ee98dcc6dca3bdb009956434582ff051e4839e`。新候选已后台启动并通过短时进程/资源加载冒烟；旧候选 PID 1256 仍指向 `/tmp/rnaseq-helper-candidate.qDAcnT/`，不能作为新源码桌面验收证据。

随后运行 `release_check.py --app`，结果 `ready_for_formal_release=false`、退出码 1：严格签名有效但为 ad-hoc，缺 Developer ID 身份、公证和干净 Mac 验收；还报告 app 扩展属性警告。此项是正式发行阻断，不否定隔离候选的本机自检结果。原始 `dist/`（1.7 GiB）及 `build/` 中间产物（65 MiB）已移入 macOS 废纸篓，可恢复；clean 候选保留。

| 验收项 | 状态 | 证据/限制 |
|---|---|---|
| Qt 拖拽契约 | 通过（自动化） | `tests/test_import_drag_drop.py`；不代表 Finder 实际拖放 |
| Cocoa chooser | 未验证 | 程序化选择不稳定；没有确认普通鼠标选择故障 |
| 当前源码桌面完整导入 | 未验证 | 本轮未进行人工桌面流程；正常主程序新进程未留作运行 |
| 1024×768 / 约 820×560 | 未验证 | 本轮无当前布局实屏截图 |
| 取消/关闭 | 通过（离屏集成）；实屏未验证 | 真实整理服务/QThread 取消按钮与宿主窗体等待退出均通过；不等于锁屏/桌面验收 |
| 崩溃归属 | 部分定位、一般退出仍未知 | 9/25 AX/SIGSEGV 有具体进程证据；本轮还复现并修复 event-filter 生命周期异常，不解释其他历史通知 |
| 独立候选构建与自检 | 通过 | clean 副本严格 ad-hoc 签名、bundle 自检及两个 R 微型分析通过 |
| 候选实屏 | 未验证（仅启动冒烟通过） | 新候选 PID 5720 于 13:54:57 已运行 4:38；未操作窗口、导入或观察布局；旧 PID 1256 仍是修复前候选 |
| 安装版更新 | 未执行 | `/Applications/RNA-Seq Helper.app` 未改动，等待候选实屏验收 |

**当前结论：② 候选构建通过、待人工验收。** 当前不覆盖安装版、不替换桌面入口；也不把 ad-hoc 签名或 CLI 验证描述为正式发布或桌面通过。下一步照 `MANUAL-ACCEPTANCE-2026-10-03.md` 用普通鼠标验收候选的选文件、Finder 拖放、事实页/列角色页/分组页和两个窗口尺寸。实屏取消/关闭仍未验证；已另备仅供取消负载的 500,000×6 合成表，严禁用它判断自动研判或统计结果。

12:45 CST 只读核对当前安装状态：`/Applications/RNA-Seq Helper.app` 仍是 2026-09-22 修改的旧 bundle，严格签名有效，但内置 PySide6/Qt 为 6.11.2；隔离候选为 6.10.3。两包都含 R.framework，worker SHA256 相同。当前未找到 `/Users/additionlee/Desktop/RNA-Seq Helper（双击启动）.app` 或 `/Users/additionlee/Applications/RNA-Seq Helper.app`。本轮不重建桌面入口；待人工验收候选后，再按授权决定是否更新安装版。

12:49:39 CST 通过 `open -g -n` 后台启动隔离候选 GUI，PID 1256；12:50:42 复查仍存活约 1 分钟，执行文件路径确认来自 clean 候选。12:49:30 之后未出现新 Python `.ips`。这只证明候选 GUI 能启动并短暂保持运行，不是全流程或长时稳定性验收；未截图、未使用 AX、未点击窗口。当前源码主 GUI 本轮未启动。

12:53:05 CST 再次核对 PID 1256，仍存活 3:26，状态为睡眠等待；相同时段没有新 `.ips`。仍只属于后台空闲观察。

12:56:48 CST 只读续查时，候选 PID 1256 仍存活约 7:09，执行文件仍来自隔离 clean 候选；对用户 DiagnosticReports 目录按 `Python-*.ips` 和 12:49:30 后修改时间进行定向查询，没有匹配项。没有截图、AX 或鼠标操作。这仍不构成桌面导入、布局、取消/关闭或长期稳定性验收。

13:00:32 CST 再复核：源码 Python/PySide6/Qt 为 3.14.7/6.10.3/6.10.3，fixture SHA256 未变；clean 候选严格 ad-hoc 签名校验通过，`verify_bundle.py` 退出码 0、`ready=true`，R 包与 limma/DESeq2 微型 profile 就绪，候选内 `worker.R` 与源码摘要一致。候选 GUI PID 1256 仍存活约 10:53。未进行屏幕操作或重跑 pytest；实屏项目仍待人工验收。

13:17:28 CST 复查 PID 1256 仍存活约 27:49，执行文件确认来自旧候选 `/tmp/rnaseq-helper-candidate.qDAcnT/`。新候选尚未启动，避免与旧候选并行造成屏幕入口混淆。已安装 `/Applications/RNA-Seq Helper.app` 的修改时间仍为 2026-09-22 23:56:47 CST，严格签名校验通过，本轮未覆盖。

13:50 CST 对最新候选执行一次 `open -g -n` 启动冒烟。PID 5720 于 13:50:59 存活 40 秒；13:52:56 复查为 2:37；13:54:57 仍存活 4:38。执行路径在 `/tmp/rnaseq-helper-candidate-20261003-obwEZq/clean/`，`lsof` 确认 Python/Qt 二进制资源从该 bundle 加载。旧候选 PID 1256 同时仍在运行。新候选未做鼠标操作、截图、AX、选文件或导入，因此只记录为新包 GUI 初始化/资源加载存活，不作为人工验收或稳定性证明。

为下一次运行中取消/关闭实屏验证，已在隔离临时目录生成 `cancel-screen-test-only.tsv`（500,000 特征×6 样本列，20,179,066 B，SHA256 `6dafd7a24d5b6ccd8d7bfd1f1464ed7c6735766b468855f537febac02dd1aec9`）。它仅用于制造可观察的任务负载，不是 RNA-Seq 生物数据，也没有用于自动研判/差异分析。本文件不进入项目、不写入数据库；具体验收步骤见人工清单。准备数据不等于取消/关闭已经通过。

## 2026-10-03 01:44–01:59 无人值守续查：Python 崩溃未复现，归属仍未知（历史快照）

以下记录仅对应 01:44–01:59 的阶段状态；12:49 之后已构建并启动隔离候选包，较新结论见本文件顶部及 `DEVELOPMENT_LOG.md`。

用户不在电脑前后，续做可自动验证的检查，没有等待截图/解锁。源码 PID 87742 于 01:47:04 CST 以 `.venv/bin/python -m rnaseq_helper.app` 启动；Python 3.14.7、PySide6/Qt 6.10.3。至 01:59 仍运行约 12 分；启动后没有新 `.ips`，并行检查未找到可归属的统一日志或系统诊断报告。这只是**空闲条件下未复现**，不能证明崩溃已修复，也不能判定为 AX/SIGSEGV 或 QThread/SIGABRT。未对目标应用做 AX 扫描/截图，避免已知可能诱发 Cocoa 辅助功能桥接崩溃的操作。

另有一次 `QT_QPA_PLATFORM=cocoa` 自动化 chooser 流程通过：测试显示 Qt 页面、选中 fixture、扫描与整理，并由 `AnalysisPage` 收到一次 `matrixReady(ExpressionMatrix)`（1 passed）。后续同平台自动选择未能稳定选中；没有新崩溃报告，原因未定。此证据只说明一次 Cocoa 平台自动化通过，不代表人工鼠标验收，也没有验证视觉布局。测试夹具保留原来的稳定离屏选择器实现。

当前源码测试定向组 **16 passed**，全量回归 **137 passed、1 skipped**。它们验证离屏导入、未知事实门禁、兼容 `ExpressionMatrix`/`matrixReady` 单次交接及线程退出守卫；不等同于桌面导入验收。此次未改源码、未构建候选、未替换安装版。之前“R worker 运行中”与 Python GUI 异常退出分属独立进程/问题，不能互作根因证据。详细证据与边界见 `DEVELOPMENT_LOG.md` 的 2026-10-03 条目。

| 验收项 | 当前证据 | 判断 |
|---|---|---|
| 崩溃归属 | 01:44–01:49 只读查无新诊断报告；源码 PID 87742 空闲运行约 2:19 | 未复现；根因未知 |
| 文件选择器 / 拖拽 | 离屏完整回归通过；Cocoa 自动化 chooser 一次全流程通过，后续选择不稳定；拖拽只做代码审查 | Cocoa 曾通过一次；人工实屏与拖拽未验证 |
| 事实门禁 / 列角色 | 当前离屏测试覆盖未知门禁与布局几何 | 离屏通过；实屏未验证 |
| `matrixReady` | 离屏用例和一次 Cocoa 自动化都确认一次传给 `AnalysisPage` 的 4×6 `ExpressionMatrix` | 自动化通过；人工实屏未验证 |
| 1024×768 / 窄窗 | 既有几何测试；无本轮截图 | 实屏未验证 |
| 运行中取消/关闭 | 定向 QThread/应用 Quit 测试 16 项通过 | 离屏通过；真实桌面未验证 |
| 候选包 | 未构建 | 未通过前置实屏与崩溃归属门槛；不打包、不替换安装版 |

当时结论为 **仍不能打包**；此后已完成隔离候选包构建，但候选仍待人工实屏验收，正式安装版未更新。

## 2026-09-25 历史续验：选择器代码链离屏验证；桌面仍锁定

当前源码再补充两项进展：活动 `QThread` 期间的应用级 Quit 请求现在会先等待任务退出；新增离屏选择器回归，从当前非原生 `QFileDialog` 选中仓库只读 fixture，验证未知单位/尺度确实阻断，明确确认 raw count/linear 后完成全量验证和保存。现有 `AnalysisPage` 实际收到恰好一次 `matrixReady(ExpressionMatrix)`，矩阵 4×6，分组页建立了 6 个样本行，输入字节未变化。该完整 chooser→group-page 测试另连续复跑 5 次均通过；导入页、应用退出守卫与此端到端用例定向组 **16 passed**；最新全量 `.venv/bin/pytest` 为 **137 passed、1 skipped**。这仍只是离屏 Qt 端到端证据，不等于 Finder/真实鼠标桌面验收。

02:02 CST 本轮开始记录：源码命令仍为 `.venv/bin/python -m rnaseq_helper.app`，现存 PID 13908 于 01:05:54 启动，实际执行文件为 `/opt/homebrew/Cellar/python@3.14/3.14.7/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python`；本地环境 Python 3.14.7、PySide6/Qt 6.10.3。只读输入 `/Users/additionlee/Desktop/Master.nosync/agent/RNA-Seq Helper/tests/fixtures/company_counts.tsv` 为 291 B，SHA256 `4d363bea15f4e742dee076182668ca7e1d69613eb649a95b05eb5c8e6dbce41f`。通过一次 Codex Computer Use 状态读取确认 Mac 锁定；未点击、未截图、未操作 AX。`system_profiler` 当前读到 Retina 屏物理分辨率 3024×1964；锁屏状态下未取得新的逻辑窗口尺寸。02:11 CST 再次只读检查，PID 13908 仍运行，已运行 65 分 07 秒；没有发现该 PID 启动后新生成的 Python `.ips`。此进程早于代码改动，不能证明改动后的桌面运行稳定。

未改变 Picker/拖拽的真实桌面通过状态；布局改动后 1024×768/820×560 实屏、完整流程的实际桌面截图、运行中取消/关闭及本轮崩溃归属仍未补齐。历史 `AXCopyHierarchy`/`libqcocoa` 类问题不能由离屏 Qt 端到端测试排除。打包门槛未通过，因此没有构建候选包、覆盖安装版或改动桌面入口。当前结论仍为 **仍不能打包**。

| 验收项 | 现有证据 | 当前判断 |
|---|---|---|
| 文件选择器 | `tests/test_import_ui_state.py::test_file_picker_path_completes_import_and_updates_group_page`；历史 picker 窗口记录见 9/24–9/25 日志 | 离屏全流程通过；本轮真实桌面选中文件未验证 |
| 拖拽入口 | `ImportPage.dropEvent` 当前实现；无本轮真实桌面证据 | 未验证 |
| 候选识别 | `evidence/source-candidate-after-user-action-1024x800-2026-09-25.png`；上项离屏回归 | 既有源码实屏曾通过；最新实例需复验 |
| 事实门禁 | `evidence/source-facts-page-unknown-1024x800-2026-09-25.png`、`source-facts-confirmed-raw-linear-1024x800-2026-09-25.png`；新测试覆盖未知阻断与显式确认 | 既有实屏和当前离屏逻辑通过；新代码实屏未验证 |
| 列角色 | `evidence/source-columns-page-1024x800-2026-09-25.png` 为修复前挤压问题；`test_import_ui_state.py` 检查 1024×768/820×560 离屏布局 | 修复后离屏通过；修复后实屏未验证 |
| `matrixReady` | `evidence/source-import-after-confirm-1024x800-2026-09-25.png`；新测试验证 `AnalysisPage` 收到一次 4×6 `ExpressionMatrix` | 既有源码实屏到达分组页；当前离屏准确验证；本轮新实屏未验证 |
| 1024×768 实屏 | `evidence/source-clean-launch-empty-1024x800-2026-09-25.png` 及前述页面截图（窗体框 1024×800，内容区 1024×768） | 初始/旧布局有证据；布局修复后需重验 |
| 约 820×560 窄窗 | `evidence/organize-page-820x560-offscreen.png` 与离屏几何测试 | 仅离屏通过；实屏未验证 |
| 运行中取消/关闭 | `tests/test_background_job_close.py`、`tests/test_app_shutdown_contract.py` | 真实 `QThread` 离屏测试通过；Finder 实屏关闭/取消未验证 |
| 崩溃归属 | 本日志记录的 PID 12456/AX 崩溃；当前 PID 13908 自 01:05:54 仍运行且无启动后新报告 | AX 触发条件有历史归属；一般 Python 退出原因仍不确定，当前仅“本条件下未复现” |
| 候选包 | 本轮未构建 | 未通过前置验收门槛；不打包、不替换安装版 |

## 2026-09-25 最新续验：补上应用级退出时的后台线程保护

排查“Python 意外退出”时，发现窗口关闭守卫此前只处理窗口 `QEvent.Close`，未拦截 `QApplication.quit()` 对应的应用级 `QEvent.Quit`。这给 macOS 应用菜单/快捷键退出留下了后台 `QThread` 尚未结束就退出事件循环的路径，可能触发 `QThread::~QThread` 类 `SIGABRT`。依据 Qt 的 [QCoreApplication::quit 文档](https://doc.qt.io/qt-6/qcoreapplication.html#quit)，应用可以处理 `QEvent.Quit` 中断退出请求。

`BackgroundJobCloseGuard` 现同时守护窗口关闭和应用级退出：有活动线程时拦截退出、请求协作取消并等待；线程都结束后再恢复原退出请求。新增的隔离测试以真实 `QThread`/`QApplication.exec()` 覆盖 `app.quit()`，并关闭“最后窗口自动退出”，确保恢复的是应用级退出本身。该测试通过并连续复跑 5 次；原关闭守卫定向组 3 passed；最新完整回归 **136 passed、1 skipped**。主线修改位于 `src/rnaseq_helper/ui/background_jobs.py`，新增 `tests/test_app_shutdown_contract.py`。

这只修复一条可复现的线程退出风险，不等于所有 Python 崩溃已解决：历史 `AXCopyHierarchy`/Qt Cocoa `SIGSEGV` 不在本修改覆盖范围内。当前桌面锁定，主线源码 GUI PID 13908 仍是修改前启动的旧进程；代码尚未在新启动的桌面应用中复验。02:00 CST 只读复核时，该 PID 已运行 54 分 37 秒且仍存活，未发现其启动后新生成的 Python `.ips`；这只能记为本次条件下未复现。布局修复后的实屏、实际拖拽、窄窗、用户取消/关闭、Picker 和候选包验收仍待完成；未打包、未替换安装版。

## 2026-09-25 前序状态：源码导入链路已实屏走通；Python 崩溃尚未完全闭环

本轮修复三项入口问题：扫描进度改为按遍历项限频；`length/start/end/GC` 等明确数值注释列不再被默认误判为样本表达列，并在界面显示理由、展开角色编辑器且允许人工覆盖；混合导入中失效路径会显示在扫描摘要里，同时保留可用候选和继续操作。完整 `.venv/bin/pytest -q` 为 **134 passed、1 skipped**。修改没有触及 R worker、统计方法、阈值、结果字段或 `ExpressionMatrix`/`matrixReady` 契约。

复核 2026-09-23 的 9 份 Python 崩溃报告：8 份主线程经过 macOS `AXCopyHierarchy`/Qt Cocoa accessibility bridge 后 `SIGSEGV`，另 1 份在 `QThread::~QThread` 清理时 `SIGABRT`。9 份进程均为 Homebrew Python 3.14.7、Qt 6.11；父进程为 `codex`、责任进程为 `ChatGPT`。报告路径已被 macOS 隐私脱敏，不能精确识别具体 Python GUI 应用。由于本项目此前使用同一 Python 3.14.7 与 Qt 6.11，且曾通过 Codex 启动/检查 Qt 界面，不能再据此排除 RNA-Seq Helper；也不能确认所有报告都来自本软件。公开的 Codex Computer Use 问题记录了相似的 Qt Cocoa 辅助功能树崩溃：[issue #41374](https://github.com/openai/codex/issues/41374)、[issue #42666](https://github.com/openai/codex/issues/42666)。

当前源码 `.venv` 已使用 PySide6/Qt 6.10.3，项目依赖限制为 `PySide6>=6.10.3,<6.11`；正式安装包仍需复核其 Qt 版本并在用户授权下决定是否替换。改用 Qt 6.10.3 只是候选规避，并无证据证明修复跨 Qt 版本的 macOS AX 崩溃。系统辅助功能权限未更改；暂时关闭 Codex Computer Use 的选择已向用户征求，尚未收到答复。9/23 后未见更新的 Python 崩溃报告，但期间没有进行新的同条件桌面对照，这不构成修复证明。

2026-09-25 01:02 CST 新增一次可归属的源码实屏崩溃：本轮 Python PID 12456（Python 3.14.7，PySide6/Qt 6.10.3）在对已打开的 Qt QFileDialog 执行 Codex Computer Use 的 Accessibility 值操作/状态刷新时退出。新报告 `~/Library/Logs/DiagnosticReports/Python-2026-09-25-010251.ips` 的 faulting thread 明确经过 `AXCopyHierarchy`，异常为 `EXC_BAD_ACCESS/SIGSEGV`；这说明 Qt 6.10.3 也未避免这次 AX 桥接崩溃。普通用户点击/导入未被证明会崩溃，导入 worker 当时也未运行；不要把它写成通用修复或根因已完全解决。该次窗口级空状态截图 `docs/development/evidence/source-empty-window-1024x800-2026-09-25.png` 只证明空状态，不能替代导入验收。仍未重新打包/安装；历史回归 134 passed、1 skipped 未在本轮重跑。继续验收时停止对 RNA-Seq Helper 使用 AX；完整成功路径须用无临时项目根注入的源码启动。源码回退快照为 `/tmp/rnaseq-helper-baseline-tPQbUE/project`；指定文件 `REVIEW-AND-ROADMAP-2026-09-23.md` 缺失，继续依据现有最终规划、导入向导设计和状态文档。

随后于 01:05:54 CST 使用无临时项目根注入的正常源码命令启动，PID 13908；Qt 内容尺寸 1024×768，macOS 窗框 1024×800。通过普通鼠标事件完成只读 fixture `tests/fixtures/company_counts.tsv` 的扫描、人工确认 raw count/linear、列用途检查、后台全量读取/校验/保存，并进入分组页；未使用 Accessibility/AX 操作。实屏证据依次为 `docs/development/evidence/source-clean-launch-empty-1024x800-2026-09-25.png`、`source-candidate-after-user-action-1024x800-2026-09-25.png`、`source-facts-page-unknown-1024x800-2026-09-25.png`、`source-facts-confirmed-raw-linear-1024x800-2026-09-25.png`、`source-columns-page-1024x800-2026-09-25.png`、`source-import-after-confirm-1024x800-2026-09-25.png`。整理项目 `~/Documents/RNA-Seq Helper Projects/company_counts-817d2e29/` 的 manifest 验证通过，矩阵为 4 特征×6 样本/24 个数值单元；生成 `expression_matrix.tsv`、`feature_metadata.tsv`、`sample_metadata.tsv` 和整理配方，分组页显示 control 3、test 3、排除 0。来源 fixture SHA256 仍为 `4d363bea15f4e742dee076182668ca7e1d69613eb649a95b05eb5c8e6dbce41f`。现有完整导入测试补上 `matrixReady` 恰好发出一次的断言；定向测试 1 passed，完整源码回归 134 passed、1 skipped。当前 1024×768 的列角色实屏图可见说明文字与表格发生挤压/遮挡，是已确认的布局问题。窗口虽然声明最小内容尺寸 820×560，本次系统级拖动没有改变实际窗框尺寸，故 820×560 尚无实屏验收。PID 13908 持续运行；截至本次检查没有启动后新生成的 Python `.ips` 报告。01:02 的 AX/Qt 文件选择器崩溃仍是已归属事件；既往“Python 崩溃”通知仍未能与当前 PID 关联，本次无 AX 鼠标导入成功也不构成普遍修复证明。未运行 R 或差异分析，正式安装版未触碰。

补充生成 820×560 的 Qt offscreen 页面截图 `docs/development/evidence/organize-page-820x560-offscreen.png`：输入为只读真实 GEO `GSE10361_series_matrix.txt.gz`，界面载入有限 40×10 预览，单位/变换仍要求交付说明确认，确认按钮保持禁用。之后用项目的 `AssetScanner` 与 `PreparationService` 完成全文件读取并校验，得到 22,284×10；校验只因 `UNKNOWN_MEASUREMENT`、`UNKNOWN_SCALE` 两项阻断，原文件 SHA256 前后一致。此流程未运行 R/差异分析。截图用于检查窄屏页面滚动和门禁，不是桌面实屏证据，也不替代真实窄窗口验收。

只读复核还确认：历史 `QThread::~QThread/SIGABRT` 报告不能归属本项目；当前关闭守卫会在窗口关闭时协作取消并等待线程，测试覆盖了守卫与真实 `QThread` 的基础路径，但没有覆盖真实主窗口在任务运行时关闭或 macOS 应用级 Quit。没有证据表明普通关闭当前必然遗留线程，因此不做猜测性线程实现改动；若此类崩溃再现，应保留与当前进程可关联的新报告，并优先补主窗口/应用退出集成覆盖。

2026-09-25 01:37 CST 续验基线：正常源码 GUI PID 13908，启动命令 `.venv/bin/python -m rnaseq_helper.app`，可执行文件 `/opt/homebrew/Cellar/python@3.14/3.14.7/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python`，Python/PySide6/Qt 为 3.14.7/6.10.3/6.10.3；输入 `tests/fixtures/company_counts.tsv`（291 B，SHA256 `4d363bea15f4e742dee076182668ca7e1d69613eb649a95b05eb5c8e6dbce41f`）；内屏 3024×1964 物理像素、1512×982 逻辑点，源码窗口内容 1024×768、窗框 1024×800。此轮没有使用 Codex Computer Use/AX，曾尝试一次 Quartz 普通鼠标点击，但当时 `loginwindow` 已是前台，事件未送达应用；没有打开文件选择器，也未重复操作。进程仍存活；截至 01:50 未发现启动后新的 Python `.ips`。这只能记为当前条件下未复现，不能证明崩溃修复。

针对 1024×768 列角色页截图中的说明挤压/遮挡，源码现已为换行提示保留自然高度，并让整理内容区以滚动承载紧凑视口；新布局回归检查 1024×768 和 820×560 离屏几何、提示无重叠、表格可滚动、页脚按钮可见。完整导入契约测试现在也断言 `matrixReady` 恰好发射一次且 payload 是 `ExpressionMatrix`。本轮实际完整回归 **135 passed、1 skipped**；但因屏幕停在 `loginwindow`，布局修复后的实际桌面截图和窄窗仍未验证。文件选择器的普通点击、实际拖拽、运行中取消/关闭仍未完成；不满足打包门槛，因此不构建/替换安装版。

## 2026-09-23 历史状态：Python 异常退出缓解候选，待实屏对照

复核本机 9 份 Python 崩溃报告：8 份 `SIGSEGV` 均沿 macOS `NSAccessibility`/`AXCopyHierarchy` 与 Qt Cocoa accessibility bridge 崩溃；另 1 份 `QThread` 析构时 `SIGABRT` 是独立线程退出问题。无证据指向 RNA 数据解析/统计代码。源码的 `BackgroundJobCloseGuard` 负责窗口关闭时等待后台线程结束。

针对崩溃进程加载的 PySide6/Qt 6.11 系列，项目依赖已限制为 `PySide6>=6.10.3,<6.11`，本机 `.venv` 使用 6.10.3。`pip check` 通过；完整回归 **130 passed、1 skipped**。临时 clean bundle 位于 `/tmp/rnaseq-helper-crash-fix-7M4Fry/RNA-Seq Helper-clean.app`，内置 R/limma/DESeq2 自检、严格 ad-hoc 签名、limma/DESeq2 微型验证均通过。

**尚未证明 AX/SIGSEGV 已消失：** macOS 桌面再次自动锁定，6.10.3 候选的实际窗口/AX 对照及当前导入向导实屏验收尚未进行。唯一安装包 `/Applications/RNA-Seq Helper.app` 仍在运行，其包内 PySide6 为 6.11 系列；本轮没有关闭或覆盖它。此前导入 A+B 离屏布局已覆盖 1024×768 与 820×560，实际截图和文件 picker 点击仍待解锁后验收。`REVIEW-AND-ROADMAP-2026-09-23.md` 当前缺失，继续依据现存向导设计、根规划、README 和源码推进。

**回退与发布：** 源码回退快照 `/tmp/rnaseq-helper-source-snapshot-JUhWCU` 仍在；候选包只用于验证，并非已安装的新版本。当前正式安装包和版本号没有变更，也未声称修复完成。

**清理状态：** 子代理只读审计未发现其他明确的旧包或项目日志垃圾。本轮已清除项目 `.pytest_cache`、源码下 12 个及测试下 2 个 `__pycache__` 目录、以及 `packaging/` 和 `packaging/dist/` 中的两个 `.DS_Store`；测试在禁用缓存/字节码写入后再次通过，确认这些项目缓存没有重建。`.venv`、参考缓存、分析结果、规划文档、开发日志及崩溃报告均保留。

## 2026-09-23 导入 A+B 历史实现进度（线程退出修复前）

正在继续导入/整理阶段 A+B；最新完整源码回归为 **125 passed、1 skipped**。当前版本在首轮调整之外，已将普通表格/GEO 的初始会话限制为最多 40×80 的预览；只有用户走到最终校验时，后台 worker 才补读全表。预览标记防止把局部行数说成总特征数；完整样本轴若超出预览范围会阻断，避免样本被静默漏掉。多工作表同级 count 候选不再默认取第一张；count/TPM 表名线索可建议先看 count，但不会确认数值单位。原始 count、TPM、log2 等在提示中不显示内部枚举名或密度分数。

保留的首轮源码界面实屏证据：984×768 截图中导入首屏无明显遮挡；工具菜单和主要键盘焦点路径可见。此后有限预览和工作簿推荐逻辑的实屏复验尚未做。GUI 组件离屏端到端已通过 1,500 特征测试，实际从有限预览、用户确认 count/linear、后台补读全表，到发出兼容 `ExpressionMatrix`/`matrixReady` 并写入临时项目目录；离屏布局核对在 1024×768 与最小 820×560 下确认页面主按钮落在窗口内、内容区收缩并保留滚动，但这不是实屏截图。当前系统仍被桌面控制接口判定为锁屏，最新源码的人工点击导入、窄屏截图仍待实测。锁屏期间核对发现现存源码 GUI 进程于 17:25 启动，而 `import_page.py` 与扫描器在 17:48、`table_reader.py` 与导入页在 18:16 更新，因此现存窗口加载的是旧代码；解锁后必须启动新进程再验收。另修正含 10x 三件套目录会吞掉 count/PDF/FASTQ 的扫描缺陷；完整数据验证现可逐行报告进度并协作取消，worker 异常首屏只显示可执行恢复建议。Excel 有界预览现在限制 openpyxl 最多物化 80 列且保留宽度不完整标志；文本预览限制单行约 1 Mi 字符和保留文本 2 百万字符；完整读取仍需留意极端单行内存。源码回归含临时混合目录 `a.pdf`、`b_counts.tsv`、`sample.fastq.gz` 及 10x 混合/缺件目录。当前安装版未重打包。缺少指定名为 `REVIEW-AND-ROADMAP-2026-09-23.md` 的文件；本轮参考了存在的 9/13 review、9/23 导入向导设计和根目录最终规划。未改统计方法、R worker、阈值、结果字段或下游矩阵契约。

自动研判不再使用文件名或数值外观确认数值单位/变换。表格内容有明确文字线索时只显示为待核实建议；没有线索时保持 UNKNOWN，不阻止小白继续查看说明或查看预览，但事实未确认前仍不能通过数据整理校验。真实只读测试数据为 Codex's House 内 `GSE10361_series_matrix.txt.gz`（约 1.6 MB），扫描识别为 22,284 × 10、GPL96，数值单位和尺度均未臆测。

**实屏验收进展/未完成项：** 源码版窗口已按 Python.app 可执行路径单独绑定，984×768 截图中导入首屏主要控件完整、未见遮挡；四步业务导航及“工具 → 环境与验证…”入口均在源码界面中确认。键盘焦点实测可依次到达当前步骤、选择文件、选择 10x 文件夹和文件表格，再回到步骤栏；后续整理/分析页面的完整键盘遍历尚未验收。曾用自动化文件选择器定位到 1.57 MiB 的 GSE10361 文件，但双击打开时 Python/QT 进程以 139 退出并出现无效 accessibility 对象日志，无法确定故障属于应用还是自动化桥接，因此真实导入预览和 `matrixReady` 交接仍未验证；本轮没有重试导入。两次拖动窗口边缘均未改变尺寸，窄窗口布局尚无实屏证据。另有未重打包的 `/Applications/RNA-Seq Helper.app` 同时运行，曾显示旧式标签页界面；后续验收以明确绑定的源码窗口为准，当前安装版未被本轮覆盖。归档解压按成员与 1 MiB 数据块检查取消，10x 完整/缺件混合扫描有回归覆盖，但长任务实屏响应仍未验收。普通文本表预览限制单物理行约 1 Mi 字符、保留文本总量 2 百万字符；完整读取不设该预览上限，极端单行仍可能在 CSV parser 返回前占用较多内存并延迟该行的协作取消。统计方法、R worker、过滤阈值、结果 schema、`ExpressionMatrix` 与 `matrixReady` 接口没有改动。详细记录见 `DEVELOPMENT_LOG.md` 与 `IMPORT-WIZARD-DESIGN-2026-09-23.md`。

## 2026-09-22 当前状态

修复旧式 Excel `.xls` 导入后界面无反馈的问题：资产识别阶段不再把二进制 Excel 送入 GEO 文本嗅探器，`.xls/.xlsx/.xlsm` 直接进入表格读取路径；GEO 嗅探器本身也增加二进制 Excel 防御判断。用真实 6 KB `.xls` 在重新安装的桌面应用中实测，选择文件后已进入“2 整理并确认”并显示工作表、预览和小白提示。完整回归为 86 passed、1 skipped；新 bundle 自检 ready、严格 ad-hoc 签名校验通过。

导入页重新整理了“小白提示”：提示框已从“请确认数据事实”表单中独立出来，改为固定高度的只读文本框，内部垂直滚动，避免长文挤压输入控件。两个下拉框改成“每个格子代表什么”和“有没有取过 log”，并给出工具提示；文案改为“先回答两个问题→照着选→最后检查”，减少抽象术语和解释性套话，保留原始 count、TPM/FPKM/RPKM/CPM、芯片信号、log2/ln/log10/z-score、参考表和 GSE/GPL 示例。

本次又修复了系统黑白/高对比外观下的界面可读性：应用改用 Qt Fusion 绘制器，显式固定中性灰阶调色板和标签栏背景，嵌套标签不再出现整条黑色底带。`2.1 确认数据事实` 改用网格布局，标签、下拉框和数字输入框按列对齐并横向铺开；已在实际安装包中截图核验外层/内层标签、2.1 控件和提示框。最新源码回归仍为 85 passed、1 skipped；重新打包的 clean bundle 自检、内置 limma/DESeq2 验证和严格 ad-hoc 签名校验均通过。

旧式 Excel `.xls` 已加入表达矩阵和参考表导入：使用 `xlrd` 读取工作表、数值和日期，不再提示“旧式 .xls 暂不支持”；文件选择框、参考表选择框和小白提示均已列出 `.xls`。方向修正复选框改为 22×22 像素并增加明确边框，事实确认区提示框进一步收缩；最终实际截图可见复选框、字段对齐和滚动提示。新增 `.xls` 回归后完整测试为 86 passed、1 skipped，clean bundle 自检仍为 ready。

新增独立 R 基线脚本 `tests/real_data/direct_gse32707_limma_compare.R`，不调用项目 worker，直接读取已保存的 GSE32707 矩阵、分组和分析计划，按 `log2(x+1) → lmFit → contrasts.fit → eBayes(trend=TRUE, robust=TRUE, legacy=TRUE) → BH` 重算。与工具保存的 47,220 个特征、92 个纳入样本（control 34、test 58）逐行比较：log2FoldChange、moderated t、p 值、BH 校正后 p 值、两组均值最大差异均为 0；显著数 9,015、绝对 log2FC≥1 数量 737，完全一致。最终全量回归为 85 passed、1 skipped；导入/布局专项为 13 passed；最终应用 bundle 自检、limma/DESeq2 微型验证和严格 ad-hoc 签名校验均通过。

## 2026-09-21 当前状态

本轮补充了 Illumina GPL 注释映射和诊断显示修复：GPL/SOFT/annot 读取器现在支持 Illumina `[Probes]` manifest（包括 `.txt.gz`），参考表选择框也支持压缩注释文件；GSE32707 配套的 `GPL10558_HumanHT-12_V4_0_R1_15002873_B.txt.gz` 实测可映射 43,951/47,220 个探针（93.08%），未映射的 3,269 个仍保留原始探针编号。报告和 XLSX 的残差自由度不再展开 47,220 个重复的 90，而显示为“90（所有特征相同）”。最新完整回归为 85 passed、1 skipped；重新打包并安装的应用已通过 bundle 自检和严格 ad-hoc 签名校验。

导入页“小白提示（先看这里）”已扩写为完整的可执行参考表：明确区分 CSV/TSV/TXT/XLSX/GEO 文件格式、原始 count/TPM/FPKM/RPKM/CPM/芯片信号等数值单位，以及线性尺度、log2、ln/log10/z-score/残差等变换；同时给出每种组合对应的 DESeq2 或 limma 路径、不能仅凭整数/小数猜测的边界，以及参考表的用途、GSE/GPL 关系、`ILMN_...` 与 GPL10558 示例、支持格式、误选文件和无参考表时的结果含义。提示区扩大并保留垂直滚动条，安装包已同步更新。

针对真实 GSE32707 Series Matrix 的分组入口已明确为：control、test，或“排除本次分析（未确认）”；不再提供独立的“未确认”和“排除”两个语义。分组页显示纳入/排除数量，排除样本不会进入矩阵、设计矩阵或差异分析。若输入事实尚未匹配安全分析 profile，界面现在给出面向 GSE 芯片信号/连续表达值的具体操作提示，而不是只显示“没有对应 profile”。

真实文件 `/Users/additionlee/Desktop/Master.nosync/agent/Codex's House/SEALI_ALI/0_Raw/GSE32707_series_matrix.txt.gz` 的离线导入验证结果：自动填入“其他连续表达值 + 原始/线性尺度”，整理按钮可用；当前源码服务层已完成 47220 个特征 × 144 个样本的 limma 分析链路，control 34、test 58、排除 52，生成 HTML、XLSX 和 5 张图。2026-09-21 已完成最新 bundle 的真实 GUI 端到端验收：从现有整理结果进入分组页，确认批量菜单显示“排除本次分析（未确认）”，生成 `LIMMA_ON_LOG_EXPRESSION / normalized-log-limma-trend-v1` 计划并点击开始分析；界面随后自动切换“结果与报告”，报告卡明确显示 HTML、`reports/deg-results.xlsx` 和 `figures/`。报告记录 `tested_count=47220`、`not_tested_count=0`、`significant_count=9015`，五张 PNG 均已生成。结果页的交付卡、全局控件和标签页样式已通过屏幕检查；最新完整回归为 85 passed、1 skipped，clean bundle 自检和严格签名校验通过。

## 2026-09-15 最新状态（优先于下方历史记录）

审查修复源码已完成：通用 log 门禁、实际设计残差方差、正式 limma 退化行及有效检验 BH、runner 绘图矩阵与契约校验。随后补充了面向新手的“小白提示”和导入后自动研判：有明确文件名/内容证据时按线索建议，没有线索时也给出“其他连续表达值 + 原始/线性尺度”的保守可执行建议，不再把“未确认”作为自动研判结果。导入与整理已拆成两个页签，整理页又拆为“确认数据事实”和“设置列角色与预览”两个独立页签；小白提示补充具体公式、信号值和“不能靠猜”说明，并设为始终显示垂直滚动条。分组页新增 GEO2R 式筛选、表头排序、可见行批量设组及 GEO 注释分列，并补充配对个体/批次说明；同时修复 normalized_counts 误判 raw count 和 raw count+log2 错进 DESeq2。完整源码回归：82 passed、1 skipped。详情见 REMEDIATION-2026-09-14.md。

当前源码已重新打包，v0.30 clean candidate 已通过内置 R、limma/DESeq2 微型验证、本机严格 ad-hoc 签名及 GUI 启动验证；放大窗口屏幕核验确认小白提示完整显示且垂直滑块可见。真实数据核验使用 Codex's House 中 1GB 内文件；其中 83.5MB 文本表暴露出同步导入较慢的问题，尚未在本轮修复。正式 Developer ID、公证和干净 Mac 验收仍未完成；v0.30 仍是未发布开发版本。

更新时间：2026-09-15

阶段：5（差异分析、五图与离线报告）

历史记录（v25）：`.venv/bin/pytest -q` → `65 passed, 1 skipped`。v25 候选 bundle 已内置最小 R 运行时；`packaging/verify_bundle.py` 返回 `ready: true`，R.home 指向 app 内路径，limma/DESeq2/jsonlite 均从 app 内加载；clean 副本严格 ad-hoc 校验通过。解锁后已完成两轮真实屏幕监测：运行时验证页通过，随后从合成 company count TSV 完整走到 DESeq2 结果页并看到 HTML/XLSX/五图；无残留 Rscript/worker。正式发布仍未完成：当前无 Developer ID/公证，干净 Mac也未验证。

## 已实现

- Python 包和最小领域/任务 DTO。
- JSON Lines 协议的独立 R worker 客户端。
- 固定 `limma::lmFit`、`contrasts.fit`、`eBayes(trend=TRUE, robust=TRUE, winsor.tail.p=c(0.05,0.10), proportion=0.01, stdev.coef.lim=c(0.1,4))` 微型验证。
- 固定 120 基因 count fixture 的 DESeq2 runner；缺包时显式失败，不切换到 limma。
- Python/R/关键 R 包自检命令和无 PySide6 时的明确降级提示。
- py2app standalone 配置样例。
- v25 候选 standalone bundle 内置 R 4.6.0 的 base/recommended 运行时和 limma、DESeq2、jsonlite、statmod 递归依赖；`embed_r_runtime.py` 只读系统 R、重写 app 内 Mach-O 依赖并为改写组件做本机 ad-hoc 签名。运行时优先使用 app 内 Rscript，并清空用户 R 包库路径，避免同名包覆盖。运行时验证页增加取消按钮；导入页增加当前/转置离线缩略图，压缩候选树把参考文件标为不可作为表达矩阵的独立对象；批次/配对信息按 `subject` 和 `batch` 字段传递给 R worker。

## 已验证

- R 4.6.0、limma、jsonlite、statmod 可被发现；DESeq2 缺失状态可被自检准确报告。
- 阶段 0 微型 limma 请求可经独立 Rscript 返回结果。
- 阶段 0 微型 DESeq2 请求可经独立 Rscript 返回结果；预设效应基因方向正确。
- DESeq2 缺失时明确失败，不静默换方法。
- PySide6 QThread 中的微型 limma 请求已验证。
- py2app standalone bundle 已构建；bundle 内自检、limma、DESeq2 和 worker 资源路径已验证。
- UI 结果回传改为显式 `QueuedConnection`，避免 PySide 自动连接类型在打包环境下不一致。
- 持有活动 worker/thread 的 Python 引用，避免 `start()` 返回后 worker 被垃圾回收导致 UI 永久停留在运行状态。
- Finder 启动场景自动解析 `/Library/Frameworks/R.framework/Resources/bin/Rscript` 等 macOS R 路径，不依赖终端 PATH。
- 已在 Finder 启动的真实 bundle 中点击验证：界面显示“微型 limma 验证通过”。
- CSV/TSV/TXT/XLSX 输入扫描、非首行表头候选、预览、列角色和单位/尺度显式确认已实现。
- 原始文件只读；整理结果写入独立项目目录的 `prepared/` 和 `preparation-recipe.json`。
- 未确认单位或尺度时，导入页现在直接禁用“应用整理并验证”，并显示下一步提示。
- 导入后自动研判单位/尺度：例如 company count 文件会给出“原始 count + 原始/线性尺度”候选并保留可修改性；证据不足的 GEO 示例保持“未确认”，不凭整数/小数外观猜测。
- 分组建议、逐样本确认、计划摘要和统一开始分析页已接入 GUI；分组变化会使旧计划失效。
- 已实现 DESeq2 count 与 TPM/FPKM/CPM/RPKM 的固定 limma-trend 调度、BH 和 NA 原因字段。
- normalized 路径在 R 之前执行 500 特征、50 个 Amean 值和 5% 组内退化门禁。
- 结果自动写入离线 HTML、XLSX、分析计划和 manifest；10x 稀疏元信息、GEO Series Matrix 表段和安全压缩清单已实现。
- 已接入五张离线 PNG：过滤表达矩阵 PCA、样本 Pearson 相关性、原始 p 值直方图、FDR 火山图、Top 特征行 Z-score 热图；固定随机种子由分析配置记录，PCA 最多使用 2,000 个高变异特征。
- 已补充图表清单和 HTML 内嵌预览；XLSX 保留结果、方法、分组和诊断页，结果中的 NA 与未检验原因不改写为零。
- GUI 已增加“结果与报告”页；分析完成后自动切换，可直接打开离线 HTML 报告或项目目录。
- 分析页已增加“取消当前任务”；取消令牌会终止等待中的 R worker，不依赖忙碌线程继续处理 Qt 槽。
- 分析页现在接收 worker 进度事件并显示“分析中：……”，避免长任务被误认为界面失去响应。
- 导入页增加“选择 10x 目录”入口；10x 细胞对象只展示安全提示，不进入 bulk runner。
- 导入页支持拖放本地文件，并在压缩包包含多个表达候选时显示对象选择对话框；特征编号列不会再被同时作为样本表达列。
- 运行时验证页现在分别提供环境检查、limma 微型验证和 DESeq2 微型验证，避免把不同验证结果混为一个按钮。
- 参考表读取异常会降级为 UNAVAILABLE 并保留原编号，不再把损坏参考文件异常直接抛到 GUI。
- 已增加本地参考映射服务：支持 CSV/TSV/XLSX 的编号→名称匹配，保留一对多关系，记录覆盖率、歧义、未映射数和 checksum；参考不可用时保留原编号并降级交付。
- 本地参考表缺失且物种/编号可识别时，可调用已安装的离线 OrgDb；没有对应包时仍保留原编号并降级，不发送表达矩阵。
- 已增加本地 GPL/SOFT/annot 读取器，支持平台表中的编号→gene symbol 关系和一对多符号，不联网、不把参考表当作表达矩阵。
- 整理结果现在保留原始注释列到 `prepared/feature_metadata.tsv`；分析 runner 会把可用的 gene_symbol 传入统一结果表，不改变统计行数。
- 项目内重建 `.venv` 后，最新 `pytest -q` 通过 42 项、跳过 1 项；新增公式无缓存阻断、转置列重算和 QThread/R worker 完成信号回归；本次测试使用本地合成 fixture，不读取用户原始数据。
- 导入页已增加本地参考表选择入口；参考映射结果写入 `prepared/feature_metadata.tsv` 和 `references/reference-result.json`，不改变表达矩阵行数。
- 标准化表达的精度诊断已按规划记录 Q(1)、Q(0.1)、低复杂度比例 L、残差退化比例 Z 和证据量；普通精度问题告警可继续，严重组合会在启动 R 前阻断。
- 新增确定性本地 mock 工厂：GEO 2000×8、公司 count 3000×12、10x 1000×600、TPM/FPKM regular 与舍入边界；新增嵌套压缩包递归展开回归测试。
- 最新本地回归为 `.venv/bin/pytest -q`：62 passed、1 skipped；本轮未下载实验数据或修改用户原始数据。
- v21 新增独立 R 标准化敏感性网格回归，覆盖过滤阈值 0.5/1/2、伪计数 0.1/0.5/1、robust 开关和均衡/不均衡深度；最新本地回归为 `60 passed, 1 skipped`。默认值仍来自固定 profile，不按显著结果数量选择。
- v22 补充慢 R worker 的真实取消回归，并在最终 v20 standalone 包中实际点击 limma/DESeq2 微型验证：均先显示等待进度，随后返回“通过”，没有残留 Rscript；最新本地回归为 `61 passed, 1 skipped`。
- 发布前离线审计仍明确为未完成：v23 已内置 R.framework，但当前 bundle 仍不是 Developer ID 签名；本机 clean 副本在含嵌套 R.framework 时仍需发布环境重新封装签名，干净 Mac/公证尚未验证，不能当作正式发布包。

## 未验证/下一步

- 完整 PySide6 数据流、QThread 取消深度测试、签名公证和干净 Mac；当前 bundle 已完成本机 ad-hoc 构建与 clean 副本严格自签校验，未做发布签名/公证。
- GEO 和 10x 均提供可重复打开的三步事实/注释或构成/边界向导；压缩包多候选对象显示目录树、用途、尺寸和完整性，仍需补充真实用户压缩包的屏幕验收。正式签名公证仍待发布环境。
- DESeq2 当前结果表使用模型估计的未收缩 log2 fold change；需要后续固定 shrinkage 依赖和 profile 后再启用收缩值，不能静默改变现有结果。
- v25 内置 R 候选已通过命令行 bundle 自检与 clean 副本严格 ad-hoc 校验；解锁后已补齐两次独立真实屏幕验收：运行时验证页通过，company count TSV 完整走到 DESeq2 结果页并生成 HTML/XLSX/五图，未残留 Rscript/worker。仍需在发布环境完成真实用户压缩包验收、clean Mac、Developer ID、公证和安装器验证。
- 最新 v13 standalone bundle 已重新构建；`packaging/verify_bundle.py` 已确认 Apple Silicon、Rscript、limma、DESeq2 和 worker 资源均可用。v13 已完成两次独立真实屏幕监测，并实际观察 R worker 等待态后回到 limma“通过”；进度由主线程 QObject 槽接收，QThread/R worker 完成信号已有回归测试。发布检查器已能稳定报告签名、R.framework 和干净 Mac 缺口。此前 v4 的 Launch error 已定位并修复为循环导入问题。
- v15 已将导入页升级为逐列显式角色表（特征编号/样本表达/说明注释/忽略），并通过唯一特征编号和最少样本列约束；源码回归、bundle 自检和 clean 副本严格校验均通过。v15 standalone 已完成两次独立真实屏幕监测，均实际走完公司 count TSV 的整理、分组、DESeq2 R worker 和结果页，并生成离线 HTML/XLSX/5 张图。仍待完整多 sheet/GEO/10x 向导交互、干净 Mac、Developer ID 签名、公证和内置 R.framework。
- v16 已增加 Excel 多工作表逐张查看、表规模/数值密度/候选表头提示及显式前后导航；导入角色表和多工作表状态均有 GUI 回归测试。最新本地回归为 `52 passed, 1 skipped`；v16 standalone 自检、clean 副本严格校验和两次独立真实屏幕监测均通过，第二次实际完成公司 count TSV 的整理、分组、DESeq2 R worker 和结果页，并生成离线 HTML/XLSX/5 张图。仍待完整 GEO/10x 向导交互、干净 Mac、Developer ID 签名、公证和内置 R.framework。
- v17 已让 GEO `sample_title`/GSM 元数据进入分组页只读注释和候选建议；标题匹配先做安全分隔符规范化，仍保留逐项人工确认。最新本地回归为 `53 passed, 1 skipped`；v17 standalone 自检、clean 副本严格校验和两次独立真实屏幕监测均通过，第一次验证 GEO 注释驱动的 control/treated 建议，第二次实际完成公司 count TSV 的整理、分组、DESeq2 R worker 和结果页，并生成离线 HTML/XLSX/5 张图。仍待完整 GEO/10x 向导交互、干净 Mac、Developer ID 签名、公证和内置 R.framework。

## 2026-09-13 · 阶段 5 · v19 10x 三步导入向导与独立 R 基准

具体变更：10x 导入页新增可重复打开的三步向导，分别展示 Matrix Market 事实、feature type 构成和当前 bulk 分析边界；继续保存只读 `tenx-manifest.json`，不稠密化、不把细胞当独立重复。新增独立直接 R 基准测试，使用独立 limma/DESeq2 调用逐项核对 worker 的关键系数、统计量和 p 值。

验证：`.venv/bin/pytest -q` → `57 passed, 1 skipped`；v19 standalone 重建后 `packaging/verify_bundle.py` 返回 `ready: true`；clean 副本 `codesign --verify --deep --strict` 通过。两次全新真实屏幕监测均通过：第一次完整走完 10x 三步向导；第二次从公司 count TSV 完成表头/列角色、原始 count/线性尺度、整理、分组、DESeq2 R worker 与离线 HTML/XLSX/5 张图结果页。正式 Developer ID 签名、公证、内置 R.framework 和干净 Mac 验收仍需发布环境。

## 2026-09-13 · 阶段 5 · v20 GEO 三步向导、压缩候选树与最终双屏验收

具体变更：GEO Series Matrix 新增“数据与平台事实→样本注释来源→分析含义确认”三步导入向导，展示平台、GSM、sample title，并明确本地离线、人工确认和不自动上传/猜分组边界。压缩包候选对象改为层级目录树，分别展示类型/用途、形状与文件大小、完整性，并保留来源路径提示；同时修正 py2app 构建配置，避免新 setuptools 将项目依赖误传给 py2app。

验证：`.venv/bin/pytest -q` → `59 passed, 1 skipped`；v20 standalone `packaging/verify_bundle.py` 返回 `ready: true`，Apple Silicon、Rscript、jsonlite、limma、statmod、DESeq2 和 worker 资源均通过；clean 副本 `codesign --verify --deep --strict` 通过。最终 bundle 完成两次全新真实屏幕监测：第一次从 GEO 测试 Series Matrix 逐步走完三页并看到 4 个 GSM、sample title 和 GPLV20；第二次从公司 count TSV 完成表头/列角色、原始 count/线性尺度、整理、分组、DESeq2 R worker 和结果页，等待期间显示已等待秒数，完成后生成离线 HTML/XLSX/5 张图，未留下 Rscript 进程。正式 Developer ID 签名、公证、内置 R.framework 和干净 Mac 验收仍需发布环境。
## 2026-09-13 · 阶段 5 · v18 10x 稀疏校验与 R worker 等待反馈

具体变更：10x Matrix Market 导入现在流式校验稀疏坐标边界、声明/实际条目数量和有限数值，不创建稠密矩阵；导入页展示维度、非零条目、稀疏度和 feature type 汇总，并明确不把细胞作为独立 bulk 样本。R worker 等待状态每 2 秒报告已等待秒数，超过 120 秒会终止进程并返回明确超时错误；补充对应 reader/UI 回归测试。

验证：`.venv/bin/pytest -q` → `55 passed, 1 skipped`；v18 standalone 重建后 `packaging/verify_bundle.py` 返回 `ready: true`，Apple Silicon、Rscript、jsonlite、limma、statmod、DESeq2 和 worker 资源均可用；clean 副本 `codesign --verify --deep --strict` 通过。v18 完成两次独立真实屏幕监测：第一次选择本地合成 10x 目录并看到 1000×600、3000 个非零条目和 99.50% 稀疏度；第二次从公司 count TSV 完成表头/列角色、单位/尺度、整理、DESeq2 R worker 与结果页，并生成离线 HTML/XLSX/5 张图。正式 Developer ID 签名、公证、内置 R.framework 和干净 Mac 验收仍需发布环境。
