from __future__ import annotations

from dataclasses import replace
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from rnaseq_helper.analysis.result_filter_service import ResultFilterService
from rnaseq_helper.domain.models import ExpressionMatrix, JobContext, ResultFilterConfig


class ResultFilterWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(
        self,
        matrix: ExpressionMatrix,
        plan_data: dict[str, Any],
        config: ResultFilterConfig,
        context: JobContext,
    ) -> None:
        super().__init__()
        self.matrix = matrix
        self.plan_data = plan_data
        self.config = config
        self.context = replace(context, on_progress=self._on_progress)
        self.service = ResultFilterService()

    def _on_progress(self, _stage: str, _fraction: float | None, message: str) -> None:
        self.progress.emit(message)

    @Slot()
    def run(self) -> None:
        try:
            result = self.service.refresh(
                self.matrix, self.plan_data, self.config, self.context,
            )
        except Exception as exc:  # noqa: BLE001 - 转为页面可读错误
            self.failed.emit(str(exc))
            return
        self.completed.emit(result)
