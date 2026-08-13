"""动作速度编辑器的展示和本地覆盖输出测试。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QHeaderView

from tests.test_pet_window import _package
from petnest.ui.animation_editor_dialog import AnimationEditorDialog
from petnest.ui.theme import COLORS


def test_editor_shows_total_mode_and_returns_shareable_frame_durations(qtbot: object, tmp_path: Path) -> None:
    dialog = AnimationEditorDialog(_package(tmp_path))
    qtbot.addWidget(dialog)
    dialog.show()

    assert dialog.findChild(__import__("PySide6").QtWidgets.QFrame, "windowShell") is not None
    assert dialog.findChild(__import__("PySide6").QtWidgets.QFrame, "previewCard") is not None
    assert dialog.findChild(__import__("PySide6").QtWidgets.QDialogButtonBox).button(
        __import__("PySide6").QtWidgets.QDialogButtonBox.StandardButton.Cancel
    ).text() == "取消"
    assert dialog.preview_card.parentWidget() is not dialog.editor_card
    assert dialog.total_timeline.isVisible()
    assert dialog.editor_heading_label.text().startswith("idle")
    assert dialog.editor_description_label.text()
    assert "checker" in dialog.preview_label.objectName().lower() or dialog.preview_label.property("checkerboard") is True
    assert dialog.action_table.rowCount() == 5
    assert "默认待机" in dialog.action_table.item(0, 1).text()
    dialog.action_table.selectRow(0)
    assert dialog.total_radio.isChecked()
    assert "按总时长播放" in dialog.mode_status_label.text()
    assert dialog.total_duration_spin.value() == 200
    dialog.total_duration_spin.setValue(100)

    durations = dialog.updated_frame_durations()
    assert durations["idle"] == (50, 50)
    assert dialog.applied_summary().endswith("100 ms")


def test_action_list_selection_uses_petnest_accent_instead_of_system_blue(qtbot: object, tmp_path: Path) -> None:
    dialog = AnimationEditorDialog(_package(tmp_path))
    qtbot.addWidget(dialog)

    dialog.action_table.selectRow(0)
    palette = dialog.action_table.palette()

    assert palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.Highlight).name().lower() == COLORS["accent_soft"].lower()
    assert palette.color(QPalette.ColorGroup.Active, QPalette.ColorRole.HighlightedText).name().lower() == COLORS["accent"].lower()
    assert palette.color(QPalette.ColorGroup.Inactive, QPalette.ColorRole.Highlight).name().lower() == COLORS["accent_soft"].lower()


def test_action_list_description_column_expands_with_the_dialog(qtbot: object, tmp_path: Path) -> None:
    dialog = AnimationEditorDialog(_package(tmp_path))
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.resize(1600, 780)
    __import__("PySide6").QtWidgets.QApplication.processEvents()

    header = dialog.action_table.horizontalHeader()
    assert header.sectionResizeMode(0) == QHeaderView.ResizeMode.ResizeToContents
    assert header.sectionResizeMode(1) == QHeaderView.ResizeMode.Stretch
    assert dialog.action_table.wordWrap()
    assert dialog.action_table.verticalHeader().sectionResizeMode(0) == QHeaderView.ResizeMode.ResizeToContents
    assert dialog.action_table.columnWidth(1) > 180


def test_editor_minimum_size_keeps_all_columns_and_frame_list_inside_their_cards(
    qtbot: object, tmp_path: Path
) -> None:
    dialog = AnimationEditorDialog(_package(tmp_path))
    qtbot.addWidget(dialog)
    dialog.resize(dialog.minimumSize())
    dialog.show()
    __import__("PySide6").QtWidgets.QApplication.processEvents()

    assert dialog.minimumWidth() == 1080
    assert dialog.preview_card.isHidden()
    assert dialog.action_card.geometry().right() < dialog.editor_card.geometry().left()

    dialog.per_frame_radio.click()
    __import__("PySide6").QtWidgets.QApplication.processEvents()

    assert dialog.frame_list.geometry().right() <= dialog.editor_card.rect().right()


def test_advanced_frame_editor_is_reset_when_switching_actions(qtbot: object, tmp_path: Path) -> None:
    dialog = AnimationEditorDialog(_package(tmp_path))
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.action_table.selectRow(0)

    assert dialog.total_radio.isChecked()
    dialog.per_frame_radio.click()
    assert not dialog.total_duration_spin.isEnabled()
    assert dialog.duration_table.isVisible()

    dialog.action_table.selectRow(1)
    assert dialog.total_radio.isChecked()
    assert dialog.duration_table.isHidden()


def test_per_frame_editor_shows_a_thumbnail_for_each_animation_frame(qtbot: object, tmp_path: Path) -> None:
    dialog = AnimationEditorDialog(_package(tmp_path))
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.per_frame_radio.click()

    assert dialog.frame_list.count() == len(dialog._package.animations["idle"].frames)
    assert not dialog.frame_list.item(0).icon().isNull()
    assert dialog.frame_list.item(1).data(Qt.ItemDataRole.UserRole) == 1


def test_preview_loops_current_timeline_and_restarts_after_duration_change(qtbot: object, tmp_path: Path) -> None:
    dialog = AnimationEditorDialog(_package(tmp_path))
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.total_duration_spin.setValue(100)

    assert dialog.preview_frame_index == 0
    assert dialog.preview_timer.interval() == 50
    dialog._advance_preview()
    assert dialog.preview_frame_index == 1


def test_clicking_thumbnail_pauses_preview_on_that_frame_and_close_stops_timer(qtbot: object, tmp_path: Path) -> None:
    dialog = AnimationEditorDialog(_package(tmp_path))
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.per_frame_radio.click()

    dialog.frame_list.itemClicked.emit(dialog.frame_list.item(1))

    assert dialog.preview_frame_index == 1
    assert not dialog.preview_timer.isActive()
    dialog.close()
    assert not dialog.preview_timer.isActive()


def test_preview_highlight_does_not_change_the_frame_list_selection(qtbot: object, tmp_path: Path) -> None:
    dialog = AnimationEditorDialog(_package(tmp_path))
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.per_frame_radio.click()
    dialog.frame_list.setCurrentRow(0)

    dialog._advance_preview()

    assert dialog.preview_frame_index == 1
    assert dialog.frame_list.currentRow() == 0


def test_preview_moves_highlight_between_only_the_previous_and_current_rows(qtbot: object, tmp_path: Path) -> None:
    dialog = AnimationEditorDialog(_package(tmp_path))
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.per_frame_radio.click()

    assert dialog._highlighted_frame_index == 0
    dialog._advance_preview()

    assert dialog._highlighted_frame_index == 1
    assert dialog.frame_list.itemWidget(dialog.frame_list.item(0)).styleSheet() == ""
    assert "background" in dialog.frame_list.itemWidget(dialog.frame_list.item(1)).styleSheet()
