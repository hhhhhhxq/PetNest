"""Tests for the reusable animation timing editor content widget."""

from __future__ import annotations

from pathlib import Path

from tests.test_pet_window import _package
from petnest.ui.animation_editor_dialog import AnimationEditorDialog
from petnest.ui.animation_timing_editor import AnimationTimingEditor


def test_timing_editor_tracks_and_restores_only_current_action(qtbot: object, tmp_path: Path) -> None:
    editor = AnimationTimingEditor(_package(tmp_path))
    qtbot.addWidget(editor)
    editor.action_table.selectRow(0)
    original = editor.total_duration_spin.value()
    editor.total_duration_spin.setValue(original + 100)

    assert editor.is_dirty()
    assert "idle" in editor.updated_frame_durations()
    editor.restore_current_action()
    assert not editor.is_dirty()
    assert editor.total_duration_spin.value() == original


def test_legacy_animation_dialog_wraps_timing_editor(qtbot: object, tmp_path: Path) -> None:
    dialog = AnimationEditorDialog(_package(tmp_path))
    qtbot.addWidget(dialog)

    assert isinstance(dialog.editor, AnimationTimingEditor)
    assert dialog.action_table is dialog.editor.action_table
    assert dialog.updated_frame_durations() == dialog.editor.updated_frame_durations()


def test_timing_editor_syncs_frame_highlight_on_real_preview_tick(qtbot: object, tmp_path: Path) -> None:
    editor = AnimationTimingEditor(_package(tmp_path))
    qtbot.addWidget(editor)
    editor.preview.set_frames(
        editor._package.animations["idle"].frames,
        frame_durations_ms=(25, 25),
    )

    qtbot.waitUntil(lambda: editor.preview_frame_index == 1, timeout=1000)

    assert editor._highlighted_frame_index == editor.preview_frame_index == 1


def test_timing_editor_uses_prototype_three_column_minimums(qtbot: object, tmp_path: Path) -> None:
    editor = AnimationTimingEditor(_package(tmp_path))
    qtbot.addWidget(editor)
    editor.resize(1000, 620)
    editor.show()
    qtbot.wait(10)

    assert editor.action_card.minimumWidth() == 205
    assert editor.editor_card.minimumWidth() == 360
    assert editor.preview_card.minimumWidth() == 260
    assert editor.preview_card.isVisible()


def test_action_selection_syncs_thumbnail_and_preview_metadata(qtbot: object, tmp_path: Path) -> None:
    editor = AnimationTimingEditor(_package(tmp_path))
    qtbot.addWidget(editor)
    editor.action_table.selectRow(0)

    action_item = editor.action_table.item(0, 0)
    assert action_item is not None
    assert not action_item.icon().isNull()
    assert editor.preview_action_value.text() == "idle"
    assert editor.preview_frame_count_value.text() == "2"
    assert editor.preview_loop_value.text() == "是"
    assert editor.preview_replay_button.text() == "重播"


def test_action_thumbnails_do_not_decode_every_animation_upfront(qtbot: object, tmp_path: Path) -> None:
    editor = AnimationTimingEditor(_package(tmp_path))
    qtbot.addWidget(editor)

    assert set(editor._preview_pixmaps) == {"idle"}


def test_action_thumbnail_column_is_wide_enough_for_complete_icon(qtbot: object, tmp_path: Path) -> None:
    editor = AnimationTimingEditor(_package(tmp_path))
    qtbot.addWidget(editor)
    editor.show()
    qtbot.wait(10)

    assert editor.action_table.columnWidth(0) >= editor.action_table.iconSize().width() + 12
    assert editor.action_table.horizontalScrollBar().maximum() == 0
    assert editor.action_table.item(0, 0).text() == ""
    assert editor.action_table.item(0, 1).text().startswith("idle\n")
