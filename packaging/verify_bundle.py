"""本机 standalone bundle 验证器；不联网、不读取用户原始数据。"""

from __future__ import annotations

import json
import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "packaging" / "dist" / "RNA-Seq Helper.app"
EXECUTABLE = APP / "Contents" / "MacOS" / "RNA-Seq Helper"
WORKER = APP / "Contents" / "Resources" / "resources" / "r" / "worker.R"


def _run(executable: Path, mode: str) -> dict[str, object]:
    completed = subprocess.run(
        [str(executable), mode],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    lines = completed.stdout.splitlines()
    start = next((index for index, line in enumerate(lines) if line.startswith("{")), None)
    payload = json.loads("\n".join(lines[start:])) if start is not None else {}
    if completed.returncode != 0:
        raise RuntimeError(f"{mode} 失败：{completed.stderr.strip() or completed.stdout[-500:]}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 macOS standalone bundle")
    parser.add_argument("--app", type=Path, default=APP)
    args = parser.parse_args()
    app = args.app.expanduser().resolve()
    executable = app / "Contents" / "MacOS" / "RNA-Seq Helper"
    worker = app / "Contents" / "Resources" / "resources" / "r" / "worker.R"
    if sys.platform != "darwin":
        print("此验证器只用于 macOS standalone bundle。", file=sys.stderr)
        return 2
    missing = [str(path) for path in (app, executable, worker) if not path.exists()]
    if missing:
        print(json.dumps({"ready": False, "missing": missing}, ensure_ascii=False, indent=2))
        return 1
    self_check = _run(executable, "--self-check")
    limma = _run(executable, "--micro-test")
    deseq2 = _run(executable, "--micro-deseq2")
    embedded_prefix = str(app / "Contents" / "Frameworks" / "R.framework")
    if not str(self_check.get("rscript", "")).startswith(embedded_prefix):
        raise RuntimeError("bundle 的 Rscript 未解析到 app 内 R.framework")
    result = {
        "ready": bool(self_check.get("ready_for_stage0_r")),
        "app": str(app),
        "standalone_r_framework": True,
        "architecture": self_check.get("architecture"),
        "rscript": self_check.get("rscript"),
        "r_packages": self_check.get("r_packages"),
        "limma_profile": limma.get("profile_id"),
        "limma_method": limma.get("method"),
        "deseq2_profile": deseq2.get("profile_id"),
        "deseq2_method": deseq2.get("method"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ready"] and result["limma_method"] and result["deseq2_method"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
