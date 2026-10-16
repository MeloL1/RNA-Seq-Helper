from __future__ import annotations

import csv
import json
import re
import shutil
from dataclasses import replace
from datetime import date
from pathlib import Path

from rnaseq_helper.analysis.planning import PlanningService
from rnaseq_helper.domain.models import (
    AnalysisPlan, DEGConfig, ExpressionMatrix, JobContext, ResultFilterConfig,
    may_contain_sensitive_metadata, persisted_local_path,
)
from rnaseq_helper.ui.workers.analysis_worker import AnalysisWorker

from PySide6.QtCore import QSettings, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QFileDialog,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
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
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        self.page_scroll = QScrollArea(self)
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.page_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        content = QWidget()
        content.setObjectName("analysisPageContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)
        title = QLabel("设置样本分组")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        self.matrix_label = QLabel("请先在“导入与整理”页完成矩阵整理。")
        layout.addWidget(self.matrix_label)

        grouping_box = QGroupBox("确认分组与样本注释")
        grouping_box.setObjectName("sampleGroupingBox")
        grouping_layout = QVBoxLayout(grouping_box)
        grouping_layout.setContentsMargins(14, 16, 14, 14)
        grouping_layout.setSpacing(12)
        overview_label = QLabel(
            "请按实验设计指定对照组和实验组；未确认的样本不会进入分析。可直接改每行组别，"
            "也可选中多行后点下方按钮，或筛选后批量设置。"
        )
        overview_label.setWordWrap(True)
        overview_label.setObjectName("groupingOverview")
        grouping_layout.addWidget(overview_label)
        design_hint = QLabel("分组方向：实验组 − 对照组；log2FoldChange > 0 表示实验组高于对照组。")
        design_hint.setWordWrap(True)
        design_hint.setObjectName("contrastDirectionHint")
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
        self.sample_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.sample_table.setSortingEnabled(True)
        self.sample_table.verticalHeader().setDefaultSectionSize(38)
        self.sample_table.horizontalHeader().setMinimumHeight(40)
        self.sample_table.setWordWrap(False)
        self.sample_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.sample_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sample_table.setMinimumHeight(420)
        self.sample_table.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.sample_table.setToolTip("点击列标题可排序；可用 Shift/Cmd 多选样本，再点击下方的分组按钮。")
        self.sample_table.itemChanged.connect(self._invalidate_plan)
        self.sample_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.sample_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.sample_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        grouping_layout.addWidget(self.sample_table)
        selection_actions = QHBoxLayout()
        selection_actions.addWidget(QLabel("先点样本 ID 所在行（⌘/Shift 可多选），再点："))
        self.selected_control_button = QPushButton("设为对照组")
        self.selected_control_button.clicked.connect(lambda: self._assign_selected_samples("control"))
        selection_actions.addWidget(self.selected_control_button)
        self.selected_test_button = QPushButton("设为实验组")
        self.selected_test_button.clicked.connect(lambda: self._assign_selected_samples("test"))
        selection_actions.addWidget(self.selected_test_button)
        self.selected_exclude_button = QPushButton("排除所选样本")
        self.selected_exclude_button.setToolTip("将当前多选的样本设为排除，不纳入本次比较。")
        self.selected_exclude_button.clicked.connect(lambda: self._assign_selected_samples("excluded"))
        selection_actions.addWidget(self.selected_exclude_button)
        selection_actions.addStretch(1)
        grouping_layout.addLayout(selection_actions)
        self.advanced_design_toggle = QToolButton()
        self.advanced_design_toggle.setText("显示配对与批次设置（可选）")
        self.advanced_design_toggle.setCheckable(True)
        self.advanced_design_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.advanced_design_toggle.toggled.connect(self._set_advanced_design_visible)
        grouping_layout.addWidget(self.advanced_design_toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.sample_table.setColumnHidden(2, True)
        self.sample_table.setColumnHidden(3, True)
        self.group_summary_label = QLabel("当前纳入分析：0 个样本；排除：0 个样本。")
        self.group_summary_label.setToolTip(
            "只有 control（对照）和 test（处理）会进入本次两组比较；标记为排除的样本会从矩阵中移除。"
        )
        self.group_summary_label.setObjectName("groupSummary")
        grouping_layout.addWidget(self.group_summary_label)
        self.suggestion_label = QLabel("样本编号和来源注释只供核对；软件不会据此猜测实验组别。")
        self.suggestion_label.setWordWrap(True)
        self.suggestion_label.setObjectName("groupingNote")
        grouping_layout.addWidget(self.suggestion_label)
        layout.addWidget(grouping_box, 1)

        destination_box = QGroupBox("结果保存位置")
        destination_layout = QHBoxLayout(destination_box)
        destination_layout.setContentsMargins(12, 8, 12, 8)
        destination_names = QVBoxLayout()
        self.destination_parent_label = QLabel("上级文件夹：完成分组后显示")
        self.destination_folder_label = QLabel("新建项目文件夹：待确定")
        for label in (self.destination_parent_label, self.destination_folder_label):
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setMinimumWidth(0)
            label.setWordWrap(False)
            destination_names.addWidget(label)
        destination_layout.addLayout(destination_names, 1)
        self.destination_button = QPushButton("选择文件夹…")
        self.destination_button.clicked.connect(self.choose_destination)
        destination_layout.addWidget(self.destination_button)
        layout.addWidget(destination_box)

        result_filter_box = QGroupBox("结果筛选（不改变统计模型）")
        result_filter_layout = QHBoxLayout(result_filter_box)
        result_filter_layout.setContentsMargins(12, 8, 12, 8)
        self.filter_fdr_radio = QRadioButton("按 FDR（校正后 P 值）")
        self.filter_raw_p_radio = QRadioButton("按原始 P 值")
        self.filter_fdr_radio.setChecked(True)
        result_filter_layout.addWidget(self.filter_fdr_radio)
        result_filter_layout.addWidget(self.filter_raw_p_radio)
        result_filter_layout.addWidget(QLabel("P 阈值"))
        self.filter_p_threshold = QLineEdit("0.05")
        self.filter_p_threshold.setMaximumWidth(90)
        self.filter_p_threshold.setToolTip("默认 0.05；范围 0 到 1。")
        result_filter_layout.addWidget(self.filter_p_threshold)
        result_filter_layout.addWidget(QLabel("|log2FC| 阈值"))
        self.filter_lfc_threshold = QLineEdit("1")
        self.filter_lfc_threshold.setMaximumWidth(90)
        self.filter_lfc_threshold.setToolTip("默认 1；必须大于或等于 0。")
        self.filter_lfc_threshold.editingFinished.connect(self._restore_default_lfc_threshold)
        result_filter_layout.addWidget(self.filter_lfc_threshold)
        self.filter_hint = QLabel("")
        self.filter_hint.setWordWrap(True)
        result_filter_layout.addWidget(self.filter_hint, 1)
        self.filter_fdr_radio.toggled.connect(self._invalidate_plan)
        self.filter_raw_p_radio.toggled.connect(self._invalidate_plan)
        self.filter_fdr_radio.toggled.connect(self._update_filter_hint)
        self.filter_p_threshold.textChanged.connect(self._update_filter_hint)
        self.filter_lfc_threshold.textChanged.connect(self._update_filter_hint)
        self.filter_p_threshold.textChanged.connect(self._invalidate_plan)
        self.filter_lfc_threshold.textChanged.connect(self._invalidate_plan)
        layout.addWidget(result_filter_box)

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
        self.page_scroll.setWidget(content)
        root_layout.addWidget(self.page_scroll)

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
        self._destination_parent = None
        self._resolved_project_dir = matrix.values.path.parent.parent if restored_project else None
        self._update_destination_label()
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
        saved_filter = ResultFilterConfig.from_mapping(
            initial_design.get("result_filter") if initial_design else None,
        )
        self.filter_fdr_radio.blockSignals(True)
        self.filter_raw_p_radio.blockSignals(True)
        self.filter_p_threshold.blockSignals(True)
        self.filter_lfc_threshold.blockSignals(True)
        self.filter_fdr_radio.setChecked(saved_filter.pvalue_mode == "fdr")
        self.filter_raw_p_radio.setChecked(saved_filter.pvalue_mode == "pvalue")
        self.filter_p_threshold.setText(f"{saved_filter.pvalue_threshold:g}")
        self.filter_lfc_threshold.setText(f"{saved_filter.log2fc_threshold:g}")
        for widget in (
            self.filter_fdr_radio, self.filter_raw_p_radio,
            self.filter_p_threshold, self.filter_lfc_threshold,
        ):
            widget.blockSignals(False)
        self._update_filter_hint()
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
        assignments = initial_design.get("assignments", {}) if initial_design else {}
        for row, sample_id in enumerate(sample_ids):
            self.sample_table.setItem(row, 0, QTableWidgetItem(sample_id))
            combo = QComboBox()
            # 未确认就是排除：新手不需要在“未确认”和“排除”之间再做一次选择。
            combo.addItem("排除本次分析（未确认）", "excluded")
            combo.addItem("control（对照）", "control")
            combo.addItem("test（处理）", "test")
            combo.setFixedHeight(30)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            saved_group = assignments.get(sample_id) if isinstance(assignments, dict) else None
            selected_group = saved_group if saved_group in {"control", "test", "excluded"} else "excluded"
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
        self.sample_table.setColumnHidden(2, not self.advanced_design_toggle.isChecked())
        self.sample_table.setColumnHidden(3, not self.advanced_design_toggle.isChecked())
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

    @Slot(bool)
    def _set_advanced_design_visible(self, visible: bool) -> None:
        self.sample_table.setColumnHidden(2, not visible)
        self.sample_table.setColumnHidden(3, not visible)
        self.advanced_design_toggle.setText(
            "隐藏配对与批次设置" if visible else "显示配对与批次设置（可选）"
        )

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
        try:
            result_filter = self._result_filter_config()
        except ValueError as exc:
            self.plan = None
            self.run_button.setEnabled(False)
            self.plan_label.setText(f"结果筛选设置无效：{exc}")
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
            result_filter=result_filter,
        )
        if self.plan.runnable:
            try:
                self._move_project_to_destination()
                self.plan = PlanningService().build(
                    self.matrix,
                    assignments,
                    DEGConfig("control", "test"),
                    paired_subjects=paired_subjects or None,
                    batch=batch or None,
                    replicate_structure=self.replicate_structure.currentData(),
                    result_filter=result_filter,
                )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                self.plan = None
                self.run_button.setEnabled(False)
                self.plan_label.setText(f"无法创建结果项目文件夹：{exc}")
                return
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
                    else f"计划摘要已保存：{project_dir / 'analysis' / 'analysis-plan.json'}"
                )
            )
            self.run_button.setEnabled(True)
            self.status_label.setText("计划已生成。请确认方法说明后点击“开始分析”。")
        else:
            messages = "\n".join(f"• {issue.message_zh}\n  操作：{issue.operation_zh}" for issue in self.plan.blockers)
            self.plan_label.setText(f"计划被阻断：\n{messages}")
            self.run_button.setEnabled(False)

    def choose_destination(self) -> None:
        if self.matrix is None:
            return
        settings = QSettings("RNA-Seq Helper", "RNA-Seq Helper")
        remembered = Path(str(settings.value("file-dialog/last-selected-folder", "") or "")).expanduser()
        parent = remembered if remembered.is_dir() else self._default_destination_parent()
        selected = QFileDialog.getExistingDirectory(
            self,
            "选择结果项目文件夹的保存位置",
            str(parent),
            QFileDialog.Option.ShowDirsOnly,
        )
        if not selected:
            return
        self._destination_parent = Path(selected).expanduser()
        settings = QSettings("RNA-Seq Helper", "RNA-Seq Helper")
        settings.setValue("file-dialog/last-selected-folder", str(self._destination_parent))
        settings.sync()
        self._update_destination_label()
        if self.plan is not None:
            self.plan = None
            self.run_button.setEnabled(False)
            self.plan_label.setText("保存位置已变化；请重新生成分析计划。")

    def _default_destination_parent(self) -> Path:
        if self._destination_parent is not None and self._destination_parent.is_dir():
            return self._destination_parent
        if self._resolved_project_dir is not None:
            return self._resolved_project_dir.parent
        source = self.matrix.source_path if self.matrix else None
        if source is not None and source.exists():
            return source.parent
        return Path.home() / "Documents" / "RNA-Seq Helper Projects"

    def _project_folder_name(self) -> str:
        assert self.matrix is not None
        if self._resolved_project_dir is not None:
            return self._resolved_project_dir.name
        source = self.matrix.source_path
        identity = ""
        if source is not None:
            for part in reversed(source.parts[:-1]):
                match = re.search(r"(?i)\b(?:GSE\d+|GSM\d+|MJ\d{6,}|[A-Z]{2,}\d{5,})\b", part)
                if match:
                    identity = match.group(0)
                    break
            if not identity:
                stem = source.name
                for suffix in (".gz", ".tsv", ".csv", ".txt", ".xls", ".xlsx"):
                    if stem.lower().endswith(suffix):
                        stem = stem[:-len(suffix)]
                stem = re.sub(r"(?i)(^|[._ -])(gene|transcript|count|tpm|fpkm|rpkm|matrix|expression)(?=$|[._ -])", " ", stem)
                identity = re.sub(r"[^\w.-]+", "-", stem, flags=re.UNICODE).strip("-._ ")[:48]
        identity = identity or "表达数据"
        unit = self.matrix.measurement_type.value
        type_name = {
            "RAW_COUNT": "Count", "TPM": "TPM", "FPKM": "FPKM",
            "RPKM": "RPKM", "CPM": "CPM", "OTHER_NORMALIZED": "其他标准化值",
            "UNKNOWN": "未确认类型",
        }.get(unit, unit.replace("_", "-") or "表达数据")
        return f"{date.today():%Y%m%d}-{identity}-{type_name}"

    def _update_destination_label(self) -> None:
        if self.matrix is None:
            self.destination_parent_label.setText("上级文件夹：完成分组后显示")
            self.destination_folder_label.setText("新建项目文件夹：待确定")
            return
        target = self._resolved_project_dir or self._available_destination()
        self.destination_parent_label.setText(f"上级文件夹：{target.parent.name or target.parent}")
        self.destination_folder_label.setText(f"新建项目文件夹：{target.name}")
        self.destination_parent_label.setToolTip(str(target.parent))
        self.destination_folder_label.setToolTip(str(target))

    def _available_destination(self) -> Path:
        parent = self._default_destination_parent()
        base = self._project_folder_name()
        target = parent / base
        suffix = 2
        while target.exists() and target.resolve() != self.matrix.values.path.parent.parent.resolve():
            target = parent / f"{base}-{suffix:02d}"
            suffix += 1
        return target

    def _move_project_to_destination(self) -> None:
        assert self.matrix is not None
        old_root = self.matrix.values.path.parent.parent
        parent = self._default_destination_parent()
        parent.mkdir(parents=True, exist_ok=True)
        target = self._available_destination()
        if old_root.resolve() == target.resolve():
            self._resolved_project_dir = old_root
            return
        shutil.move(str(old_root), str(target))

        def moved(ref):
            return replace(ref, path=target / ref.path.relative_to(old_root))

        self.matrix = replace(
            self.matrix,
            values=moved(self.matrix.values),
            feature_metadata=moved(self.matrix.feature_metadata),
            sample_metadata=moved(self.matrix.sample_metadata),
        )
        self._resolved_project_dir = target
        manifest_path = target / "project.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["project_id"] = persisted_local_path(target.name)
        manifest["project_id_redacted"] = may_contain_sensitive_metadata(target.name)
        for key, relative in (
            ("preparation_recipe", "preparation-recipe.json"),
            ("sample_metadata", "prepared/sample_metadata.tsv"),
        ):
            manifest[key] = persisted_local_path(target / relative)
        if manifest.get("reference_result"):
            manifest["reference_result"] = persisted_local_path(target / "references" / "reference-result.json")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self._update_destination_label()

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
        active = result_dict.get("display_summary", {})
        mode = "FDR" if active.get("pvalue_mode", "fdr") == "fdr" else "原始 P 值（未校正）"
        self.status_label.setText(
            f"分析完成：检测 {summary.get('tested_count', 0)} 个特征；按 {mode} < "
            f"{active.get('pvalue_threshold', 0.05)} 且 |log2FC| ≥ "
            f"{active.get('log2fc_threshold', 1)} 筛选，符合条件 {active.get('significant_magnitude_count', 0)} 个。"
            f"统计模型阈值保持不变。结果已写入 analysis/。{warning_suffix}"
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

    def _result_filter_config(self) -> ResultFilterConfig:
        try:
            p_threshold = float(self.filter_p_threshold.text().strip())
            lfc_threshold = float(self.filter_lfc_threshold.text().strip())
        except ValueError as exc:
            raise ValueError("请输入有效的数值阈值") from exc
        return ResultFilterConfig(
            pvalue_mode="fdr" if self.filter_fdr_radio.isChecked() else "pvalue",
            pvalue_threshold=p_threshold,
            log2fc_threshold=lfc_threshold,
        )

    @Slot()
    def _restore_default_lfc_threshold(self) -> None:
        if not self.filter_lfc_threshold.text().strip():
            self.filter_lfc_threshold.setText("1")

    @Slot()
    def _update_filter_hint(self, *_args: object) -> None:
        mode = "FDR（校正后 P 值）" if self.filter_fdr_radio.isChecked() else "原始 P 值（未校正）"
        lfc_text = self.filter_lfc_threshold.text().strip() or "1（留空将恢复默认值）"
        note = "；原始 P 值未经过多重检验校正" if self.filter_raw_p_radio.isChecked() else ""
        self.filter_hint.setText(
            f"当前按 {mode} < {self.filter_p_threshold.text().strip() or '0.05'}，"
            f"且 |log2FC| ≥ {lfc_text} 筛选；不改变统计模型。{note}"
        )

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
        self.suggestion_label.setText(
            "比较方向：实验组（test） − 对照组（control）；log2FoldChange > 0 表示实验组相对更高。"
            if counts["control"] and counts["test"]
            else "请至少指定一个对照组样本和一个实验组样本；软件不会根据样本编号猜组别。"
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

    @Slot(str)
    def _assign_selected_samples(self, group: str) -> None:
        """Assign the selected sample rows to a group using an explicit button."""
        if group not in {"control", "test", "excluded"}:
            return
        selected_ids = {
            self.sample_table.item(index.row(), 0).text()
            for index in self.sample_table.selectionModel().selectedRows()
            if self.sample_table.item(index.row(), 0) is not None
        }
        changed = False
        for row in range(self.sample_table.rowCount()):
            sample_item = self.sample_table.item(row, 0)
            combo = self.sample_table.cellWidget(row, 1)
            if sample_item is None or sample_item.text() not in selected_ids or not isinstance(combo, QComboBox):
                continue
            index = combo.findData(group)
            if index >= 0 and combo.currentIndex() != index:
                combo.blockSignals(True)
                combo.setCurrentIndex(index)
                combo.blockSignals(False)
                changed = True
        if changed:
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
