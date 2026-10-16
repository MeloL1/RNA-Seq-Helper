from __future__ import annotations

import os
import shutil
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from rnaseq_helper.domain.models import (
    DataAsset, Evidence, MeasurementType, ValueScale, may_contain_sensitive_metadata,
)
from rnaseq_helper.preparation.service import PreparationService, WizardSession
from rnaseq_helper.recognition.scanner import AssetScanner, ScanProgress, ScanResult
from rnaseq_helper.services.archive_service import ArchiveCancelled, ArchiveSafetyError, ArchiveService
from rnaseq_helper.readers.geo_reader import GeoSeriesMatrix
from rnaseq_helper.readers.tenx_reader import TenXBundle, TenXReader, TenXReadError
from rnaseq_helper.ui.workers.import_worker import ImportProgress, ImportTaskWorker

from PySide6.QtCore import Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QFileDialog, QFileSystemModel, QLineEdit,
    QComboBox, QDialog, QDialogButtonBox, QGridLayout, QGroupBox, QLayout,
    QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox, QCheckBox, QInputDialog,
    QPlainTextEdit, QScrollArea, QStackedWidget, QTableWidget, QTableWidgetItem,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QSizePolicy, QHeaderView,
    QTabWidget, QToolButton,
)


class BeginnerHintTextEdit(QPlainTextEdit):
    """只读的小白说明框；保留 text() 兼容旧的界面回归测试。"""

    def text(self) -> str:
        return self.toPlainText()


class ArchiveCandidateDialog(QDialog):
    """显示压缩包中逻辑候选对象，避免只靠文件名猜用途。"""

    def __init__(self, candidates: list[DataAsset], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("选择压缩包内的表达对象")
        self.resize(760, 360)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("请根据用途、尺寸和来源选择表达对象；参考文件只作映射，不能作为表达矩阵打开；10x 细胞对象不会进入 bulk 分析。"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["对象/成员", "类型/用途", "尺寸", "完整性/来源"])
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        roots: dict[str, QTreeWidgetItem] = {}
        source_paths = [candidate.source_paths[0] for candidate in candidates if candidate.source_paths]
        common_root = Path(os.path.commonpath([str(path.parent) for path in source_paths])) if source_paths else Path(".")
        for index, candidate in enumerate(candidates):
            shape = "×".join(str(value) for value in candidate.shape_hint) if candidate.shape_hint else "未知"
            if candidate.kind == "TENX":
                purpose = "10x 细胞级稀疏矩阵"
            elif candidate.kind == "REFERENCE":
                purpose = "平台/基因注释参考（不作为表达矩阵）"
            else:
                purpose = candidate.role
            source = candidate.source_paths[0] if candidate.source_paths else common_root
            try:
                relative = source.relative_to(common_root)
            except ValueError:
                relative = Path(source.name)
            parent = self.tree.invisibleRootItem()
            parts = relative.parts[:-1]
            for part_index, part in enumerate(parts):
                key = str(Path(*parts[:part_index + 1]))
                if key not in roots:
                    roots[key] = QTreeWidgetItem(parent, [part, "目录", "", ""])
                parent = roots[key]
            leaf = relative.name if relative.parts else candidate.kind
            size_bytes = sum(
                path.stat().st_size
                for path in candidate.source_paths
                if path.is_file()
            )
            if size_bytes >= 1024 * 1024:
                size_text = f"{size_bytes / (1024 * 1024):.1f} MB"
            elif size_bytes >= 1024:
                size_text = f"{size_bytes / 1024:.1f} KB"
            else:
                size_text = f"{size_bytes} B"
            if candidate.kind == "TENX":
                completeness = "完整三件套"
            elif candidate.kind == "REFERENCE":
                completeness = "参考候选；请在导入页单独选择"
            else:
                completeness = "可读取候选"
            item = QTreeWidgetItem(parent, [
                leaf,
                f"{candidate.kind} / {purpose}",
                f"{shape}；{size_text}",
                completeness,
            ])
            # 参考文件可以在树中审查，但不允许被“打开”成表达矩阵。
            item.setData(0, Qt.ItemDataRole.UserRole, index if candidate.kind != "REFERENCE" else -1)
            item.setToolTip(0, "；".join(str(path) for path in candidate.source_paths))
            item.setToolTip(3, "；".join(str(path) for path in candidate.source_paths))
        self.tree.expandAll()
        if self.tree.topLevelItemCount():
            first = self.tree.topLevelItem(0)
            while first.childCount():
                first = first.child(0)
            self.tree.setCurrentItem(first)
        layout.addWidget(self.tree, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Open)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @classmethod
    def choose(cls, candidates: list[DataAsset], parent: QWidget | None = None) -> DataAsset | None:
        dialog = cls(candidates, parent)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        item = dialog.tree.currentItem()
        if item is None:
            return None
        index = item.data(0, Qt.ItemDataRole.UserRole)
        return candidates[int(index)] if index is not None and int(index) >= 0 else None


class TenXWizardDialog(QDialog):
    """把 10x 细胞对象的事实、组成和安全边界分成可审查的三步。"""

    def __init__(self, bundle: TenXBundle, manifest_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("10x 稀疏对象导入向导")
        self.resize(760, 500)
        self.pages = QStackedWidget()
        self.page_labels: list[QLabel] = []
        self._build_pages(bundle, manifest_path)

        self.back_button = QPushButton("上一步")
        self.next_button = QPushButton("下一步")
        self.done_button = QPushButton("完成并返回")
        self.back_button.clicked.connect(self._previous)
        self.next_button.clicked.connect(self._next)
        self.done_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(self.back_button)
        buttons.addStretch(1)
        buttons.addWidget(self.next_button)
        buttons.addWidget(self.done_button)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("10x 含有细胞条形码；本向导只确认结构和安全边界，不把细胞伪装成 bulk 重复。"))
        layout.addWidget(self.pages, 1)
        layout.addLayout(buttons)
        self._update_buttons()

    def _build_pages(self, bundle: TenXBundle, manifest_path: Path) -> None:
        facts = QWidget()
        facts_layout = QVBoxLayout(facts)
        facts_layout.addWidget(QLabel("第 1 步 / 数据事实：以下信息来自 Matrix Market 维度行和三件套文件，不是按文件名猜测。"))
        sparsity = 1.0 - bundle.nonzero_entries / max(1, bundle.rows * bundle.columns)
        facts_layout.addWidget(QLabel(
            f"观察单位：CELL（细胞）\n"
            f"矩阵：{bundle.rows} 个特征 × {bundle.columns} 个细胞\n"
            f"存储：稀疏 Matrix Market；非零条目：{bundle.nonzero_entries}\n"
            f"稀疏度：{sparsity:.2%}\n"
            f"只读清单：{manifest_path}"
        ))
        facts_layout.addWidget(QLabel(
            "原始文件保持只读。任何供者、样本或细胞类型信息都必须另有实验记录，软件不会从细胞条形码推断分组。"
        ))
        facts_layout.addStretch(1)

        composition = QWidget()
        composition_layout = QVBoxLayout(composition)
        composition_layout.addWidget(QLabel("第 2 步 / 特征构成：不同 feature type 不能未经确认混进 bulk 基因矩阵。"))
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["feature type", "特征行数"])
        for row, (name, count) in enumerate(sorted(bundle.feature_type_counts.items())):
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(name))
            table.setItem(row, 1, QTableWidgetItem(str(count)))
        table.resizeColumnsToContents()
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        composition_layout.addWidget(table)
        composition_layout.addWidget(QLabel(
            f"Gene Expression：{bundle.gene_expression_rows} 行。其余类型会保留在事实清单中，不会自动当成基因表达。"
        ))
        composition_layout.addStretch(1)

        boundary = QWidget()
        boundary_layout = QVBoxLayout(boundary)
        boundary_layout.addWidget(QLabel("第 3 步 / 分析边界：当前版本的可执行路径到这里停止。"))
        boundary_layout.addWidget(QLabel(
            "• 不能把 600 个细胞条形码当作 600 个独立生物学重复。\n"
            "• 若要继续两组差异分析，请先取得供者/样本级信息，并按实验设计做 pseudobulk。\n"
            "• pseudobulk 后仍需回到“导入与整理”，确认样本单位、分组、配对和批次。\n"
            "• 本向导已写出 tenx-manifest.json，可用于复核输入而不会改写三件套。"
        ))
        boundary_layout.addStretch(1)

        for page in (facts, composition, boundary):
            self.pages.addWidget(page)

    def _update_buttons(self) -> None:
        index = self.pages.currentIndex()
        last = self.pages.count() - 1
        self.back_button.setEnabled(index > 0)
        self.next_button.setVisible(index < last)
        self.done_button.setVisible(index == last)

    def _next(self) -> None:
        self.pages.setCurrentIndex(min(self.pages.count() - 1, self.pages.currentIndex() + 1))
        self._update_buttons()

    def _previous(self) -> None:
        self.pages.setCurrentIndex(max(0, self.pages.currentIndex() - 1))
        self._update_buttons()


class GeoWizardDialog(QDialog):
    """显示 GEO 平台和样本注释的来源，并要求人工核实其分组含义。"""

    def __init__(self, geo: GeoSeriesMatrix, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("GEO Series Matrix 导入向导")
        self.resize(820, 520)
        self.pages = QStackedWidget()
        self._build_pages(geo)
        self.back_button = QPushButton("上一步")
        self.next_button = QPushButton("下一步")
        self.done_button = QPushButton("完成并返回")
        self.back_button.clicked.connect(self._previous)
        self.next_button.clicked.connect(self._next)
        self.done_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addWidget(self.back_button)
        buttons.addStretch(1)
        buttons.addWidget(self.next_button)
        buttons.addWidget(self.done_button)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("GEO 元数据来自用户提供的 Series Matrix 文件；本地模式不会上传表达矩阵，也不会联网替你猜分组。"))
        layout.addWidget(self.pages, 1)
        layout.addLayout(buttons)
        self._update_buttons()

    def _build_pages(self, geo: GeoSeriesMatrix) -> None:
        facts = QWidget()
        facts_layout = QVBoxLayout(facts)
        facts_layout.addWidget(QLabel("第 1 步 / 数据与平台事实"))
        platforms = "、".join(dict.fromkeys(geo.platform_ids)) or "文件未提供平台编号"
        facts_layout.addWidget(QLabel(
            f"来源文件：{geo.path}\n"
            f"表达表约 {geo.raw_table.row_count} 行 × {geo.raw_table.column_count} 列\n"
            f"平台：{platforms}\n"
            f"样本数：{len(geo.sample_accessions) or max(0, geo.raw_table.column_count - 1)}\n"
            "平台混合会被阻断；本页只确认平台和结构，不把平台编号当作实验分组。"
        ))
        facts_layout.addStretch(1)

        samples = QWidget()
        samples_layout = QVBoxLayout(samples)
        samples_layout.addWidget(QLabel("第 2 步 / 样本注释来源：GSM 和 sample title 只作为审查线索。"))
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["GSM", "sample title", "platform"])
        count = max(len(geo.sample_accessions), len(geo.sample_titles))
        for row in range(count):
            table.insertRow(row)
            values = (
                geo.sample_accessions[row] if row < len(geo.sample_accessions) else "（未提供）",
                geo.sample_titles[row] if row < len(geo.sample_titles) else "（未提供）",
                geo.platform_ids[row] if row < len(geo.platform_ids) else "（未提供）",
            )
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.resizeColumnsToContents()
        samples_layout.addWidget(table)
        samples_layout.addStretch(1)

        meaning = QWidget()
        meaning_layout = QVBoxLayout(meaning)
        meaning_layout.addWidget(QLabel("第 3 步 / 分析含义确认"))
        meaning_layout.addWidget(QLabel(
            "• 软件可以根据 sample title 给出 control/treated 等候选，但不会自动提交分析。\n"
            "• 请在“分组与分析”页逐个确认每个 GSM 对应的实验组，并核实是否存在配对或批次。\n"
            "• 若只有 GSM 编号而没有实验说明，软件会保留未确认状态，不能把编号顺序当作分组。\n"
            "• 平台注释和表达矩阵的探针编号保持一一对应；名称映射只作为注释，不复制统计行。"
        ))
        meaning_layout.addStretch(1)
        for page in (facts, samples, meaning):
            self.pages.addWidget(page)

    def _update_buttons(self) -> None:
        index = self.pages.currentIndex()
        last = self.pages.count() - 1
        self.back_button.setEnabled(index > 0)
        self.next_button.setVisible(index < last)
        self.done_button.setVisible(index == last)

    def _next(self) -> None:
        self.pages.setCurrentIndex(min(self.pages.count() - 1, self.pages.currentIndex() + 1))
        self._update_buttons()

    def _previous(self) -> None:
        self.pages.setCurrentIndex(max(0, self.pages.currentIndex() - 1))
        self._update_buttons()


class ImportPage(QWidget):
    """阶段 5 导入/显式整理页；不直接修改用户选中的源文件。"""

    matrixReady = Signal(object)
    projectOpenRequested = Signal(str)
    stepAvailabilityChanged = Signal(int, bool)
    workflowStepRequested = Signal(int)
    _queuedProgress = Signal(int, object)
    _queuedSuccess = Signal(int, object)
    _queuedFailure = Signal(int, str)
    _queuedCancelled = Signal(int)
    _queuedThreadFinished = Signal(int, object, object)

    def __init__(self, parent: QWidget | None = None, *, project_root: Path | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.scanner = AssetScanner()
        self.preparer = PreparationService()
        self.project_root = project_root or Path.home() / "Documents" / "RNA-Seq Helper Projects"
        self.session: WizardSession | None = None
        self.reference_path: Path | None = None
        self.tenx_bundle: TenXBundle | None = None
        self.tenx_manifest_path: Path | None = None
        self.geo_matrix: GeoSeriesMatrix | None = None
        self.assets: tuple[DataAsset, ...] = ()
        self.selected_asset: DataAsset | None = None
        self._judgement_asset: DataAsset | None = None
        self._recommended_asset_id: str | None = None
        self._active_thread: QThread | None = None
        self._active_worker: ImportTaskWorker | None = None
        self._external_cancel = None
        self._task_generation = 0
        self._task_success = None
        self._task_name = ""
        self._archive_root: Path | None = None
        self._pending_reference_path: Path | None = None
        self._queuedProgress.connect(self._on_import_progress, Qt.ConnectionType.QueuedConnection)
        self._queuedSuccess.connect(self._on_task_success, Qt.ConnectionType.QueuedConnection)
        self._queuedFailure.connect(self._on_task_failure, Qt.ConnectionType.QueuedConnection)
        self._queuedCancelled.connect(self._on_task_cancelled, Qt.ConnectionType.QueuedConnection)
        self._queuedThreadFinished.connect(self._on_task_thread_finished, Qt.ConnectionType.QueuedConnection)
        self._build_ui()

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt API
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.load_paths(paths)
            event.acceptProposedAction()
        else:
            event.ignore()

    def _build_legacy_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)
        title = QLabel("导入表达矩阵")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        layout.addWidget(title)
        layout.addWidget(QLabel("第 1 步选择文件，第 2 步确认整理；软件只读取原文件，结果保存到独立项目目录。"))

        self.step_tabs = QTabWidget()
        self.step_tabs.setDocumentMode(True)
        import_panel = QWidget()
        import_layout = QVBoxLayout(import_panel)
        import_layout.setContentsMargins(12, 12, 12, 12)
        import_layout.setSpacing(10)
        organize_panel = QWidget()
        organize_layout = QVBoxLayout(organize_panel)
        organize_layout.setContentsMargins(12, 12, 12, 12)
        organize_layout.setSpacing(10)
        self.organize_tabs = QTabWidget()
        self.organize_tabs.setDocumentMode(True)
        facts_panel = QWidget()
        facts_layout = QVBoxLayout(facts_panel)
        facts_layout.setContentsMargins(8, 8, 8, 8)
        facts_layout.setSpacing(10)
        roles_panel = QWidget()
        roles_layout = QVBoxLayout(roles_panel)
        roles_layout.setContentsMargins(12, 12, 12, 12)
        roles_layout.setSpacing(16)
        self.organize_tabs.addTab(facts_panel, "2.1 确认数据事实")
        self.organize_tabs.addTab(roles_panel, "2.2 设置列角色与预览")
        organize_layout.addWidget(self.organize_tabs, 1)
        self.step_tabs.addTab(import_panel, "1 选择并查看文件")
        self.step_tabs.addTab(organize_panel, "2 整理并确认")
        layout.addWidget(self.step_tabs, 1)

        top = QHBoxLayout()
        top.setSpacing(10)
        self.choose_button = QPushButton("选择文件")
        self.choose_button.clicked.connect(self.choose_file)
        self.choose_10x_button = QPushButton("选择 10x 目录")
        self.choose_10x_button.clicked.connect(self.choose_10x_directory)
        self.file_label = QLabel("尚未选择文件")
        top.addWidget(self.choose_button)
        top.addWidget(self.choose_10x_button)
        top.addWidget(self.file_label, 1)
        import_layout.addLayout(top)

        reference_row = QHBoxLayout()
        reference_row.setSpacing(10)
        self.reference_button = QPushButton("选择参考表（补充 gene symbol，可选）")
        self.reference_button.clicked.connect(self.choose_reference)
        self.reference_label = QLabel("未选择；将保留原始特征编号")
        self.reference_button.setToolTip(
            "参考表只负责把 feature/probe 编号补充成 gene symbol，不是表达矩阵。"
        )
        reference_row.addWidget(self.reference_button)
        reference_row.addWidget(self.reference_label, 1)
        import_layout.addLayout(reference_row)

        self.sheet_combo = QComboBox()
        self.sheet_combo.currentTextChanged.connect(self.sheet_changed)
        self.previous_sheet_button = QPushButton("‹ 上一张")
        self.previous_sheet_button.clicked.connect(lambda: self._change_sheet(-1))
        self.next_sheet_button = QPushButton("下一张 ›")
        self.next_sheet_button.clicked.connect(lambda: self._change_sheet(1))
        for button in (self.previous_sheet_button, self.next_sheet_button):
            button.setFixedWidth(94)
            button.setVisible(False)
        sheet_row = QHBoxLayout()
        sheet_row.setSpacing(10)
        sheet_row.addWidget(self.sheet_combo, 1)
        sheet_row.addWidget(self.previous_sheet_button)
        sheet_row.addWidget(self.next_sheet_button)
        self.sheet_summary = QLabel("选择文件后显示工作表说明。")
        self.sheet_summary.setWordWrap(True)
        self.auto_judgement = QLabel(
            "选好文件后，这里会显示软件建议；如果和原始说明不一样，请改下拉框。"
        )
        self.auto_judgement.setWordWrap(True)
        self.auto_judgement.setStyleSheet("color: #245; padding: 4px 0;")
        self.organize_auto_judgement = QLabel(
            "选好文件后，这里会显示软件建议；如果和原始说明不一样，请改下拉框。"
        )
        self.organize_auto_judgement.setWordWrap(True)
        self.organize_auto_judgement.setStyleSheet("color: #245; padding: 4px 0;")
        self.current_thumbnail = QLabel()
        self.current_thumbnail.setFixedHeight(126)
        self.current_thumbnail.setToolTip("当前表格的离线缩略图；只显示少量单元格，不代替全量验证")
        self.transposed_thumbnail = QLabel()
        self.transposed_thumbnail.setFixedHeight(126)
        self.transposed_thumbnail.setToolTip("转置后表格的离线缩略图；仅用于方向确认")
        thumbnail_row = QHBoxLayout()
        thumbnail_row.addWidget(self.current_thumbnail, 1)
        thumbnail_row.addWidget(self.transposed_thumbnail, 1)
        self.tenx_preview = QLabel("选择 10x 目录后显示稀疏矩阵预览。")
        self.tenx_preview.setWordWrap(True)
        self.tenx_preview.setVisible(False)
        self.tenx_wizard_button = QPushButton("查看 10x 导入向导")
        self.tenx_wizard_button.setEnabled(False)
        self.tenx_wizard_button.clicked.connect(self.show_tenx_wizard)
        self.geo_wizard_button = QPushButton("查看 GEO 导入向导")
        self.geo_wizard_button.setEnabled(False)
        self.geo_wizard_button.clicked.connect(self.show_geo_wizard)
        self.header_spin = QSpinBox()
        self.header_spin.setMinimum(1)
        self.header_spin.setMaximum(1000)
        self.header_spin.valueChanged.connect(self.header_changed)
        self.data_start_spin = QSpinBox()
        self.data_start_spin.setMinimum(2)
        self.data_start_spin.setMaximum(1000000)
        self.data_start_spin.valueChanged.connect(self.controls_changed)
        self.measurement_combo = QComboBox()
        for value, label in (
            (MeasurementType.UNKNOWN, "未确认（先看提示）"),
            (MeasurementType.RAW_COUNT, "原始 count（原始计数）"),
            (MeasurementType.TPM, "TPM"),
            (MeasurementType.FPKM, "FPKM"),
            (MeasurementType.RPKM, "RPKM"),
            (MeasurementType.CPM, "CPM"),
            (MeasurementType.OTHER_NORMALIZED, "其他标准化值（如芯片信号）"),
        ):
            self.measurement_combo.addItem(label, value.value)
        self.measurement_combo.currentIndexChanged.connect(self.controls_changed)
        self.scale_combo = QComboBox()
        for value, label in (
            (ValueScale.UNKNOWN, "未确认（先看提示）"),
            (ValueScale.LINEAR, "没取 log（原始/线性）"),
            (ValueScale.LOG2, "已取 log2"),
            (ValueScale.OTHER_TRANSFORM, "其他变换（ln/log10/z-score）"),
        ):
            self.scale_combo.addItem(label, value.value)
        self.scale_combo.currentIndexChanged.connect(self.controls_changed)
        for combo in (self.sheet_combo, self.measurement_combo, self.scale_combo):
            combo.setFixedHeight(34)
        self.measurement_combo.setToolTip(
            "先看数据说明：每个数值是原始 count、TPM/FPKM/RPKM/CPM，还是芯片信号？"
        )
        self.scale_combo.setToolTip(
            "再看数据说明有没有写 log2、ln、log10 或 z-score；不能只看数字长相。"
        )
        self.transpose_check = QCheckBox("转置表格（把行列互换）")
        self.transpose_check.setMinimumHeight(40)
        self.transpose_check.stateChanged.connect(self.orientation_changed)
        for field in (
            self.sheet_combo,
            self.header_spin,
            self.data_start_spin,
            self.measurement_combo,
            self.scale_combo,
        ):
            field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        form = QGridLayout()
        form.setHorizontalSpacing(14)
        # 事实确认是给新手看的表单；行与行之间要有明显留白，避免看成一条
        # 连续的长选择条。控件本身保持统一高度，靠间距建立视觉分组。
        form.setVerticalSpacing(16)
        form.setContentsMargins(10, 10, 10, 10)
        form.setColumnMinimumWidth(0, 170)
        form.setColumnStretch(1, 1)
        form.addWidget(QLabel("工作表"), 0, 0)
        form.addLayout(sheet_row, 0, 1)
        form.addWidget(QLabel("表头所在行"), 1, 0)
        form.addWidget(self.header_spin, 1, 1)
        form.addWidget(QLabel("数据开始行"), 2, 0)
        form.addWidget(self.data_start_spin, 2, 1)
        form.addWidget(QLabel("每个格子代表什么"), 3, 0)
        form.addWidget(self.measurement_combo, 3, 1)
        form.addWidget(QLabel("有没有取过 log"), 4, 0)
        form.addWidget(self.scale_combo, 4, 1)
        form.addWidget(QLabel("方向修正"), 5, 0)
        form.addWidget(self.transpose_check, 5, 1)
        settings = QGroupBox("请确认数据事实")
        settings.setLayout(form)
        settings.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        settings.setMinimumHeight(285)
        settings.setMaximumHeight(315)
        facts_layout.addWidget(settings)
        hint_box = QGroupBox("小白提示：先看这里")
        hint_layout = QVBoxLayout(hint_box)
        hint_layout.addWidget(QLabel(
            "先找数据说明，再按下面的例子选择；看不到说明时不要凭数字长相猜。"
        ))
        self.facts_hint = BeginnerHintTextEdit()
        self.facts_hint.setPlainText(
            "先只回答两个问题；看不到数据说明时不能靠猜：\n"
            "1. 表里的数字是什么？是原始 count、TPM/FPKM/RPKM/CPM，还是芯片信号？\n"
            "2. 数字有没有取过对数？说明里有没有写 log2、ln 或 log10？\n\n"
            "CSV、TSV、TXT、XLS、XLSX 是文件格式，只说明“数据装在哪里”；GEO Series Matrix 是 GEO 的文件类型。\n"
            "它们都不能直接说明数字是什么，也不能说明数字有没有取 log。请看论文 Methods、GEO 的 data processing 或文件注释。\n\n"
            "【照着选】\n"
            "① 说明写 gene counts/原始 count、raw counts、read counts\n"
            "   选：原始 count + 没取 log（原始/线性）\n"
            "   软件：DESeq2。只有真正的原始 count 才能这样选；TPM、FPKM、CPM、RPKM 不能冒充 count。\n\n"
            "② 说明写 TPM、FPKM、CPM 或 RPKM，没有写 log\n"
            "   选：对应单位 + 没取 log（原始/线性）\n"
            "   软件：limma；软件会按固定规则做 log2(x+1)。\n\n"
            "③ 说明写芯片 signal intensity、probe intensity、normalized expression，\n"
            "   但没有写具体公式\n"
            "   选：其他标准化值 + 没取 log（原始/线性）\n"
            "   软件：limma；软件会按固定规则做 log2(x+1)。\n\n"
            "④ 说明写 log2(TPM)、log2(TPM+1)、log2 expression，或明确写 log2(...)\n"
            "   选：能看出原单位就选原单位，看不出就选其他标准化值；再选“已取 log2”\n"
            "   软件：limma；不会再重复取 log2。\n\n"
            "⑤ 说明写 ln、log10、z-score、residual/残差，或只写 transformed/normalized 但没写公式\n"
            "   选：其他标准化值 + 其他变换（ln/log10/z-score）\n"
            "   不要猜。当前版本不会把这些值假装成原始 count 或 log2 表达。\n\n"
            "【参考表是干什么的】\n"
            "参考表不是表达矩阵，也不参与差异分析；它只把行名（feature/probe ID）补成 gene symbol。\n"
            "它不会改表达数值、样本数或行数；没有匹配上的编号会保留，多个 symbol 会保留在同一个编号下。\n"
            "GEO 里 GSE 是数据集，GPL 是检测平台。行名如果是 ILMN_...，要选同平台、同物种的 GPL 表。\n"
            "例如 GSE32707 使用 GPL10558_HumanHT-12_V4_0_R1_15002873_B.txt.gz。\n"
            "可选格式：CSV、TSV、TXT、XLS、XLSX、SOFT、ANNOT、BGX，或这些文本表的 .gz 压缩文件。\n"
            "表里应有 feature/probe ID 和 gene symbol 两类列。不要选 gene list、差异结果、分组表、FASTQ/BAM，\n"
            "也不要选不同平台或不同物种的注释表。没有合适参考表时仍可分析，只是结果会使用原始编号。\n\n"
            "最后检查：表头、特征编号列、样本表达列、转置方向；再点击“应用整理并验证”。"
        )
        self.facts_hint.setReadOnly(True)
        self.facts_hint.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.facts_hint.setMinimumHeight(185)
        self.facts_hint.setMaximumHeight(220)
        self.facts_hint.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.facts_hint.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.facts_hint.setStyleSheet(
            "QPlainTextEdit { color: #29313a; background: #ffffff; "
            "border: 1px solid #c9d2dc; border-radius: 6px; padding: 8px; }"
        )
        hint_layout.addWidget(self.facts_hint)
        hint_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        hint_box.setMinimumHeight(270)
        hint_box.setMaximumHeight(290)
        facts_layout.addWidget(hint_box)
        facts_layout.addWidget(self.organize_auto_judgement)
        facts_layout.addStretch(1)
        import_layout.addWidget(self.sheet_summary)
        import_layout.addWidget(self.auto_judgement)
        import_layout.addLayout(thumbnail_row)
        import_layout.addWidget(self.tenx_preview)
        wizard_buttons = QHBoxLayout()
        wizard_buttons.addWidget(self.tenx_wizard_button)
        wizard_buttons.addWidget(self.geo_wizard_button)
        import_layout.addLayout(wizard_buttons)
        import_layout.addStretch(1)

        columns_box = QGroupBox("列角色（必须逐列确认）")
        columns_layout = QVBoxLayout(columns_box)
        columns_layout.setContentsMargins(14, 16, 14, 14)
        columns_layout.setSpacing(12)
        role_hint = QLabel("每列请选择一种用途：特征编号、样本表达、说明/注释或忽略。软件不会把说明列默认为样本列。")
        role_hint.setWordWrap(True)
        columns_layout.addWidget(role_hint)
        self.column_roles = QTableWidget(0, 3)
        self.column_roles.setHorizontalHeaderLabels(["原列名", "列角色", "数据示例"])
        self.column_roles.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.column_roles.setAlternatingRowColors(True)
        self.column_roles.verticalHeader().setVisible(False)
        self.column_roles.verticalHeader().setDefaultSectionSize(40)
        self.column_roles.horizontalHeader().setMinimumHeight(38)
        self.column_roles.setMinimumHeight(230)
        columns_layout.addWidget(self.column_roles)
        roles_layout.addWidget(columns_box, 1)

        self.preview = QTableWidget()
        self.preview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview.setAlternatingRowColors(True)
        self.preview.verticalHeader().setDefaultSectionSize(34)
        self.preview.horizontalHeader().setMinimumHeight(36)
        self.preview.setMinimumHeight(210)
        roles_layout.addWidget(self.preview, 2)
        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        self.status_label = QLabel("先选择文件。")
        self.prepare_button = QPushButton("应用整理并验证")
        self.prepare_button.setEnabled(False)
        self.prepare_button.clicked.connect(self.finish_preparation)
        bottom.addWidget(self.status_label, 1)
        bottom.addWidget(self.prepare_button)
        roles_layout.addLayout(bottom)

    def _build_ui(self) -> None:
        """四步流程中的前两步：先看资产清单，再逐题确认表格。"""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        title = QLabel("加入并确认表达数据")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        layout.addWidget(title)
        layout.addWidget(QLabel("原文件只读；先选表达表，再确认基因编号、样本和数值说明。"))

        self.step_tabs = QStackedWidget()
        self.step_tabs.setObjectName("importStepStack")
        layout.addWidget(self.step_tabs, 1)

        import_panel = QWidget()
        import_page_layout = QVBoxLayout(import_panel)
        import_page_layout.setContentsMargins(0, 0, 0, 0)
        import_page_layout.setSpacing(8)
        import_body = QWidget()
        import_layout = QVBoxLayout(import_body)
        import_layout.setContentsMargins(4, 4, 4, 4)
        import_layout.setSpacing(10)
        drop_zone = QWidget()
        drop_zone.setObjectName("importDropZone")
        drop_zone.setStyleSheet(
            "#importDropZone { background:#ffffff; border:2px dashed #555; border-radius:10px; }"
        )
        drop_layout = QVBoxLayout(drop_zone)
        drop_layout.setContentsMargins(16, 12, 16, 12)
        drop_layout.setSpacing(8)
        self.drop_hint = QLabel("把交付文件或文件夹拖到这里\n也可以点击下方按钮选择多个文件")
        self.drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_hint.setWordWrap(True)
        self.drop_hint.setStyleSheet("font-size:16px; font-weight:600; border:0;")
        drop_layout.addWidget(self.drop_hint)
        choices = QHBoxLayout()
        choices.addStretch(1)
        self.choose_button = QPushButton("选择文件（可多选）")
        self.choose_button.clicked.connect(self.choose_file)
        self.choose_10x_button = QPushButton("选择 10x 文件夹")
        self.choose_10x_button.clicked.connect(self.choose_10x_directory)
        choices.addWidget(self.choose_button)
        choices.addWidget(self.choose_10x_button)
        choices.addStretch(1)
        drop_layout.addLayout(choices)
        self.open_project_button = QPushButton("打开已保存项目")
        self.open_project_button.setToolTip(
            "会检查并读取已保存项目，不会重新分析。若发现上次分析写入中断，软件会先按事务记录恢复旧结果或清理未完成的临时文件；之后可核对或调整分组。点击“开始分析”会替换旧分析结果，不会覆盖原始输入文件。"
        )
        self.open_project_button.clicked.connect(self.choose_project)
        project_row = QHBoxLayout()
        project_row.addStretch(1)
        project_row.addWidget(self.open_project_button)
        project_row.addStretch(1)
        drop_layout.addLayout(project_row)
        import_layout.addWidget(drop_zone)

        self.file_label = QLabel("尚未添加文件")
        self.file_label.setWordWrap(True)
        import_layout.addWidget(self.file_label)
        self.asset_summary_label = QLabel(
            "软件会逐项说明哪些文件能用、哪些会忽略。若同时有原始 count 和 TPM，优先推荐原始 count；"
            "FASTQ/FQ 是原始测序文件，本版本不会直接分析。"
        )
        self.asset_summary_label.setWordWrap(True)
        import_layout.addWidget(self.asset_summary_label)
        self.asset_table = QTableWidget(0, 4)
        self.asset_table.setHorizontalHeaderLabels(["文件", "识别结果", "预览尺寸", "说明"])
        self.asset_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.asset_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.asset_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.asset_table.setAlternatingRowColors(True)
        self.asset_table.verticalHeader().setVisible(False)
        self.asset_table.setMinimumHeight(210)
        self.asset_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.asset_table.setWordWrap(True)
        self.asset_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.asset_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.asset_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.asset_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.asset_table.setColumnWidth(0, 235)
        self.asset_table.setColumnWidth(1, 175)
        self.asset_table.setColumnWidth(2, 120)
        self.asset_table.itemSelectionChanged.connect(self._asset_selection_changed)
        import_layout.addWidget(self.asset_table, 1)

        self.auto_judgement = QLabel("等待识别。")
        self.auto_judgement.setWordWrap(True)
        import_layout.addWidget(self.auto_judgement)
        self.tenx_preview = QLabel("")
        self.tenx_preview.setWordWrap(True)
        self.tenx_preview.setVisible(False)
        import_layout.addWidget(self.tenx_preview)
        special_actions = QHBoxLayout()
        self.tenx_wizard_button = QPushButton("查看 10x 对象说明")
        self.tenx_wizard_button.setEnabled(False)
        self.tenx_wizard_button.clicked.connect(self.show_tenx_wizard)
        self.geo_wizard_button = QPushButton("查看 GEO 样本说明")
        self.geo_wizard_button.setEnabled(False)
        self.geo_wizard_button.clicked.connect(self.show_geo_wizard)
        special_actions.addWidget(self.tenx_wizard_button)
        special_actions.addWidget(self.geo_wizard_button)
        special_actions.addStretch(1)
        import_layout.addLayout(special_actions)

        import_scroll = QScrollArea()
        import_scroll.setObjectName("importContentScroll")
        import_scroll.setWidgetResizable(True)
        import_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        import_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        import_scroll.setWidget(import_body)
        import_page_layout.addWidget(import_scroll, 1)

        import_footer = QHBoxLayout()
        self.status_label = QLabel("先添加交付文件。")
        self.status_label.setWordWrap(True)
        self.continue_button = QPushButton("整理所选表达表")
        self.continue_button.setEnabled(False)
        self.continue_button.clicked.connect(self._continue_with_selected_asset)
        import_footer.addWidget(self.status_label, 1)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancel_import)
        import_footer.addWidget(self.cancel_button)
        import_footer.addWidget(self.continue_button)
        import_page_layout.addLayout(import_footer)
        self.step_tabs.addWidget(import_panel)

        organize_panel = QWidget()
        organize_layout = QVBoxLayout(organize_panel)
        organize_layout.setContentsMargins(4, 4, 4, 4)
        organize_layout.setSpacing(8)
        self.question_label = QLabel("确认表格")
        self.question_label.setStyleSheet("font-size:17px; font-weight:700;")
        organize_layout.addWidget(self.question_label)
        self.organize_auto_judgement = QLabel("")
        self.organize_auto_judgement.setWordWrap(True)
        self.organize_auto_judgement.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum
        )
        organize_layout.addWidget(self.organize_auto_judgement)

        self.organize_tabs = QStackedWidget()
        self.organize_tabs.setObjectName("tableQuestions")
        self._question_titles = (
            "确认表格结构",
            "确认每个格子的数值",
            "确认基因编号与样本列",
        )
        layout_page = QWidget()
        structure_page_layout = QVBoxLayout(layout_page)
        structure_page_layout.setContentsMargins(12, 10, 12, 10)
        structure_page_layout.setSpacing(8)

        self.sheet_combo = QComboBox()
        self.sheet_combo.currentTextChanged.connect(self.sheet_changed)
        self.sheet_combo.setToolTip("XLS/XLSX 工作簿里的一张表；不同表可能放着不同类型的数据。")
        self.header_spin = QSpinBox()
        self.header_spin.setRange(1, 1000)
        self.header_spin.valueChanged.connect(self.header_changed)
        self.data_start_spin = QSpinBox()
        self.data_start_spin.setRange(2, 1_000_000)
        self.data_start_spin.valueChanged.connect(self.controls_changed)
        self.transpose_check = QCheckBox("行是样本、列是基因时勾选（交换行列）")
        self.transpose_check.stateChanged.connect(self.orientation_changed)
        for field in (self.sheet_combo, self.header_spin, self.data_start_spin):
            field.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            field.setFixedHeight(36)
        self.sheet_summary = QLabel("")
        self.sheet_summary.setWordWrap(True)
        self.structure_recommendation = QLabel("")
        self.structure_recommendation.setWordWrap(True)
        self.structure_why_toggle = QToolButton()
        self.structure_why_toggle.setText("为什么要核对表头和方向？")
        self.structure_why_toggle.setCheckable(True)
        self.structure_why_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.structure_why = QLabel(
            "表头行错了，样本名可能被当成数据；行列方向错了，软件可能把样本当基因。"
            "请对照下方预览检查编号、样本名和数值是否落在正确位置。"
        )
        self.structure_why.setWordWrap(True)
        self.structure_why.setVisible(False)
        self.structure_why_toggle.toggled.connect(self.structure_why.setVisible)

        self.structure_edit_toggle = QToolButton()
        self.structure_edit_toggle.setText("需要修改工作表、表头或方向？展开设置")
        self.structure_edit_toggle.setCheckable(True)
        self.structure_edit_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.structure_controls = QWidget()
        self.structure_controls.setVisible(False)
        structure_form = QGridLayout(self.structure_controls)
        structure_form.setContentsMargins(0, 0, 0, 0)
        structure_form.setHorizontalSpacing(14)
        structure_form.setVerticalSpacing(10)
        structure_form.setColumnMinimumWidth(0, 160)
        structure_form.setColumnStretch(1, 1)
        structure_form.addWidget(QLabel("工作表"), 0, 0)
        structure_form.addWidget(self.sheet_combo, 0, 1)
        structure_form.addWidget(QLabel("样本名称所在行（表头）"), 1, 0)
        structure_form.addWidget(self.header_spin, 1, 1)
        structure_form.addWidget(QLabel("第一行数据"), 2, 0)
        structure_form.addWidget(self.data_start_spin, 2, 1)
        structure_form.addWidget(QLabel("行列方向"), 3, 0)
        structure_form.addWidget(self.transpose_check, 3, 1)
        self.structure_edit_toggle.toggled.connect(self._toggle_structure_controls)

        structure_page_layout.addWidget(self.sheet_summary)
        structure_page_layout.addWidget(self.structure_recommendation)
        structure_page_layout.addWidget(self.structure_why_toggle)
        structure_page_layout.addWidget(self.structure_why)
        structure_page_layout.addWidget(self.structure_edit_toggle)
        structure_page_layout.addWidget(self.structure_controls)
        structure_page_layout.addStretch(1)
        self.organize_tabs.addWidget(layout_page)

        facts_page = QWidget()
        facts_layout = QVBoxLayout(facts_page)
        facts_layout.setContentsMargins(12, 10, 12, 10)
        facts_layout.setSpacing(10)
        self.measurement_combo = QComboBox()
        for value, label_text in (
            (MeasurementType.UNKNOWN, "请选择（需要看数据说明）"),
            (MeasurementType.RAW_COUNT, "原始 count（每个基因的读段计数）"),
            (MeasurementType.TPM, "TPM（每百万转录本）"),
            (MeasurementType.FPKM, "FPKM（按长度与测序量校正）"),
            (MeasurementType.RPKM, "RPKM（按长度与测序量校正）"),
            (MeasurementType.CPM, "CPM（每百万计数）"),
            (MeasurementType.OTHER_NORMALIZED, "其他表达值（如芯片信号）"),
        ):
            self.measurement_combo.addItem(label_text, value.value)
        self.measurement_combo.currentIndexChanged.connect(self.controls_changed)
        self.measurement_combo.setFixedHeight(38)
        self.measurement_combo.setToolTip("count 是原始读段计数；TPM/FPKM/RPKM/CPM 是经过换算的表达量。")
        self.scale_combo = QComboBox()
        for value, label_text in (
            (ValueScale.UNKNOWN, "请选择（需要看数据说明）"),
            (ValueScale.LINEAR, "没有取对数（原始/线性数值）"),
            (ValueScale.LOG2, "已取 log2（以 2 为底的对数）"),
            (ValueScale.OTHER_TRANSFORM, "其他变换（ln、log10、z-score 等）"),
        ):
            self.scale_combo.addItem(label_text, value.value)
        self.scale_combo.currentIndexChanged.connect(self.controls_changed)
        self.scale_combo.setFixedHeight(38)
        self.scale_combo.setToolTip("CSV/TSV/XLS/XLSX 只是文件格式；要看说明里是否写了 log2、ln、log10 或 z-score。")
        self.measurement_suggestion = QLabel("软件线索：尚未发现可靠的单位说明。")
        self.measurement_suggestion.setWordWrap(True)
        self.evidence_toggle = QToolButton()
        self.evidence_toggle.setText("查看识别依据与原文")
        self.evidence_toggle.setCheckable(True)
        self.evidence_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.evidence_scroll = QScrollArea()
        self.evidence_scroll.setObjectName("recognitionEvidenceScroll")
        self.evidence_scroll.setWidgetResizable(True)
        self.evidence_scroll.setMinimumHeight(100)
        self.evidence_scroll.setMaximumHeight(180)
        self.evidence_scroll.setWidget(self.measurement_suggestion)
        self.evidence_scroll.setVisible(False)
        self.evidence_toggle.toggled.connect(self.evidence_scroll.setVisible)
        self.evidence_toggle.toggled.connect(self._evidence_visibility_changed)
        self.use_evidence_button = QPushButton("确认并采用文件原文候选")
        self.use_evidence_button.setToolTip(
            "只会填入与当前表格/工作表关联、并显示了原文摘录的单位或尺度候选。"
            "点击表示你确认这些已显示的项目；没有证据的项目仍保持未确认。"
        )
        self.use_evidence_button.setVisible(False)
        self.use_evidence_button.clicked.connect(self._accept_text_evidence)
        self.short_fact_hint = QLabel(
            "请对照交付说明确认：每个格子的数值是什么、是否取过对数。仅看整数或小数长相不能判断。"
        )
        self.short_fact_hint.setWordWrap(True)
        facts_form = QGridLayout()
        facts_form.setContentsMargins(0, 0, 0, 0)
        facts_form.setVerticalSpacing(14)
        facts_form.setColumnMinimumWidth(0, 180)
        facts_form.setColumnStretch(1, 1)
        facts_form.addWidget(QLabel("每个格子的数值"), 0, 0)
        facts_form.addWidget(self.measurement_combo, 0, 1)
        facts_form.addWidget(QLabel("是否取过对数"), 1, 0)
        facts_form.addWidget(self.scale_combo, 1, 1)
        facts_layout.addLayout(facts_form)
        facts_layout.addWidget(self.use_evidence_button)
        facts_layout.addWidget(self.evidence_toggle)
        facts_layout.addWidget(self.evidence_scroll)
        facts_layout.addWidget(self.short_fact_hint)
        self.fact_explanation_toggle = QToolButton()
        self.fact_explanation_toggle.setText("为什么要确认？查看判断说明")
        self.fact_explanation_toggle.setCheckable(True)
        self.fact_explanation_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        facts_layout.addWidget(self.fact_explanation_toggle)
        self.facts_hint = BeginnerHintTextEdit()
        self.facts_hint.setPlainText(
            "先只回答两个问题；看不到说明时不能靠猜：\n"
            "1. 每个格子的数字是什么？gene counts/原始 count、TPM、FPKM、RPKM、CPM，还是芯片信号？\n"
            "2. 数字有没有取过对数？说明里有没有写 log2、ln 或 log10？\n\n"
            "CSV、TSV、TXT、XLS、XLSX 是文件格式，只说明数据装在哪里；GEO Series Matrix 是 GEO 文件类型。它们都不能说明数字的单位或是否取过 log。请看交付说明、论文 Methods 或 GEO 的 data processing。\n\n"
            "【照着选】\n"
            "① 说明写 gene counts/原始 count、raw counts、read counts：选“原始 count + 没取 log”。只有真正的原始整数计数才选这个，交给 DESeq2；TPM/FPKM/CPM/RPKM 不能冒充 count。\n\n"
            "② 说明写 TPM、FPKM、CPM 或 RPKM，且没有写 log：选对应单位 + “没取 log”。当前分析路径使用 limma，并按固定规则处理线性表达值。\n\n"
            "③ 说明写芯片 signal intensity、probe intensity 或 normalized expression，但没有具体公式：选“其他标准化值”。先按交付说明确认是否 log；不能凭数值大小判断。\n\n"
            "④ 说明明确写 log2(...)，例如 log2(TPM)、log2(TPM+1)、log2 expression：能看出原单位就选原单位，看不出选“其他标准化值”；尺度选“已取 log2”。log2(TPM+1) 里的 +1 是公式的一部分，不要重复取 log。\n\n"
            "⑤ 说明写 ln、log10、z-score、residual/残差，或只写 transformed/normalized 却没有公式：选“其他变换”。当前门禁不会把它假装成原始 count 或标准 log2 表达。\n\n"
            "【参考表是干什么的】\n"
            "参考表不是表达矩阵，也不参与差异计算；它只把行名（feature/probe ID）补成 gene symbol。不会改表达数值、样本数或行数；无法匹配的编号会保留。\n"
            "GEO 里的 GSE 是数据集，GPL 是检测平台。若行名是 ILMN_...，要选同一平台、同一物种的 GPL 注释表。例如 GSE32707 使用 GPL10558_HumanHT-12_V4_0_R1_15002873_B.txt.gz。\n"
            "参考表可用 CSV、TSV、TXT、XLS、XLSX、SOFT、ANNOT、BGX，或这些文本表的 .gz 压缩文件；表中要有 feature/probe ID 和 gene symbol 列。不要选 gene list、差异结果、分组表、FASTQ/BAM，或不同平台/物种的注释表。没有合适参考表时仍可分析，只是结果保留原始编号。\n\n"
            "【检查表格】\n"
            "表头行是样本名称所在行；第一行数据要在表头之后。特征编号是基因/探针 ID，样本列是每个样本的数值。样本数值列需至少两列；说明列可以设为注释或忽略。\n"
            "如果样本在行、基因在列，才勾选“转置表格”。\n"
            "最后检查：表头、特征编号列、样本表达列、转置方向；预览几行，确认编号、样本顺序和数值位置。"
        )
        self.facts_hint.setReadOnly(True)
        self.facts_hint.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.facts_hint.setMaximumHeight(170)
        self.facts_hint.setVisible(False)
        self.fact_explanation_toggle.toggled.connect(self.facts_hint.setVisible)
        facts_layout.addWidget(self.facts_hint)
        facts_layout.addStretch(1)
        self.organize_tabs.addWidget(facts_page)

        roles_page = QWidget()
        roles_layout = QVBoxLayout(roles_page)
        roles_layout.setContentsMargins(10, 8, 10, 8)
        roles_layout.setSpacing(8)
        # Compact windows scroll this page; wrapped guidance must retain its
        # measured height rather than being squeezed under the role editor.
        roles_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.role_hint = QLabel("逐列检查：哪列是基因编号，哪些列是样本数值；说明列可标为注释或忽略。")
        self.role_hint.setWordWrap(True)
        self.role_hint.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        roles_layout.addWidget(self.role_hint)
        self.roles_edit_toggle = QToolButton()
        self.roles_edit_toggle.setText("需要修改列用途？展开逐列设置")
        self.roles_edit_toggle.setCheckable(True)
        self.roles_edit_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        roles_layout.addWidget(self.roles_edit_toggle)
        self.roles_why_toggle = QToolButton()
        self.roles_why_toggle.setText("为什么要检查每列用途？")
        self.roles_why_toggle.setCheckable(True)
        self.roles_why_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        roles_layout.addWidget(self.roles_why_toggle)
        self.roles_why = QLabel(
            "统计分析只应读取样本表达数值。基因编号用于标识行；基因名称、功能描述等是注释；"
            "把注释或编号误设为样本，会让分析结果失真。"
        )
        self.roles_why.setWordWrap(True)
        self.roles_why.setVisible(False)
        self.roles_why_toggle.toggled.connect(self.roles_why.setVisible)
        self.roles_editor = QWidget()
        self.roles_editor.setVisible(False)
        roles_editor_layout = QVBoxLayout(self.roles_editor)
        roles_editor_layout.setContentsMargins(0, 0, 0, 0)
        self.column_roles = QTableWidget(0, 3)
        self.column_roles.setHorizontalHeaderLabels(["原列名", "列用途", "数值示例"])
        self.column_roles.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.column_roles.setAlternatingRowColors(True)
        self.column_roles.verticalHeader().setVisible(False)
        self.column_roles.verticalHeader().setDefaultSectionSize(34)
        self.column_roles.horizontalHeader().setMinimumHeight(36)
        self.column_roles.setMinimumHeight(145)
        self.column_roles.setMaximumHeight(245)
        roles_editor_layout.addWidget(self.column_roles)
        roles_layout.addWidget(self.roles_editor, 1)
        self.roles_edit_toggle.toggled.connect(self._toggle_roles_editor)
        self.organize_tabs.addWidget(roles_page)
        self.organize_layout_index = 0
        self.organize_facts_index = 1
        self.organize_roles_index = 2

        self.current_thumbnail = QLabel()
        self.current_thumbnail.setVisible(False)
        self.transposed_thumbnail = QLabel()
        self.transposed_thumbnail.setVisible(False)
        self.previous_sheet_button = None
        self.next_sheet_button = None

        preview_box = QGroupBox("表格预览（抽看前几行）")
        preview_layout = QVBoxLayout(preview_box)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        self.preview = QTableWidget()
        self.preview.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.preview.setAlternatingRowColors(True)
        self.preview.verticalHeader().setVisible(False)
        self.preview.horizontalHeader().setMinimumHeight(34)
        self.preview.setMinimumHeight(145)
        self.preview.setMaximumHeight(215)
        self.preview.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.preview.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.preview.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        preview_layout.addWidget(self.preview)

        organize_content = QWidget()
        content_layout = QVBoxLayout(organize_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)
        content_layout.addWidget(self.organize_tabs)
        content_layout.addWidget(preview_box)
        content_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setObjectName("organizeContentScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setWidget(organize_content)
        organize_layout.addWidget(scroll, 1)

        reference_row = QHBoxLayout()
        self.reference_button = QPushButton("可选：选择参考表补 gene symbol")
        self.reference_button.clicked.connect(self.choose_reference)
        self.reference_label = QLabel("未选；会保留原始基因编号")
        self.reference_label.setWordWrap(True)
        self.reference_button.setToolTip("gene symbol 是常见基因名称；参考表只做编号映射，不参与差异计算。")
        reference_row.addWidget(self.reference_button)
        reference_row.addWidget(self.reference_label, 1)
        organize_layout.addLayout(reference_row)

        self.organize_status_label = QLabel("")
        self.organize_status_label.setWordWrap(True)
        organize_layout.addWidget(self.organize_status_label)
        footer = QHBoxLayout()
        self.back_button = QPushButton("返回文件清单")
        self.back_button.clicked.connect(self._back_question)
        self.back_button.setEnabled(False)
        footer.addWidget(self.back_button)
        footer.addStretch(1)
        self.organize_cancel_button = QPushButton("取消")
        self.organize_cancel_button.setVisible(False)
        self.organize_cancel_button.clicked.connect(self.cancel_import)
        footer.addWidget(self.organize_cancel_button)
        self.prepare_button = QPushButton("继续：确认数值")
        self.prepare_button.setEnabled(False)
        self.prepare_button.clicked.connect(self.advance_question)
        footer.addWidget(self.prepare_button)
        organize_layout.addLayout(footer)
        self.step_tabs.addWidget(organize_panel)
        self.step_tabs.setCurrentIndex(0)

    def show_workflow_step(self, step: int) -> None:
        """主窗口四步导航的前两步映射到本页的两个顺序面板。"""
        if step not in (0, 1):
            return
        if step == 1 and self.session is None:
            self.stepAvailabilityChanged.emit(1, False)
            self.status_label.setText("先选择一个可分析的表达表格。")
            return
        self.step_tabs.setCurrentIndex(step)
        if step == 1:
            self._update_question_state()

    @Slot()
    def advance_question(self) -> None:
        if self.session is None:
            return
        index = self.organize_tabs.currentIndex()
        if index < self.organize_tabs.count() - 1:
            self.organize_tabs.setCurrentIndex(index + 1)
            self._update_question_state()
            return
        self.finish_preparation()

    @Slot()
    def _back_question(self) -> None:
        index = self.organize_tabs.currentIndex()
        if index > 0:
            self.organize_tabs.setCurrentIndex(index - 1)
            self._update_question_state()
        else:
            self.workflowStepRequested.emit(0)

    @staticmethod
    def _prepare_file_dialog(dialog: QFileDialog) -> None:
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        for model in dialog.findChildren(QFileSystemModel):
            model.setOption(QFileSystemModel.Option.DontWatchForChanges, True)
        file_name_edit = dialog.findChild(QLineEdit, "fileNameEdit")
        if file_name_edit is not None:
            file_name_edit.setCompleter(None)

    @Slot()
    def choose_file(self) -> None:
        dialog = QFileDialog(
            self,
            "选择交付文件（可多选）",
            str(Path.home()),
        )
        dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        dialog.setNameFilter(
            "常见文件 (*.csv *.tsv *.txt *.tab *.xls *.xlsx *.xlsm *.zip *.tar *.tar.gz *.tgz *.gz *.fastq *.fq *.bam *.sam *.pdf);;所有文件 (*)"
        )
        self._prepare_file_dialog(dialog)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.load_paths(tuple(Path(path) for path in dialog.selectedFiles()))

    @Slot()
    def choose_project(self) -> None:
        dialog = QFileDialog(self, "打开已保存的 RNA-Seq Helper 项目", str(self.project_root))
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        self._prepare_file_dialog(dialog)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selectedFiles():
            self.projectOpenRequested.emit(dialog.selectedFiles()[0])

    @Slot()
    def choose_10x_directory(self) -> None:
        dialog = QFileDialog(self, "选择包含 10x 三件套的目录", str(Path.home()))
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        self._prepare_file_dialog(dialog)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            paths = dialog.selectedFiles()
            if paths:
                self.load_paths((Path(paths[0]),))

    @Slot()
    def choose_reference(self) -> None:
        dialog = QFileDialog(
            self,
            "选择本地基因注释参考表",
            str(Path.home()),
        )
        dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        dialog.setNameFilter("参考表 (*.csv *.tsv *.txt *.xls *.xlsx *.xlsm *.soft *.annot *.bgx *.gz);;所有文件 (*)")
        self._prepare_file_dialog(dialog)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selectedFiles():
            self.reference_path = Path(dialog.selectedFiles()[0])
            self.reference_label.setText(str(self.reference_path))
            if self.session is not None:
                self.session = replace(self.session, reference_path=self.reference_path)

    def load_path(self, path: Path) -> None:
        """兼容旧调用；实际扫描统一走支持多文件的异步入口。"""
        self.load_paths((path,))

    def load_paths(self, paths: tuple[Path, ...] | list[Path]) -> None:
        if self._active_thread is not None:
            self.status_label.setText("当前任务仍在结束；请等取消完成后再重新导入。")
            return
        selected = tuple(dict.fromkeys(Path(path).expanduser() for path in paths))
        if not selected:
            return
        self.session = None
        self.assets = ()
        self.selected_asset = None
        self.tenx_preview.setVisible(False)
        self.tenx_bundle = None
        self.tenx_manifest_path = None
        self.geo_matrix = None
        self.reference_path = None
        self.reference_label.setText("未选；会保留原始基因编号")
        self.tenx_wizard_button.setEnabled(False)
        self.geo_wizard_button.setEnabled(False)
        self.asset_table.setRowCount(0)
        self.file_label.setText("；".join(path.name for path in selected))
        self.auto_judgement.setText("正在检查所选文件；原始文件不会被修改。")
        self.step_tabs.setCurrentIndex(0)
        self.continue_button.setEnabled(False)
        self.stepAvailabilityChanged.emit(1, False)

        def scan(progress, cancelled):
            return self.scanner.scan(selected, progress=progress, cancelled=cancelled)

        self._start_background_task("正在检查文件", scan, self._scan_completed)

    def _start_background_task(self, label, task, on_success, *, cancellable: bool = True) -> None:
        if self._active_thread is not None:
            return
        self._task_generation += 1
        generation = self._task_generation
        thread = QThread(self)
        worker = ImportTaskWorker(task)
        self._active_thread = thread
        self._active_worker = worker
        self._task_success = on_success
        self._task_name = label
        worker.moveToThread(thread)
        thread.started.connect(worker.run, Qt.ConnectionType.QueuedConnection)
        worker.progress.connect(
            lambda event, current=generation: self._queuedProgress.emit(current, event),
            Qt.ConnectionType.DirectConnection,
        )
        worker.succeeded.connect(
            lambda result, current=generation: self._queuedSuccess.emit(current, result),
            Qt.ConnectionType.DirectConnection,
        )
        worker.failed.connect(
            lambda message, current=generation: self._queuedFailure.emit(current, message),
            Qt.ConnectionType.DirectConnection,
        )
        worker.cancelled.connect(
            lambda current=generation: self._queuedCancelled.emit(current),
            Qt.ConnectionType.DirectConnection,
        )
        for signal in (worker.succeeded, worker.failed, worker.cancelled):
            signal.connect(thread.quit, Qt.ConnectionType.QueuedConnection)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda current=generation, current_thread=thread, current_worker=worker:
            self._queuedThreadFinished.emit(current, current_thread, current_worker),
            Qt.ConnectionType.DirectConnection,
        )
        self._set_busy(True, cancellable=cancellable)
        self._set_status(label)
        thread.start()

    def _set_busy(self, busy: bool, *, cancellable: bool = True) -> None:
        self.choose_button.setEnabled(not busy)
        self.choose_10x_button.setEnabled(not busy)
        self.sheet_combo.setEnabled(not busy)
        self.header_spin.setEnabled(not busy)
        self.data_start_spin.setEnabled(not busy)
        self.measurement_combo.setEnabled(not busy)
        self.scale_combo.setEnabled(not busy)
        self.transpose_check.setEnabled(not busy)
        self.reference_button.setEnabled(not busy)
        self.continue_button.setEnabled(not busy and self._asset_can_open(self.selected_asset))
        self.back_button.setEnabled(not busy and self.session is not None)
        self.prepare_button.setEnabled(not busy and self._question_can_continue())
        self.open_project_button.setEnabled(not busy)
        show_cancel = busy and cancellable
        self.cancel_button.setEnabled(show_cancel)
        self.organize_cancel_button.setEnabled(show_cancel)
        self.cancel_button.setVisible(show_cancel)
        self.organize_cancel_button.setVisible(show_cancel)

    def _set_status(self, message: str) -> None:
        self.status_label.setToolTip("")
        self.organize_status_label.setToolTip("")
        self.status_label.setText(message)
        self.organize_status_label.setText(message)

    def _on_import_progress(self, generation: int, event: object) -> None:
        if generation != self._task_generation:
            return
        if isinstance(event, ScanProgress):
            if event.phase == "discover":
                message = f"正在列出文件（已发现 {event.completed} 项）"
            elif event.phase == "geo-read":
                message = f"正在读取 GEO 表格（已处理约 {event.completed:,} 行）：{event.path.name if event.path else ''}"
            elif event.total:
                path_name = event.path.name if event.path else ""
                message = f"正在检查 {event.completed}/{event.total} 个文件：{path_name}"
            else:
                message = "正在检查文件"
        elif isinstance(event, ImportProgress):
            if event.completed is not None and event.total:
                unit = f" {event.unit}" if event.unit else ""
                message = f"{event.phase} {event.completed:,}/{event.total:,}{unit}：{event.label}"
            elif event.completed is not None:
                message = f"{event.phase}（已读取约 {event.completed:,} 行）：{event.label}"
            else:
                message = event.phase + (f"：{event.label}" if event.label else "")
        else:
            message = str(event)
        if isinstance(event, ImportProgress):
            self._set_busy(True, cancellable=event.cancellable)
        self._set_status(message)

    def _on_task_success(self, generation: int, result: object) -> None:
        if generation != self._task_generation:
            return
        callback = self._task_success
        self._task_success = None
        if callback is not None:
            try:
                callback(result)
            except Exception as exc:  # noqa: BLE001 - 界面回调错误也要可见
                self._show_task_failure("导入", str(exc))

    def _on_task_failure(self, generation: int, message: str) -> None:
        if generation == self._task_generation:
            self._task_success = None
            self._show_task_failure(self._task_name, message)

    def _show_task_failure(self, task_name: str, detail: str) -> None:
        task = task_name.removeprefix("正在").strip() or "文件处理"
        lowered = detail.casefold()
        if "permission denied" in lowered or "access denied" in lowered:
            suggestion = "当前账户无法读取该位置；请检查文件权限或另选一个可访问的副本"
        elif "no such file" in lowered or "not found" in lowered:
            suggestion = "找不到所选文件；它可能已移动，请重新选择"
        elif "bad zip" in lowered or "not a zip" in lowered or "corrupt" in lowered:
            suggestion = "文件可能损坏或格式与扩展名不符；请用原软件打开并另存为受支持格式"
        elif "decode" in lowered or "codec" in lowered or "unicode" in lowered:
            suggestion = "文件编码无法识别；请另存为 UTF-8 CSV/TSV 后重试"
        elif "no space" in lowered or "disk full" in lowered:
            suggestion = "磁盘空间不足；请释放空间或选择其他可写入位置"
        elif "安全预览上限" in detail or "预览内容超过安全上限" in detail:
            suggestion = "表格预览行或说明内容异常宽；请删去无关列/超长说明，或另存为精简的 CSV/TSV 后重试"
        elif "field larger than field limit" in lowered:
            suggestion = "CSV/TXT 中有单个格子的文字过长；请删去超长说明，或另存为精简的 CSV/TSV 后重试"
        else:
            suggestion = "请检查文件是否完整、格式是否受支持以及当前账户是否有读取权限"
        self._set_status(f"{task}未完成：{suggestion}。原始文件未修改，可以修正后重试。")
        detail_tooltip = f"详细原因：{detail[:600]}" if detail else ""
        self.status_label.setToolTip(detail_tooltip)
        self.organize_status_label.setToolTip(detail_tooltip)

    def _on_task_cancelled(self, generation: int) -> None:
        if generation == self._task_generation:
            self._task_success = None
            self._set_status("已取消；原文件未修改。可以重新选择文件继续。")

    def _on_task_thread_finished(self, generation: int, thread: QThread, worker: ImportTaskWorker) -> None:
        if generation != self._task_generation or self._active_thread is not thread:
            return
        self._active_thread = None
        self._active_worker = None
        self._task_success = None
        self._set_busy(False)
        self._update_asset_action()
        self._update_question_state()

    @Slot()
    def cancel_import(self) -> None:
        if self._external_cancel is not None:
            self._external_cancel()
            self.cancel_button.setEnabled(False)
            self.organize_cancel_button.setEnabled(False)
            self._set_status("正在停止项目校验；不会启动新分析。若有中断事务，软件会按记录恢复……")
            return
        if self._active_worker is None:
            return
        self._active_worker.request_cancel()
        self.cancel_button.setEnabled(False)
        self.organize_cancel_button.setEnabled(False)
        self._set_status("正在取消；等待当前安全读写步骤结束……")

    def begin_external_check(self, cancel_callback) -> None:
        self._set_busy(True, cancellable=False)
        self._external_cancel = cancel_callback
        self.cancel_button.setText("取消打开项目")
        self.organize_cancel_button.setText("取消打开项目")
        self.cancel_button.setVisible(True)
        self.organize_cancel_button.setVisible(True)
        self.cancel_button.setEnabled(True)
        self.organize_cancel_button.setEnabled(True)

    def update_external_check(self, completed: int, total: int) -> None:
        mb_done = completed / (1024 * 1024)
        mb_total = total / (1024 * 1024)
        self._set_status(f"正在核验项目文件：{mb_done:.1f}/{mb_total:.1f} MB。可取消；不会重新运行分析。")

    def end_external_check(self, message: str | None = None) -> None:
        self._external_cancel = None
        self._set_busy(False)
        self.cancel_button.setText("取消")
        self.organize_cancel_button.setText("取消")
        self.cancel_button.setVisible(False)
        self.organize_cancel_button.setVisible(False)
        self.cancel_button.setEnabled(False)
        self.organize_cancel_button.setEnabled(False)
        if message:
            self._set_status(message)

    def _scan_completed(self, result: ScanResult) -> None:
        self.assets = result.assets
        self._render_assets()
        issues_text = "\n".join(
            f"未纳入：{issue.message_zh}（{issue.operation_zh}）"
            for issue in result.issues
        )
        if not self.assets:
            issue = issues_text or "没有发现可识别文件。"
            if result.cancelled:
                self._set_status(f"已停止；已检查 0 项。{issue}")
            else:
                self._set_status(issue)
            return
        usable = [asset for asset in self.assets if self._asset_can_open(asset)]
        ignored = sum(asset.kind == "AUXILIARY" for asset in self.assets)
        candidates = sum(asset.kind in {"TABLE", "GEO_SERIES_MATRIX", "TENX", "ARCHIVE"} for asset in self.assets)
        self.asset_summary_label.setText(
            f"已检查 {len(self.assets)} 项：{candidates} 个可继续检查的候选，{ignored} 个说明/图片文件已标为忽略。"
            + (f"\n扫描问题：\n{issues_text}" if issues_text else "")
        )
        if usable:
            self._select_recommended_asset()
            if result.cancelled:
                self._set_status(
                    f"扫描已停止；已完成 {len(self.assets)} 项。已完成的候选保留，可继续选择；未检查文件未纳入清单。"
                )
            elif self.selected_asset is None:
                self._set_status("发现多个同等优先候选；请在清单中明确点选要整理的表达表，不会自动取第一项。")
            else:
                self._set_status("清单中已高亮建议优先查看的候选；也可以点选其他表达表。")
        else:
            raw = any(asset.kind == "RAW_SEQUENCING" for asset in self.assets)
            message = (
                "检测到原始测序文件；本软件不支持 FASTQ/BAM/SAM 比对或定量，请向提供方索取表达矩阵。"
                if raw else "没有可分析的表达表格；可忽略说明文件，或重新选择 count/TPM 表格。"
            )
            self._set_status(
                f"扫描已停止；已完成 {len(self.assets)} 项。{message}"
                if result.cancelled else message
            )
        # 扫描取消后候选可保留用于选择；但第 2 步必须等表达表读取完成。
        if not any(asset.kind in {"TABLE", "GEO_SERIES_MATRIX"} for asset in self.assets):
            self.stepAvailabilityChanged.emit(1, False)

    @staticmethod
    def _asset_can_open(asset: DataAsset | None) -> bool:
        return asset is not None and asset.kind in {"TABLE", "GEO_SERIES_MATRIX", "TENX", "ARCHIVE", "REFERENCE"}

    def _asset_description(self, asset: DataAsset) -> str:
        if asset.kind == "RAW_SEQUENCING":
            return "原始测序文件；本软件不支持比对/定量"
        if asset.kind == "AUXILIARY":
            if any(path.suffix.lower() == ".pdf" for path in asset.source_paths):
                return "PDF 可作为交付说明留存查看；不会读取为表达矩阵"
            return "说明或图片可留存查看；不会读取为表达矩阵"
        if asset.kind == "REFERENCE":
            return "基因注释参考；不能当表达矩阵"
        if asset.kind == "ARCHIVE":
            return "压缩包；选择后先做安全检查"
        if asset.kind == "TENX":
            return "10x 细胞对象；不能当 bulk 样本"
        if asset.kind == "UNREADABLE":
            return "无法读取；请检查格式或文件是否损坏"
        if asset.kind == "UNKNOWN":
            return "用途不明；不会自动作为表达矩阵"
        if any("未替你任选" in item.basis for item in asset.evidence):
            return "含多张用途不明工作表；继续时需要你明确选择"
        hint = asset.measurement_hint
        if hint != MeasurementType.UNKNOWN:
            hint_name = {
                MeasurementType.RAW_COUNT: "原始 count",
                MeasurementType.TPM: "TPM",
                MeasurementType.FPKM: "FPKM",
                MeasurementType.RPKM: "RPKM",
                MeasurementType.CPM: "CPM",
                MeasurementType.OTHER_NORMALIZED: "其他连续表达值",
            }.get(hint, "表达值")
            return f"可读取表格；文字线索可能是 {hint_name}（尚未确认）"
        return "可读取表格；单位和变换仍需对照说明确认"

    @staticmethod
    def _asset_category(asset: DataAsset) -> str:
        return {
            "TABLE": "可分析表格候选",
            "GEO_SERIES_MATRIX": "GEO 表达表候选",
            "TENX": "原始测序/细胞对象",
            "REFERENCE": "参考表",
            "RAW_SEQUENCING": "原始测序文件（不支持）",
            "AUXILIARY": "说明或无关文件（忽略）",
            "ARCHIVE": "压缩包（待安全检查）",
            "UNREADABLE": "无法读取",
        }.get(asset.kind, "无法识别")

    def _render_assets(self) -> None:
        self._recommended_asset_id = None
        self.asset_table.setRowCount(len(self.assets))
        for row, asset in enumerate(self.assets):
            source = asset.source_paths[0] if asset.source_paths else Path("未知文件")
            name = source.name if source.is_file() else source.name + "/"
            shape = "—"
            if asset.shape_hint:
                if asset.kind == "TENX":
                    shape = f"{asset.shape_hint[0]} 特征 × {asset.shape_hint[1]} 细胞"
                else:
                    shape = f"预览 {asset.shape_hint[0]} 行 × {asset.shape_hint[1]} 列"
            description = self._asset_description(asset)
            self.asset_table.setItem(row, 0, QTableWidgetItem(name))
            self.asset_table.setItem(row, 1, QTableWidgetItem(self._asset_category(asset)))
            self.asset_table.setItem(row, 2, QTableWidgetItem(shape))
            self.asset_table.setItem(row, 3, QTableWidgetItem(description))
            for column in range(4):
                item = self.asset_table.item(row, column)
                if item is not None:
                    item.setToolTip("\n".join(str(path) for path in asset.source_paths))
        self._update_asset_action()

    def _select_recommended_asset(self) -> None:
        eligible = [(index, asset) for index, asset in enumerate(self.assets) if self._asset_can_open(asset)]
        if not eligible:
            return
        priority = {
            "TABLE": 40,
            "GEO_SERIES_MATRIX": 35,
            "TENX": 25,
            "ARCHIVE": 20,
            "REFERENCE": 10,
        }
        ranked = [
            (
                (100 if asset.measurement_hint == MeasurementType.RAW_COUNT else 0,
                 priority.get(asset.kind, 0), asset.confidence),
                index,
                asset,
            )
            for index, asset in eligible
        ]
        best_score = max(item[0] for item in ranked)
        winners = [item for item in ranked if item[0] == best_score]
        self.selected_asset = None
        self.asset_table.clearSelection()
        self.asset_table.setCurrentCell(-1, -1)
        if len(winners) != 1:
            self.auto_judgement.setText(
                f"初步判读：发现 {len(winners)} 个同等优先的可读候选，软件不会默认选第一个。"
                "请在下方点选你要整理的表格；其他文件仍留在清单中。"
            )
            self._update_asset_action()
            return
        _, row, asset = winners[0]
        self.selected_asset = asset
        self._recommended_asset_id = asset.asset_id
        category_item = self.asset_table.item(row, 1)
        if category_item is not None:
            category_item.setText(f"建议优先查看 · {self._asset_category(asset)}")
        self.asset_table.setCurrentCell(row, 0)
        self.asset_table.selectRow(row)
        count_tpm_sheet_advice = any("原始计数更适合当前统计模型" in item.basis for item in asset.evidence)
        if asset.measurement_hint == MeasurementType.RAW_COUNT or count_tpm_sheet_advice:
            reason = (
                "推荐理由：原始 count 通常更适合当前 RNA-seq 统计模型。"
                "如果这是同一工作簿中的 count/TPM 工作表比较，此处仅凭表名优先建议；仍请按交付说明核实。"
                if count_tpm_sheet_advice else
                "推荐理由：这是有 count 文本线索的候选；原始计数通常是 RNA-seq 差异分析的首选输入。"
                "这只是可撤销的导入建议，请仍以交付说明核实。"
            )
        else:
            reason = "这是当前最清楚的可读表达表候选；单位和变换仍须按交付说明确认。"
        self.auto_judgement.setText(
            f"优先查看：{asset.source_paths[0].name}。{reason}\n{self._asset_description(asset)}。"
        )

    @Slot()
    def _asset_selection_changed(self) -> None:
        row = self.asset_table.currentRow()
        self.selected_asset = self.assets[row] if 0 <= row < len(self.assets) else None
        if self._recommended_asset_id and (
            self.selected_asset is None or self.selected_asset.asset_id != self._recommended_asset_id
        ):
            for previous_row, asset in enumerate(self.assets):
                if asset.asset_id == self._recommended_asset_id:
                    previous_item = self.asset_table.item(previous_row, 1)
                    if previous_item is not None:
                        previous_item.setText(self._asset_category(asset))
                    break
            self._recommended_asset_id = None
        if self.selected_asset is not None:
            category_item = self.asset_table.item(row, 1)
            if category_item is not None and self.selected_asset.asset_id != self._recommended_asset_id:
                category_item.setText(f"当前选择 · {self._asset_category(self.selected_asset)}")
            if self.selected_asset.measurement_hint == MeasurementType.RAW_COUNT:
                reason = "该候选带有原始 count 线索，通常更适合差异分析；请与交付说明核对。"
            else:
                reason = "当前选择为可读表达表；软件不会按文件名或数字大小替你确认单位和变换。"
            self.auto_judgement.setText(
                f"当前点选：{self.selected_asset.source_paths[0].name}。{reason}\n"
                f"{self._asset_description(self.selected_asset)}。"
            )
        self._update_asset_action()

    def _update_asset_action(self) -> None:
        asset = self.selected_asset
        allowed = self._asset_can_open(asset)
        if hasattr(self, "continue_button"):
            self.continue_button.setEnabled(allowed and self._active_thread is None)
            if asset and asset.kind == "REFERENCE":
                self.continue_button.setText("将此文件设为参考表")
            elif asset and asset.kind == "ARCHIVE":
                self.continue_button.setText("安全检查并查看压缩包内容")
            else:
                self.continue_button.setText("整理所选表达表")

    @Slot()
    def _continue_with_selected_asset(self) -> None:
        asset = self.selected_asset
        if asset is None:
            return
        if asset.kind == "REFERENCE":
            self.reference_path = asset.source_paths[0]
            self.reference_label.setText(f"已选参考表：{self.reference_path.name}")
            self._set_status("参考表只用于补充 gene symbol；现在请点选表达表继续。")
        elif asset.kind == "ARCHIVE":
            self._expand_archive(asset)
        elif asset.kind == "TENX":
            self._load_tenx(asset)
        elif asset.kind in {"TABLE", "GEO_SERIES_MATRIX"}:
            self._load_expression_asset(asset, None)

    def _expand_archive(self, archive_asset: DataAsset) -> None:
        path = archive_asset.source_paths[0]
        root = self.project_root / f"{path.stem}-input-{uuid4().hex[:8]}"

        def task(progress, cancelled):
            created = not root.exists()
            try:
                progress(ImportProgress("正在检查压缩包安全清单"))
                manifest = ArchiveService().inspect(path)
                extracted = ArchiveService().extract_recursive(
                    manifest,
                    root,
                    progress=lambda done, total, member: progress(
                        ImportProgress("正在安全展开", done, total, member)
                    ),
                    cancelled=cancelled,
                )
                if cancelled():
                    raise ArchiveCancelled("已取消压缩包展开")
                nested = self.scanner.scan(extracted, progress=progress, cancelled=cancelled)
                if nested.cancelled:
                    raise ArchiveCancelled("已取消压缩包内容检查")
                return (root, archive_asset, nested)
            except Exception:
                if created and root.exists():
                    shutil.rmtree(root)
                raise

        self._start_background_task("正在安全检查压缩包", task, self._archive_expanded)

    def _archive_expanded(self, result) -> None:
        root, parent_asset, scan_result = result
        assets = []
        for asset in scan_result.assets:
            assets.append(replace(
                asset,
                parent_asset_id=parent_asset.asset_id,
                archive_member_paths=tuple(
                    str(source.relative_to(root)) for source in asset.source_paths if source.is_relative_to(root)
                ),
            ))
        self._archive_root = root
        self.assets = tuple(assets)
        self.selected_asset = None
        self._render_assets()
        self.asset_summary_label.setText(f"压缩包内共发现 {len(self.assets)} 个对象；请在清单中选择表达表，参考表不可作为表达矩阵。")
        self._select_recommended_asset()
        if self.selected_asset is None:
            self._set_status("压缩包已安全检查，但没有发现可分析表达表；FASTQ/BAM 原始文件不会被展开为表达矩阵。")
        else:
            self._set_status("已安全展开并完成内容清单；请核对候选后选择要整理的表格。")

    def _load_tenx(self, asset: DataAsset) -> None:
        directory = asset.source_paths[0].parent

        def task(progress, cancelled):
            progress(ImportProgress("正在检查 10x 矩阵组成"))
            bundle = TenXReader().find_bundle(directory)
            project = self.project_root / f"{directory.name}-10x-{uuid4().hex[:8]}"
            manifest_path = bundle.write_manifest(project / "tenx-manifest.json")
            return bundle, manifest_path

        self._start_background_task("正在检查 10x 对象", task, self._tenx_loaded)

    def _tenx_loaded(self, result) -> None:
        bundle, manifest_path = result
        self.tenx_bundle = bundle
        self.tenx_manifest_path = manifest_path
        type_summary = "；".join(f"{name}: {count} 行" for name, count in bundle.feature_type_counts.items())
        sparsity = 1.0 - bundle.nonzero_entries / max(1, bundle.rows * bundle.columns)
        self.tenx_preview.setText(
            f"识别到 {bundle.rows} 个特征 × {bundle.columns} 个细胞，稀疏度 {sparsity:.1%}；{type_summary}。"
            "这是单细胞对象，软件不会把细胞当作独立 bulk 样本；如做 bulk 分析，请使用供者级 pseudobulk。"
        )
        self.tenx_preview.setVisible(True)
        self.tenx_wizard_button.setEnabled(True)
        self._set_status("10x 对象检查完成；它不会进入 bulk 表达整理步骤。")

    def _load_expression_asset(self, asset: DataAsset, sheet_name: str | None) -> None:
        path = asset.source_paths[0]
        project = self.project_root / f"{path.stem}-{uuid4().hex[:8]}"

        def task(progress, cancelled):
            progress(ImportProgress("正在后台读取表格；大文件可随时取消"))
            sheets = (None,) if asset.kind == "GEO_SERIES_MATRIX" else self.preparer.reader.list_sheets(path)
            recommended = AssetScanner.recommended_sheet(sheets)
            selected_sheet = sheet_name if sheet_name in sheets else recommended
            if len(sheets) > 1 and selected_sheet is None:
                return asset, None, sheets, None
            session = self.preparer.start(
                asset,
                project,
                selected_sheet,
                preview_only=True,
                progress=lambda rows: progress(ImportProgress("正在读取表格", rows, None, path.name)),
                cancelled=cancelled,
            )
            if cancelled():
                raise ArchiveCancelled("已取消表格读取")
            measurement, scale, text_evidence = self.scanner.inspect_text_facts(
                path,
                session.raw_table.rows[:40],
                selected_sheet=selected_sheet,
                sheet_count=len(sheets),
            )
            retained_evidence = tuple(
                item for item in asset.evidence
                if item.fact_key not in {"measurement_type", "value_scale"}
                and not item.basis.startswith("文字线索提示可能")
            )
            loaded_asset = replace(
                asset,
                shape_hint=(session.raw_table.row_count, session.raw_table.column_count),
                measurement_hint=measurement,
                scale_hint=scale,
                evidence=retained_evidence + text_evidence,
            )
            session = replace(session, asset=loaded_asset)
            return loaded_asset, session, sheets, session.geo_matrix

        self._selected_expression_asset = asset
        self._pending_reference_path = self.reference_path
        self._start_background_task("正在准备表格预览", task, self._expression_loaded)

    def _expression_loaded(self, result) -> None:
        asset, session, sheets, geo = result
        if session is None:
            labels = [str(sheet) for sheet in sheets if sheet is not None]
            selected, accepted = QInputDialog.getItem(
                self,
                "请选择工作表",
                "这个工作簿有多张用途不明的工作表。软件不会默认取第一张，请选包含表达矩阵的工作表：",
                labels,
                0,
                False,
            )
            if accepted and selected:
                self._load_expression_asset(asset, selected)
            else:
                self._set_status("工作表尚未选择；未读取或整理任何一张表。可重新点选文件并选择工作表。")
            return
        self.selected_asset = asset
        self.session = session
        self.geo_matrix = geo
        self.sheet_combo.blockSignals(True)
        self.sheet_combo.clear()
        for sheet in sheets:
            self.sheet_combo.addItem(sheet or "文本文件")
        selected = session.recipe.sheet_name or "文本文件"
        selected_index = self.sheet_combo.findText(selected)
        if selected_index >= 0:
            self.sheet_combo.setCurrentIndex(selected_index)
        self.sheet_combo.blockSignals(False)
        self.reference_path = self._pending_reference_path
        self._pending_reference_path = None
        if self.reference_path is None:
            self.reference_label.setText("未选；会保留原始基因编号")
        else:
            self.reference_label.setText(f"已选参考表：{self.reference_path.name}")
        if geo is not None:
            self.geo_wizard_button.setEnabled(True)
            platforms = tuple(dict.fromkeys(geo.platform_ids))
            if platforms:
                self.reference_label.setText(f"可选：同平台 {', '.join(platforms)} 注释参考表")
        self.structure_edit_toggle.setChecked(False)
        self.roles_edit_toggle.setChecked(False)
        self.file_label.setText(asset.source_paths[0].name)
        self._apply_auto_judgement(asset)
        self.organize_tabs.setCurrentIndex(0)
        self.step_tabs.setCurrentIndex(1)
        self._refresh_controls()
        self.stepAvailabilityChanged.emit(1, True)
        self._update_question_state()
        self.status_label.setText("预览已就绪；候选线索不是已确认事实，请按数据说明完成必要问题。")
        self._update_action_state()

    @Slot()
    def show_tenx_wizard(self) -> None:
        if self.tenx_bundle is None or self.tenx_manifest_path is None:
            return
        dialog = TenXWizardDialog(self.tenx_bundle, self.tenx_manifest_path, self)
        dialog.exec()

    @Slot()
    def show_geo_wizard(self) -> None:
        if self.geo_matrix is None:
            return
        GeoWizardDialog(self.geo_matrix, self).exec()

    @Slot(int)
    def _change_sheet(self, offset: int) -> None:
        if self.sheet_combo.count() == 0:
            return
        target = max(0, min(self.sheet_combo.count() - 1, self.sheet_combo.currentIndex() + offset))
        if target != self.sheet_combo.currentIndex():
            self.sheet_combo.setCurrentIndex(target)

    @Slot(str)
    def sheet_changed(self, _sheet: str) -> None:
        if self.session is None:
            return
        selected = self.sheet_combo.currentText()
        selected = None if selected == "文本文件" else selected
        asset = self.session.asset
        if selected == self.session.recipe.sheet_name:
            return
        self._load_expression_asset(asset, selected)

    @Slot()
    def controls_changed(self, *_args: object) -> None:
        if self._judgement_asset is not None:
            self._render_auto_judgement(self._judgement_asset)
        if self.session is not None:
            self._refresh_sheet_summary()
            self._render_preview()
            self._update_action_state()

    @Slot(int)
    def orientation_changed(self, _state: int) -> None:
        if self.session is not None:
            patch = self._current_patch()
            rows = self.preparer._view_rows(self.session.raw_table.rows, bool(patch["transpose"]))
            width = max((len(row) for row in rows), default=0)
            sample_columns = self.preparer._numeric_columns(rows, int(patch["data_start_row"]), width)
            feature_column = self.preparer._feature_id_column(
                rows,
                int(patch["data_start_row"]),
                width,
                sample_columns,
            )
            patch.update({
                "feature_id_column": feature_column,
                "sample_columns": sample_columns,
                "annotation_columns": [index for index in range(width) if index not in sample_columns and index != feature_column],
            })
            self.session = replace(
                self.session,
                recipe=self.preparer._patch_recipe(self.session.recipe, patch),
            )
            self._populate_column_controls()
            self._refresh_sheet_summary()
            self._render_preview()
            self._update_action_state()

    @Slot(int)
    def header_changed(self, _value: int) -> None:
        """表头变化后同步列角色标签，避免继续显示旧表头。"""
        if self.session is not None:
            self.session = replace(
                self.session,
                recipe=self.preparer._patch_recipe(self.session.recipe, self._current_patch()),
            )
            self._populate_column_controls()
            self._refresh_sheet_summary()
            self._render_preview()
            self._update_action_state()

    def _refresh_controls(self) -> None:
        assert self.session is not None
        self.header_spin.blockSignals(True)
        self.header_spin.setValue(self.session.recipe.header_row + 1)
        self.header_spin.blockSignals(False)
        self.data_start_spin.blockSignals(True)
        self.data_start_spin.setValue(self.session.recipe.data_start_row + 1)
        self.data_start_spin.blockSignals(False)
        self.transpose_check.blockSignals(True)
        self.transpose_check.setChecked(self.session.recipe.transpose)
        self.transpose_check.blockSignals(False)
        self._populate_column_controls()
        self._refresh_sheet_summary()
        self._render_preview()
        self._update_action_state()

    def _apply_auto_judgement(self, asset: DataAsset) -> None:
        """显示有证据等级的候选判断，但不替用户确认单位或转换。"""
        self._judgement_asset = asset
        # 有原文候选时默认展示证据，保持一键确认前可见；未知输入默认折叠。
        self.evidence_toggle.setChecked(any(
            item.fact_key in {"measurement_type", "value_scale"} and item.excerpt
            for item in asset.evidence
        ))
        self.measurement_combo.setCurrentIndex(0)
        self.scale_combo.setCurrentIndex(0)
        self._render_auto_judgement(asset)

    @Slot(bool)
    def _evidence_visibility_changed(self, _expanded: bool) -> None:
        if self._judgement_asset is not None:
            self._render_auto_judgement(self._judgement_asset)

    @Slot()
    def _accept_text_evidence(self) -> None:
        """一次确认并填入有原文摘录支持的候选；缺证据的字段继续保持 UNKNOWN。"""
        asset = self._judgement_asset or (self.session.asset if self.session else None)
        if asset is None:
            return
        if asset.measurement_hint != MeasurementType.UNKNOWN:
            self.measurement_combo.setCurrentIndex(
                self.measurement_combo.findData(asset.measurement_hint.value)
            )
        if asset.scale_hint != ValueScale.UNKNOWN:
            self.scale_combo.setCurrentIndex(
                self.scale_combo.findData(asset.scale_hint.value)
            )

    def _render_auto_judgement(self, asset: DataAsset) -> None:
        measurement = asset.measurement_hint
        scale = asset.scale_hint
        measurement_labels = {
            MeasurementType.RAW_COUNT: "原始 count",
            MeasurementType.TPM: "TPM",
            MeasurementType.FPKM: "FPKM",
            MeasurementType.RPKM: "RPKM",
            MeasurementType.CPM: "CPM",
            MeasurementType.OTHER_NORMALIZED: "其他连续表达值",
        }
        scale_labels = {
            ValueScale.LINEAR: "原始/线性尺度",
            ValueScale.LOG2: "已取 log2",
            ValueScale.OTHER_TRANSFORM: "其他已知转换",
        }
        evidence_lines: list[str] = []
        fact_evidence = [
            item for item in asset.evidence
            if item.fact_key in {"measurement_type", "value_scale"} and item.excerpt
        ]
        candidate_facts = (
            ("measurement_type", measurement.value, MeasurementType.UNKNOWN.value),
            ("value_scale", scale.value, ValueScale.UNKNOWN.value),
        )
        supported_candidates = [
            (fact_key, candidate)
            for fact_key, candidate, unknown in candidate_facts
            if candidate != unknown
        ]
        display_evidence: list[Evidence] = []
        display_keys: set[tuple[str, str, str, bool]] = set()

        def safe_evidence_source(source: str, default: str) -> str:
            if not source:
                return default
            if may_contain_sensitive_metadata(source):
                return "[含疑似个人或样本标识的文件名已隐藏]"
            return Path(source).name

        def add_display_evidence(item: Evidence) -> None:
            key = (item.fact_key, item.fact_value, item.reported_transform, item.excerpt_redacted)
            if key not in display_keys and len(display_evidence) < 8:
                display_keys.add(key)
                display_evidence.append(item)

        for fact_key, candidate in supported_candidates:
            matching_candidate = [
                item for item in fact_evidence
                if item.fact_key == fact_key and item.fact_value == candidate
            ]
            preferred = next(
                (item for item in matching_candidate if item.reported_transform and not item.excerpt_redacted),
                None,
            )
            if preferred is None:
                preferred = next((item for item in matching_candidate if not item.excerpt_redacted), None)
            if preferred is None:
                preferred = next((item for item in matching_candidate if item.reported_transform), None)
            if preferred is None and matching_candidate:
                preferred = matching_candidate[0]
            if preferred is not None:
                add_display_evidence(preferred)
        for item in fact_evidence:
            add_display_evidence(item)

        for item in display_evidence:
            source = (
                "相关原文（来源路径已隐藏）"
                if item.excerpt_redacted
                else safe_evidence_source(item.source, "当前文件")
            )
            location = f" · {item.location}" if item.location and not item.excerpt_redacted else ""
            excerpt_kind = "脱敏摘录" if item.excerpt_redacted else "原文摘录"
            evidence_lines.append(f"• {excerpt_kind}候选：{source}{location}：“{item.excerpt}”")
        unlinked_notes = [
            item for item in asset.evidence
            if item.evidence_level in {
                "unlinked_sidecar", "sidecar_scan_skipped", "sidecar_scan_incomplete",
                "linked_sidecar_no_fact_text",
            }
        ]
        for item in unlinked_notes[:2]:
            source = "同目录说明文件" if item.source else "同目录"
            evidence_lines.append(f"• {item.basis}（{source}）")
        if len(display_evidence) < len(fact_evidence):
            evidence_lines.append(f"• 另有 {len(fact_evidence) - len(display_evidence)} 条文字候选未展开。")
        for item in asset.evidence:
            if item in fact_evidence or item in unlinked_notes:
                continue
            if item.evidence_level == "geo_processing_context":
                source = safe_evidence_source(item.source, "当前 GEO 文件")
                note = item.excerpt or "[没有可安全展示的说明内容]"
                evidence_lines.append(
                    f"• GEO 处理说明（{source} · {item.location}；{item.basis}）：“{note}”"
                )
                continue
            if not item.basis or "数值密度" in item.basis or item.basis == "扩展名与内容可读取":
                continue
            source = item.source.strip()
            if source and Path(source).is_absolute():
                source = safe_evidence_source(source, "当前文件")
            location = f"（来源/核查范围：{source}）" if source else ""
            evidence_lines.append(f"• {item.basis}{location}")
        candidates: list[str] = []
        if measurement != MeasurementType.UNKNOWN:
            candidates.append(f"单位候选：{measurement_labels.get(measurement, measurement.value)}")
        if scale != ValueScale.UNKNOWN:
            candidates.append(f"尺度候选：{scale_labels.get(scale, scale.value)}")
        has_conflicting_measurement = len({
            item.fact_value for item in fact_evidence if item.fact_key == "measurement_type"
        }) > 1
        has_conflicting_scale = len({
            item.fact_value for item in fact_evidence if item.fact_key == "value_scale"
        }) > 1
        if has_conflicting_measurement or has_conflicting_scale:
            verdict = "初步判读：文件里有互相冲突或涉及不同数据的文字线索，软件不会替你选；请核对当前表格对应的说明。"
            if candidates:
                verdict += "其他没有冲突的候选：" + "；".join(candidates) + "。"
        elif candidates:
            verdict = "初步判读：文件文字给出以下候选，尚未替你确认：" + "；".join(candidates) + "。"
        else:
            verdict = (
                "初步判读：这是可读取的表达表候选，但文件文字没有说明数值单位或转换；"
                "仅凭数值外观无法可靠区分原始 count、TPM/FPKM/CPM、芯片信号或是否取过 log。"
            )
        evidence_heading = (
            "\n识别依据（下面是原文摘录；仅作候选，仍需你确认）：\n"
            if fact_evidence else "\n识别依据（显示软件线索及核查范围，不代表原文摘录）：\n"
        )
        evidence_text = evidence_heading + (
            "\n".join(evidence_lines)
            if evidence_lines else "• 没有找到单位或转换的文字线索。"
        )

        selected_measurement = self.measurement_combo.currentData()
        selected_scale = self.scale_combo.currentData()
        reported_formulas = {
            item.reported_transform
            for item in fact_evidence
            if item.fact_key == "value_scale" and item.reported_transform
        }
        if selected_measurement == MeasurementType.UNKNOWN.value:
            if measurement != MeasurementType.UNKNOWN:
                label = measurement_labels.get(measurement, measurement.value)
                question = f"先对照交付说明确认：单位候选“{label}”是否符合这张表？"
            else:
                question = (
                    "先确认每个格子的数字代表什么。请在交付说明的“数据类型/表达矩阵/单位”中找"
                    " raw counts、TPM、FPKM 等说明。"
                )
        elif selected_scale == ValueScale.UNKNOWN.value:
            if scale != ValueScale.UNKNOWN:
                label = scale_labels.get(scale, scale.value)
                question = f"再对照交付说明确认：尺度候选“{label}”是否符合这张表？"
            else:
                question = (
                    "接着确认数字是否做过 log 转换。请在交付说明的“处理方法/转换公式”中找"
                    " log2、ln、log10 或具体公式。"
                )
        elif selected_scale == ValueScale.LOG2.value and len(reported_formulas) != 1:
            formula_status = "公式线索互相不一致" if len(reported_formulas) > 1 else "文件没有写完整公式或伪计数"
            question = (
                f"你已选 log2；{formula_status}。请查看交付说明/论文 Methods；"
                "软件不会反推或补造公式，缺失时会如实记录。"
            )
        else:
            question = "你已选择数值单位和尺度；请确保选择与数据提供方说明一致。"
        if (
            selected_measurement != MeasurementType.UNKNOWN.value
            and selected_scale != ValueScale.UNKNOWN.value
        ):
            confirmation_status = f"\n当前状态：{question}"
        else:
            confirmation_status = f"\n现在先确认一项：{question}"
        text = (
            verdict + evidence_text + confirmation_status
            + "\n只有尚未确认的事实会阻止开始分析；你仍可查看预览。不要靠数字大小猜单位或变换。"
        )
        self.auto_judgement.setText(text)
        summary = verdict if candidates or has_conflicting_measurement or has_conflicting_scale else (
            "识别摘要：可读取表达表；数值单位和变换尚未确认。"
        )
        self.organize_auto_judgement.setText(summary + confirmation_status)
        self.measurement_suggestion.setText(evidence_text.strip())
        self.use_evidence_button.setVisible(bool(fact_evidence))
        scan_incomplete = any(
            item.evidence_level in {"sidecar_scan_skipped", "sidecar_scan_incomplete"}
            for item in asset.evidence
        )
        can_confirm_all = self.evidence_toggle.isChecked() and bool(supported_candidates) and not scan_incomplete and all(
            any(
                item.fact_key == fact_key
                and item.fact_value == candidate
                and item.excerpt
                and not item.excerpt_redacted
                for item in display_evidence
            )
            for fact_key, candidate in supported_candidates
        )
        self.use_evidence_button.setEnabled(can_confirm_all)
        if scan_incomplete:
            self.use_evidence_button.setToolTip(
                "说明文件未能完整核查；为避免漏掉相互冲突的说法，不能一键采用候选。"
                "请检查交付说明后，在上方逐项手动确认。"
            )
        elif fact_evidence and supported_candidates and not can_confirm_all:
            self.use_evidence_button.setToolTip(
                "识别到了文字候选，但可引用内容包含可能的个人/样本信息，软件已隐藏原句；"
                "请查看交付说明后，在上方逐项手动确认。"
            )
        elif fact_evidence and not supported_candidates:
            self.use_evidence_button.setToolTip(
                "文件中的单位或尺度文字候选互相冲突；软件不会替你挑选。"
                "请对照交付说明，在上方逐项手动确认。"
            )
        else:
            self.use_evidence_button.setToolTip(
                "只会填入与当前表格/工作表关联、并显示了原文摘录的单位或尺度候选。"
                "点击表示你确认这些已显示的项目；没有证据的项目仍保持未确认。"
            )

    def _refresh_sheet_summary(self) -> None:
        if self.session is None:
            self.sheet_summary.setText("选择文件后显示工作表说明。")
            self._update_sheet_navigation()
            return
        raw = self.session.raw_table
        candidates = self.preparer.candidate_header_rows(raw.rows)
        selected = raw.sheet_name or "文本文件"
        sheet_note = ""
        if self.sheet_combo.count() > 1:
            sheet_note = f"；共 {self.sheet_combo.count()} 张表，可用上方下拉框逐张查看，不会自动拼接"
        data_start = max(0, self.data_start_spin.value() - 1)
        sample_count = len(self._role_columns()[1]) if self.column_roles.rowCount() else len(self.session.recipe.sample_columns)
        if raw.is_complete:
            feature_count = max(
                0,
                (raw.column_count if self.transpose_check.isChecked() else raw.row_count) - data_start,
            )
            shape_summary = f"按当前设置约 {feature_count:,} 个特征（如基因）× {sample_count} 个样本"
        else:
            shape_summary = (
                f"目前只读取了预览中的前 {raw.row_count:,} 行、最多 {raw.column_count:,} 列；"
                "完整特征数会在最终校验时统计"
            )
        self.sheet_summary.setText(
            f"当前工作表：{selected}；{shape_summary}。表头线索在第 "
            f"{', '.join(str(index + 1) for index in candidates) or '未找到'} 行附近"
            f"；尚未确认数值单位{sheet_note}。"
        )
        candidate_text = ", ".join(str(index + 1) for index in candidates[:3]) or "未找到"
        orientation = "样本在行、基因在列（已转置）" if self.transpose_check.isChecked() else "基因在行、样本在列"
        self.structure_recommendation.setText(
            f"软件建议：第 {self.header_spin.value()} 行是样本名称，第 {self.data_start_spin.value()} 行开始数据；"
            f"依据：前几行表头线索（第 {candidate_text} 行）和当前列值布局。当前方向：{orientation}。"
            "这只是结构建议，数值单位仍需根据交付说明确认。"
        )
        self._update_sheet_navigation()

    def _update_sheet_navigation(self) -> None:
        """工作表只通过同一尺寸的下拉框切换，不再显示上一张/下一张方块。"""
        return

    def _question_can_continue(self) -> bool:
        if self.session is None:
            return False
        question = self.organize_tabs.currentIndex()
        if question == 0:
            row_count = len(self.session.raw_table.rows)
            header = self.header_spin.value() - 1
            first_data = self.data_start_spin.value() - 1
            return 0 <= header < row_count and header < first_data < row_count
        if question == 1:
            return (
                self.measurement_combo.currentData() != MeasurementType.UNKNOWN.value
                and self.scale_combo.currentData() != ValueScale.UNKNOWN.value
            )
        feature_column, sample_columns, _, _ = self._role_columns()
        return feature_column is not None and len(sample_columns) >= 2

    def _update_question_state(self) -> None:
        if self.session is None:
            self.question_label.setText("确认表格")
            self.back_button.setEnabled(False)
            self.prepare_button.setEnabled(False)
            return
        index = self.organize_tabs.currentIndex()
        self.question_label.setText(f"第 {index + 1} / {self.organize_tabs.count()} 步：{self._question_titles[index]}")
        self.back_button.setEnabled(self._active_thread is None)
        self.back_button.setText("上一步" if index > 0 else "返回文件清单")
        self.prepare_button.setText(
            "确认预览，继续核对数值" if index == 0 else
            "确认数值，检查列用途" if index == 1 else
            "确认列用途，开始整理"
        )
        self.prepare_button.setEnabled(
            self._active_thread is None and self._question_can_continue()
        )

    def _update_action_state(self) -> None:
        self._update_question_state()
        if self.session is None or self._question_can_continue():
            return
        index = self.organize_tabs.currentIndex()
        messages = (
            "请确认表头行和第一行数据位置；数据行要在表头之后。",
            "请根据交付说明选择数值单位和转换方式。",
            "请指定一列特征编号和至少两列样本表达；不需要的列可设为忽略。",
        )
        self.organize_status_label.setText(messages[index])

    def _populate_column_controls(self) -> None:
        assert self.session is not None
        header_index = max(0, self.header_spin.value() - 1)
        rows = self.preparer._view_rows(self.session.raw_table.rows, self.transpose_check.isChecked())
        width = max((len(row) for row in rows), default=0)
        headers = list(rows[header_index]) if header_index < len(rows) else []
        self.column_roles.setRowCount(width)
        role_options = (
            ("feature_id", "特征编号"),
            ("sample", "样本表达"),
            ("annotation", "说明/注释"),
            ("ignored", "忽略"),
        )
        data_start = max(0, self.data_start_spin.value() - 1)
        for index in range(width):
            label = headers[index] if index < len(headers) else f"列 {index + 1}"
            self.column_roles.setItem(index, 0, QTableWidgetItem(f"第 {index + 1} 列：{label}"))
            values = [
                row[index].strip()
                for row in rows[data_start:data_start + 3]
                if index < len(row) and row[index].strip()
            ]
            self.column_roles.setItem(index, 2, QTableWidgetItem(", ".join(values[:3]) or "（空）"))
            role_combo = QComboBox()
            for role, role_label in role_options:
                role_combo.addItem(role_label, role)
            if index == self.session.recipe.feature_id_column:
                role = "feature_id"
            elif index in self.session.recipe.sample_columns:
                role = "sample"
            elif index in self.session.recipe.annotation_columns:
                role = "annotation"
            else:
                role = "ignored"
            role_combo.setCurrentIndex(next(pos for pos in range(role_combo.count()) if role_combo.itemData(pos) == role))
            role_combo.setFixedHeight(30)
            role_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            role_combo.currentIndexChanged.connect(lambda _value, row=index: self._role_changed(row))
            self.column_roles.setCellWidget(index, 1, role_combo)
        # 2.2 不是“把三个窄列塞满”：角色列需要足够宽，示例列负责承接剩余空间。
        # 固定前两列后，窗口放大/缩小时表格仍然稳定可读。
        self.column_roles.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.column_roles.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.column_roles.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.column_roles.setColumnWidth(0, 270)
        self.column_roles.setColumnWidth(1, 220)
        feature_column, sample_columns, _, _ = self._role_columns()
        feature_label = headers[feature_column] if feature_column is not None and feature_column < len(headers) else "尚未选定"
        sample_labels = [headers[index] if index < len(headers) else f"第 {index + 1} 列" for index in sample_columns]
        sample_summary = "、".join(sample_labels[:4]) + ("等" if len(sample_labels) > 4 else "")
        self._role_hint_summary = (
            f"软件暂建议：‘{feature_label}’是基因编号；识别到 {len(sample_columns)} 列样本数值"
            f"（{sample_summary or '尚未选定'}）。"
        )
        self._suspected_numeric_annotation_labels = [
            headers[index].strip() if index < len(headers) else f"第 {index + 1} 列"
            for index in range(width)
            if index != feature_column
            and self.preparer._is_numeric_annotation_header(
                headers[index] if index < len(headers) else ""
            )
            and self._column_is_numerically_dense(rows, data_start, index)
        ]
        self._update_editors_for_current_table()

    @staticmethod
    def _column_is_numerically_dense(rows: tuple[tuple[str, ...], ...], start: int, column: int) -> bool:
        values = [
            row[column].strip()
            for row in rows[start:start + 20]
            if column < len(row) and row[column].strip()
        ]
        return bool(values) and sum(PreparationService._is_number(value) for value in values) / len(values) >= 0.7

    def _update_editors_for_current_table(self) -> None:
        """常见且结构清楚的矩阵先给简短确认；有歧义时直接展开可修正设置。"""
        if self.session is None:
            return

        raw = self.session.raw_table
        rows = self.preparer._view_rows(raw.rows, self.transpose_check.isChecked())
        header_index = self.header_spin.value() - 1
        candidates = self.preparer.candidate_header_rows(rows)
        feature_column, sample_columns, annotation_columns, ignored_columns = self._role_columns()
        headers = list(rows[header_index]) if 0 <= header_index < len(rows) else []
        sample_ids = [
            headers[index].strip() if index < len(headers) else ""
            for index in sample_columns
        ]
        sample_ids_are_clear = (
            len(sample_ids) >= 2
            and all(sample_ids)
            and len(set(sample_ids)) == len(sample_ids)
        )
        structure_needs_review = (
            self.sheet_combo.count() > 1
            or not candidates
            or candidates[0] != header_index
            or self.data_start_spin.value() != self.header_spin.value() + 1
            or self.transpose_check.isChecked()
            or raw.row_count <= raw.column_count
            or feature_column is None
            or not sample_ids_are_clear
        )
        structure_expanded = structure_needs_review or self.structure_edit_toggle.isChecked()
        if structure_expanded != self.structure_edit_toggle.isChecked():
            self.structure_edit_toggle.setChecked(structure_expanded)
        self.structure_controls.setVisible(structure_expanded)

        feature_header = (
            headers[feature_column].strip().casefold()
            if feature_column is not None and feature_column < len(headers)
            else ""
        )
        feature_header_is_clear = any(
            token in feature_header
            for token in ("gene", "feature", "probe", "id", "ensembl", "symbol", "ref")
        )
        roles_need_review = (
            not feature_header_is_clear
            or not sample_ids_are_clear
            or bool(annotation_columns)
            or bool(ignored_columns)
            or bool(getattr(self, "_suspected_numeric_annotation_labels", ()))
        )
        roles_expanded = roles_need_review or self.roles_edit_toggle.isChecked()
        if roles_expanded != self.roles_edit_toggle.isChecked():
            self.roles_edit_toggle.setChecked(roles_expanded)
        self.roles_editor.setVisible(roles_expanded)
        suspected = getattr(self, "_suspected_numeric_annotation_labels", ())
        warning = (
            "发现可能是长度、起止位置或 GC 含量的数值注释列（"
            + "、".join(suspected)
            + "）；已从样本表达建议中排除，并展开列角色供你检查。"
            if suspected else ""
        )
        role_action = (
            "列用途需要核对，可直接在下表逐列修改。"
            if roles_expanded
            else "请对照预览；看起来正确可继续，不符时点上方展开逐列调整。"
        )
        self.role_hint.setText(
            warning + self._role_hint_summary + role_action + "数值单位仍需按交付说明确认。"
        )

    @Slot(bool)
    def _toggle_structure_controls(self, expanded: bool) -> None:
        self.structure_controls.setVisible(expanded)
        self.structure_edit_toggle.setText(
            "收起表格结构设置" if expanded else "需要修改工作表、表头或方向？展开设置"
        )

    @Slot(bool)
    def _toggle_roles_editor(self, expanded: bool) -> None:
        self.roles_editor.setVisible(expanded)
        self.roles_edit_toggle.setText(
            "收起逐列设置" if expanded else "需要修改列用途？展开逐列设置"
        )

    def _role_changed(self, row: int) -> None:
        """列角色即时生效；特征编号只能有一列，避免隐式覆盖。"""
        combo = self.column_roles.cellWidget(row, 1)
        if not isinstance(combo, QComboBox):
            return
        if combo.currentData() == "feature_id":
            for other in range(self.column_roles.rowCount()):
                if other == row:
                    continue
                other_combo = self.column_roles.cellWidget(other, 1)
                if not isinstance(other_combo, QComboBox) or other_combo.currentData() != "feature_id":
                    continue
                other_combo.blockSignals(True)
                other_combo.setCurrentIndex(2)
                other_combo.blockSignals(False)
        self.controls_changed()

    def _role_columns(self) -> tuple[int | None, list[int], list[int], list[int]]:
        feature_column: int | None = None
        sample_columns: list[int] = []
        annotation_columns: list[int] = []
        ignored_columns: list[int] = []
        for row in range(self.column_roles.rowCount()):
            combo = self.column_roles.cellWidget(row, 1)
            role = combo.currentData() if isinstance(combo, QComboBox) else "ignored"
            if role == "feature_id":
                feature_column = row
            elif role == "sample":
                sample_columns.append(row)
            elif role == "annotation":
                annotation_columns.append(row)
            else:
                ignored_columns.append(row)
        return feature_column, sample_columns, annotation_columns, ignored_columns

    def _current_patch(self) -> dict[str, object]:
        feature_column, sample_columns, annotation_columns, ignored_columns = self._role_columns()
        fact_evidence = tuple(
            item for item in self.session.asset.evidence
            if item.fact_key in {"measurement_type", "value_scale"}
        ) if self.session is not None else ()
        measurement_value = str(self.measurement_combo.currentData())
        scale_value = str(self.scale_combo.currentData())
        measurement_hint = (
            self.session.asset.measurement_hint.value if self.session is not None else MeasurementType.UNKNOWN.value
        )
        scale_hint = (
            self.session.asset.scale_hint.value if self.session is not None else ValueScale.UNKNOWN.value
        )
        reported_formulas = {
            item.reported_transform
            for item in fact_evidence
            if item.fact_key == "value_scale" and item.reported_transform
        }
        reported_transform = (
            next(iter(reported_formulas))
            if scale_value == ValueScale.LOG2.value
            and scale_value == scale_hint
            and len(reported_formulas) == 1
            else ""
        )

        def confirmation(fact_key: str, selected: str, candidate: str) -> dict[str, object]:
            matching = [item for item in fact_evidence if item.fact_key == fact_key]
            evidence_values = {item.fact_value for item in matching if item.fact_value}
            if selected in {MeasurementType.UNKNOWN.value, ValueScale.UNKNOWN.value}:
                status = "not_confirmed"
            elif len(evidence_values) > 1:
                status = "user_resolved_conflicting_text"
            elif matching and selected == candidate:
                status = "user_confirmed_text_candidate"
            elif matching:
                status = "user_overrode_text_candidate"
            else:
                status = "user_confirmed_without_direct_text"
            evidence_by_key: dict[tuple[str, str], object] = {}
            for item in matching:
                key = (item.fact_value, item.reported_transform)
                evidence_by_key.setdefault(key, item)
            preserved = list(evidence_by_key.values())
            selected_evidence = preserved[:]
            for item in matching:
                if item not in selected_evidence and len(selected_evidence) < max(8, len(preserved)):
                    selected_evidence.append(item)
            return {
                "fact_key": fact_key,
                "candidate_value": candidate,
                "selected_value": selected,
                "status": status,
                "evidence": [item.as_dict() for item in selected_evidence],
            }

        return {
            "header_row": self.header_spin.value() - 1,
            "data_start_row": self.data_start_spin.value() - 1,
            "feature_id_column": feature_column if feature_column is not None else 0,
            "sample_columns": sample_columns,
            "annotation_columns": annotation_columns,
            "ignored_columns": ignored_columns,
            "measurement_type": self.measurement_combo.currentData(),
            "value_scale": self.scale_combo.currentData(),
            "fact_confirmations": (
                confirmation("measurement_type", measurement_value, measurement_hint),
                confirmation("value_scale", scale_value, scale_hint),
            ),
            "reported_transform": reported_transform,
            "transpose": self.transpose_check.isChecked(),
        }

    def _render_preview(self) -> None:
        if self.session is None:
            return
        preview = self.preparer.preview(self.session, self._current_patch(), (0, 8))
        self.preview.clear()
        self.preview.setRowCount(len(preview.rows))
        self.preview.setColumnCount(preview.column_count_hint or 0)
        for row_index, row in enumerate(preview.rows):
            for column_index, value in enumerate(row):
                self.preview.setItem(row_index, column_index, QTableWidgetItem(value))
        preview_header = self.preview.horizontalHeader()
        preview_header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for column in range(self.preview.columnCount()):
            self.preview.setColumnWidth(column, max(120, min(220, self.preview.columnWidth(column))))
        self.organize_status_label.setText(
            f"下方仅预览 {len(preview.rows)} 行 × {preview.column_count_hint:,} 列。"
            + ("完整行数和数据有效性将在最终校验时检查。" if not self.session.raw_table.is_complete else "")
        )

    @Slot()
    def finish_preparation(self) -> None:
        if self.session is None or self._active_thread is not None:
            return
        session = self.preparer.apply(self.session, self._current_patch())
        if self.reference_path is not None:
            session = replace(session, reference_path=self.reference_path)

        def task(progress, cancelled):
            full_session = self.preparer.complete_read(
                session,
                progress=lambda rows: progress(ImportProgress("正在完整读取表格", rows, None, session.asset.source_paths[0].name)),
                cancelled=cancelled,
            )
            if cancelled():
                raise ArchiveCancelled("已取消完整读取")
            progress(ImportProgress("正在验证全部数据", label=session.asset.source_paths[0].name))
            summary = self.preparer.validate(
                full_session,
                cancelled=cancelled,
                progress=lambda completed, total: progress(ImportProgress(
                    "正在验证全部数据",
                    completed,
                    total,
                    session.asset.source_paths[0].name,
                )),
            )
            if not summary.passed:
                return summary, None
            if cancelled():
                raise ArchiveCancelled("已取消整理")
            source_path = full_session.asset.source_paths[0]
            source_sha256 = self.preparer.fingerprint_source(
                source_path,
                progress=lambda completed, total: progress(ImportProgress(
                    "正在校验来源文件",
                    completed,
                    total,
                    source_path.name,
                    unit="字节",
                )),
                cancelled=cancelled,
                expected_signature=full_session.source_signature,
            )
            if cancelled():
                raise ArchiveCancelled("已取消来源文件校验")
            progress(ImportProgress("正在保存整理后的表达表；此阶段也可取消", cancellable=True))
            return summary, self.preparer.finish(
                full_session,
                summary=summary,
                source_sha256=source_sha256,
                cancelled=cancelled,
            )

        self.session = session
        self._start_background_task("正在验证并整理表达表", task, self._preparation_completed, cancellable=True)

    def _preparation_completed(self, result) -> None:
        summary, matrix = result
        if not summary.passed:
            text = "\n".join(
                f"• {issue.message_zh}\n  操作：{issue.operation_zh}"
                for issue in summary.issues[:8]
            )
            QMessageBox.warning(self, "还不能运行", text or "整理结果未通过验证")
            self._set_status(f"验证未通过：{len(summary.blockers)} 个问题；请根据提示修正后重试。")
            return
        self._set_status(f"整理完成，结果已写入：{matrix.values.path.parent}")
        self.matrixReady.emit(matrix)
