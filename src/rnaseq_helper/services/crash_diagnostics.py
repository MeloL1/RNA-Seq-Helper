"""Local fatal-signal diagnostics, kept alive through interpreter teardown.

No locals, expression values or application payloads are written. Stack traces
can contain local source paths: these files are not anonymized reports.
"""
from __future__ import annotations

import faulthandler
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import BinaryIO


_stream: BinaryIO | None = None
_path: Path | None = None
_LOG_NAME = re.compile(r"fatal-(\d+)-[A-Za-z0-9_]+\.log\Z")


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _remove_empty_stopped_logs(directory: Path) -> None:
    # Never remove nonempty evidence, symlinks, or a live process's file.
    for path in directory.iterdir():
        match = _LOG_NAME.fullmatch(path.name)
        if match is None:
            continue
        try:
            info = path.lstat()
            if (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and info.st_size == 0 and not _process_exists(int(match[1]))):
                path.unlink()
        except OSError:
            continue


def enable_gui_crash_diagnostics(directory: Path | None = None) -> Path | None:
    """Enable once before GUI creation; do not close on event-loop return.

The OS releases this descriptor on exit. A subsequent launch removes only empty
logs of stopped processes; fatal-signal evidence is never rotated or overwritten.
An existing external faulthandler setup is left untouched. Failure to initialize
diagnostics must not prevent the user from opening the application.
"""
    global _stream, _path
    if _stream is not None:
        return _path
    if faulthandler.is_enabled():
        return None
    directory = directory or Path.home() / "Library" / "Logs" / "RNA-Seq Helper" / "fatal"
    stream = None
    path = None
    descriptor = None
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise OSError("diagnostic directory is not private")
        _remove_empty_stopped_logs(directory)
        descriptor, name = tempfile.mkstemp(prefix=f"fatal-{os.getpid()}-", suffix=".log", dir=directory)
        path = Path(name)
        stream = os.fdopen(descriptor, "wb", buffering=0)
        descriptor = None  # ownership transferred to the file object
        faulthandler.enable(file=stream, all_threads=True)
    except (OSError, RuntimeError, ValueError):
        try:
            if stream is not None:
                stream.close()
            elif descriptor is not None:
                os.close(descriptor)
        except OSError:
            pass
        try:
            if path is not None:
                path.unlink(missing_ok=True)
        except OSError:
            pass
        if sys.stderr is not None:
            try:
                print("崩溃诊断未能启用；软件仍可启动。", file=sys.stderr)
            except (OSError, ValueError):
                pass  # Finder launches may not have a writable error stream.
        return None
    _stream, _path = stream, path
    return path
