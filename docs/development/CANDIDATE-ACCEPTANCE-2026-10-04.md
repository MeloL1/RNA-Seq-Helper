# 10 月 4 日候选验收证据

## 新UI修订HADQ06（当前源码；桌面待验）

用户已给出Hx6JkY的GSE10361扫描候选/结构预览/数值页截图，这段手动操作成功；截图带Appshot AX文本，不能称无AX对照，也不证明全流程稳定。重复说明挤占预览的问题已修正为单份摘要/必要问题＋限高滚动证据；UNKNOWN门禁和原文确认要求保留。176 passed、1 skipped（47.81秒）。

新的隔离候选 `/private/tmp/rnaseq-helper-compact-ui.HADQ06/RNA-Seq Helper.app`，复用旧runtime仅更新ImportPage/字节码；全Python源码一致、严格ad-hoc签名通过，bundle自检ready=true、limma/DESeq2 CLI profile通过。ImportPage SHA256 `07e961323e333b9a23452824faefd5b4157cb8f04c13209642e31a0e594a2c2f`。两尺寸离屏页面几何检查已完成，但未进行该候选的实屏操作或新截图。用户运行中的Hx6JkY未覆盖、未关闭；安装版未更新。原生崩溃独立保留未修复结论。

## 02:06 CST · 当前候选桌面验收失败（优先于下方历史结果）

Hx6JkY 更新 scanner 后 PID36715 实际选择 GSE10361，进入扫描；随后进程原生 SIGSEGV退出，新的系统 .ips 明确对应 PID。Qt Cocoa 选中项辅助功能接口/AXCopyHierarchy栈，未完成导入。详情见 `CRASH-2026-10-04.md`。不再对候选读取AX，改为原生报告/最小进程复现；没有新修复、没有安装版更新。下方CLI/签名/离屏回归通过均不代表桌面稳定。

## 最新修订：scanner 关联修复后版本

Hx6JkY **同路径已更新源码版本**：修正 README 自身名称误关联、短表名漏关联及文件名子串误匹配。四项新增文字合同测试，定向 34 passed，全量 172 passed、1 skipped（47.35 秒）；修改前快照 `/private/tmp/rnaseq-helper-sidecar-link-fix.wq9TNr/scanner.py`。

仅更新 scanner/字节码并重签名，未重建 runtime。全 Python 源码比对一致；源码/包内 scanner SHA256 `83666d61762e00c5bc420622eb9f1d7dd34b1d0964a3b90cd78a8c61977c521d`；严格签名通过，verify_bundle ready=true、limma/DESeq2 CLI profile 通过。ImportPage、worker 未改。

下文 GUI 路径输入、GSE 组件读取和签名的启动后复核均为更新前证据；更新后只有源码/回归/CLI/签名证据，**没有新增桌面验收通过项**。安装版未更新，MySQL 未访问。当前仍需完整 GUI 扫描/预览、拖放、布局和取消/关闭；不反复请求解锁或用组件验证替代桌面验收。

## 范围与现状

先验收既有 UtT843 候选，不更动安装版。本轮通过 GUI 验证了 R 启动、进度、完成和立即取消；真实 GSE 导入暴露新的文件名补全卡顿。它是本轮新定位的问题，不等于所有历史 Python 退出已经修复。

旧候选：`/private/tmp/rnaseq-helper-r2-release-candidate.UtT843/clean/RNA-Seq Helper.app`。
新候选：`/private/tmp/rnaseq-helper-chooser-candidate.Hx6JkY/clean/RNA-Seq Helper.app`，约 1.7 GiB。复用原已验证 bundle runtime，仅更新 ImportPage 源码和对应字节码后重新 ad-hoc 签名；未重复 py2app/R 依赖构建。全 Python 源码目录与当前源码无差异，`import_page.py` SHA256 同为 `fa8fedb322317102e6a4ff47aac423c8bcc0facbf6d66b9f93aa82e0f76496aa`。Bundle 自检 `ready=true`、两个 R CLI profile 通过，严格签名在 GUI 启动后再次核验通过。清理新副本扩展属性时 liblzma 返回一条 permission denied，但未影响重新签名及严格校验；不能称无全部扩展属性。

| 项目 | 当前证据 | 结论 |
|---|---|---|
| 包内 Python 源码与当前源码 | Hx6JkY 修复后全目录 diff 无差异，排除字节码 | 当前源码一致 |
| R worker | SHA256 `22cd26e83d92d0f7ede7b50839ee98dcc6dca3bdb009956434582ff051e4839e` | 未改 |
| GUI limma 微型验证 | 观察运行状态及“limma 微型验证通过。”、按钮恢复 | UtT843 通过 |
| GUI DESeq2 微型验证 | 观察运行状态及“DESeq2 微型验证通过。”、按钮恢复 | UtT843 通过 |
| GUI 微型任务立即取消 | 同一调用中观察运行后点击取消，得到“验证失败：任务已取消”、按钮恢复 | UtT843 通过；提示将取消写作失败，留作后续文案修整 |
| GSE10361 文件选择器键盘路径输入 | UtT843 输入超时；Hx6JkY 重复同一路径后 1.19 秒工具调用正常返回，主窗口显示真实文件名及正在检查文件 | Hx6JkY 路径输入通过；不是普通鼠标浏览完整验收 |
| GSE10361 GUI 扫描 | Hx6JkY 已启动扫描但未观察到候选结果；采样主线程正常等待事件，QThread 停在 Python 文件打开调用，随后桌面工具确认自动锁屏 | 未完成；不宣称扫描、预览、事实门禁或完整分析通过 |
| GSE10474 候选组件读取/校验 | 主机 Python 明确加载 Hx6JkY 内的 scanner/preparation 源码；扫描、40×35 预览、完整读取、未知事实校验全部完成 | 通过（受限组件诊断）；不是 .app 文件访问或 GUI 验收 |
| Finder 拖放 | 只在 Finder 定位并选中原文件，没有完成跨窗口拖放 | 未验证 |
| 事实/列角色/分组双尺寸和外观 | 仅添加数据页和微型验证对话框截图 | 未验证 |
| 整理运行中取消/关闭 | 既有离屏契约通过，本轮没有实屏证据 | 未验证 |
| 安装版更新 | 没有替换 `/Applications` 或桌面入口 | 未执行 |
| 正式发布 | 只有本机 ad-hoc，缺 Developer ID/公证/干净 Mac | 不具备正式分发条件 |

截图保留在本轮对话工具输出，未另存项目图片。启动与进程采样不是正常 GUI 关窗验收。无响应 PID 33700 核对路径及无 R 任务后已 SIGTERM 结束。

## 卡顿证据及修复边界

采样：`/private/tmp/rnaseq-helper-candidate-33700-20261004.sample.txt`（01:32:16 CST，2 秒）。主线程 183/183 个样本位于：

`QDialog::exec → QCompleter::eventFilter → QLineEdit::keyPressEvent → QFileSystemModel::fetchMore → QFileInfoGatherer::watchPaths → QFileSystemWatcher::addPaths → QDirIterator → __opendir2 → __open_nocancel`。

Finder 仍响应，无对应新 Python/app `.ips`；这是文件选择路径补全阶段阻塞，未采到 AX 崩溃栈。缓解仅关闭三个导入相关 chooser 的文件名自动补全和目录监视，保留手动浏览、明确打开、多选/目录选择/参考过滤以及取消。不会保证任意不可访问文件系统都不会阻塞；关闭监视后打开期间外部文件变化不承诺自动刷新。

## 真实 GSE 的事实证据

原始数据只读、不下载、不运行独立 R 分析。本地矩阵文件（不是整个 accession 目录）大小经 `stat` 核对：

- GSE10361：`/Users/additionlee/Desktop/Master.nosync/agent/Codex's House/SEALI_ALI/0_Raw/GSE10361_series_matrix.txt.gz`，1,645,548 B。解压文本第 46 行的 `!Sample_data_processing` 仅写 `Affymetrix STATISTICAL_ALGORITHM_TYPE`，不明确具体算法、单位或 log 底数。
- GSE10474：同目录 `GSE10474_series_matrix.txt.gz`，2,124,974 B。解压文本第 46 行写 `GCRMA`；第 9 行总体设计为 13 例 ALI+sepsis、21 例 sepsis alone。算法名字本身不作为本文件具体单位/变换的充分证据。代理报告的 251,252,192 B 是 accession 汇总，不能当作这个压缩矩阵的文件大小。

本地 `SEALI_ALI/2_Script/00_read_data.R` 第 137–150 行则从 GSE10474 CEL 用 RMA 重处理后映射/折叠并写 RDS，只借 Series Matrix 提取标题和分组。这不是原 GEO 提交矩阵的处理证明，也未验证现有 RDS 来自哪次执行。不能把两个输入混为同一版本。

因此当前不能为了验收绕过 UNKNOWN 门禁或猜造 log2 确认；完整正式分析仍需与所选矩阵对应的明确处理说明。两项 GUI 微型验证的固定输入不用于证明真实数据识别准确性。

## 清理与持久化

- 经 lsof 确认无占用后，将 obwEZq 与 qDAcnT 两份更早 app 移入用户废纸篓（合计约 3.4 GiB，可恢复；未清空废纸篓，不能称释放了对应磁盘空间）。旧 `/tmp` app 入口已消失。
- qDAcnT 中取消测试负载保留，20,179,066 B，SHA256 `6dafd7a24d5b6ccd8d7bfd1f1464ed7c6735766b468855f537febac02dd1aec9`。移除了空 PI00wN 和上述已空父/子目录。
- 本轮四个微型任务的空工作目录经 lsof 确认无占用后 rmdir。当前故障对照候选、采样证据、源码/文档/环境/原始数据不删除。
- MySQL 未访问、未登记本文件。此前凭据回显事件尚无轮换完成证据；不读取凭据或复用泄露值。

## 修复验证与续接

### 01:55 CST · GSE10474 的新增受限组件诊断

中断前的 tccd 扩展查询 session 26917 在续接时已不存在（Unknown process id），进程检查也没有该查询或候选 GUI 进程；未重启查询，无法把缺失输出解释为无授权问题。

为区别处理逻辑与桌面进程的文件访问，做一次 15 秒硬限额、只读的 GSE10474 子进程诊断。它使用主机 `.venv/bin/python`，明确从 Hx6JkY 的 `Contents/Resources/lib/python3.14` 加载 `recognition/scanner.py` 和 `preparation/service.py`；断言模块路径在候选内，并设置 `PYTHONDONTWRITEBYTECODE=1`，不改候选。未调用独立 R、未启动 GUI、未改产品代码、未重复回归或构建。

- 输入：2,124,974 B，SHA256 `3cbf46e72f45f39da53f89c9c49aad0d24e83ea70c60f48135d7cccbc6976ee4`，读取前后相同。
- 扫描：GEO_SERIES_MATRIX，单位/尺度 UNKNOWN/UNKNOWN。
- 有限预览：40 行×35 列；完整读取/校验：22,277 个特征、34 个样本、757,418 个数值单元格。
- 阻断：UNKNOWN_MEASUREMENT、UNKNOWN_SCALE，未保存矩阵、未生成分析结果，临时项目目录为空并自动移除。
- 本次处理约 0.1778 秒；子进程峰值 RSS 103.33 MiB。这里只记录一次受限组件运行，不作规模性能推广。
- 范围限制：不是 `.app` 可执行文件的进程，具有不同运行/访问上下文；而且输入与之前卡住的 GSE10361 不同。因此不能把它说成解决了原 GUI 文件打开阻塞、证明了桌面文件权限或正式分析可用。

这份新真实输入补充了候选组件读取与未知门禁证据，未弥补表中缺失的桌面流程。继续保留全部人工待验项，不因组件通过覆盖安装版。

chooser 定向测试 **6 passed（0.48 秒）**，主流程稳定后只运行一次全量回归：`QT_QPA_PLATFORM=offscreen .venv/bin/pytest -p no:cacheprovider -q`，**168 passed、1 skipped（46.63 秒）**。没有重跑既有 162 项基线来充作无代码变化的新进展，本轮全量覆盖新增 chooser 修复。

源码恢复点：`/private/tmp/rnaseq-helper-file-dialog-safety.0Ui68G/import_page.py`。两位 Luna/MAX 代理均已结束并关闭。

新候选 PID 35379 已确实进入真实 GSE 扫描；工具随后返回“Mac is locked”。一秒 sample（`/private/tmp/rnaseq-helper-candidate-35379-20261004.sample.txt`）显示主线程处于正常 macOS 事件等待，QThread 的 92 个样本处于 Python `_io_FileIO` 的 `__open`。没有足够证据判定是文件服务、授权等待或其他原因，tccd 的该 PID 窄范围日志查询为空，不能据此断言文件权限错误。遵照无人值守指示，不重复截图/解锁；扫描未交付结果即核对 PID 后 SIGTERM 结束本次测试，不记作正常协作取消或关窗通过。原 GSE 摘要仍一致。

下次直接验收 Hx6JkY，不再构建或重跑已通过测试：先补扫描完成/候选/预览及未知门禁，必要时只对当前文件打开阻塞做一次有时间限制的核验；然后补 Finder 拖放、指定双尺寸、整理取消/关闭和新候选 GUI R 按钮复验。整体验收未通过，不删除 UtT843 故障对照、不更新安装版。
