from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from rnaseq_helper.domain.models import ExpressionMatrix


class ResultsPage(QWidget):
    """把分析完成后的离线交付入口集中展示给非生信用户。"""

    _XLSX_HINT = "XLSX 结果表只含 5 列：feature_key、gene_symbol、log2FoldChange、pvalue、padj。"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.matrix: ExpressionMatrix | None = None
        self._report_path: Path | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)
        title = QLabel("结果与报告")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)
        subtitle = QLabel("分析完成后，从这里打开可复核的离线报告、结果表和项目文件。")
        subtitle.setStyleSheet("color: #52606d; margin-bottom: 4px;")
        layout.addWidget(subtitle)

        delivery_box = QGroupBox("分析交付")
        delivery_layout = QVBoxLayout(delivery_box)
        delivery_layout.setContentsMargins(14, 16, 14, 14)
        delivery_layout.setSpacing(12)
        self.status_label = QLabel("完成一次分析后，这里会显示离线报告入口。")
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(54)
        delivery_layout.addWidget(self.status_label)
        button_row = QHBoxLayout()
        button_row.setSpacing(12)
        self.open_report_button = QPushButton("打开离线 HTML 报告")
        self.open_report_button.setEnabled(False)
        self.open_report_button.clicked.connect(self.open_report)
        button_row.addWidget(self.open_report_button)
        self.open_project_button = QPushButton("打开项目文件夹")
        self.open_project_button.setEnabled(False)
        self.open_project_button.clicked.connect(self.open_project)
        button_row.addWidget(self.open_project_button)
        button_row.addStretch(1)
        delivery_layout.addLayout(button_row)
        layout.addWidget(delivery_box)
        layout.addStretch(1)

    @Slot(object)
    def set_matrix(self, matrix: ExpressionMatrix) -> None:
        self.matrix = matrix
        self._report_path = matrix.values.path.parent.parent / "reports" / "analysis-report.html"
        self.status_label.setText(
            "矩阵已整理。完成分析后，离线 HTML、XLSX、五张图和分析清单会出现在项目目录。\n"
            + self._XLSX_HINT
        )
        self.open_project_button.setEnabled(True)

    @Slot(object)
    def set_result(self, _result: object) -> None:
        if self.matrix is None:
            return
        project_dir = self.matrix.values.path.parent.parent
        self._report_path = project_dir / "reports" / "analysis-report.html"
        result = dict(_result) if isinstance(_result, dict) else {}
        issues = result.get("issues", [])
        warning = ""
        if issues:
            warning = "\n存在运行告警；详情见离线 HTML 报告及项目中的 analysis/deg-result.json。"
        effect_hint = ""
        if str(result.get("method", "")).startswith("LIMMA"):
            effect_hint = (
                "\n效应值说明：log2FoldChange 是当前 log 表达尺度上的模型差异，"
                "不是原始线性表达均值比；具体转换见 HTML 报告。"
            )
        self.status_label.setText(
            "分析完成。可打开离线 HTML 报告；完整结果表为 reports/deg-results.xlsx，"
            f"五张图位于 figures/。{warning}{effect_hint}\n{self._XLSX_HINT}\n项目目录：{project_dir}"
        )
        self.open_report_button.setEnabled(self._report_path.exists())
        self.open_project_button.setEnabled(project_dir.exists())

    @Slot(object)
    def set_saved_project(self, snapshot: object) -> None:
        """展示已保存项目的现有产物；不触发分析，也不改写项目文件。"""
        matrix = getattr(snapshot, "matrix", None)
        project_dir = getattr(snapshot, "project_dir", None)
        if matrix is None or project_dir is None:
            return
        self.matrix = matrix
        project_dir = Path(project_dir)
        self._report_path = getattr(snapshot, "report_path", None)
        report_valid = getattr(snapshot, "report_valid", False) is True
        result = getattr(snapshot, "saved_result", None)
        plan = getattr(snapshot, "saved_plan", None)
        warnings = tuple(getattr(snapshot, "warnings", ()))
        if result is not None:
            status = (
                "已读取保存项目及其既有分析结果，没有重跑分析。若检测到上次分析发布中断，"
                "软件会按事务记录恢复旧结果或清理未完成的临时文件；详情见下方恢复提示。"
                "若在“确认样本”页再次运行分析，将按您的设置覆盖此项目中的旧分析计划、结果、图表和报告；原始输入文件不会被覆盖。"
            )
            if getattr(snapshot, "result_integrity_valid", False) is not True:
                status += "\n注意：旧结果未通过完整哈希核验，仅作为历史记录保留。"
            if plan is None:
                status += "\n注意：分析计划无法通过一致性校验，已保留结果供查看，但不会恢复计划。"
        else:
            status = (
                "项目矩阵已读取；没有发现可通过一致性校验的既有分析结果，因此未重跑分析。"
                "若检测到上次分析发布中断，软件会先恢复旧结果或清理未完成的临时文件；详情见下方恢复提示。"
            )
        if warnings:
            status += "\n恢复提示：\n• " + "\n• ".join(warnings)
        if self._report_path is not None and not report_valid:
            status += "\n为避免打开与当前项目不匹配的文件，离线 HTML 报告未启用。"
        self.status_label.setText(f"{status}\n项目目录：{project_dir}")
        self.open_report_button.setEnabled(bool(report_valid and self._report_path and self._report_path.is_file()))
        self.open_project_button.setEnabled(project_dir.is_dir())

    @Slot()
    def open_report(self) -> None:
        if self._report_path and self._report_path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._report_path)))

    @Slot()
    def open_project(self) -> None:
        if self.matrix is not None:
            project_dir = self.matrix.values.path.parent.parent
            if project_dir.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(project_dir)))
