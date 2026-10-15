from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QObject, Signal, Slot

from rnaseq_helper.analysis.service import AnalysisService
from rnaseq_helper.domain.models import AnalysisPlan, ExpressionMatrix, JobContext


class AnalysisWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, matrix: ExpressionMatrix, plan: AnalysisPlan, context: JobContext) -> None:
        super().__init__()
        self.matrix = matrix
        self.plan = plan
        self.context = replace(context, on_progress=self._on_progress)
        self.service = AnalysisService()

    def _on_progress(self, _stage: str, _fraction: float | None, message: str) -> None:
        self.progress.emit(message)

    @Slot()
    def run(self) -> None:
        try:
            result = self.service.run(self.matrix, self.plan, self.context)
        except Exception as exc:  # noqa: BLE001 - 转为页面可读错误
            self.failed.emit(str(exc))
            return
        self.completed.emit(result)
