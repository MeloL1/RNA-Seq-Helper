"""离线发布前检查；不联网、不签名、不读取用户表达矩阵。"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
from pathlib import Path


def _run(command: list[str]) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(command, capture_output=True, check=False)
    except OSError as exc:
        return 127, "", str(exc)
    # xattr -lr 可能返回 FinderInfo 等非 UTF-8 字节；发布检查不能因此崩溃。
    stdout = completed.stdout.decode("utf-8", errors="replace").strip()
    stderr = completed.stderr.decode("utf-8", errors="replace").strip()
    return completed.returncode, stdout, stderr


def main() -> int:
    parser = argparse.ArgumentParser(description="离线检查 RNA-Seq Helper macOS 发布包")
    parser.add_argument("--app", type=Path, default=Path("packaging/dist/RNA-Seq Helper.app"))
    args = parser.parse_args()
    app = args.app.expanduser().resolve()
    executable = app / "Contents" / "MacOS" / "RNA-Seq Helper"
    worker = app / "Contents" / "Resources" / "resources" / "r" / "worker.R"
    blockers: list[str] = []
    warnings: list[str] = []
    if platform.system() != "Darwin":
        blockers.append("当前系统不是 macOS")
    if not app.is_dir() or not executable.is_file() or not worker.is_file():
        blockers.append("app、主程序或 R worker 资源不完整")

    signature = {"valid": False, "identity": None, "detail": "codesign 不可用或尚未检查"}
    if shutil.which("codesign") and app.is_dir():
        code, stdout, stderr = _run(["codesign", "--verify", "--deep", "--strict", str(app)])
        detail = stderr or stdout
        signature["valid"] = code == 0
        signature["detail"] = detail or ("通过" if code == 0 else "校验失败")
        _, display, verbose_error = _run(["codesign", "-dv", "--verbose=4", str(app)])
        identity_line = next((line for line in (display + "\n" + verbose_error).splitlines() if line.startswith("Authority=")), None)
        signature["identity"] = identity_line.split("=", 1)[1] if identity_line else None
        if not signature["valid"]:
            blockers.append("codesign --verify --deep --strict 未通过")
        elif not signature["identity"] or signature["identity"] == "-":
            blockers.append("当前签名是 ad-hoc，不是开发者证书签名")
    else:
        blockers.append("缺少 codesign 或 app")

    if shutil.which("security"):
        code, stdout, _ = _run(["security", "find-identity", "-v", "-p", "codesigning"])
        valid_identity_count = next((int(line.split()[0]) for line in stdout.splitlines() if "valid identities found" in line), 0)
        if valid_identity_count == 0:
            warnings.append("本机没有可用开发者签名身份")

    if shutil.which("xattr") and app.is_dir():
        code, stdout, stderr = _run(["xattr", "-lr", str(app)])
        if code == 0 and stdout:
            warnings.append("app 内仍有扩展属性；发布前应从无扩展属性构建目录复制")
        elif code not in {0, 1} and stderr:
            warnings.append(f"扩展属性检查失败：{stderr}")

    embedded_r = (app / "Contents" / "Frameworks" / "R.framework").exists()
    if not embedded_r:
        blockers.append("app 未内置 R.framework；当前包依赖本机 Rscript")
    result = {
        "ready_for_formal_release": not blockers,
        "app": str(app),
        "architecture": platform.machine(),
        "standalone_r_framework": embedded_r,
        "signature": signature,
        "blockers": blockers,
        "warnings": warnings,
        "next_steps": [
            "在发布机用 Developer ID Application 证书签名",
            "在具备 Apple notarization 权限的环境执行公证并 stapler validate",
            "在干净 Mac 上验证双击启动、中文/空格路径、断网、权限和休眠恢复",
        ],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ready_for_formal_release"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
