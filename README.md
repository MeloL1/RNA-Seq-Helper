# RNA-Seq Helper

面向非生信用户的本地 GEO2R 式两组表达分析工具。当前实现已进入阶段 5：包含安全导入与显式整理、分组和分析计划、独立 R worker、DESeq2/limma-trend 差异分析、PCA/相关性/火山图/热图，以及离线 HTML/XLSX 报告。当前开发版本为 v0.30，尚未正式发布；候选包已内置最小 R 4.6.0 运行时，可在本机 clean 副本中离线启动。

## 开发运行

```bash
.venv/bin/python -m rnaseq_helper.app --self-check
.venv/bin/python -m rnaseq_helper.app --micro-test
.venv/bin/python -m rnaseq_helper.app --micro-deseq2
.venv/bin/python -m pytest -q
```

安装 GUI 依赖后启动空壳：

```bash
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m rnaseq_helper.app
```

运行本机已安装版本：

```bash
open "/Applications/RNA-Seq Helper.app"
```

重新构建当前打包版后，产物会生成在 `packaging/dist/`：

```bash
open "packaging/dist/RNA-Seq Helper.app"
```

## 常见提示

- “R worker 运行中……”表示正在等待独立 R 进程；新版会每 2 秒显示已等待时间。请求写入 R worker 并关闭输入后，开始计算单次响应等待时间；代码默认超过 600 秒会终止该 worker 并报告超时。这个时限不含启动/准备请求的时间，也不含结果返回后的 Python 处理、绘图、报告生成，因此不是整个导入或分析流程的总时限。任务期间可随时取消。微型验证正常会显示“limma/DESeq2 微型验证通过”，否则会报告具体失败原因。
- “还不能确认这些数字是原始计数、TPM、FPKM……”不是程序崩溃，而是安全门禁；软件会先提示确认单位，再提示确认尺度。可以先看预览；对数据说明不确定时不要猜，事实未确认前不会放行分析。
- 导入文件后软件会给出单位/尺度候选，并展示线索来自哪个文件、工作表和扫描范围；这不是原文引用，也不会自动代替确认。单位与尺度未确认时会按顺序一次提示一项；没有足够证据时保持“未确认”，允许看预览，但不放行分析。
- 2026-10-03 的隔离候选包内置 R.framework；源码运行仍按本机配置定位 R。当前安装版早于本轮源码，不能用来验收最新界面。候选包的状态、准确路径及人工验收步骤见 `docs/development/STATUS.md` 与 `docs/development/MANUAL-ACCEPTANCE-2026-10-03.md`。

R worker 通过 JSON Lines 与 Python 独立进程通信。它不读取用户原始数据目录，也不会联网下载数据。R 脚本保留清华 CRAN 镜像配置，实际安装依赖由用户明确执行。

## 目录约定

- `src/rnaseq_helper/domain/`：不可变领域 DTO 和任务上下文。
- `src/rnaseq_helper/r_bridge/`：独立 R worker 协议与客户端。
- `src/rnaseq_helper/services/`：运行时检查和阶段 0 自检。
- `src/rnaseq_helper/ui/`：仅包含 Qt 相关代码。
- `resources/r/`：固定 R 入口。
- `packaging/`：py2app 配置和构建说明。

结果项目会写入 `~/Documents/RNA-Seq Helper Projects/`，包含 `prepared/`、`analysis/`、`figures/` 和 `reports/`。原始输入文件保持只读。

GUI 也提供“选择 10x 目录”入口；10x 细胞级数据仅做完整性/稀疏元信息检查，不会直接当作 bulk 样本分析。

表达矩阵和本地参考表支持 CSV、TSV、TXT、XLS、XLSX 等格式；旧式 `.xls` 使用 `xlrd` 读取，`.xlsx/.xlsm` 使用 `openpyxl` 读取。Excel 工作表不会自动拼接，需在“整理并确认”中逐张查看并选择正确工作表。

截至 2026-10-04，当前源码的隔离候选位于 `/private/tmp/rnaseq-helper-compact-ui.HADQ06/RNA-Seq Helper.app`，内置 R 4.6.0、limma、DESeq2、jsonlite、statmod，新增紧凑识别布局和GUI致命信号日志。源码比对、strict ad-hoc 签名及CLI自检通过；R微型profile在新增诊断前已通过，其分支未改。**新版桌面验收尚未完成，Python原生崩溃尚未修复**：此前Hx6JkY候选真实GSE桌面验证发生Qt Cocoa/辅助功能崩溃，之后用户手动走到数值页，但不能据此证明全流程稳定。新版在正常手动使用中再次退出时，可将 `~/Library/Logs/RNA-Seq Helper/fatal/` 下非空日志与同PID系统崩溃报告配对诊断；日志可能包含本机源码路径，不应直接公开分享。CLI和离屏测试不代表普通桌面流程稳定。此前obwEZq/qDAcnT包已移入废纸篓，不能继续按旧路径启动。安装版未覆盖，也不能用于验收最新源码。项目尚非正式发行版，缺Developer ID签名、公证、干净Mac验收及正式安装器。当前状态见 `docs/development/STATUS.md`、`docs/development/CRASH-2026-10-04.md` 和 `docs/development/CRASH-DIAGNOSTICS-2026-10-04.md`；人工清单见 `docs/development/MANUAL-ACCEPTANCE-2026-10-03.md`。
