"""将本机 R.framework 的最小可用子集复制进 app，并重写绝对 dylib 依赖。

本脚本只读 source R.framework，不会修改或删除系统 R。它面向本项目当前
的 limma/DESeq2 微型验证与 bulk 分析路径；GEOquery、注释库等未纳入运行时，
因为它们不是当前离线表达分析的必需依赖。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path


CORE_PACKAGES = ("DESeq2", "limma", "jsonlite", "statmod")


def _run(command: list[str], *, text: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=text, encoding="utf-8", errors="replace", check=False)


def _source_version(source: Path) -> tuple[str, Path]:
    current = source / "Versions" / "Current"
    if not current.exists():
        raise SystemExit(f"R.framework 缺少 Versions/Current：{current}")
    resolved = current.resolve()
    return resolved.name, resolved


def _dependency_packages(rscript: Path) -> list[str]:
    package_expr = (
        'ip <- installed.packages(); '
        'pkgs <- c("DESeq2","limma","jsonlite","statmod"); '
        'base <- ip[ip[,"Priority"] %in% c("base","recommended"), "Package"]; '
        'd <- tools::package_dependencies(pkgs, db=ip, recursive=TRUE, '
        'which=c("Depends","Imports","LinkingTo")); '
        'cat(paste(sort(unique(c(pkgs, base, unlist(d)))), collapse="\\n"))'
    )
    completed = _run([str(rscript), "--vanilla", "-e", package_expr])
    if completed.returncode != 0:
        raise SystemExit(f"无法解析 R 包依赖：{completed.stderr.strip()}")
    packages = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    missing = [package for package in CORE_PACKAGES if package not in packages]
    if missing:
        raise SystemExit(f"当前 R 缺少必需包：{', '.join(missing)}")
    return packages


def _copytree(source: Path, destination: Path, *, ignore=None) -> None:
    shutil.copytree(source, destination, symlinks=True, ignore=ignore)


def _resource_ignore(source_version: Path):
    library = source_version / "Resources" / "library"

    def ignore(path: str, names: list[str]) -> set[str]:
        if Path(path).resolve() == library.resolve():
            return set(names)
        if Path(path) == source_version / "Resources":
            return {"library"}
        return set()

    return ignore


def _rewrite_script(script: Path) -> None:
    content = script.read_text(encoding="utf-8")
    content = content.replace(
        'R_HOME_DIR="/Library/Frameworks/R.framework/Resources"',
        'R_HOME_DIR="$(cd "$(dirname "$0")/.." && pwd)"',
    )
    content = content.replace(
        'R_SHARE_DIR="/Library/Frameworks/R.framework/Resources/share"',
        'R_SHARE_DIR="${R_HOME_DIR}/share"',
    )
    content = content.replace(
        'R_INCLUDE_DIR="/Library/Frameworks/R.framework/Resources/include"',
        'R_INCLUDE_DIR="${R_HOME_DIR}/include"',
    )
    content = content.replace(
        'R_DOC_DIR="/Library/Frameworks/R.framework/Resources/doc"',
        'R_DOC_DIR="${R_HOME_DIR}/doc"',
    )
    script.write_text(content, encoding="utf-8")
    script.chmod(script.stat().st_mode | 0o111)


def _rewrite_rscript(script: Path) -> None:
    # 官方 Rscript Mach-O 将安装时的绝对 R_HOME 编译进二进制；直接复制
    # 会回到 /Library/Frameworks。wrapper 使用 app 内同一份 exec/R。
    script.write_text(
        "#!/bin/sh\n"
        "set -e\n"
        'R_HOME_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"\n'
        'export R_HOME="$R_HOME_DIR"\n'
        'export R_SHARE_DIR="$R_HOME_DIR/share"\n'
        'export R_INCLUDE_DIR="$R_HOME_DIR/include"\n'
        'export R_DOC_DIR="$R_HOME_DIR/doc"\n'
        'R_ARCH=""\n'
        'export R_ARCH\n'
        '. "$R_HOME_DIR/etc${R_ARCH}/ldpaths"\n'
        'if [ "$#" -eq 1 ] && [ "$1" = "--version" ]; then\n'
        '  exec "$R_HOME_DIR/bin/R" --version\n'
        'fi\n'
        'r_args=""\n'
        'while [ "$#" -gt 0 ]; do\n'
        '  case "$1" in\n'
        '    -e) expr="$2"; shift 2; exec "$R_HOME_DIR/bin/exec${R_ARCH}/R" --no-echo --no-restore -e "$expr" "$@" ;;\n'
        '    -*) r_args="$r_args $1"; shift ;;\n'
        '    *) script="$1"; shift; break ;;\n'
        '  esac\n'
        'done\n'
        'if [ -n "${script:-}" ]; then\n'
        '  exec "$R_HOME_DIR/bin/exec${R_ARCH}/R" --no-echo --no-restore $r_args --file="$script" --args "$@"\n'
        'fi\n'
        'exec "$R_HOME_DIR/bin/exec${R_ARCH}/R" --no-echo --no-restore $r_args "$@"\n',
        encoding="utf-8",
    )
    script.chmod(0o755)


def _macho_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix not in {".dylib", ".so"} and not (
            path.parent.name == "exec" and path.name == "R"
        ):
            continue
        probe = _run(["file", "-b", str(path)])
        if probe.returncode == 0 and "Mach-O" in probe.stdout:
            files.append(path)
    return files


def _rewrite_macho_dependencies(source_version: Path, destination_version: Path) -> int:
    source_prefix = str(source_version / "Resources") + "/"
    rewrites = 0
    for binary in _macho_files(destination_version):
        listing = _run(["otool", "-L", str(binary)])
        if listing.returncode != 0:
            raise SystemExit(f"无法读取 Mach-O 依赖：{binary}")
        for line in listing.stdout.splitlines()[1:]:
            dependency = line.strip().split(" ", 1)[0]
            if not dependency.startswith(source_prefix):
                continue
            relative = Path(dependency).relative_to(source_version)
            target = destination_version / relative
            if not target.exists() and not target.is_symlink():
                raise SystemExit(f"内置 runtime 缺少动态库：{target}")
            loader_relative = os.path.relpath(target, binary.parent)
            replacement = f"@loader_path/{loader_relative}"
            completed = _run(["install_name_tool", "-change", dependency, replacement, str(binary)])
            if completed.returncode != 0:
                raise SystemExit(f"无法重写 {binary} 的依赖 {dependency}：{completed.stderr.strip()}")
            rewrites += 1
    return rewrites


def _sign_macho_files(root: Path) -> int:
    signed = 0
    for binary in _macho_files(root):
        completed = _run(["codesign", "--force", "--timestamp=none", "--sign", "-", str(binary)])
        if completed.returncode != 0:
            raise SystemExit(f"无法为内置 R 组件签名：{binary}：{completed.stderr.strip()}")
        signed += 1
    return signed


def _make_framework_links(framework: Path, version: str) -> None:
    versions = framework / "Versions"
    current = versions / "Current"
    if current.exists() or current.is_symlink():
        current.unlink()
    current.symlink_to(version)
    # 运行时只需要 Resources；R.framework 的开发头文件/根级兼容链接会被
    # codesign 当成嵌套 framework 的未封装根目录内容。
    for name, target in {"Resources": "Versions/Current/Resources"}.items():
        link = framework / name
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(target)


def main() -> int:
    parser = argparse.ArgumentParser(description="把最小 R runtime 内置到 RNA-Seq Helper.app")
    parser.add_argument("--app", type=Path, default=Path("packaging/dist/RNA-Seq Helper.app"))
    parser.add_argument("--source", type=Path, default=Path("/Library/Frameworks/R.framework"))
    args = parser.parse_args()
    app = args.app.expanduser().resolve()
    source = args.source.expanduser().resolve()
    executable = app / "Contents" / "MacOS" / "RNA-Seq Helper"
    source_rscript = source / "Versions" / "Current" / "Resources" / "bin" / "Rscript"
    if not executable.is_file():
        raise SystemExit(f"app 主程序不存在：{executable}")
    if not source_rscript.is_file():
        raise SystemExit(f"source Rscript 不存在：{source_rscript}")
    framework = app / "Contents" / "Frameworks" / "R.framework"
    if framework.exists() or framework.is_symlink():
        raise SystemExit(f"目标已存在，为避免覆盖请先选择新 app：{framework}")

    version, source_version = _source_version(source)
    packages = _dependency_packages(source_rscript)
    destination_version = framework / "Versions" / version
    destination_version.parent.mkdir(parents=True, exist_ok=False)
    _copytree(source_version, destination_version, ignore=_resource_ignore(source_version))
    destination_library = destination_version / "Resources" / "library"
    destination_library.mkdir(parents=True, exist_ok=True)
    source_library = source_version / "Resources" / "library"
    for package in packages:
        package_source = source_library / package
        if not package_source.is_dir():
            raise SystemExit(f"R 包目录不存在：{package_source}")
        _copytree(package_source, destination_library / package)
    _make_framework_links(framework, version)
    _rewrite_script(destination_version / "Resources" / "bin" / "R")
    _rewrite_rscript(destination_version / "Resources" / "bin" / "Rscript")
    rewrites = _rewrite_macho_dependencies(source_version, destination_version)
    signed = _sign_macho_files(destination_version)
    print(f"embedded R.framework: {framework}")
    print(f"version: {version}")
    print(f"packages: {len(packages)}")
    print(f"macho dependency rewrites: {rewrites}")
    print(f"macho components signed: {signed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
