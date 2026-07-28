"""动作速度编辑器的展示和本地覆盖输出测试。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
