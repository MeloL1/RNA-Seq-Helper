"""有界原生生命周期探针；不代表 macOS Cocoa/外部 AX 验收。"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap


def _probe(source: str) -> None:
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", textwrap.dedent(source)],
        capture_output=True, text=True, env=env, timeout=15,
    )
    assert result.returncode == 0, (
        f"native probe exit={result.returncode}\n{result.stdout}\n{result.stderr}"
    )
    assert "PROBE_COMPLETE" in result.stdout


def test_active_accessible_selection_survives_table_reset_and_gc() -> None:
    _probe('''
        import gc
        from PySide6.QtGui import QAccessible
        from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem
        app = QApplication([])
        # 未激活时不发送模型变更通知，不能把旧缓存当作产品故障。
        QAccessible.setActive(True)
        assert QAccessible.isActive()
        table = QTableWidget(4, 4)
        interface = QAccessible.queryAccessibleInterface(table)
        selection = interface.selectionInterface()
        assert selection is not None
        for cycle in range(50):
            table.setRowCount(4)
            for row in range(4):
                for column in range(4):
                    table.setItem(row, column, QTableWidgetItem(str(cycle)))
            table.selectAll()
            cells = selection.selectedItems()
            assert len(cells) == 16
            assert all(cell is not None and cell.isValid() for cell in cells)
            del cells
            table.clearSelection()
            table.setRowCount(0)
            app.processEvents()
            gc.collect()
            assert selection.selectedItems() == []
        print("PROBE_COMPLETE", flush=True)
    ''')


def test_import_page_layout_destruction_and_gc_in_separate_process() -> None:
    _probe('''
        import gc
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
        from rnaseq_helper.ui.pages.import_page import ImportPage
        app = QApplication([])
        for cycle in range(20):
            page = ImportPage()
            assert page.layout() is not None
            assert page._active_thread is None
            page.close()
            page.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            del page
            gc.collect()
            app.processEvents()
        print("PROBE_COMPLETE", flush=True)
    ''')
