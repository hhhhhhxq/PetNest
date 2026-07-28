"""动作速度编辑器的展示和本地覆盖输出测试。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt

from tests.test_pet_window import _package
from petnest.ui.animation_editor_dialog import AnimationEditorDialog


def test_editor_shows_total_mode_and_returns_shareable_frame_durations(qtbot: object, tmp_path: Path) -> None:
    dialog = AnimationEditorDialog(_package(tmp_path))
    qtbot.addWidget(dialog)
    dialog.show()

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
