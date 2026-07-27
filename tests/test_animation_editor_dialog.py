"""动作速度编辑器的展示和本地覆盖输出测试。"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from tests.test_pet_window import _package
from petnest.models.settings import AnimationOverride
from petnest.ui.animation_editor_dialog import AnimationEditorDialog


def test_editor_lists_actions_and_returns_only_local_override(qtbot: object, tmp_path: Path) -> None:
    dialog = AnimationEditorDialog(_package(tmp_path), {"idle": AnimationOverride(1.25, (200, 80))})
    qtbot.addWidget(dialog)
    dialog.show()

    assert dialog.action_table.rowCount() == 5
    assert "默认待机" in dialog.action_table.item(0, 1).text()
    dialog.action_table.selectRow(0)
    dialog.speed_spin.setValue(1.5)

    overrides = dialog.updated_overrides()
    assert overrides["idle"].speed_multiplier == 1.5
    assert overrides["idle"].frame_durations_ms == (200, 80)
