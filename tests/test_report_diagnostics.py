from rnaseq_helper.services.report_service import ReportService


def test_constant_residual_df_is_compact_and_beginner_readable() -> None:
    assert ReportService._diagnostic_label("residual_df") == "残差自由度（每个特征）"
    assert ReportService._format_diagnostic_value("residual_df", [90, 90, 90]) == "90（所有特征相同）"


def test_varying_residual_df_remains_auditable() -> None:
    assert ReportService._format_diagnostic_value("residual_df", [90, 89]) == "[90, 89]"
