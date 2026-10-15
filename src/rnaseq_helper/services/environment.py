from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .runtime_paths import resolve_rscript


@dataclass(frozen=True)
class EnvironmentStatus:
    python: str
    architecture: str
    rscript: str | None
    r_version: str | None
    r_packages: dict[str, bool]
    pyside6_available: bool
    messages: tuple[str, ...]

    @property
    def ready_for_stage0_r(self) -> bool:
        return bool(self.rscript and self.r_version and all(self.r_packages.values()))

    def as_dict(self) -> dict[str, object]:
        return {
            "python": self.python,
            "architecture": self.architecture,
            "rscript": self.rscript,
            "r_version": self.r_version,
            "r_packages": self.r_packages,
            "pyside6_available": self.pyside6_available,
            "ready_for_stage0_r": self.ready_for_stage0_r,
            "messages": list(self.messages),
        }


class EnvironmentService:
    REQUIRED_R_PACKAGES = ("jsonlite", "limma", "statmod", "DESeq2")

    def check(self) -> EnvironmentStatus:
        resolved_rscript = resolve_rscript()
        rscript = resolved_rscript if Path(resolved_rscript).is_file() else None
        messages: list[str] = []
        r_version = None
        packages = {name: False for name in self.REQUIRED_R_PACKAGES}
        if rscript:
            try:
                version_proc = subprocess.run([rscript, "--version"], capture_output=True, text=True, check=False, timeout=10)
                r_version = (version_proc.stdout or version_proc.stderr).strip().splitlines()[0] if (version_proc.stdout or version_proc.stderr) else None
                expr = "pkgs <- c(%s); cat(paste(as.integer(vapply(pkgs, requireNamespace, logical(1), quietly=TRUE)), collapse=','))" % ",".join(json.dumps(name) for name in self.REQUIRED_R_PACKAGES)
                package_proc = subprocess.run([rscript, "--vanilla", "-e", expr], capture_output=True, text=True, check=False, timeout=15)
                values = package_proc.stdout.strip().split(",")
                if len(values) == len(self.REQUIRED_R_PACKAGES) and all(value in {"0", "1"} for value in values):
                    packages.update(dict(zip(self.REQUIRED_R_PACKAGES, (value == "1" for value in values))))
                else:
                    messages.append("无法读取 R 包状态；请检查 Rscript 输出。")
            except subprocess.TimeoutExpired:
                messages.append("Rscript 环境检查超时；未启动分析，请检查 R 安装或重新运行自检。")
        else:
            messages.append("未找到 Rscript；阶段 0 R 验证无法运行。")
        try:
            import PySide6  # noqa: F401
            pyside6_available = True
        except ImportError:
            pyside6_available = False
            messages.append("未安装 PySide6；GUI 空壳暂不能启动，可先运行命令行自检。")
        missing = [name for name, present in packages.items() if not present]
        if missing:
            messages.append("R 缺少包：" + ", ".join(missing))
        if not messages:
            messages.append("阶段 0 运行时检查通过。")
        return EnvironmentStatus(sys.version.split()[0], platform.machine(), rscript, r_version, packages, pyside6_available, tuple(messages))
