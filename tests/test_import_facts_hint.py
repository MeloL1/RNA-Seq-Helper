from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from rnaseq_helper.ui.pages.import_page import ImportPage


def test_import_page_explains_unit_and_scale_for_beginner_users() -> None:
    application = QApplication.instance() or QApplication([])
    page = ImportPage()
    hint = page.facts_hint.text()

    assert "gene counts/原始 count" in hint
    assert "TPM、FPKM、CPM 或 RPKM" in hint
    assert "log2(...)" in hint
    assert "不能靠猜" in hint
    assert "先只回答两个问题" in hint
    assert "参考表不是表达矩阵" in hint
    assert "GSE32707" in hint
    assert "GPL10558" in hint
    assert "gene symbol" in hint
    assert "ln、log10、z-score" in hint
    assert "DESeq2" in hint
    assert "limma" in hint
    assert "最后检查：表头、特征编号列、样本表达列、转置方向" in hint

    page.close()
    application.processEvents()
