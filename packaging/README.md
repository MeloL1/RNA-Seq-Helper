# macOS 打包

候选 standalone bundle 需要先构建 Python/Qt，再把本机 R 的最小依赖子集内置进去：

```bash
cd packaging && ../.venv/bin/python setup.py py2app
../.venv/bin/python embed_r_runtime.py --app 'dist/RNA-Seq Helper.app'
```

`embed_r_runtime.py` 只读 `/Library/Frameworks/R.framework`，当前内置 R 4.6.0、base/recommended 包及 limma、DESeq2、jsonlite、statmod 的递归依赖，不删除或改写系统 R。它还会重写 app 内动态库路径，并为被改写的 Mach-O 组件做本机 ad-hoc 签名。正式发布仍须在发布环境用 Developer ID 重新签名和公证。

构建完成后可用离线验证器检查 app 内的 Python、R、limma、DESeq2 和 worker 资源：

```bash
.venv/bin/python packaging/verify_bundle.py
```

也可以验证 clean 副本：

```bash
.venv/bin/python packaging/verify_bundle.py --app "/tmp/RNA-Seq-Helper-clean.app"
```

正式发布前可运行离线发布检查器；它只报告缺口，不会伪造开发者签名或联网公证：

```bash
.venv/bin/python packaging/release_check.py
```

若构建目录带有 Finder 扩展属性，可复制一份不带扩展属性的检查副本；脚本不会覆盖源 bundle。当前含内置 R.framework 的 clean 副本已能通过本机严格 ad-hoc 校验，但这不等同 Developer ID 或公证：

```bash
.venv/bin/python packaging/prepare_clean_bundle.py --output /tmp/RNA-Seq-Helper-clean.app
```

在具备 PySide6、numpy 和 py2app 的固定构建环境后，检查 `.app` 内的 Qt 插件、R.framework、BLAS/Fortran 动态库、worker 路径和 Apple Silicon/Intel 架构，再进行签名、公证和干净 Mac 验证。当前版本尚未声称完成正式打包。

若项目路径继承了 macOS FinderInfo/provenance 扩展属性，严格签名校验可能误报资源错误。发布前应从无扩展属性的干净构建目录重新签名；本阶段只验证了本机 ad-hoc 构建和无扩展属性复制品的校验。
