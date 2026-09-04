from __future__ import annotations

from pathlib import Path

from PIL import Image
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QEnterEvent, QGuiApplication, QImage, QPainter
from PySide6.QtWidgets import QBoxLayout

from petnest.core.interaction_items import ResolvedInteractionItem
from petnest.models.pet_package import InteractionItemDefinition
from petnest.ui.interaction_item_toolbox import (
    INTERACTION_ITEM_MIME,
    InteractionItemButton,
    InteractionItemPanel,
    InteractionItemToolbox,
    LauncherArcPlacement,
    place_interaction_panel,
    plan_launcher_arc,
)


def _resolved_item(
    tmp_path: Path, identifier: str, label: str | None = None
) -> ResolvedInteractionItem:
    icon = tmp_path / f"{identifier}.png"
    Image.new("RGBA", (24, 24), (217, 134, 99, 255)).save(icon)
    definition = InteractionItemDefinition(
        identifier, label or f"Item {identifier}", icon
    )
    return ResolvedInteractionItem(
        definition=definition,
        event_name=f"interaction.item.{identifier}",
        action_name=f"action_{identifier}",
    )


def test_button_mime_contains_only_generic_item_identifier(
    qtbot, tmp_path: Path
) -> None:
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
    assert button.size() == QSize(70, 78)
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


def test_item_button_emits_drag_lifecycle(qtbot, tmp_path: Path, monkeypatch) -> None:
    button = InteractionItemButton(_resolved_item(tmp_path, "toy_ball"))
    qtbot.addWidget(button)
    events: list[tuple[str, str, object | None]] = []
    button.drag_started.connect(lambda item_id: events.append(("start", item_id, None)))
    button.drag_finished.connect(
        lambda item_id, result: events.append(("finish", item_id, result))
    )
    monkeypatch.setattr(
        button,
        "_execute_drag",
        lambda _drag: Qt.DropAction.MoveAction,
    )

    result = button._start_drag()

    assert result == Qt.DropAction.MoveAction
    assert events == [
        ("start", "toy_ball", None),
        ("finish", "toy_ball", Qt.DropAction.MoveAction),
    ]


def test_toolbox_relays_item_drag_lifecycle(qtbot, tmp_path: Path) -> None:
    toolbox = InteractionItemToolbox()
    qtbot.addWidget(toolbox)
    toolbox.set_items((_resolved_item(tmp_path, "toy"),))
    events: list[tuple[str, object | None]] = []
    toolbox.item_drag_started.connect(lambda item_id: events.append((item_id, None)))
    toolbox.item_drag_finished.connect(
        lambda item_id, result: events.append((item_id, result))
    )

    button = toolbox.item_buttons[0]
    button.drag_started.emit("toy")
    button.drag_finished.emit("toy", Qt.DropAction.IgnoreAction)

    assert events == [
        ("toy", None),
        ("toy", Qt.DropAction.IgnoreAction),
    ]


def test_item_button_keeps_text_inside_label_chip_with_or_without_icon(
    qtbot, tmp_path: Path
) -> None:
    toolbox = InteractionItemToolbox()
    qtbot.addWidget(toolbox)
    toolbox.set_items((_resolved_item(tmp_path, "toy"),))
    button = toolbox.item_buttons[0]
    toolbox.show()
    qtbot.wait(1)

    def dark_text_rows() -> list[int]:
        image = QImage(button.size(), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor(0, 0, 0, 0))
        painter = QPainter(image)
        button.render(painter, QPoint())
        painter.end()
        return [
            y
            for y in range(40, button.height() - 4)
            if any(
                image.pixelColor(x, y).alpha() > 80
                and image.pixelColor(x, y).lightness() < 110
                for x in range(8, button.width() - 8)
            )
        ]

    normal_rows = dark_text_rows()
    button._set_dragging_visual(True)
    dragging_rows = dark_text_rows()

    assert normal_rows and min(normal_rows) >= 54 and max(normal_rows) <= 73
    assert dragging_rows and min(dragging_rows) >= 54 and max(dragging_rows) <= 73


def test_item_button_preserves_non_square_icon_aspect_ratio(
    qtbot, tmp_path: Path
) -> None:
    icon_path = tmp_path / "wide.png"
    Image.new("RGBA", (80, 40), (5, 250, 5, 255)).save(icon_path)
    item = ResolvedInteractionItem(
        definition=InteractionItemDefinition("wide", "Wide", icon_path),
        event_name="interaction.item.wide",
        action_name="action_wide",
    )
    button = InteractionItemButton(item)
    qtbot.addWidget(button)
    button.show()

    image = QImage(button.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    button.render(painter, QPoint())
    painter.end()
    green_pixels = [
        (x, y)
        for y in range(button.height())
        for x in range(button.width())
        if image.pixelColor(x, y).green() > 235
        and image.pixelColor(x, y).red() < 20
        and image.pixelColor(x, y).blue() < 20
    ]

    assert green_pixels
    xs = [point[0] for point in green_pixels]
    ys = [point[1] for point in green_pixels]
    assert max(xs) - min(xs) + 1 == 44
    assert max(ys) - min(ys) + 1 == 22


def test_interaction_item_panel_is_a_transparent_card_container(qtbot) -> None:
    panel = InteractionItemPanel()
    qtbot.addWidget(panel)
    panel.resize(300, 110)
    panel.show()

    image = QImage(panel.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    panel.render(painter, QPoint())
    painter.end()

    assert image.pixelColor(150, 55).alpha() == 0
    assert not hasattr(panel, "shelf_pixmap")


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


def test_toolbox_keeps_all_items_in_three_column_rows_and_opens_or_collapses(
    qtbot, tmp_path: Path
) -> None:
    items = tuple(_resolved_item(tmp_path, str(index)) for index in range(10))
    toolbox = InteractionItemToolbox()
    qtbot.addWidget(toolbox)

    toolbox.set_items(items)

    assert [button.item.definition.identifier for button in toolbox.item_buttons] == [
        str(index) for index in range(10)
    ]
    assert toolbox.hint_label.text() == "拖给宠物"
    assert [toolbox._item_layout.getItemPosition(index)[:2] for index in range(10)] == [
        (0, 0),
        (0, 1),
        (0, 2),
        (1, 0),
        (1, 1),
        (1, 2),
        (2, 0),
        (2, 1),
        (2, 2),
        (3, 0),
    ]
    assert not toolbox.is_expanded
    toolbox.open_panel()
    toolbox.show()
    qtbot.wait(1)
    assert toolbox.is_expanded
    assert toolbox._item_grid.height() > toolbox._item_scroll.viewport().height()
    scroll_bar = toolbox._item_scroll.verticalScrollBar()
    assert scroll_bar.maximum() > 0
    scroll_bar.setValue(scroll_bar.maximum())
    assert scroll_bar.value() == scroll_bar.maximum()
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
    assert [button.item.definition.identifier for button in toolbox.item_buttons] == [
        "new"
    ]

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
    right_anchor = QRect(right.window_position, QSize(87, 79))
    left_anchor = QRect(left.window_position, QSize(87, 79))
    right_panel = QRect(
        place_interaction_panel(
            right_anchor,
            right_pet,
            panel_size,
            available,
            preferred_side=right.side,
        ),
        panel_size,
    )
    left_panel = QRect(
        place_interaction_panel(
            left_anchor,
            left_pet,
            panel_size,
            available,
            preferred_side=left.side,
        ),
        panel_size,
    )

    assert right.side == "right"
    assert left.side == "left"
    assert not right_panel.intersects(right_pet)
    assert not left_panel.intersects(left_pet)
    assert not right_panel.intersects(right_anchor)
    assert not left_panel.intersects(left_anchor)
    assert available.contains(right_panel)
    assert available.contains(left_panel)


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
    delta = (
        toolbox.notebook_launcher.geometry().center()
        - toolbox.launcher.geometry().center()
    )
    assert delta == QPoint(43, 35)
    assert round((delta.x() ** 2 + delta.y() ** 2) ** 0.5, 1) == 55.4
    assert toolbox.launcher.hitButton(QPoint(43, 43))
    assert toolbox.notebook_launcher.hitButton(QPoint(43, 43))
    assert toolbox.notebook_launcher.accessibleName() == "便签本"
    assert not toolbox.notebook_launcher.icon().isNull()


def test_toolbox_applies_mirrored_arc_and_panel_direction(
    qtbot, tmp_path: Path
) -> None:
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


def test_opening_panel_keeps_launcher_under_cursor_near_screen_edge(
    qtbot, tmp_path: Path
) -> None:
    screen = QGuiApplication.primaryScreen()
    assert screen is not None
    available = screen.availableGeometry()
    pet_rect = QRect(
        available.right() - 179,
        available.top() + 100,
        80,
        100,
    )
    toolbox = InteractionItemToolbox()
    qtbot.addWidget(toolbox)
    toolbox.set_items(tuple(_resolved_item(tmp_path, str(index)) for index in range(5)))

    toolbox.show_for(pet_rect)
    qtbot.wait(1)
    before = toolbox.launcher.mapToGlobal(QPoint())

    toolbox.open_panel()
    qtbot.wait(1)

    assert toolbox.launcher.mapToGlobal(QPoint()) == before
    assert toolbox.panel.isWindow()
    assert available.contains(toolbox.panel.frameGeometry())

    toolbox.collapse()
    qtbot.wait(1)

    assert toolbox.launcher.mapToGlobal(QPoint()) == before


def test_separate_panel_relays_hover_to_toolbox(qtbot) -> None:
    toolbox = InteractionItemToolbox()
    qtbot.addWidget(toolbox)
    hovered: list[bool] = []
    toolbox.hover_changed.connect(hovered.append)

    toolbox.panel.enterEvent(QEnterEvent(QPointF(), QPointF(), QPointF()))
    toolbox.panel.leaveEvent(QEvent(QEvent.Type.Leave))

    assert hovered == [True, False]


def test_detached_panel_visibility_follows_toolbox_owner(qtbot, tmp_path: Path) -> None:
    screen = QGuiApplication.primaryScreen()
    assert screen is not None
    toolbox = InteractionItemToolbox()
    qtbot.addWidget(toolbox)
    toolbox.set_items((_resolved_item(tmp_path, "toy"),))

    toolbox.open_panel()
    qtbot.wait(1)

    assert toolbox.is_expanded
    assert not toolbox.panel.isVisible()

    toolbox.show_for(QRect(screen.availableGeometry().topLeft(), QSize(80, 100)))
    toolbox.open_panel()
    qtbot.wait(1)
    assert toolbox.panel.isVisible()

    toolbox.hide()
    qtbot.wait(1)

    assert not toolbox.panel.isVisible()


def test_panel_can_use_space_above_pet_without_overlapping_anchor() -> None:
    available = QRect(0, 0, 800, 600)
    pet_rect = QRect(650, 450, 80, 100)
    anchor_rect = QRect(738, 428, 62, 79)
    panel_size = QSize(300, 190)

    point = place_interaction_panel(
        anchor_rect,
        pet_rect,
        panel_size,
        available,
        preferred_side="right",
    )
    panel_rect = QRect(point, panel_size)

    assert point.y() == anchor_rect.top() - 6 - panel_size.height()
    assert available.contains(panel_rect)
    assert not panel_rect.intersects(anchor_rect)
    assert not panel_rect.intersects(pet_rect)


def test_panel_size_is_capped_to_small_screen_with_both_scroll_directions(
    qtbot, tmp_path: Path
) -> None:
    toolbox = InteractionItemToolbox()
    qtbot.addWidget(toolbox)
    toolbox.set_items(
        tuple(_resolved_item(tmp_path, str(index)) for index in range(10))
    )

    toolbox._fit_contents(QSize(200, 150))

    assert toolbox.panel.width() <= 200
    assert toolbox.panel.height() <= 150
    assert (
        toolbox._item_scroll.horizontalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )


def test_vertical_scrollbar_never_clips_last_column_at_borderline_width(
    qtbot, tmp_path: Path
) -> None:
    toolbox = InteractionItemToolbox()
    qtbot.addWidget(toolbox)
    toolbox.set_items(
        tuple(_resolved_item(tmp_path, str(index)) for index in range(10))
    )

    toolbox._fit_contents(QSize(228, 300))

    assert toolbox._item_scroll.viewport().width() < toolbox._item_grid.width()
    assert (
        toolbox._item_scroll.horizontalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )


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


def test_notebook_only_launcher_uses_the_inner_arc_slot_on_both_sides(qtbot) -> None:
    toolbox = InteractionItemToolbox()
    qtbot.addWidget(toolbox)
    toolbox.set_items(())
    toolbox.set_notebook_enabled(True)

    toolbox._apply_arc_side("right")
    assert toolbox.notebook_launcher.pos() == QPoint(0, 0)

    toolbox._apply_arc_side("left")
    assert toolbox.notebook_launcher.pos() == QPoint(43, 0)
