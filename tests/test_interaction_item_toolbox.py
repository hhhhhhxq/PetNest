from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QEvent, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QEnterEvent

from petnest.core.interaction_items import ResolvedInteractionItem
from petnest.models.pet_package import InteractionItemDefinition
from petnest.ui.interaction_item_toolbox import (
    INTERACTION_ITEM_MIME,
    InteractionItemButton,
    InteractionItemToolbox,
    clamp_toolbox_position,
)


def _resolved_item(tmp_path: Path, identifier: str) -> ResolvedInteractionItem:
    icon = tmp_path / f"{identifier}.png"
    Image.new("RGBA", (24, 24), (217, 134, 99, 255)).save(icon)
    definition = InteractionItemDefinition(identifier, f"Item {identifier}", icon)
    return ResolvedInteractionItem(
        definition=definition,
        event_name=f"interaction.item.{identifier}",
        action_name=f"action_{identifier}",
    )


def test_button_mime_contains_only_generic_item_identifier(qtbot, tmp_path: Path) -> None:
    item = _resolved_item(tmp_path, "toy_ball")
    button = InteractionItemButton(item)
    qtbot.addWidget(button)

    mime = button.mime_data()

    assert mime.formats() == [INTERACTION_ITEM_MIME]
    assert bytes(mime.data(INTERACTION_ITEM_MIME)).decode("utf-8") == "toy_ball"
    assert item.action_name.encode() not in bytes(mime.data(INTERACTION_ITEM_MIME))
    assert button.toolTip() == item.definition.label
    assert button.accessibleName() == item.definition.label
    assert button.iconSize() == QSize(36, 36)
    assert button.size() == QSize(52, 52)
    assert not button.icon().isNull()


def test_toolbox_keeps_first_eight_items_in_order_and_opens_or_collapses(
    qtbot, tmp_path: Path
) -> None:
    items = tuple(_resolved_item(tmp_path, str(index)) for index in range(10))
    toolbox = InteractionItemToolbox()
    qtbot.addWidget(toolbox)

    toolbox.set_items(items)

    assert [button.item.definition.identifier for button in toolbox.item_buttons] == [
        str(index) for index in range(8)
    ]
    assert not toolbox.is_expanded
    toolbox.open_panel()
    assert toolbox.is_expanded
    toolbox.collapse()
    assert not toolbox.is_expanded


def test_setting_new_items_detaches_old_buttons_and_empty_items_hide_toolbox(
    qtbot, tmp_path: Path
) -> None:
    toolbox = InteractionItemToolbox()
    qtbot.addWidget(toolbox)
    toolbox.set_items((_resolved_item(tmp_path, "old"),))
    old_button = toolbox.item_buttons[0]
    toolbox.show_for(QRect(20, 20, 40, 40))
    assert toolbox.isVisible()

    toolbox.set_items((_resolved_item(tmp_path, "new"),))

    assert old_button.parent() is None
    assert [button.item.definition.identifier for button in toolbox.item_buttons] == ["new"]

    toolbox.open_panel()
    toolbox.set_items(())

    assert toolbox.item_buttons == ()
    assert not toolbox.is_expanded
    assert not toolbox.isVisible()


def test_clamp_toolbox_position_flips_left_and_clamps_bottom_edge() -> None:
    available = QRect(0, 0, 300, 200)
    size = QSize(120, 80)

    right_edge = clamp_toolbox_position(QRect(270, 80, 20, 20), available, size)
    bottom_edge = clamp_toolbox_position(QRect(100, 190, 20, 20), available, size)

    assert right_edge.x() == 142
    assert bottom_edge.y() == 120
    assert available.contains(QRect(right_edge, size))
    assert available.contains(QRect(bottom_edge, size))


def test_toolbox_has_nonactivating_always_on_top_flags_and_emits_hover(
    qtbot, tmp_path: Path
) -> None:
    toolbox = InteractionItemToolbox()
    qtbot.addWidget(toolbox)
    toolbox.set_items((_resolved_item(tmp_path, "hover"),))
    flags = toolbox.windowFlags()
    hovered: list[bool] = []
    toolbox.hover_changed.connect(hovered.append)

    toolbox.enterEvent(QEnterEvent(QPointF(), QPointF(), QPointF()))
    toolbox.leaveEvent(QEvent(QEvent.Type.Leave))

    assert flags & Qt.WindowType.Tool
    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.WindowDoesNotAcceptFocus
    assert flags & Qt.WindowType.WindowStaysOnTopHint
    assert toolbox.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert hovered == [True, False]
