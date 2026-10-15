from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from rnaseq_helper.services.report_service import ReportService


def test_xlsx_export_is_a_minimal_readable_result_table(tmp_path: Path) -> None:
    output = tmp_path / "deg-results.xlsx"
    result = {
        "table": [
            {
                "feature_key": "feature-1",
                "gene_symbol": None,
                "log2FoldChange": 1.25,
                "pvalue": float("nan"),
                "padj": None,
                "tested": False,
                "reason_not_tested": "all_zero",
            },
            {
                "feature_key": "feature-2",
                "gene_symbol": "GENE2",
                "log2FoldChange": -0.5,
                "pvalue": 0.01,
                "padj": 0.02,
                "direction": "down",
            },
        ]
    }

    ReportService._write_xlsx(output, object(), object(), result, "ignored", {})

    workbook = load_workbook(output, data_only=True)
    assert workbook.sheetnames == ["DEG Results"]
    sheet = workbook["DEG Results"]
    assert [cell.value for cell in sheet[1]] == list(ReportService.RESULT_EXPORT_COLUMNS)
    assert sheet.max_column == len(ReportService.RESULT_EXPORT_COLUMNS)
    assert [cell.value for cell in sheet[2]] == ["feature-1", "NA", 1.25, "NA", "NA"]
    assert [cell.value for cell in sheet[3]] == ["feature-2", "GENE2", -0.5, 0.01, 0.02]
    workbook.close()
