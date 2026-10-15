"""复制并验证无 Finder 扩展属性的本机 bundle；不覆盖源 bundle。"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="创建用于本机签名检查的 clean app 副本")
    parser.add_argument("--source", type=Path, default=Path("packaging/dist/RNA-Seq Helper.app"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = args.source.expanduser().resolve()
    output = args.output.expanduser().resolve()
    if not source.is_dir() or output.exists():
        raise SystemExit("源 bundle 不存在，或目标路径已存在；为避免覆盖请另选目标路径。")
    output.parent.mkdir(parents=True, exist_ok=True)
    # --norsrc 在当前 macOS 上会把 R.framework 内的链接式资源目录排除，
    # 造成 clean 副本看似成功但实际丢失内置 R。只禁用扩展属性即可满足
    # 严格签名检查，同时保留 bundle 的完整 Frameworks 结构。
    subprocess.run(["ditto", "--noextattr", str(source), str(output)], check=True)
    # provenance 可能在复制后由系统重新附加；只清理这个新建的临时副本，
    # 不触碰源 bundle 或用户文件。
    subprocess.run(["xattr", "-cr", str(output)], check=True)
    # py2app 在本机可能复制出一个已经被 install_name_tool 改写、但未重新签名的
    # liblzma；用 Homebrew 原件重建其 app 内 ID，再签名该子组件。
    liblzma = output / "Contents" / "Frameworks" / "liblzma.5.dylib"
    homebrew_liblzma = Path("/opt/homebrew/opt/xz/lib/liblzma.5.dylib")
    if liblzma.exists() and homebrew_liblzma.exists():
        shutil.copy2(homebrew_liblzma, liblzma)
        subprocess.run(["install_name_tool", "-id", "@executable_path/../Frameworks/liblzma.5.dylib", str(liblzma)], check=True)
        subprocess.run(["codesign", "--force", "--timestamp=none", "--sign", "-", str(liblzma)], check=True)
    subprocess.run(["codesign", "--force", "--deep", "--timestamp=none", "--sign", "-", str(output)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(output)], check=True)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
