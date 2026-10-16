from __future__ import annotations

import csv
from pathlib import Path

from rnaseq_helper.analysis.planning import PlanningService
from rnaseq_helper.domain.models import AnalysisPlan, DEGConfig, ExpressionMatrix, JobContext
from rnaseq_helper.grouping.service import GroupingService
from rnaseq_helper.ui.workers.analysis_worker import AnalysisWorker

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)


class AnalysisPage(QWidget):
    """阶段 2 的最小分组、计划确认和分析运行页。"""

    analysisReady = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.matrix: ExpressionMatrix | None = None
        self._metadata_columns: list[str] = []
        self.plan: AnalysisPlan | None = None
        self._restored_project = False
        self._jobs: list[tuple[QThread, AnalysisWorker, JobContext]] = []
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)
        title = QLabel("确认分组并开始分析")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)
        self.matrix_label = QLabel("请先在“导入与整理”页完成矩阵整理。")
        layout.addWidget(self.matrix_label)

        grouping_box = QGroupBox("确认分组与样本注释")
        grouping_layout = QVBoxLayout(grouping_box)
        grouping_layout.setContentsMargins(14, 16, 14, 14)
        grouping_layout.setSpacing(12)
        overview_label = QLabel(
            "先用筛选框找样本，再把筛选后的可见行批量设为同一组；点击列标题可排序。只有 control 和 test 会进入本次比较，其他样本直接选择“排除本次分析（未确认）”。列名和 GEO2R 注释只生成建议，不能代替实验事实。"
        )
        overview_label.setWordWrap(True)
        overview_label.setStyleSheet("font-weight: 600; padding-bottom: 2px;")
        grouping_layout.addWidget(overview_label)
        design_hint = QLabel(
            "配对个体：同一个人/动物的前后测或左右侧样本填写相同编号；独立样本留空。\n"
            "批次：不同日期、测序批次或芯片批次填写相同批次名；没有批次信息就留空，不要随便填写。"
        )
        design_hint.setWordWrap(True)
        design_hint.setStyleSheet("color: #3b4752; padding-bottom: 4px;")
        grouping_layout.addWidget(design_hint)
        replicate_row = QHBoxLayout()
        replicate_row.setContentsMargins(8, 2, 8, 4)
        replicate_row.setSpacing(10)
        replicate_row.addWidget(QLabel("样本之间的关系（必选）"))
        self.replicate_structure = QComboBox()
        self.replicate_structure.addItem("请选择：先核对实验记录", None)
        self.replicate_structure.addItem(
            "每列是一个整体生物样本（不是单个细胞），且样本彼此独立",
            "independent",
        )
        self.replicate_structure.addItem("同一个体有多列（配对/重复测量）", "paired")
        self.replicate_structure.addItem("每列是单个细胞/细胞核（当前不支持）", "cell")
        self.replicate_structure.addItem("技术重复、混合样本或不确定", "unknown")
        self.replicate_structure.setMinimumWidth(360)
        self.replicate_structure.setToolTip(
            "只有每列代表一个整体生物样本、且样本彼此独立时才选第一项。"
            "单个细胞/细胞核不能当作 bulk 生物学重复；单细胞数据应先按供者汇总为 pseudobulk。"
            "同一个人/动物的多个样本选配对；技术重复、混合样本或不确定时不要选独立。"
        )
        self.replicate_structure.currentIndexChanged.connect(self._invalidate_plan)
        replicate_row.addWidget(self.replicate_structure, 1)
        grouping_layout.addLayout(replicate_row)
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(8, 4, 8, 4)
        filter_row.setSpacing(10)
        filter_row.addWidget(QLabel("筛选样本/注释"))
        self.sample_filter = QLineEdit()
        self.sample_filter.setPlaceholderText("例如输入 GSM、control、tumor、某个 sample title")
        self.sample_filter.setMinimumWidth(280)
        self.sample_filter.setClearButtonEnabled(True)
        self.sample_filter.textChanged.connect(self._filter_samples)
        filter_row.addWidget(self.sample_filter, 1)
        filter_row.addWidget(QLabel("批量设置可见行"))
        self.bulk_group = QComboBox()
        self.bulk_group.addItem("不修改", None)
        self.bulk_group.addItem("排除本次分析（未确认）", "excluded")
        self.bulk_group.addItem("control（对照）", "control")
        self.bulk_group.addItem("test（处理）", "test")
        self.bulk_group.setMinimumWidth(205)
        self.bulk_group.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        filter_row.addWidget(self.bulk_group)
        self.bulk_apply = QPushButton("应用到可见行")
        self.bulk_apply.setFixedWidth(132)
        self.bulk_apply.clicked.connect(self._apply_bulk_group)
        filter_row.addWidget(self.bulk_apply)
        grouping_layout.addLayout(filter_row)
        self.sample_table = QTableWidget(0, 8)
        self.sample_table.setHorizontalHeaderLabels([
            "样本 ID", "分组（仅纳入样本选择）", "配对个体（可选）", "批次（可选）", "GEO 编号（只读）",
            "样本标题（只读）", "平台（只读）", "其他来源注释（只读）",
        ])
        self.sample_table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.EditKeyPressed)
        self.sample_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.sample_table.setSortingEnabled(True)
        self.sample_table.verticalHeader().setDefaultSectionSize(38)
        self.sample_table.horizontalHeader().setMinimumHeight(40)
        self.sample_table.setWordWrap(False)
        self.sample_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.sample_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.sample_table.setToolTip("点击列标题可排序；使用上方筛选框定位样本，可批量修改可见行的分组。")
        self.sample_table.itemChanged.connect(self._invalidate_plan)
        for column in range(7):
            self.sample_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.sample_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        grouping_layout.addWidget(self.sample_table)
        self.group_summary_label = QLabel("当前纳入分析：0 个样本；排除：0 个样本。")
        self.group_summary_label.setToolTip(
            "只有 control（对照）和 test（处理）会进入本次两组比较；标记为排除的样本会从矩阵中移除。"
        )
        grouping_layout.addWidget(self.group_summary_label)
        self.suggestion_label = QLabel("尚无分组建议。")
        self.suggestion_label.setWordWrap(True)
        self.suggestion_label.setStyleSheet("color: #3b4752; padding-top: 2px;")
        grouping_layout.addWidget(self.suggestion_label)
        layout.addWidget(grouping_box, 1)

        actions = QHBoxLayout()
        actions.setSpacing(12)
        self.plan_button = QPushButton("确认分组并生成分析计划")
        self.plan_button.setEnabled(False)
        self.plan_button.clicked.connect(self.build_plan)
        actions.addWidget(self.plan_button)
        self.run_button = QPushButton("开始分析")
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self.run_analysis)
        actions.addWidget(self.run_button)
        self.cancel_button = QPushButton("取消当前任务")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_analysis)
        actions.addWidget(self.cancel_button)
        for button, width in (
            (self.plan_button, 236),
            (self.run_button, 140),
            (self.cancel_button, 156),
        ):
            button.setFixedWidth(width)
        actions.addStretch(1)
        layout.addLayout(actions)

        status_box = QGroupBox("计划与运行状态")
        status_layout = QVBoxLayout(status_box)
        status_layout.setContentsMargins(14, 14, 14, 12)
        status_layout.setSpacing(8)
        self.plan_label = QLabel("分析方法将在分组确认后显示。")
        self.plan_label.setWordWrap(True)
        status_layout.addWidget(self.plan_label)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        status_layout.addWidget(self.status_label)
        layout.addWidget(status_box)

    @Slot(object)
    def set_matrix(
        self,
        matrix: ExpressionMatrix,
        initial_design: dict[str, object] | None = None,
        restored_project: bool = False,
    ) -> None:
        self.matrix = matrix
        self.plan = None
        self._restored_project = restored_project
        saved_structure = None
        if initial_design:
            candidate = initial_design.get("replicate_structure")
            expected_type = "paired" if candidate == "paired" else "independent_two_group"
            if (
                candidate in {"independent", "paired"}
                and initial_design.get("replicate_structure_confirmed") is True
                and initial_design.get("type") == expected_type
            ):
                saved_structure = candidate
        structure_index = self.replicate_structure.findData(saved_structure)
        self.replicate_structure.setCurrentIndex(structure_index if structure_index >= 0 else 0)
        sample_ids = self._read_sample_ids(matrix)
        sample_metadata = self._read_sample_metadata(matrix)
        available_metadata = sorted({
            key for metadata in sample_metadata.values() for key in metadata
            if key not in {"sample_id", "geo_accession", "sample_title", "platform_id"}
        })
        # GEO 会附带地址、机构、作者、实验流程等大量字段；这些仍完整保存，
        # 但分组页只展示最能帮助新手判断实验分组的来源/条件，避免表格横向失控。
        preferred_metadata = [
            key for key in ("source_name_ch1", "characteristics_ch1")
            if key in available_metadata
        ]
        self._metadata_columns = preferred_metadata or available_metadata[:2]
        headers = [
            "样本 ID", "分组（仅纳入样本选择）", "配对个体（可选）", "批次（可选）", "GEO 编号（只读）",
            "样本标题（只读）", "平台（只读）",
            *[f"{key}（只读）" for key in self._metadata_columns],
        ]
        self.sample_table.setColumnCount(len(headers))
        self.sample_table.setHorizontalHeaderLabels(headers)
        self.sample_table.blockSignals(True)
        self.sample_table.setSortingEnabled(False)
        self.sample_table.setRowCount(len(sample_ids))
        suggestions = GroupingService().suggest(sample_ids, sample_metadata)
        suggestion = suggestions[0]
        self.suggestion_label.setText(
            f"建议：{suggestion.title_zh}（依据：{suggestion.evidence_zh}；置信度 {suggestion.confidence:.2f}）。请逐项核实。"
        )
        for row, sample_id in enumerate(sample_ids):
            self.sample_table.setItem(row, 0, QTableWidgetItem(sample_id))
            combo = QComboBox()
            # 未确认就是排除：新手不需要在“未确认”和“排除”之间再做一次选择。
            combo.addItem("排除本次分析（未确认）", "excluded")
            combo.addItem("control（对照）", "control")
            combo.addItem("test（处理）", "test")
            combo.setFixedHeight(30)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            assignments = initial_design.get("assignments", {}) if initial_design else {}
            saved_group = assignments.get(sample_id) if isinstance(assignments, dict) else None
            suggested = suggestion.assignments.get(sample_id)
            selected_group = saved_group if saved_group in {"control", "test", "excluded"} else (
                "excluded" if restored_project else suggested
            )
            if selected_group in {"control", "test", "excluded"}:
                combo.setCurrentIndex(combo.findData(selected_group))
            combo.currentIndexChanged.connect(self._invalidate_plan)
            self.sample_table.setCellWidget(row, 1, combo)
            for column, key in ((2, "paired_subjects"), (3, "batch")):
                mapping = initial_design.get(key, {}) if initial_design else {}
                value = mapping.get(sample_id, "") if isinstance(mapping, dict) else ""
                self.sample_table.setItem(row, column, QTableWidgetItem(str(value)))
            metadata = sample_metadata.get(sample_id, {})
            for column, key in ((4, "geo_accession"), (5, "sample_title"), (6, "platform_id")):
                value = metadata.get(key, "") or "—"
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.sample_table.setItem(row, column, item)
            for offset, key in enumerate(self._metadata_columns, start=7):
                value = metadata.get(key, "") or "—"
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.sample_table.setItem(row, offset, item)
            for column in [0, 4, 5, 6, *range(7, 7 + len(self._metadata_columns))]:
                item = self.sample_table.item(row, column)
                if item is not None:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.sample_table.blockSignals(False)
        self.sample_table.setSortingEnabled(True)
        self.sample_table.resizeColumnsToContents()
        for column, width in ((0, 150), (1, 170), (2, 140), (3, 110), (4, 120), (5, 220), (6, 100)):
            if column < self.sample_table.columnCount():
                self.sample_table.setColumnWidth(column, width)
        for column in range(7, self.sample_table.columnCount()):
            self.sample_table.setColumnWidth(column, 220)
        self.matrix_label.setText(
            f"已整理矩阵：{matrix.values.shape[0]} 个特征 × {matrix.values.shape[1]} 个样本；请确认下方分组。"
        )
        if restored_project:
            self.matrix_label.setText(
                self.matrix_label.text()
                + "\n这是已打开的项目；点击“开始分析”将覆盖此项目中的分析计划、结果、图表和报告（不会覆盖原始输入文件）。"
            )
        self.plan_button.setEnabled(bool(sample_ids))
        self.run_button.setEnabled(False)
        self._update_group_summary()
        self.plan_label.setText("建议仅供参考；完成逐项核实后点击“确认分组并生成分析计划”。")
        self.status_label.clear()

    @Slot()
    def _invalidate_plan(self) -> None:
        if self.matrix is not None:
            self.plan = None
            self.run_button.setEnabled(False)
            self._update_group_summary()
            self.plan_label.setText("分组已变化，原分析计划失效；请重新生成并确认。")

    @Slot()
    def build_plan(self) -> None:
        if self.matrix is None:
            return
        assignments = self._assignments()
        paired_subjects = self._mapping_column(2)
        batch = self._mapping_column(3)
        self.plan = PlanningService().build(
            self.matrix,
            assignments,
            DEGConfig("control", "test"),
            paired_subjects=paired_subjects or None,
            batch=batch or None,
            replicate_structure=self.replicate_structure.currentData(),
        )
        project_dir = self.matrix.values.path.parent.parent
        if not self._restored_project:
            PlanningService.save(self.plan, project_dir)
        if self.plan.runnable:
            limits = "\n".join(f"• {item}" for item in self.plan.limitations_zh) or "• 无额外限制"
            self.plan_label.setText(
                f"方法：{self.plan.method}\n{self.plan.method_reason_zh}\n"
                f"Profile：{self.plan.method_profile_id}\n{limits}\n"
                + (
                    "新计划将在分析成功后与结果一起保存。"
                    if self._restored_project
                    else f"计划摘要已保存：{project_dir / 'analysis-plan.json'}"
                )
            )
            self.run_button.setEnabled(True)
            self.status_label.setText("计划已生成。请确认方法说明后点击“开始分析”。")
        else:
            messages = "\n".join(f"• {issue.message_zh}\n  操作：{issue.operation_zh}" for issue in self.plan.blockers)
            self.plan_label.setText(f"计划被阻断：\n{messages}")
            self.run_button.setEnabled(False)

    @Slot()
    def run_analysis(self) -> None:
        if self.matrix is None or self.plan is None or not self.plan.runnable:
            return
        self.run_button.setEnabled(False)
        self.plan_button.setEnabled(False)
        self.status_label.setText("R worker 正在执行已确认的分析计划……")
        thread = QThread(self)
        worker = AnalysisWorker(self.matrix, self.plan, JobContext(self.matrix.values.path.parent.parent))
        self._jobs.append((thread, worker, worker.context))
        worker.moveToThread(thread)
        thread.started.connect(worker.run, Qt.ConnectionType.QueuedConnection)
        worker.completed.connect(self._analysis_completed, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(self._analysis_failed, Qt.ConnectionType.QueuedConnection)
        worker.progress.connect(self._analysis_progress, Qt.ConnectionType.QueuedConnection)
        worker.completed.connect(thread.quit, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(thread.quit, Qt.ConnectionType.QueuedConnection)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda current=(thread, worker, worker.context): self._jobs.remove(current))
        self.cancel_button.setEnabled(True)
        thread.start()

    @Slot()
    def cancel_analysis(self) -> None:
        if not self._jobs:
            return
        self._jobs[-1][2].cancel_event.set()
        self.cancel_button.setEnabled(False)
        self.status_label.setText("正在取消 R worker……")

    @Slot(object)
    def _analysis_completed(self, result: object) -> None:
        result_dict = dict(result)
        summary = result_dict.get("summary", {})
        worker_issues = result_dict.get("issues", [])
        warning_suffix = ""
        if worker_issues:
            messages = [
                str(issue.get("message_zh", issue)) if isinstance(issue, dict) else str(issue)
                for issue in worker_issues
            ]
            warning_suffix = f"\n运行告警：{'；'.join(messages)}"
        self.status_label.setText(
            f"分析完成：检测 {summary.get('tested_count', 0)} 个特征，"
            f"FDR<{summary.get('fdr_threshold', 0.05)} 且 |效应|≥{summary.get('lfc_threshold', 1)} 的特征 "
            f"有 {summary.get('significant_magnitude_count', 0)} 个。结果已写入 analysis/。{warning_suffix}"
        )
        self.analysisReady.emit(result_dict)
        self.plan_button.setEnabled(True)
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    @Slot(str)
    def _analysis_failed(self, error: str) -> None:
        if error.startswith("任务已取消"):
            self.status_label.setText("分析已取消；原有结果保持不变。")
        else:
            self.status_label.setText(f"分析失败：{error}")
        self.plan_button.setEnabled(True)
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    @Slot(str)
    def _analysis_progress(self, message: str) -> None:
        if message.startswith("正在保存分析结果"):
            self.cancel_button.setEnabled(False)
        self.status_label.setText(f"分析中：{message}")

    def _assignments(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for row in range(self.sample_table.rowCount()):
            sample_item = self.sample_table.item(row, 0)
            combo = self.sample_table.cellWidget(row, 1)
            if sample_item is not None and isinstance(combo, QComboBox):
                # 旧项目或外部调用可能仍返回空值；空值也按“未确认=排除”归一化。
                result[sample_item.text()] = str(combo.currentData() or "excluded")
        return result

    def _update_group_summary(self) -> None:
        assignments = self._assignments()
        counts = {"control": 0, "test": 0, "excluded": 0}
        for value in assignments.values():
            if value in counts:
                counts[value] += 1
            else:
                counts["excluded"] += 1
        self.group_summary_label.setText(
            "当前纳入分析：{active} 个样本（control {control}，test {test}）；排除：{excluded} 个样本。"
            .format(
                active=counts["control"] + counts["test"],
                control=counts["control"],
                test=counts["test"],
                excluded=counts["excluded"],
            )
        )

    def _mapping_column(self, column: int) -> dict[str, str]:
        result: dict[str, str] = {}
        for row in range(self.sample_table.rowCount()):
            sample_item = self.sample_table.item(row, 0)
            value_item = self.sample_table.item(row, column)
            if sample_item is not None and value_item is not None and value_item.text().strip():
                result[sample_item.text()] = value_item.text().strip()
        return result

    @Slot(str)
    def _filter_samples(self, text: str) -> None:
        needle = text.strip().casefold()
        for row in range(self.sample_table.rowCount()):
            values = []
            for column in range(self.sample_table.columnCount()):
                item = self.sample_table.item(row, column)
                if item is not None:
                    values.append(item.text())
            self.sample_table.setRowHidden(row, bool(needle) and needle not in " ".join(values).casefold())

    @Slot()
    def _apply_bulk_group(self) -> None:
        group = self.bulk_group.currentData()
        if not group:
            return
        for row in range(self.sample_table.rowCount()):
            if self.sample_table.isRowHidden(row):
                continue
            combo = self.sample_table.cellWidget(row, 1)
            if isinstance(combo, QComboBox):
                combo.setCurrentIndex(combo.findData(group))
        self._invalidate_plan()

    @staticmethod
    def _read_sample_metadata(matrix: ExpressionMatrix) -> dict[str, dict[str, str]]:
        """读取整理阶段保存的样本注释；注释只用于建议和展示，不进入数值矩阵。"""

        result: dict[str, dict[str, str]] = {}
        try:
            with matrix.sample_metadata.path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
        except (OSError, UnicodeError):
            return result
        for row in rows:
            sample_id = str(row.get("sample_id", "")).strip()
            if sample_id:
                result[sample_id] = {
                    str(key): str(value).strip()
                    for key, value in row.items()
                    if key and value is not None and str(value).strip()
                }
        return result

    @staticmethod
    def _format_sample_annotation(metadata: dict[str, str]) -> str:
        parts = []
        for key in ("geo_accession", "sample_title", "platform_id"):
            value = metadata.get(key, "").strip()
            if value:
                parts.append(f"{key}: {value}")
        return "；".join(parts) if parts else "无附加样本注释"

    @staticmethod
    def _read_sample_ids(matrix: ExpressionMatrix) -> tuple[str, ...]:
        rows = matrix.sample_metadata.path.read_text(encoding="utf-8").splitlines()[1:]
        return tuple(row.split("\t", 1)[0] for row in rows if row.strip())
