"""py2app standalone build configuration; do not use alias mode for delivery."""

from pathlib import Path
import sys

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

APP = [str(ROOT / "src" / "rnaseq_helper" / "app.py")]
DATA_FILES = [
    ("resources/r", [str(ROOT / "resources" / "r" / "worker.R")]),
    ("resources/ui", [str(ROOT / "resources" / "ui" / "combobox-arrow.svg")]),
]
OPTIONS = {
    "argv_emulation": False,
    "packages": ["rnaseq_helper", "openpyxl", "xlrd"],
    "includes": ["numpy", "PySide6.QtCore", "PySide6.QtWidgets", "shiboken6"],
    "iconfile": None,
    "plist": {
        "CFBundleName": "RNA-Seq Helper",
        "CFBundleDisplayName": "RNA-Seq Helper",
        "CFBundleIdentifier": "org.rnaseqhelper.app",
        "CFBundleShortVersionString": "0.30.0",
    },
}

if __name__ == "__main__":
    from setuptools import setup

    # 运行依赖由 pyproject.toml 安装到当前构建环境，再由 standalone
    # 收集进 .app；py2app 0.28.x 不接受 distribution.install_requires。
    setup(
        app=APP,
        data_files=DATA_FILES,
        options={"py2app": OPTIONS},
        setup_requires=[],
    )
