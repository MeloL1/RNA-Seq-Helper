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
        from PySide6.QtCore import QObject, QThread, QTimer, Qt, Slot
        from PySide6.QtGui import QAction, QIcon
        from PySide6.QtWidgets import (
            QApplication, QDialog, QGroupBox, QHBoxLayout, QLabel, QMainWindow,
            QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
        )
        from rnaseq_helper.ui.background_jobs import BackgroundJobCloseGuard
        from rnaseq_helper.ui.pages import AnalysisPage, ImportPage, ResultsPage
        from rnaseq_helper.ui.workers.project_worker import ProjectLoadWorker
    except ImportError:
        print("无法启动 GUI：请先安装 PySide6。可运行 --self-check 或 --micro-test。", file=sys.stderr)
        return 2

    app = QApplication(sys.argv)
    app.setStyleSheet(
        "QWidget { font-size: 13px; }"
        "QPushButton[workflowStep=active] { color: #007AFF; font-weight: 700; }"
        "QPushButton[workflowStep=ready] { color: palette(text); }"
        "QPushButton[workflowStep=locked] { color: palette(mid); }"
        "QGroupBox { margin-top: 12px; padding: 10px; border: 1px solid palette(mid); border-radius: 5px; }"
        "QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }"
        "QLineEdit, QComboBox, QSpinBox { min-height: 30px; padding: 2px 7px; }"
        "QTableWidget::item { padding: 4px; }"
        "QLabel#pageTitle { font-size: 20px; font-weight: 650; }"
        "QLabel#sectionTitle { font-size: 16px; font-weight: 650; }"
        "QLabel#groupingOverview, QLabel#groupSummary { font-weight: 650; }"
        "QLabel#groupSummary { font-size: 15px; padding: 4px 2px; }"
        "QLabel#pageSubtitle, QLabel#groupingNote { color: palette(mid); }"
        "QLabel#recognitionSummary { color: #245f9e; padding: 4px 0; }"
        "QWidget#importDropZone { background: palette(base); border: 1px dashed palette(mid); border-radius: 8px; }"
        "QWidget#workflowActionBar { border-top: 1px solid palette(mid); }"
        "QPushButton#primaryAction { background: #007AFF; color: white; border: 0; border-radius: 6px; font-weight: 650; padding: 6px 18px; }"
        "QPushButton#primaryAction:disabled { background: palette(mid); color: palette(window); }"
        "QToolTip { padding: 5px; }"
    )
    window = QMainWindow()
    window.setWindowTitle("RNA-Seq Helper")
    icon_path = _ui_resource_path("AppIcon.icns")
    if icon_path is not None:
        window.setWindowIcon(QIcon(str(icon_path)))
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
    workflow_layout.setContentsMargins(18, 10, 18, 0)
    workflow_layout.setSpacing(8)
    navigation = QHBoxLayout()
    navigation.setSpacing(10)
    step_labels = ("1  导入数据", "2  检查数据", "3  设置分组", "4  分析结果")
    step_buttons = [QPushButton(label) for label in step_labels]
    for button_step in step_buttons:
        button_step.setMinimumHeight(34)
        navigation.addWidget(button_step, 1)
    workflow_layout.addLayout(navigation)
    pages = QStackedWidget()
    pages.addWidget(import_page)
    pages.addWidget(analysis_page)
    pages.addWidget(results_page)
    workflow_layout.addWidget(pages, 1)

    action_bar = QWidget()
    action_bar.setObjectName("workflowActionBar")
    action_layout = QHBoxLayout(action_bar)
    action_layout.setContentsMargins(0, 8, 0, 12)
    action_layout.setSpacing(10)
    action_status = QLabel("选择表达数据文件开始。")
    action_status.setObjectName("actionStatus")
    action_status.setWordWrap(True)
    action_status.setMaximumHeight(42)
    action_layout.addWidget(action_status, 1)
    action_back = QPushButton("返回")
    action_primary = QPushButton("继续")
    action_primary.setObjectName("primaryAction")
    action_layout.addWidget(action_back)
    action_layout.addWidget(action_primary)
    workflow_layout.addWidget(action_bar)

    ready_steps = [True, False, False, False]
    current_step = 0
    project_jobs: list[tuple[QThread, object]] = []

    def refresh_stepper() -> None:
        for index, step_button in enumerate(step_buttons):
            step_button.setEnabled(ready_steps[index])
            state = "active" if index == current_step else "ready" if ready_steps[index] else "locked"
            step_button.setProperty("workflowStep", state)
            step_button.style().unpolish(step_button)
            step_button.style().polish(step_button)

    def refresh_action_bar() -> None:
        for inner_button in (
            import_page.back_button,
            import_page.cancel_button,
            import_page.organize_cancel_button,
            analysis_page.cancel_button,
        ):
            inner_button.hide()
        if current_step == 0:
            importing = import_page._active_thread is not None and import_page._active_thread.isRunning()
            action_back.setText("取消任务" if importing else "返回")
            action_back.setEnabled(importing)
            action_primary.setText(import_page.continue_button.text())
            action_primary.setEnabled(not importing and import_page.continue_button.isEnabled())
            action_status.setText(import_page.status_label.text() or "选择表达数据文件开始。")
        elif current_step == 1:
            importing = import_page._active_thread is not None and import_page._active_thread.isRunning()
            action_back.setText("取消任务" if importing else "返回文件清单")
            action_back.setEnabled(importing or import_page._active_thread is None)
            action_primary.setText("整理并进入分组")
            action_primary.setEnabled(not importing and import_page.prepare_button.isEnabled())
            action_status.setText(import_page.organize_status_label.text() or "核对结构、数值类型和列用途。")
        elif current_step == 2:
            analyzing = any(thread.isRunning() for thread, _worker, _context in analysis_page._jobs)
            action_back.setText("取消任务" if analyzing else "返回检查数据")
            action_back.setEnabled(True)
            action_primary.setText("开始分析" if analysis_page.plan and analysis_page.plan.runnable else "生成分析计划")
            action_primary.setEnabled(not analyzing and (
                analysis_page.run_button.isEnabled()
                if analysis_page.plan and analysis_page.plan.runnable
                else analysis_page.plan_button.isEnabled()
            ))
            action_status.setText(analysis_page.status_label.text() or "确认实验组和对照组后生成分析计划。")
        else:
            action_back.setEnabled(True)
            action_primary.setText("打开离线报告")
            action_primary.setEnabled(results_page.open_report_button.isEnabled())
            action_status.setText("分析完成后可查看报告、结果表和项目文件。")

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
        refresh_action_bar()

    for index, step_button in enumerate(step_buttons):
        step_button.clicked.connect(lambda _checked=False, current=index: show_workflow_step(current))

    def action_back_clicked() -> None:
        if current_step < 2 and import_page._active_thread is not None and import_page._active_thread.isRunning():
            import_page.cancel_import()
        elif current_step == 2 and any(thread.isRunning() for thread, _worker, _context in analysis_page._jobs):
            analysis_page.cancel_analysis()
        elif current_step == 1:
            show_workflow_step(0)
        elif current_step == 2:
            show_workflow_step(1)
        elif current_step == 3:
            show_workflow_step(2)

    def action_primary_clicked() -> None:
        if current_step == 0:
            import_page.continue_button.click()
        elif current_step == 1:
            import_page.prepare_button.click()
        elif current_step == 2:
            if analysis_page.plan and analysis_page.plan.runnable:
                analysis_page.run_button.click()
            else:
                analysis_page.plan_button.click()
        elif current_step == 3:
            results_page.open_report_button.click()
        refresh_action_bar()

    action_back.clicked.connect(action_back_clicked)
    action_primary.clicked.connect(action_primary_clicked)
    import_page.continue_button.hide()
    import_page.prepare_button.hide()
    analysis_page.plan_button.hide()
    analysis_page.run_button.hide()
    analysis_page.cancel_button.hide()
    import_page.stepAvailabilityChanged.connect(
        lambda index, available: _update_import_step(index, available)
    )
    import_page.workflowStepRequested.connect(show_workflow_step)
    footer_timer = QTimer(window)
    footer_timer.setInterval(400)
    footer_timer.timeout.connect(refresh_action_bar)
    footer_timer.start()

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
    def analysis_finished(result: object) -> None:
        # 生成计划时项目目录会从导入暂存位置移动到用户选定的位置；
        # 必须先把最新矩阵路径交给结果页，再计算报告/项目按钮状态。
        if analysis_page.matrix is not None:
            results_page.set_matrix(analysis_page.matrix)
        results_page.set_result(result, analysis_page.plan)
        ready_steps[3] = True
        show_workflow_step(3)

    def matrix_prepared(_matrix: object) -> None:
        ready_steps[2] = True
        show_workflow_step(2)

    import_page.matrixReady.connect(matrix_prepared)
    analysis_page.analysisReady.connect(analysis_finished)
    results_page.regroupRequested.connect(lambda: show_workflow_step(2))

    def open_saved_project(project_dir: str) -> None:
        if import_page._active_thread is not None and import_page._active_thread.isRunning():
            import_page.status_label.setText("请先等待当前导入/整理任务完成或取消，再打开已保存项目。")
            return
        if any(current_thread.isRunning() for current_thread, _worker, _context in analysis_page._jobs):
            import_page.status_label.setText("请先等待当前分析任务完成或取消，再打开已保存项目。")
            return
        if any(current_thread.isRunning() for current_thread, _worker in project_jobs):
            import_page.status_label.setText("正在读取另一个项目；请等待校验完成。")
            return
        import_page.open_project_button.setEnabled(False)
        import_page.status_label.setText("正在检查项目清单、矩阵、样本顺序和既有结果……")
        project_thread = QThread(window)
        project_worker = ProjectLoadWorker(Path(project_dir))
        import_page.begin_external_check(project_worker.request_cancel)
        project_jobs.append((project_thread, project_worker))
        project_worker.moveToThread(project_thread)

        def project_loaded(snapshot: object) -> None:
            import_page.end_external_check()
            analysis_page.set_matrix(
                snapshot.matrix,
                initial_design=(snapshot.saved_plan or {}).get("design"),
                restored_project=True,
            )
            results_page.set_matrix(snapshot.matrix)
            results_page.set_saved_project(snapshot)
            ready_steps[1] = False
            ready_steps[2] = True
            ready_steps[3] = True
            show_workflow_step(3)
            import_page.status_label.setText(
                "项目已恢复。可在“确认样本”中核对或修改分组；点击“开始分析”后将直接替换原项目中的分析计划、结果、图表和报告。"
            )

        def project_failed(message: str) -> None:
            import_page.end_external_check(f"项目未能恢复：{message}")
            import_page.status_label.setText(f"项目未能恢复：{message}")
            QMessageBox.warning(window, "无法打开项目", message)

        def project_cancelled() -> None:
            import_page.end_external_check("已取消打开项目；没有启动新分析。若有中断事务，软件已按记录恢复。")

        project_worker.completed.connect(project_loaded, Qt.ConnectionType.QueuedConnection)
        project_worker.failed.connect(project_failed, Qt.ConnectionType.QueuedConnection)
        project_worker.progress.connect(import_page.update_external_check, Qt.ConnectionType.QueuedConnection)
        project_worker.cancelled.connect(project_cancelled, Qt.ConnectionType.QueuedConnection)
        project_worker.completed.connect(project_thread.quit, Qt.ConnectionType.QueuedConnection)
        project_worker.failed.connect(project_thread.quit, Qt.ConnectionType.QueuedConnection)
        project_worker.cancelled.connect(project_thread.quit, Qt.ConnectionType.QueuedConnection)
        project_thread.started.connect(project_worker.run, Qt.ConnectionType.QueuedConnection)
        project_thread.finished.connect(project_worker.deleteLater)
        project_thread.finished.connect(project_thread.deleteLater)

        def project_thread_finished(current_thread=project_thread, current_worker=project_worker) -> None:
            if (current_thread, current_worker) in project_jobs:
                project_jobs.remove((current_thread, current_worker))
            import_page.open_project_button.setEnabled(True)
            import_page.end_external_check()

        project_thread.finished.connect(project_thread_finished)
        project_thread.start()

    import_page.projectOpenRequested.connect(open_saved_project)
    workflow.setMinimumWidth(760)
    window.setCentralWidget(workflow)
    refresh_stepper()
    thread: QThread | None = None
    active_jobs: list[tuple[QThread, object]] = []

    def active_threads() -> tuple[QThread, ...]:
        threads = [current_thread for current_thread, _worker in active_jobs]
        threads.extend(current_thread for current_thread, _worker in project_jobs)
        threads.extend(current_thread for current_thread, _worker, _context in analysis_page._jobs)
        threads.extend(results_page.active_threads())
        if import_page._active_thread is not None:
            threads.append(import_page._active_thread)
        unique: list[QThread] = []
        for current_thread in threads:
            if current_thread not in unique:
                unique.append(current_thread)
        return tuple(unique)

    def cancel_active_jobs() -> None:
        results_page.cancel_refresh()
        for _current_thread, worker in tuple(active_jobs):
            context = getattr(worker, "context", None)
            cancel_event = getattr(context, "cancel_event", None)
            if cancel_event is not None:
                cancel_event.set()
        for _current_thread, _worker, context in tuple(analysis_page._jobs):
            context.cancel_event.set()
        if import_page._active_worker is not None:
            import_page._active_worker.request_cancel()
        for _current_thread, worker in tuple(project_jobs):
            worker.request_cancel()

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
    window.setMinimumSize(900, 600)
    window.resize(1120, 760)
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
