from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from rnaseq_helper.domain.models import MeasurementType, ValueScale
from rnaseq_helper.ui.pages.import_page import ImportPage


def test_explicit_table_text_is_only_a_candidate_until_user_selects_it() -> None:
    application = QApplication.instance() or QApplication([])
    source = Path(__file__).parent / "fixtures" / "company_counts.tsv"
    page = ImportPage()
    page.load_path(source)

    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: loop.quit() if page._active_thread is None else None)
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    timer.start()
    timeout.start(10000)
    loop.exec()
    timer.stop()
    timeout.stop()
    assert page._active_thread is None
    page.continue_button.click()
    timer.start()
    timeout.start(10000)
    loop.exec()
    timer.stop()
    timeout.stop()
    application.processEvents()

    assert page.session is not None
    assert page.measurement_combo.currentData() == MeasurementType.UNKNOWN.value
    assert page.scale_combo.currentData() == ValueScale.UNKNOWN.value
    assert "初步判读" in page.auto_judgement.text()
    assert "单位候选：原始 count" in page.auto_judgement.text()
    assert "原始 count 表" in page.auto_judgement.text()
    assert "仍需你确认" in page.auto_judgement.text()
    assert "交付说明" in page.auto_judgement.text()

    page.close()
    application.processEvents()
