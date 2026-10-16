"""Render the maintained SVG source into a macOS ICNS iconset."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


ROOT = Path(__file__).resolve().parents[1]
SVG = ROOT / "resources" / "ui" / "app-icon.svg"
ICNS = ROOT / "resources" / "ui" / "AppIcon.icns"
SIZES = (16, 32, 64, 128, 256, 512)


def main() -> None:
    renderer = QSvgRenderer(str(SVG))
    if not renderer.isValid():
        raise SystemExit(f"Invalid SVG icon source: {SVG}")
    with tempfile.TemporaryDirectory(prefix="rnaseq-helper-iconset-") as temp:
        iconset = Path(temp) / "AppIcon.iconset"
        iconset.mkdir()
        for size in SIZES:
            for scale in (1, 2):
                pixels = size * scale
                image = QImage(QSize(pixels, pixels), QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(Qt.GlobalColor.transparent)
                painter = QPainter(image)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                renderer.render(painter)
                painter.end()
                suffix = "@2x" if scale == 2 else ""
                image.save(str(iconset / f"icon_{size}x{size}{suffix}.png"), "PNG")
        subprocess.run(["/usr/bin/iconutil", "-c", "icns", str(iconset), "-o", str(ICNS)], check=True)
    print(f"Created {ICNS}")


if __name__ == "__main__":
    main()
