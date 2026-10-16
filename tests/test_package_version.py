from pathlib import Path
import tomllib

import rnaseq_helper


def test_runtime_version_matches_project_metadata():
    project_file = Path(__file__).resolve().parents[1] / "pyproject.toml"
    project = tomllib.loads(project_file.read_text(encoding="utf-8"))

    assert rnaseq_helper.__version__ == project["project"]["version"]
