from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def resolve_rscript(requested: str = "Rscript") -> str:
    """解析 Finder 启动时不一定继承的 shell PATH。"""

    if requested != "Rscript":
        return requested
    # py2app 冻结后，优先使用 app 内置的 R.framework；否则会因 Finder
    # 环境的 PATH、用户库或系统 R 版本不同而出现“同一 app 不同结果”。
    executable = Path(sys.executable).resolve()
    embedded = executable.parent.parent / "Frameworks" / "R.framework" / "Resources" / "bin" / "Rscript"
    candidates = [
        os.environ.get("RNASEQ_HELPER_RSCRIPT"),
        str(embedded),
        shutil.which("Rscript"),
        "/Library/Frameworks/R.framework/Resources/bin/Rscript",
        "/usr/local/bin/Rscript",
        "/opt/homebrew/bin/Rscript",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return requested
