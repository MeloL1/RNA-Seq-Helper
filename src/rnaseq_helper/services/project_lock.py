from __future__ import annotations

from contextlib import contextmanager
import errno
import fcntl
import os
from pathlib import Path
from typing import Iterator


class ProjectBusyError(RuntimeError):
    """The same project is currently being analyzed or opened by another app process."""


@contextmanager
def project_directory_lock(project_dir: Path) -> Iterator[None]:
    """Take a non-blocking exclusive advisory lock without writing into the project."""
    root = Path(project_dir).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("项目目录不可用。")
    descriptor = os.open(root, os.O_RDONLY)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise ProjectBusyError(
                    "这个项目正在被另一个 RNA-Seq Helper 任务使用；请等它结束后再打开或重新分析。"
                ) from exc
            raise
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)
