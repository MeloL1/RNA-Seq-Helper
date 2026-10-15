from __future__ import annotations

from pathlib import Path

from rnaseq_helper.services import runtime_paths


def test_embedded_rscript_precedes_shell_path(tmp_path, monkeypatch):
    app = tmp_path / "RNA-Seq Helper.app"
    executable = app / "Contents" / "MacOS" / "RNA-Seq Helper"
    embedded = app / "Contents" / "Frameworks" / "R.framework" / "Resources" / "bin" / "Rscript"
    executable.parent.mkdir(parents=True)
    embedded.parent.mkdir(parents=True)
    executable.touch()
    embedded.touch()
    external = tmp_path / "external-rscript"
    external.touch()
    monkeypatch.setattr(runtime_paths.sys, "executable", str(executable))
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(runtime_paths.shutil, "which", lambda _: str(external))

    assert runtime_paths.resolve_rscript() == str(embedded)
