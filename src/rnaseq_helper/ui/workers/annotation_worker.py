from __future__ import annotations

from dataclasses import replace
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from rnaseq_helper.analysis.annotation_service import AnnotationService
from rnaseq_helper.domain.models import ExpressionMatrix, JobContext


class AnnotationWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, matrix: ExpressionMatrix, plan_data: dict[str, Any], mapping: dict[str, str], context: JobContext):
        super().__init__()
        self.matrix = matrix
        self.plan_data = plan_data
        self.mapping = mapping
        self.context = replace(context, on_progress=self._on_progress)

    def _on_progress(self, _stage: str, _fraction: float | None, message: str) -> None:
        self.progress.emit(message)

    @Slot()
    def run(self) -> None:
        try:
            result = AnnotationService().apply(self.matrix, self.plan_data, self.mapping, self.context)
        except Exception as exc:  # noqa: BLE001 - convert to a visible UI error
            self.failed.emit(str(exc))
        else:
            self.completed.emit(result)
