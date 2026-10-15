# 2026-09-14 审查问题修复记录

状态：进行中，尚未整体验收。

用户授权三个 Luna（gpt-5.6-luna）high 代理并行修复，主代理整合。

- log_gates：通用 log 门禁、实际设计残差检查；仅 planning.py 与专用测试。
- r_variance：正式 limma 退化行、版本参数和 R 绘图矩阵输出；仅 worker.R 与专用测试。
- plot_matrix：使用 runner 绘图矩阵、尺度标签、过滤后索引与专用测试。
- 主代理：AnalysisService 契约校验、整合回归和日志。

接口约定：result.plot_matrix = {feature_ids, sample_ids, values, transform}；values 为特征×样本行数组，sample_ids 必须与输入顺序相同，特征为唯一输入子集，数值有限且转换说明非空。count 不得回退原始计数绘图。

已修改：analysis/service.py 增加该契约校验；tests/test_review_plot_contract.py 定向验证通过（1 passed）。其余修改和全量回归待代理完成后核对。没有重新打包，现有 .app 尚不包含本轮修复。

## 整合验收

最新完整回归：`.venv/bin/pytest -q -rs` → **77 passed, 1 skipped**，43.59秒。跳过项为缺DESeq2的失败分支测试，因为本机已安装该包；正常路径已覆盖。上一轮因df.prior=0被误判失败，已修正为允许非负值和正Inf，保留方差有限正检查。

已验证：通用log完整门禁、12恒定特征阻断、未知转换证据阻断、实际batch/subject残差、正式limma退化行NA与有效BH、runner绘图子集/样本索引、count VST（失败明确标记normalized-count log回退）、相关性零方差掩码及空热图。

代码：planning.py、worker.R、plot_service.py、analysis/service.py；新增tests/test_review_log_gates.py、test_review_r_variance.py、test_review_plot_matrix.py、test_review_plot_contract.py。

现有 .app 未重打包，不包含本轮源码修改。原审查中的输入转换UI、导入QThread、完整参考自动化、120秒超时和正式发布验收仍待后续工作，本轮不扩展范围。

额度核查：2026-09-14账号五小时已用39%、周已用24%，无本轮开始前快照，无法计算本轮或逐代理用量。三个spawn调用均明确gpt-5.6-luna/high，工具未提供逐代理计费明细。后续建议单代理medium，难点才high；不将API定价视为订阅额度折算。
