"""User-visible library selection, permission guidance and layout regressions."""

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, Qt

from petnest.core.package_loader import PackageLoader
from petnest.ui.pet_action_exchange_dialog import PetActionExchangeDialog


@pytest.fixture
def library(qtbot, tmp_path):
    cat = PackageLoader().load(
        Path(__file__).resolve().parents[1] / "pets/keyboard_cat"
    )
    saved = {"keys": True, "coat": "black", "keyboard": "cream"}
    status = ["监听正常"]
    dialog = PetActionExchangeDialog(
        [cat],
        tmp_path,
        current_pet_id=cat.identifier,
        preferences=lambda _: dict(saved),
        save_preferences=lambda _, value: saved.update(value),
        input_status=lambda: status[0],
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(10)
    return dialog, saved, status


def test_visual_choices_apply_without_switching_pet(library, qtbot):
    dialog, saved, _ = library
    page = dialog.my_pets_page
    before = page.preview._pixmap.toImage()
    qtbot.mouseClick(page.coat.buttons[1], Qt.MouseButton.LeftButton)
    qtbot.mouseClick(page.keyboard.buttons[1], Qt.MouseButton.LeftButton)
    assert saved["coat"] == "siamese"
    assert saved["keyboard"] == "dark"
    assert page.preview._pixmap.toImage() != before
    assert not page.footer_state().primary_enabled
    assert sum(b.isChecked() for b in page.coat.buttons) == 1
    assert all(not b.icon().isNull() for b in page.keyboard.buttons)


def test_permission_guidance_changes_with_actual_state(library):
    dialog, _, status = library
    page = dialog.my_pets_page
    assert "已连接" in page.permission_status.text()
    assert page.permission_button.isHidden() and page.retry_button.isHidden()
    page.keys.setChecked(False)
    assert "已关闭" in page.permission_status.text()
    status[0] = "需要允许 PetNest 的输入监控"
    page.keys.setChecked(True)
    if __import__("sys").platform == "darwin":
        assert not page.permission_button.isHidden()
        assert "输入监控" in page.input_explanation.text()
    page._current_id = "another-pet"
    page._sync_status()
    assert "使用这只宠物后生效" == page.permission_status.text()
    assert page.permission_button.isHidden() and page.retry_button.isHidden()


@pytest.mark.parametrize("size", [(1220, 760), (1180, 680)])
def test_preview_and_controls_never_overlap_in_permission_flow(library, qtbot, size):
    dialog, _, status = library
    page = dialog.my_pets_page
    status[0] = "需要允许 PetNest 的输入监控"
    page._sync_status()
    dialog.resize(*size)
    qtbot.wait(10)
    cards = [page.preview_card, page.outfit, page.interaction_card, page.input_card]
    for index, card in enumerate(cards):
        assert page.detail.rect().contains(card.geometry())
        for other in cards[index + 1 :]:
            assert not card.geometry().intersects(other.geometry())
    for widget in (
        page.preview,
        page.scale,
        page.permission_status,
        page.permission_button,
        page.retry_button,
        page.privacy,
    ):
        rect = widget.rect().translated(widget.mapTo(widget.parentWidget(), QPoint()))
        assert widget.parentWidget().rect().contains(rect)
    assert page.detail_scroll.horizontalScrollBar().maximum() == 0
    # Content below the viewport remains reachable instead of being clipped.
    page.detail_scroll.ensureWidgetVisible(page.privacy)
    qtbot.wait(10)
    viewport = page.detail_scroll.viewport()
    assert viewport.rect().contains(
        page.privacy.mapTo(viewport, page.privacy.rect().center())
    )
