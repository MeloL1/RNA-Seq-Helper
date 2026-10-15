from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from rnaseq_helper.domain.models import JobContext
from rnaseq_helper.r_bridge.client import RBridgeClient

try:
    from PySide6.QtCore import QObject, Signal, Slot
except ImportError:  # 允许核心自检在无 GUI 依赖环境运行
    QObject = object  # type: ignore[misc,assignment]
    Signal = lambda *args, **kwargs: None  # type: ignore[assignment]
    Slot = lambda *args, **kwargs: (lambda func: func)  # type: ignore[assignment]


class RuntimeWorker(QObject):
    """在 QThread 中执行 R 请求的最小 worker；不在 Qt 主线程运行 R。"""

    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, workdir: Path) -> None:
        super().__init__()
        self.context = replace(JobContext(workdir), on_progress=self._on_progress)
        self.client = RBridgeClient()

    def _on_progress(self, _stage: str, _fraction: float | None, message: str) -> None:
        self.progress.emit(message)

    @Slot()
    def run_micro_test(self) -> None:
        self._run("micro_limma")

    @Slot()
    def run_micro_deseq2(self) -> None:
        self._run("micro_deseq2")

    def _run(self, method: str) -> None:
        try:
            response = self.client.run(method, _micro_payload(), self.context)
            self.completed.emit(response)
        except Exception as exc:  # noqa: BLE001 - 转换为用户可见 worker 错误
            self.failed.emit(str(exc))


def _micro_payload() -> dict[str, object]:
    feature_ids = [f"gene_{index:03d}" for index in range(1, 121)]
    matrix = [
        [5.0, 5.1, 4.9, 7.0, 7.1, 6.9],
        [2.0, 2.1, 2.0, 2.2, 2.1, 2.2],
        [4.0, 4.0, 4.0, 4.0, 4.0, 4.0],
    ]
    counts = [
        [100, 110, 90, 220, 230, 210],
        [50, 52, 48, 55, 53, 57],
        [100, 100, 100, 100, 100, 100],
    ]
    for index in range(4, 121):
        base = 80 + index * 2
        noise_scale = 1 + (index % 13) * 0.7
        offsets = [((index * multiplier) % 19) - 9 for multiplier in (3, 5, 7, 11, 13, 17)]
        control = [max(1, round(base + offsets[position] * noise_scale)) for position in range(3)]
        treated = [max(1, round(base + offsets[position + 3] * noise_scale)) for position in range(3)]
        counts.append(control + treated)
        matrix.append([value / 20.0 for value in control + treated])
    return {
        "matrix": matrix,
        "counts": counts,
        "feature_ids": feature_ids,
        "sample_ids": ["C1", "C2", "C3", "T1", "T2", "T3"],
        "groups": ["control", "control", "control", "treated", "treated", "treated"],
        "control": "control",
        "test": "treated",
    }
