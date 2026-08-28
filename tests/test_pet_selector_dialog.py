from __future__ import annotations

from pathlib import Path

from petnest.ui.pet_selector_dialog import PetSelectorDialog
from tests.test_pet_window import _package


def test_pet_selector_uses_shared_light_theme(qtbot: object, tmp_path: Path) -> None:
    dialog = PetSelectorDialog((_package(tmp_path),))
    qtbot.addWidget(dialog)

    assert "PingFang SC" in dialog.styleSheet()
    assert "#746B66" in dialog.styleSheet()
