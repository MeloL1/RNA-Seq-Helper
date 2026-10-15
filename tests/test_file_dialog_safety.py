from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFileSystemModel,
    QLineEdit,
)

from rnaseq_helper.ui.pages.import_page import ImportPage


CHOOSERS = (
    pytest.param(
        "choose_file",
        "GSE_UI_contract.tsv",
        QFileDialog.FileMode.ExistingFiles,
        "*.tsv",
        False,
        id="expression-files",
    ),
    pytest.param(
        "choose_10x_directory",
        "filtered_feature_bc_matrix",
        QFileDialog.FileMode.Directory,
        None,
        True,
        id="10x-directory",
    ),
    pytest.param(
        "choose_reference",
        "GPL_UI_contract.annot",
        QFileDialog.FileMode.ExistingFile,
        "*.annot",
        False,
        id="reference-file",
    ),
)


@pytest.mark.parametrize(
    "chooser_name,target_name,file_mode,expected_filter,show_dirs_only",
    CHOOSERS,
)
@pytest.mark.parametrize("accept", (True, False), ids=("open", "cancel"))
def test_import_choosers_disable_completion_and_keep_accept_cancel_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    chooser_name: str,
    target_name: str,
    file_mode: QFileDialog.FileMode,
    expected_filter: str | None,
    show_dirs_only: bool,
    accept: bool,
) -> None:
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))

    target = tmp_path / target_name
    if file_mode == QFileDialog.FileMode.Directory:
        target.mkdir()
    elif target.suffix == ".tsv":
        # This tiny text file exists only to exercise QFileDialog selection.
        target.write_text("gene_id\tcontrol_1\tcontrol_2\nfixture\t1\t2\n", encoding="utf-8")
    else:
        target.write_text("ID\tGENE\nfixture\tGENE1\n", encoding="utf-8")

    page = ImportPage(project_root=tmp_path / "projects")
    loaded_paths: list[tuple[Path, ...]] = []
    monkeypatch.setattr(page, "load_paths", lambda paths: loaded_paths.append(tuple(paths)))
    interaction: dict[str, object] = {}

    def drive_dialog() -> None:
        if interaction.get("dialog") is not None or interaction.get("timed_out"):
            return
        active_modal = application.activeModalWidget()
        if not isinstance(active_modal, QFileDialog):
            QTimer.singleShot(10, drive_dialog)
            return
        dialog = active_modal

        interaction["dialog"] = dialog
        try:
            interaction["non_native"] = dialog.testOption(QFileDialog.Option.DontUseNativeDialog)
            interaction["file_mode"] = dialog.fileMode()
            interaction["accept_mode"] = dialog.acceptMode()
            interaction["show_dirs_only"] = dialog.testOption(QFileDialog.Option.ShowDirsOnly)
            interaction["filters"] = dialog.nameFilters()

            line_edit = dialog.findChild(QLineEdit, "fileNameEdit")
            models = dialog.findChildren(QFileSystemModel)
            interaction["line_edit_found"] = line_edit is not None
            interaction["completer_disabled"] = line_edit is not None and line_edit.completer() is None
            interaction["model_watch_options"] = [
                model.testOption(QFileSystemModel.Option.DontWatchForChanges)
                for model in models
            ]

            button_box = dialog.findChild(QDialogButtonBox)
            if button_box is None:
                raise RuntimeError("QFileDialog button box was not found")

            if accept:
                if line_edit is None:
                    raise RuntimeError("QFileDialog filename input was not found")
                open_button = button_box.button(QDialogButtonBox.StandardButton.Open)
                if open_button is None:
                    raise RuntimeError("QFileDialog Open button was not found")
                line_edit.setFocus()
                line_edit.clear()
                QTest.keyClicks(line_edit, target_name)
                application.processEvents()
                QTest.mouseClick(open_button, Qt.MouseButton.LeftButton)
                interaction["open_button_clicked"] = True
            else:
                cancel_button = button_box.button(QDialogButtonBox.StandardButton.Cancel)
                if cancel_button is None:
                    raise RuntimeError("QFileDialog Cancel button was not found")
                QTest.mouseClick(cancel_button, Qt.MouseButton.LeftButton)
                interaction["cancel_button_clicked"] = True

            interaction["selected_files"] = dialog.selectedFiles()
            interaction["dialog_result"] = dialog.result()
        except Exception as error:  # Keep Qt timer exceptions visible to pytest assertions.
            interaction["error"] = repr(error)
            dialog.reject()

    def reject_on_timeout() -> None:
        interaction["timed_out"] = True
        modal = application.activeModalWidget()
        if modal is not None:
            modal.reject()

    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(reject_on_timeout)
    timeout.start(5000)
    QTimer.singleShot(0, drive_dialog)
    getattr(page, chooser_name)()
    timeout.stop()

    assert "error" not in interaction, interaction.get("error")
    assert not interaction.get("timed_out", False)
    assert interaction["non_native"] is True
    assert interaction["file_mode"] == file_mode
    assert interaction["accept_mode"] == QFileDialog.AcceptMode.AcceptOpen
    assert interaction["show_dirs_only"] is show_dirs_only
    assert interaction["line_edit_found"] is True
    assert interaction["completer_disabled"] is True
    model_watch_options = interaction["model_watch_options"]
    assert model_watch_options
    assert all(model_watch_options)
    if expected_filter is not None:
        assert any(expected_filter in name_filter for name_filter in interaction["filters"])

    if accept:
        assert interaction["open_button_clicked"] is True
        assert interaction["dialog_result"] == QDialog.DialogCode.Accepted
        selected_files = interaction["selected_files"]
        assert len(selected_files) == 1
        assert Path(selected_files[0]).resolve() == target.resolve()
        if chooser_name == "choose_reference":
            assert page.reference_path is not None
            assert page.reference_path.resolve() == target.resolve()
        else:
            assert len(loaded_paths) == 1
            assert tuple(path.resolve() for path in loaded_paths[0]) == (target.resolve(),)
    else:
        assert interaction["cancel_button_clicked"] is True
        assert interaction["dialog_result"] == QDialog.DialogCode.Rejected
        assert loaded_paths == []
        if chooser_name == "choose_reference":
            assert page.reference_path is None

    dialog = interaction["dialog"]
    assert isinstance(dialog, QFileDialog)
    dialog.close()
    dialog.deleteLater()
    page.close()
    page.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()
