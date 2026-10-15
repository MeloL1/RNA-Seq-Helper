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
        issues = dict(_result).get("issues", []) if isinstance(_result, dict) else []
        warning = ""
        if issues:
            warning = "\n存在运行告警，详情已写入 HTML/XLSX 报告。"
        self.status_label.setText(
            "分析完成。可打开离线 HTML 报告；完整结果表为 reports/deg-results.xlsx，"
            f"五张图位于 figures/。{warning}\n{self._XLSX_HINT}\n项目目录：{project_dir}"
        )
        self.open_report_button.setEnabled(self._report_path.exists())
        self.open_project_button.setEnabled(project_dir.exists())

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
