# RNA-Seq Helper

面向非生信用户的本地 GEO2R 式两组表达分析工具。当前版本为 0.35.0，包含安全导入与显式整理、分组和分析计划、独立 R worker、DESeq2/limma-trend 差异分析、交互式结果工作台、差异基因检索与逐样本表达查看、分析历史、结果筛选与离线报告。

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
- v0.35.0 加宽了导入清单的识别结果/预览尺寸列，并在离线 HTML 报告中分别列出正、负 log2FoldChange 的代表性基因，每个方向最多 10 个；完整统计结果仍保留在 XLSX 中。

R worker 通过 JSON Lines 与 Python 独立进程通信。它不读取用户原始数据目录，也不会联网下载数据。R 脚本保留清华 CRAN 镜像配置，实际安装依赖由用户明确执行。

## 目录约定

- `src/rnaseq_helper/domain/`：不可变领域 DTO 和任务上下文。
- `src/rnaseq_helper/r_bridge/`：独立 R worker 协议与客户端。
- `src/rnaseq_helper/services/`：运行时检查和阶段 0 自检。
- `src/rnaseq_helper/ui/`：仅包含 Qt 相关代码。
- `resources/r/`：固定 R 入口。
- `packaging/`：py2app 配置和构建说明。

分组设置之后可确认结果保存位置；默认在所选表达数据所在文件夹内新建项目文件夹，名称包含日期、数据标识和当前确认的数据类型。可改选项目文件夹的上级位置；计划和分析结果放在 `analysis/`，图放在 `figures/`，报告和 XLSX 放在 `reports/`，整理矩阵放在 `prepared/`。项目根目录不散放结果文件，原始输入文件保持只读。

GUI 也提供“选择 10x 目录”入口；10x 细胞级数据仅做完整性/稀疏元信息检查，不会直接当作 bulk 样本分析。

表达矩阵和本地参考表支持 CSV、TSV、TXT、XLS、XLSX 等格式；旧式 `.xls` 使用 `xlrd` 读取，`.xlsx/.xlsm` 使用 `openpyxl` 读取。Excel 工作表不会自动拼接，需在“整理并确认”中逐张查看并选择正确工作表。

筛选阈值与统计模型参数分离；应用筛选只刷新结果展示，不重跑 R，也不更改原始统计列。
