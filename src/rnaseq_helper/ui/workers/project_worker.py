from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, Signal, Slot

from rnaseq_helper.services.project_store import (
    ProjectLoadCancelled, ProjectLoadError, ProjectStore, ProjectSnapshot,
)


class ProjectLoadWorker(QObject):
    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)
    cancelled = Signal()

    def __init__(self, project_dir: Path) -> None:
        super().__init__()
        self.project_dir = project_dir
        self._cancel_event = Event()

    def request_cancel(self) -> None:
        self._cancel_event.set()

    @Slot()
    def run(self) -> None:
        try:
            snapshot: ProjectSnapshot = ProjectStore.load(
                self.project_dir,
                progress=lambda done, total: self.progress.emit(done, total),
                cancelled=self._cancel_event.is_set,
            )
        except ProjectLoadCancelled:
            self.cancelled.emit()
        except (ProjectLoadError, OSError) as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # Keep malformed older projects inside the user-facing error boundary.
            self.failed.emit(f"项目读取失败：{exc}")
        else:
            self.completed.emit(snapshot)
