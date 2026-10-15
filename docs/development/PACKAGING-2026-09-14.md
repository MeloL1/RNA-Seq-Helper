# RNA-Seq Helper 打包记录（2026-09-14）

## 构建

按 `packaging/README.md` 的既有流程，在当前源码工作目录执行：

```bash
cd "/Users/additionlee/Desktop/Master.nosync/agent/RNA-Seq Helper/packaging"
../.venv/bin/python setup.py py2app --force
../.venv/bin/python embed_r_runtime.py --app 'dist/RNA-Seq Helper.app'
```

`py2app` 生成 arm64 standalone bundle。`embed_r_runtime.py` 从系统 `/Library/Frameworks/R.framework` 只读复制最小运行时；日志为 R 4.6、75 个包、105 次 Mach-O 依赖重写、90 个组件签名。未修改系统 R，也未读取或下载实验数据。

随后用 `prepare_clean_bundle.py` 生成无 Finder 扩展属性的 clean 副本，并完成本机 ad-hoc 签名。项目目录会被 macOS 自动附加 provenance，严格签名校验因此使用 clean canonical app：

```text
/Users/additionlee/Applications/RNA-Seq Helper.app
```

桌面双击入口为 Finder alias：

```text
/Users/additionlee/Desktop/RNA-Seq Helper（双击启动）.app
```

该 alias 指向上述 canonical app；桌面没有覆盖原有 RNA-Seq Helper 用户软件。项目内 `packaging/dist/RNA-Seq Helper.app` 保留当前构建产物，带 provenance 的路径不作为严格签名证据。

## 验证

```bash
./.venv/bin/python packaging/verify_bundle.py \
  --app "/Users/additionlee/Applications/RNA-Seq Helper.app"
```

结果：`ready=true`，架构 `arm64`，Rscript 解析到 app 内 `Contents/Frameworks/R.framework`；jsonlite、limma、statmod、DESeq2 均存在；limma 方法为 `LIMMA_ON_LOG_EXPRESSION`，DESeq2 方法为 `DESEQ2`。

```bash
codesign --verify --deep --strict "/Users/additionlee/Applications/RNA-Seq Helper.app"
```

结果通过，为本机 ad-hoc 签名，不代表 Developer ID 签名、公证或干净 Mac 验收。

启动验证：

```bash
open "/Users/additionlee/Applications/RNA-Seq Helper.app"
```

启动后 app 进程持续运行；命令行 self-check 与 GUI 进程均未立即退出。

## 源码与包一致性

内置 worker 与源码 `resources/r/worker.R` 的 SHA256 均为：

```text
22cd26e83d92d0f7ede7b50839ee98dcc6dca3bdb009956434582ff051e4839e
```

本次包基于 2026-09-14 回归通过的当前源码（77 passed, 1 skipped），包含 planning.py、worker.R、plot_service.py 和 analysis/service.py 的修复；未重复运行整套 pytest。
