import unittest
from pathlib import Path

from rnaseq_helper.services.environment import EnvironmentService
from rnaseq_helper.services.runtime_paths import resolve_rscript


class EnvironmentTests(unittest.TestCase):
  def test_environment_status_has_explicit_fields(self):
    status = EnvironmentService().check()
    self.assertTrue(status.python)
    self.assertTrue(status.architecture)
    self.assertEqual(set(status.r_packages), {"jsonlite", "limma", "statmod", "DESeq2"})

  def test_rscript_resolves_without_shell_path(self):
    resolved = resolve_rscript("Rscript")
    self.assertTrue(Path(resolved).is_file())
