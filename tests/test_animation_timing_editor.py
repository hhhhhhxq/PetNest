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
