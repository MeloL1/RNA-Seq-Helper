from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest

from rnaseq_helper.domain.models import JobContext, RJobRequest
from rnaseq_helper.r_bridge.client import RBridgeClient, RBridgeError
from rnaseq_helper.ui.workers.runtime_worker import _micro_payload


class RBridgeTests(unittest.TestCase):
  def test_micro_limma_worker(self):
    rscript = shutil.which("Rscript")
    if not rscript:
        self.skipTest("Rscript 不可用")
    context = JobContext(Path.cwd())
    result = RBridgeClient(rscript=rscript).run("micro_limma", _micro_payload(), context)
    self.assertEqual(result.result["method"], "LIMMA_ON_LOG_EXPRESSION")
    self.assertEqual(len(result.result["table"]), 120)
    self.assertGreater(result.result["table"][0]["coefficient"], 0)


  def test_deseq2_does_not_fallback_silently(self):
    rscript = shutil.which("Rscript")
    if not rscript:
        self.skipTest("Rscript 不可用")
    installed = subprocess.run([rscript, "--vanilla", "-e", "cat(requireNamespace('DESeq2', quietly=TRUE))"], capture_output=True, text=True, check=False)
    if installed.stdout.strip() == "TRUE":
        self.skipTest("DESeq2 已安装；由正常路径测试覆盖")
    with self.assertRaisesRegex(RBridgeError, "DESeq2"):
        RBridgeClient(rscript=rscript).run("micro_deseq2", {}, JobContext(Path.cwd()))

  def test_deseq2_fixture_when_available(self):
    rscript = shutil.which("Rscript")
    if not rscript:
        self.skipTest("Rscript 不可用")
    installed = subprocess.run([rscript, "--vanilla", "-e", "cat(requireNamespace('DESeq2', quietly=TRUE))"], capture_output=True, text=True, check=False)
    if installed.stdout.strip() != "TRUE":
        self.skipTest("DESeq2 未安装")
    result = RBridgeClient(rscript=rscript).run("micro_deseq2", _micro_payload(), JobContext(Path.cwd()))
    self.assertEqual(result.result["method"], "DESEQ2")
    self.assertEqual(len(result.result["table"]), 120)

  def test_analyze_deseq2_reports_tiny_matrix_fallback(self):
    rscript = shutil.which("Rscript")
    if not rscript:
        self.skipTest("Rscript 不可用")
    installed = subprocess.run([rscript, "--vanilla", "-e", "cat(requireNamespace('DESeq2', quietly=TRUE))"], capture_output=True, text=True, check=False)
    if installed.stdout.strip() != "TRUE":
        self.skipTest("DESeq2 未安装")
    payload = {
        "feature_ids": ["gene_1", "gene_2", "gene_3", "gene_4"],
        "sample_ids": ["C1", "C2", "C3", "T1", "T2", "T3"],
        "groups": ["control", "control", "control", "treated", "treated", "treated"],
        "control": "control",
        "test": "treated",
        "fdr_threshold": 0.05,
        "lfc_threshold": 1,
        "measurement_type": "RAW_COUNT",
        "counts": [
            [100, 110, 90, 220, 230, 210],
            [50, 52, 48, 55, 53, 57],
            [100, 100, 100, 100, 100, 100],
            [80, 82, 78, 160, 165, 155],
        ],
        "gene_symbols": ["GENE1", "GENE2", "GENE3", "GENE4"],
        "min_samples": 0,
    }
    result = RBridgeClient(rscript=rscript).run("analyze_deseq2", payload, JobContext(Path.cwd()), "deseq2-count-v1")
    self.assertEqual(result.result["method"], "DESEQ2")
    self.assertEqual(result.result["parameters"]["dispersion_estimation"], "gene-wise-fallback")
    self.assertEqual(result.result["parameters"]["dispersion_fit_type"], "gene-wise")
    self.assertEqual(result.result["parameters"]["size_factor_type"], "ratio")
    self.assertEqual(result.result["parameters"]["test"], "Wald")
    self.assertEqual(result.result["parameters"]["p_adjust_method"], "BH")
    self.assertEqual(result.result["issues"][0]["code"], "DESEQ2_GENEWISE_DISPERSION_FALLBACK")

  def test_submit_accepts_explicit_request(self):
    rscript = shutil.which("Rscript")
    if not rscript:
        self.skipTest("Rscript 不可用")
    request = RJobRequest("explicit-request", "ping", {})
    result = RBridgeClient(rscript=rscript).submit(request, JobContext(Path.cwd()))
    self.assertEqual(result.request_id, "explicit-request")

  def test_cancel_terminates_a_slow_worker(self):
    """取消必须终止独立进程，而不是只更新 Qt 按钮状态。"""
    with tempfile.TemporaryDirectory(prefix="rnaseq-helper-slow-r-") as workdir:
      fake_rscript = Path(workdir) / "fake-rscript"
      fake_rscript.write_text("#!/bin/sh\nsleep 30\n", encoding="utf-8")
      fake_rscript.chmod(0o755)
      context = JobContext(Path(workdir))
      cancel = threading.Timer(0.3, context.cancel_event.set)
      cancel.start()
      try:
        with self.assertRaisesRegex(RBridgeError, "取消"):
          RBridgeClient(rscript=str(fake_rscript)).run("ping", {}, context)
      finally:
        cancel.cancel()
