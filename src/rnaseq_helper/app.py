from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from rnaseq_helper.domain.models import JobContext
from rnaseq_helper.r_bridge.client import RBridgeClient, RBridgeError
from rnaseq_helper.services.environment import EnvironmentService
from rnaseq_helper.ui.workers.runtime_worker import _micro_payload


def _self_check() -> int:
    status = EnvironmentService().check()
    print(json.dumps(status.as_dict(), ensure_ascii=False, indent=2))
    return 0 if status.ready_for_stage0_r else 1


def _micro_test(method: str = "micro_limma") -> int:
    with tempfile.TemporaryDirectory(prefix="rnaseq-helper-stage0-") as workdir:
        context = JobContext(Path(workdir), on_progress=lambda stage, _, message: print(f"[{stage}] {message}"))
        try:
            response = RBridgeClient().run(method, _micro_payload(), context)
        except RBridgeError as exc:
            print(f"微型 R 验证失败：{exc}", file=sys.stderr)
            return 1
    print(json.dumps(response.result, ensure_ascii=False, indent=2))
    return 0


def _ui_resource_path(name: str) -> Path | None:
    candidates = (
        Path(sys.executable).resolve().parent.parent / "Resources" / "resources" / "ui" / name,
        Path(__file__).resolve().parents[2] / "resources" / "ui" / name,
    )
    return next((path for path in candidates if path.is_file()), None)


def _gui() -> int:
    try:
        from PySide6.QtCore import QObject, QThread, Qt, Slot
        from PySide6.QtGui import QAction, QColor, QPalette
        from PySide6.QtWidgets import (
            QApplication, QDialog, QGroupBox, QHBoxLayout, QLabel, QMainWindow,
            QPushButton, QStackedWidget, QVBoxLayout, QWidget,
        )
        from rnaseq_helper.ui.background_jobs import BackgroundJobCloseGuard
        from rnaseq_helper.ui.pages import AnalysisPage, ImportPage, ResultsPage
    except ImportError:
        print("无法启动 GUI：请先安装 PySide6。可运行 --self-check 或 --micro-test。", file=sys.stderr)
        return 2

    app = QApplication(sys.argv)
    # 使用 Qt 自带的 Fusion 绘制器，避免 macOS 高对比主题改变步骤导航和表格背景。
    app.setStyle("Fusion")
    # macOS 黑白/高对比模式可能把未明确指定的 QTabBar 背景解析成黑色。
    # 这里把关键调色板角色固定为中性灰阶，避免样式表之外仍被系统主题反转。
    palette = app.palette()
    palette_colors = {
        QPalette.ColorRole.Window: "#f7f7f7",
        QPalette.ColorRole.WindowText: "#111111",
        QPalette.ColorRole.Base: "#ffffff",
        QPalette.ColorRole.AlternateBase: "#f0f0f0",
        QPalette.ColorRole.Text: "#111111",
        QPalette.ColorRole.Button: "#ffffff",
        QPalette.ColorRole.ButtonText: "#111111",
        QPalette.ColorRole.BrightText: "#000000",
        QPalette.ColorRole.Highlight: "#cfcfcf",
        QPalette.ColorRole.HighlightedText: "#000000",
        QPalette.ColorRole.Light: "#ffffff",
        QPalette.ColorRole.Midlight: "#dddddd",
        QPalette.ColorRole.Mid: "#888888",
        QPalette.ColorRole.Dark: "#444444",
        QPalette.ColorRole.Shadow: "#111111",
    }
    for role, color in palette_colors.items():
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    # 不依赖系统彩色/高对比主题：黑白或灰度模式下仍用边框、底色和字重
    # 区分层级，不能只靠蓝色、浅灰色或透明背景表达状态。
    style_sheet = """
        QWidget { font-size: 13px; color: #111111; background: #f7f7f7; }
        QMainWindow { background: #f7f7f7; }
        QPushButton[workflowStep="active"] { background: #111111; color: #ffffff; font-weight: 700; border: 2px solid #111111; }
        QPushButton[workflowStep="ready"] { background: #ffffff; color: #111111; border: 1px solid #333333; }
        QPushButton[workflowStep="locked"] { background: #e9e9e9; color: #666666; border: 1px solid #888888; }
        QGroupBox { margin-top: 14px; padding: 14px 12px 12px; border: 1px solid #555555; border-radius: 6px; background: #ffffff; }
        QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #000000; font-weight: 700; background: #ffffff; }
        QLabel { background: transparent; color: #111111; }
        QLineEdit, QComboBox, QSpinBox { height: 34px; min-height: 34px; max-height: 34px; padding: 0 8px; border: 1px solid #444444; border-radius: 4px; background: #ffffff; color: #111111; }
        QPushButton { min-height: 40px; padding: 5px 14px; border: 1px solid #444444; border-radius: 4px; background: #ffffff; color: #111111; }
        QPushButton[workflowStep="active"], QPushButton[workflowStep="ready"], QPushButton[workflowStep="locked"] { min-height: 48px; }
        QComboBox { padding-right: 30px; }
        QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right; width: 28px; border-left: 1px solid #888888; background: #eeeeee; }
        QTableWidget QComboBox { height: 30px; min-height: 30px; max-height: 30px; padding: 0 24px 0 6px; border-radius: 3px; }
        QTableWidget QComboBox::drop-down { width: 22px; }
        QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border: 2px solid #000000; }
        QPushButton:hover { background: #eeeeee; border: 2px solid #000000; }
        QPushButton:focus { outline: 2px solid #000000; outline-offset: 2px; }
        QPushButton:pressed { background: #d9d9d9; }
        QPushButton:disabled { color: #666666; background: #e9e9e9; border-color: #888888; }
        QCheckBox { background: transparent; color: #111111; spacing: 8px; min-height: 34px; }
        QCheckBox::indicator { width: 22px; height: 22px; border-radius: 3px; }
        QCheckBox::indicator:unchecked { border: 2px solid #333333; background: #ffffff; }
        QCheckBox::indicator:checked { border: 2px solid #000000; background: #111111; }
        QCheckBox:focus, QToolButton:focus { outline: 2px solid #000000; outline-offset: 2px; }
        QTableWidget { gridline-color: #777777; alternate-background-color: #f0f0f0; selection-background-color: #cfcfcf; selection-color: #000000; border: 1px solid #444444; border-radius: 4px; }
        QTableWidget::item { padding: 4px; }
        QHeaderView::section { padding: 8px 6px; background: #e5e5e5; color: #111111; font-weight: 700; border: 0; border-bottom: 1px solid #555555; }
        QScrollArea { border: 0; background: #ffffff; }
        QScrollBar:vertical { width: 16px; background: #eeeeee; border: 1px solid #555555; }
        QScrollBar::handle:vertical { min-height: 32px; background: #777777; border: 1px solid #111111; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 16px; background: #dddddd; border: 1px solid #555555; }
        QPlainTextEdit { background: #ffffff; color: #111111; }
        QToolTip { padding: 5px; color: #111111; background: #ffffff; border: 1px solid #444444; }
    """
    arrow_path = _ui_resource_path("combobox-arrow.svg")
    if arrow_path is not None:
        style_sheet += (
            f'\nQComboBox::down-arrow {{ image: url("{arrow_path.as_posix()}"); '
            "width: 12px; height: 12px; }\n"
        )
    app.setStyleSheet(style_sheet)
    window = QMainWindow()
    window.setWindowTitle("RNA-Seq Helper · 阶段 5")
    tools_menu = window.menuBar().addMenu("工具")
    label = QLabel("欢迎使用 RNA-Seq Helper\n可先检查运行环境，再运行微型验证。")
    label.setWordWrap(True)
    label.setMinimumHeight(72)
    self_check_button = QPushButton("检查 Python / R 环境")
    button = QPushButton("运行 limma 微型验证")
    deseq2_button = QPushButton("运行 DESeq2 微型验证")
    cancel_button = QPushButton("取消当前验证")
    cancel_button.setEnabled(False)
    verification_box = QGroupBox("环境与 R worker 验证")
    verification_layout = QVBoxLayout(verification_box)
    verification_layout.setContentsMargins(16, 18, 16, 16)
    verification_layout.setSpacing(12)
    verification_layout.addWidget(label)
    verification_layout.addWidget(self_check_button)
    button_row = QHBoxLayout()
    button_row.setSpacing(12)
    button_row.addWidget(button)
    button_row.addWidget(deseq2_button)
    button_row.addWidget(cancel_button)
    button_row.addStretch(1)
    verification_layout.addLayout(button_row)
    layout = QVBoxLayout()
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(14)
    layout.addWidget(verification_box)
    layout.addStretch(1)
    container = QWidget()
    container.setLayout(layout)
    verification_dialog = QDialog(window)
    verification_dialog.setWindowTitle("环境与 R 微型验证")
    verification_dialog.setMinimumSize(620, 320)
    verification_dialog.setLayout(QVBoxLayout())
    verification_dialog.layout().addWidget(container)
    verify_action = QAction("环境与验证…", window)
    verify_action.triggered.connect(lambda _checked=False: verification_dialog.exec())
    tools_menu.addAction(verify_action)

    import_page = ImportPage()
    analysis_page = AnalysisPage()
    results_page = ResultsPage()
    workflow = QWidget()
    workflow_layout = QVBoxLayout(workflow)
    workflow_layout.setContentsMargins(14, 12, 14, 14)
    workflow_layout.setSpacing(12)
    navigation = QHBoxLayout()
    navigation.setSpacing(10)
    step_labels = ("1  添加数据", "2  确认表格", "3  确认样本", "4  查看结果")
    step_buttons = [QPushButton(label) for label in step_labels]
    for button_step in step_buttons:
        button_step.setMinimumHeight(48)
        navigation.addWidget(button_step, 1)
    workflow_layout.addLayout(navigation)
    pages = QStackedWidget()
    pages.addWidget(import_page)
    pages.addWidget(analysis_page)
    pages.addWidget(results_page)
    workflow_layout.addWidget(pages, 1)

    ready_steps = [True, False, False, False]
    current_step = 0

    def refresh_stepper() -> None:
        for index, step_button in enumerate(step_buttons):
            step_button.setEnabled(ready_steps[index])
            state = "active" if index == current_step else "ready" if ready_steps[index] else "locked"
            step_button.setProperty("workflowStep", state)
            step_button.style().unpolish(step_button)
            step_button.style().polish(step_button)

    def show_workflow_step(index: int) -> None:
        nonlocal current_step
        if not 0 <= index < len(step_buttons) or not ready_steps[index]:
            return
        current_step = index
        if index < 2:
            pages.setCurrentWidget(import_page)
            import_page.show_workflow_step(index)
        elif index == 2:
            pages.setCurrentWidget(analysis_page)
        else:
            pages.setCurrentWidget(results_page)
        refresh_stepper()

    for index, step_button in enumerate(step_buttons):
        step_button.clicked.connect(lambda _checked=False, current=index: show_workflow_step(current))
    import_page.stepAvailabilityChanged.connect(
        lambda index, available: _update_import_step(index, available)
    )
    import_page.workflowStepRequested.connect(show_workflow_step)

    def _update_import_step(index: int, available: bool) -> None:
        if 0 <= index < 2:
            ready_steps[index] = available
            if index == 1 and not available and current_step == 1:
                show_workflow_step(0)
                return
            if index == 1 and available and current_step == 0:
                show_workflow_step(1)
            else:
                refresh_stepper()

    import_page.matrixReady.connect(analysis_page.set_matrix)
    import_page.matrixReady.connect(results_page.set_matrix)
    analysis_page.analysisReady.connect(results_page.set_result)
    def analysis_finished(_result: object) -> None:
        ready_steps[3] = True
        show_workflow_step(3)

    def matrix_prepared(_matrix: object) -> None:
        ready_steps[2] = True
        show_workflow_step(2)

    import_page.matrixReady.connect(matrix_prepared)
    analysis_page.analysisReady.connect(analysis_finished)
    workflow.setMinimumWidth(760)
    window.setCentralWidget(workflow)
    refresh_stepper()
    thread: QThread | None = None
    active_jobs: list[tuple[QThread, object]] = []

    def active_threads() -> tuple[QThread, ...]:
        threads = [current_thread for current_thread, _worker in active_jobs]
        threads.extend(current_thread for current_thread, _worker, _context in analysis_page._jobs)
        if import_page._active_thread is not None:
            threads.append(import_page._active_thread)
        unique: list[QThread] = []
        for current_thread in threads:
            if current_thread not in unique:
                unique.append(current_thread)
        return tuple(unique)

    def cancel_active_jobs() -> None:
        for _current_thread, worker in tuple(active_jobs):
            context = getattr(worker, "context", None)
            cancel_event = getattr(context, "cancel_event", None)
            if cancel_event is not None:
                cancel_event.set()
        for _current_thread, _worker, context in tuple(analysis_page._jobs):
            context.cancel_event.set()
        if import_page._active_worker is not None:
            import_page._active_worker.request_cancel()

    def show_safe_close_status() -> None:
        message = "正在安全结束后台任务；任务结束后窗口会自动关闭。"
        window.setWindowTitle("RNA-Seq Helper · 正在安全结束任务")
        if pages.currentWidget() is import_page:
            import_page._set_status(message)
        elif pages.currentWidget() is analysis_page:
            analysis_page.status_label.setText(message)
        else:
            label.setText(message)

    close_guard = BackgroundJobCloseGuard(
        window,
        running_threads=active_threads,
        cancel_jobs=cancel_active_jobs,
        show_waiting_status=show_safe_close_status,
    )
    window.installEventFilter(close_guard)

    class UiResultHandler(QObject):
        """将 worker 的结果明确排队回 Qt 主线程，避免跨线程触碰控件。"""

        def __init__(self, owner: QMainWindow) -> None:
            super().__init__(owner)

        @Slot(object)
        def completed(self, _result: object) -> None:
            label.setText(f"{verification_name}通过。")
            button.setEnabled(True)
            deseq2_button.setEnabled(True)
            cancel_button.setEnabled(False)

        @Slot(str)
        def failed(self, error: str) -> None:
            label.setText(f"验证失败：{error}")
            button.setEnabled(True)
            deseq2_button.setEnabled(True)
            cancel_button.setEnabled(False)

        @Slot(str)
        def progress(self, message: str) -> None:
            label.setText(f"R worker：{message}")

    result_handler = UiResultHandler(window)

    verification_name = "limma 微型验证"

    def start(method: str) -> None:
        nonlocal verification_name
        nonlocal thread
        from rnaseq_helper.ui.workers.runtime_worker import RuntimeWorker

        button.setEnabled(False)
        deseq2_button.setEnabled(False)
        cancel_button.setEnabled(True)
        verification_name = "limma 微型验证" if method == "micro_limma" else "DESeq2 微型验证"
        label.setText("R worker 运行中……")
        thread = QThread(window)
        worker = RuntimeWorker(Path(tempfile.mkdtemp(prefix="rnaseq-helper-ui-")))
        # 必须持有 Python wrapper；否则 start() 返回后 worker 可能被回收，
        # R 任务虽已结束，完成信号却没有接收者。
        active_jobs.append((thread, worker))
        worker.moveToThread(thread)
        worker_slot = worker.run_micro_test if method == "micro_limma" else worker.run_micro_deseq2
        thread.started.connect(worker_slot, Qt.ConnectionType.QueuedConnection)
        worker.progress.connect(result_handler.progress, Qt.ConnectionType.QueuedConnection)
        worker.completed.connect(result_handler.completed, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(result_handler.failed, Qt.ConnectionType.QueuedConnection)
        # 让每个任务只关闭自己的线程；结果处理器不再依赖可被下一次点击
        # 覆盖的全局 thread 变量。
        worker.completed.connect(thread.quit, Qt.ConnectionType.QueuedConnection)
        worker.failed.connect(thread.quit, Qt.ConnectionType.QueuedConnection)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda current_thread=thread, current_worker=worker: active_jobs.remove((current_thread, current_worker)))
        thread.start()

    def cancel_current() -> None:
        if not active_jobs:
            return
        current_worker = active_jobs[-1][1]
        context = getattr(current_worker, "context", None)
        if context is not None:
            context.cancel_event.set()
        cancel_button.setEnabled(False)
        label.setText("正在取消 R worker……")

    def run_environment_check() -> None:
        status = EnvironmentService().check()
        label.setText("\n".join(status.messages) + f"\nRscript：{status.rscript or '未找到'}")

    self_check_button.clicked.connect(run_environment_check)
    button.clicked.connect(lambda: start("micro_limma"))
    deseq2_button.clicked.connect(lambda: start("micro_deseq2"))
    cancel_button.clicked.connect(cancel_current)
    window.setMinimumSize(820, 560)
    window.resize(1024, 768)
    window.show()
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RNA-Seq Helper 阶段 5")
    parser.add_argument("--self-check", action="store_true", help="检查 Python、R 和关键 R 包")
    parser.add_argument("--micro-test", action="store_true", help="运行固定输入的 limma-trend 微型验证")
    parser.add_argument("--micro-deseq2", action="store_true", help="运行固定输入的 DESeq2 微型验证")
    args = parser.parse_args(argv)
    if args.self_check:
        return _self_check()
    if args.micro_test:
        return _micro_test()
    if args.micro_deseq2:
        return _micro_test("micro_deseq2")
    from rnaseq_helper.services.crash_diagnostics import enable_gui_crash_diagnostics

    enable_gui_crash_diagnostics()
    return _gui()


if __name__ == "__main__":
    raise SystemExit(main())
