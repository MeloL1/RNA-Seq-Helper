from __future__ import annotations

from dataclasses import dataclass
from threading import Event
from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot


ImportTask = Callable[[Callable[[object], None], Callable[[], bool]], object]


@dataclass(frozen=True)
class ImportProgress:
    phase: str
    completed: int | None = None
    total: int | None = None
    label: str = ""
    cancellable: bool = True
    unit: str = ""


class ImportTaskWorker(QObject):
    """在独立 QThread 中执行导入/预览/整理任务，主线程只接收结果和状态。"""

    succeeded = Signal(object)
    failed = Signal(str)
    progress = Signal(object)
    cancelled = Signal()

    def __init__(self, task: ImportTask) -> None:
        super().__init__()
        self.task = task
        self.cancel_event = Event()

    def request_cancel(self) -> None:
        self.cancel_event.set()

    @Slot()
    def run(self) -> None:
        try:
            result = self.task(self.progress.emit, self.cancel_event.is_set)
        except Exception as exc:  # noqa: BLE001 - 转为导入页可读错误
            if self.cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.failed.emit(str(exc))
            return
        # 扫描器把已检查项目放进 cancelled=True 的结果中；交回它才能保留
        # 部分候选。其他任务在取消后不应把半成品当成功结果发布。
        if self.cancel_event.is_set() and not getattr(result, "cancelled", False):
            self.cancelled.emit()
        else:
            self.succeeded.emit(result)
