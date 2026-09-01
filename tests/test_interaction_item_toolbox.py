from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QEnterEvent, QGuiApplication
from PySide6.QtWidgets import QBoxLayout

from petnest.core.interaction_items import ResolvedInteractionItem
from petnest.models.pet_package import InteractionItemDefinition
from petnest.ui.interaction_item_toolbox import (
    INTERACTION_ITEM_MIME,
    InteractionItemButton,
    InteractionItemPanel,
    InteractionItemToolbox,
    LauncherArcPlacement,
    plan_launcher_arc,
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


def test_plan_launcher_arc_uses_right_outer_top_c_shape_by_default() -> None:
    placement = plan_launcher_arc(
        QRect(200, 100, 80, 100),
        QRect(0, 0, 800, 600),
        QSize(0, 0),
        expanded=False,
    )

    assert isinstance(placement, LauncherArcPlacement)
    assert placement.side == "right"
    assert placement.window_position == QPoint(288, 78)
    assert placement.canvas_offset == QPoint(0, 0)
    assert placement.toolbox_position == QPoint(0, 0)
    assert placement.notebook_position == QPoint(43, 35)


def test_plan_launcher_arc_mirrors_the_whole_pair_near_right_edge() -> None:
    placement = plan_launcher_arc(
        QRect(720, 100, 60, 100),
        QRect(0, 0, 800, 600),
        QSize(0, 0),
        expanded=False,
    )

    assert placement.side == "left"
    assert placement.window_position == QPoint(625, 78)
    assert placement.toolbox_position == QPoint(43, 0)
    assert placement.notebook_position == QPoint(0, 35)
    assert placement.notebook_position - placement.toolbox_position == QPoint(-43, 35)


def test_plan_launcher_arc_shifts_both_buttons_down_at_top_edge() -> None:
    placement = plan_launcher_arc(
        QRect(200, 5, 80, 100),
        QRect(0, 0, 800, 600),
        QSize(0, 0),
        expanded=False,
    )

    assert placement.window_position.y() == 0
    assert placement.notebook_position - placement.toolbox_position == QPoint(43, 35)


def test_expanded_arc_panel_stays_outside_pet_on_both_sides() -> None:
    available = QRect(0, 0, 800, 600)
    panel_size = QSize(300, 190)
    right_pet = QRect(150, 150, 80, 100)
    left_pet = QRect(700, 150, 60, 100)

    right = plan_launcher_arc(right_pet, available, panel_size, expanded=True)
    left = plan_launcher_arc(left_pet, available, panel_size, expanded=True)
    right_panel = QRect(
        right.window_position + right.canvas_offset + QPoint(87 + 6, 0),
        panel_size,
    )
    left_panel = QRect(left.window_position, panel_size)

    assert right.side == "right"
    assert left.side == "left"
    assert not right_panel.intersects(right_pet)
    assert not left_panel.intersects(left_pet)
    assert available.contains(QRect(right.window_position, QSize(393, 190)))
    assert available.contains(QRect(left.window_position, QSize(393, 190)))


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


def test_matching_toolbox_and_notebook_launchers(qtbot) -> None:
    toolbox = InteractionItemToolbox()
    qtbot.addWidget(toolbox)

    toolbox.set_notebook_enabled(True)

    assert toolbox.launcher.size() == QSize(44, 44)
    assert toolbox.notebook_launcher.size() == QSize(44, 44)
    assert toolbox.launcher.iconSize() == QSize(25, 25)
    assert toolbox.notebook_launcher.iconSize() == QSize(25, 25)
    assert toolbox.launcher_canvas.size() == QSize(87, 79)
    assert toolbox.launcher.geometry() == QRect(0, 0, 44, 44)
    assert toolbox.notebook_launcher.geometry() == QRect(43, 35, 44, 44)
    delta = toolbox.notebook_launcher.geometry().center() - toolbox.launcher.geometry().center()
    assert delta == QPoint(43, 35)
    assert round((delta.x() ** 2 + delta.y() ** 2) ** 0.5, 1) == 55.4
    assert toolbox.launcher.hitButton(QPoint(43, 43))
    assert toolbox.notebook_launcher.hitButton(QPoint(43, 43))
    assert toolbox.notebook_launcher.accessibleName() == "便签本"
    assert not toolbox.notebook_launcher.icon().isNull()


def test_toolbox_applies_mirrored_arc_and_panel_direction(qtbot, tmp_path: Path) -> None:
    toolbox = InteractionItemToolbox()
    qtbot.addWidget(toolbox)
    toolbox.set_items((_resolved_item(tmp_path, "toy"),))
    toolbox.set_notebook_enabled(True)

    toolbox._apply_arc_side("left")

    assert toolbox.launcher.pos() == QPoint(43, 0)
    assert toolbox.notebook_launcher.pos() == QPoint(0, 35)
    assert toolbox.layout().direction() == QBoxLayout.Direction.RightToLeft


def test_reposition_mirrors_actual_toolbox_near_screen_right_edge(
    qtbot, tmp_path: Path
) -> None:
    screen = QGuiApplication.primaryScreen()
    assert screen is not None
    available = screen.availableGeometry()
    pet_rect = QRect(available.right() - 39, available.top() + 100, 40, 100)
    toolbox = InteractionItemToolbox()
    qtbot.addWidget(toolbox)
    toolbox.set_items((_resolved_item(tmp_path, "toy"),))
    toolbox.set_notebook_enabled(True)

    toolbox.show_for(pet_rect)

    assert toolbox._arc_side == "left"
    assert toolbox.layout().direction() == QBoxLayout.Direction.RightToLeft
    assert available.contains(toolbox.frameGeometry())


def test_notebook_launcher_survives_empty_items(qtbot) -> None:
    toolbox = InteractionItemToolbox()
    qtbot.addWidget(toolbox)
    requests: list[bool] = []
    toolbox.notebook_requested.connect(lambda: requests.append(True))
    toolbox.set_items(())
    toolbox.set_notebook_enabled(True)

    toolbox.show_for(QRect(20, 20, 80, 80))

    assert toolbox.isVisible()
    assert not toolbox.launcher.isVisible()
    assert toolbox.notebook_launcher.isVisible()
    toolbox.notebook_launcher.click()
    assert requests == [True]
