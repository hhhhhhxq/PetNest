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
    InteractionItemPanel,
    InteractionItemToolbox,
    clamp_toolbox_position,
)


def _resolved_item(
    tmp_path: Path, identifier: str, label: str | None = None
) -> ResolvedInteractionItem:
    icon = tmp_path / f"{identifier}.png"
    Image.new("RGBA", (24, 24), (217, 134, 99, 255)).save(icon)
    definition = InteractionItemDefinition(identifier, label or f"Item {identifier}", icon)
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
    assert button.toolTip() == "拖动 Item toy_ball 到宠物身上"
    assert button.accessibleName() == item.definition.label
    assert button.iconSize() == QSize(44, 44)
    assert button.size() == QSize(68, 88)
    assert not button.icon().isNull()


def test_item_button_advertises_dragging(qtbot, tmp_path: Path) -> None:
    item = _resolved_item(tmp_path, "toy_ball")
    button = InteractionItemButton(item)
    qtbot.addWidget(button)
    button.show()

    assert button.objectName() == "interactionItemButton"
    assert button.cursor().shape() == Qt.CursorShape.OpenHandCursor
    assert button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextUnderIcon
    assert button.text() == button.fontMetrics().elidedText(
        item.definition.label,
        Qt.TextElideMode.ElideRight,
        60,
    )
    assert button.property("lifted") is False
    assert not hasattr(button, "contact_shadow_rect")

    button.enterEvent(QEnterEvent(QPointF(), QPointF(), QPointF()))
    assert button.property("lifted") is True
    assert button.iconSize() == QSize(48, 48)

    qtbot.mousePress(button, Qt.MouseButton.LeftButton)
    assert button.cursor().shape() == Qt.CursorShape.ClosedHandCursor
    qtbot.mouseRelease(button, Qt.MouseButton.LeftButton)
    assert button.cursor().shape() == Qt.CursorShape.OpenHandCursor

    button.leaveEvent(QEvent(QEvent.Type.Leave))
    assert button.property("lifted") is False
    assert button.iconSize() == QSize(44, 44)


def test_interaction_item_panel_loads_transparent_wood_shelf_asset(qtbot) -> None:
    panel = InteractionItemPanel()
    qtbot.addWidget(panel)
    panel.resize(300, 110)
    panel.show()

    assert panel.shelf_asset_path.name == "wood_shelf.png"
    assert panel.shelf_pixmap.size() == QSize(1200, 400)
    source = panel.shelf_pixmap.toImage()
    assert source.pixelColor(600, 20).alpha() == 0
    assert source.pixelColor(600, 260).alpha() > 0
    assert source.pixelColor(600, 320).alpha() == 0
    assert panel.shelf_target_rect().top() == -9
    assert panel.shelf_target_rect().size() == QSize(300, 92)


def test_item_button_elides_long_label_but_keeps_full_accessible_text(
    qtbot, tmp_path: Path
) -> None:
    label = "一个非常非常长的互动道具名称"
    button = InteractionItemButton(_resolved_item(tmp_path, "long", label))
    qtbot.addWidget(button)

    assert button.text().endswith("…")
    assert button.text() != label
    assert button.accessibleName() == label
    assert label in button.toolTip()


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
    assert toolbox.hint_label.text() == "拖给宠物"
    assert [toolbox._item_layout.getItemPosition(index)[:2] for index in range(8)] == [
        (0, 0),
        (0, 1),
        (0, 2),
        (0, 3),
        (1, 0),
        (1, 1),
        (1, 2),
        (1, 3),
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


def test_first_open_plays_drag_hint_once(qtbot, tmp_path: Path) -> None:
    toolbox = InteractionItemToolbox()
    qtbot.addWidget(toolbox)
    toolbox.set_items((_resolved_item(tmp_path, "toy"),))
    starts: list[bool] = []
    toolbox.intro_hint_started.connect(lambda: starts.append(True))

    assert not toolbox.intro_has_played

    toolbox.open_panel()
    first_animation = toolbox._intro_animation
    toolbox.collapse()
    toolbox.open_panel()

    assert starts == [True]
    assert toolbox.intro_has_played
    assert first_animation is not None
    assert toolbox._intro_animation is None


def test_empty_toolbox_does_not_consume_first_open_hint(qtbot, tmp_path: Path) -> None:
    toolbox = InteractionItemToolbox()
    qtbot.addWidget(toolbox)

    toolbox.open_panel()

    assert not toolbox.intro_has_played

    toolbox.set_items((_resolved_item(tmp_path, "later"),))
    toolbox.open_panel()

    assert toolbox.intro_has_played


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


def test_toolbox_uses_translucent_window_and_icon_only_launcher(qtbot) -> None:
    toolbox = InteractionItemToolbox()
    qtbot.addWidget(toolbox)

    assert toolbox.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert toolbox.launcher.objectName() == "interactionItemLauncher"
    assert toolbox.launcher.cursor().shape() == Qt.CursorShape.PointingHandCursor
    assert toolbox.launcher.iconSize() == QSize(25, 25)
    assert "QToolButton#interactionItemLauncher" in toolbox.styleSheet()
    assert "QToolButton {" not in toolbox.styleSheet()

    icon = toolbox.launcher.icon().pixmap(QSize(25, 25)).toImage()
    filled_side = icon.pixelColor(8, 19)
    center_seam = icon.pixelColor(12, 19)
    assert filled_side.alpha() > 0
    assert center_seam.alpha() > 0
    assert center_seam.lightness() + 20 < filled_side.lightness()
