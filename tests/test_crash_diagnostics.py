from __future__ import annotations

import os
import io
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest

from rnaseq_helper.services import crash_diagnostics as diagnostics


@pytest.fixture
def handler(monkeypatch):
    monkeypatch.setattr(diagnostics, "_stream", None)
    monkeypatch.setattr(diagnostics, "_path", None)
    monkeypatch.setattr(diagnostics.faulthandler, "is_enabled", lambda: False)
    enable = Mock()
    monkeypatch.setattr(diagnostics.faulthandler, "enable", enable)
    yield enable
    if diagnostics._stream is not None:
        diagnostics._stream.close()


def test_private_log_kept_open_and_idempotent(tmp_path, handler):
    directory = tmp_path / "fatal"
    path = diagnostics.enable_gui_crash_diagnostics(directory)
    assert path is not None and path.parent == directory
    assert directory.stat().st_mode & 0o777 == 0o700
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.read_bytes() == b""
    stream = diagnostics._stream
    assert stream is not None and not stream.closed
    handler.assert_called_once_with(file=stream, all_threads=True)
    assert diagnostics.enable_gui_crash_diagnostics(directory) == path
    assert not stream.closed


def test_cleanup_preserves_evidence_live_logs_and_unrelated_files(tmp_path, handler, monkeypatch):
    directory = tmp_path / "fatal"
    directory.mkdir(mode=0o700)
    empty = directory / "fatal-123-empty.log"
    evidence = directory / "fatal-123-evidence.log"
    live = directory / "fatal-456-live.log"
    unrelated = directory / "notes.log"
    link = directory / "fatal-123-link.log"
    for path in (empty, live, unrelated):
        path.touch()
    evidence.write_bytes(b"Fatal Python error: Segmentation fault\n")
    link.symlink_to(unrelated)
    monkeypatch.setattr(diagnostics, "_process_exists", lambda pid: pid == 456)
    diagnostics.enable_gui_crash_diagnostics(directory)
    assert not empty.exists()
    assert evidence.read_bytes().startswith(b"Fatal Python error")
    assert live.exists() and unrelated.exists() and link.is_symlink()


def test_nonprivate_directory_is_not_modified(tmp_path, handler):
    directory = tmp_path / "fatal"
    directory.mkdir(mode=0o755)
    assert diagnostics.enable_gui_crash_diagnostics(directory) is None
    assert directory.stat().st_mode & 0o777 == 0o755
    assert list(directory.iterdir()) == []
    handler.assert_not_called()


def test_existing_handler_is_not_replaced(tmp_path, handler, monkeypatch):
    monkeypatch.setattr(diagnostics.faulthandler, "is_enabled", lambda: True)
    assert diagnostics.enable_gui_crash_diagnostics(tmp_path / "fatal") is None
    assert not (tmp_path / "fatal").exists()
    handler.assert_not_called()


def test_enable_failure_leaves_no_log_and_does_not_block_startup(tmp_path, handler):
    handler.side_effect = RuntimeError("unavailable")
    directory = tmp_path / "fatal"
    assert diagnostics.enable_gui_crash_diagnostics(directory) is None
    assert list(directory.iterdir()) == []
    assert diagnostics._stream is None


@pytest.mark.parametrize("error_stream", [None, "closed", "broken"])
def test_unwritable_error_stream_does_not_block_startup(tmp_path, handler, monkeypatch, error_stream):
    if error_stream == "closed":
        error_stream = io.StringIO()
        error_stream.close()
    elif error_stream == "broken":
        error_stream = Mock()
        error_stream.write.side_effect = OSError("not writable")
    monkeypatch.setattr(diagnostics.sys, "stderr", error_stream)
    handler.side_effect = RuntimeError("enable failed")
    assert diagnostics.enable_gui_crash_diagnostics(tmp_path / "fatal") is None
    assert diagnostics._stream is None


def test_fdopen_failure_closes_descriptor_even_if_unlink_fails(tmp_path, handler, monkeypatch):
    close = Mock(wraps=os.close)
    monkeypatch.setattr(diagnostics.os, "close", close)
    monkeypatch.setattr(diagnostics.os, "fdopen", Mock(side_effect=OSError("fdopen failed")))
    monkeypatch.setattr(Path, "unlink", Mock(side_effect=OSError("unlink failed")))
    assert diagnostics.enable_gui_crash_diagnostics(tmp_path / "fatal") is None
    close.assert_called_once()
    handler.assert_not_called()


def test_close_failure_does_not_block_startup(tmp_path, handler, monkeypatch):
    real_fdopen = os.fdopen
    streams = []

    def broken_close(descriptor, *args, **kwargs):
        stream = real_fdopen(descriptor, *args, **kwargs)
        streams.append(stream)
        proxy = Mock()
        proxy.close.side_effect = OSError("close failed")
        return proxy

    monkeypatch.setattr(diagnostics.os, "fdopen", broken_close)
    handler.side_effect = RuntimeError("enable failed")
    try:
        assert diagnostics.enable_gui_crash_diagnostics(tmp_path / "fatal") is None
    finally:
        for stream in streams:
            stream.close()


def test_only_gui_entry_enables_diagnostics(tmp_path, handler, monkeypatch):
    from rnaseq_helper import app

    activate = Mock(return_value=tmp_path / "fatal.log")
    monkeypatch.setattr(diagnostics, "enable_gui_crash_diagnostics", activate)
    monkeypatch.setattr(app, "_self_check", lambda: 0)
    monkeypatch.setattr(app, "_micro_test", lambda method="micro_limma": 0)
    monkeypatch.setattr(app, "_gui", lambda: 0)
    for option in ("--self-check", "--micro-test", "--micro-deseq2"):
        assert app.main([option]) == 0
    activate.assert_not_called()
    assert app.main([]) == 0
    activate.assert_called_once_with()


def test_real_thread_dump_at_process_teardown_without_crashing(tmp_path):
    # Exercise the real descriptor/handler in isolation, never SIGSEGV/abort.
    script = """
import atexit
import faulthandler
import sys
from pathlib import Path
from rnaseq_helper.services import crash_diagnostics as diagnostics
from rnaseq_helper import app
activate = diagnostics.enable_gui_crash_diagnostics
diagnostics.enable_gui_crash_diagnostics = lambda: activate(Path(sys.argv[1]))
app._gui = lambda: 0
assert app.main([]) == 0
assert diagnostics._stream is not None and not diagnostics._stream.closed
def dump_at_exit():
    private_value = 'DO_NOT_INCLUDE_LOCALS'
    faulthandler.dump_traceback(file=diagnostics._stream, all_threads=True)
atexit.register(dump_at_exit)
"""
    environment = os.environ.copy()
    environment.pop("PYTHONFAULTHANDLER", None)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    process = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path / "fatal")],
        env=environment, capture_output=True, text=True, timeout=10,
    )
    assert process.returncode == 0, process.stderr
    logs = list((tmp_path / "fatal").glob("*.log"))
    assert len(logs) == 1
    trace = logs[0].read_text()
    assert 'File "<string>"' in trace
    assert "DO_NOT_INCLUDE_LOCALS" not in trace
