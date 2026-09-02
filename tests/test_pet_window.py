"""PySide6 desktop pet window behavior, exercised without a real display."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QEnterEvent,
    QImage,
    QMouseEvent,
    QPainter,
    QPixmap,
)
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid

from petnest.core.animation_player import AnimationPlayer
from petnest.core.codex_link import CodexLinkSnapshot
from petnest.core.state_machine import PetStateMachine
from petnest.models.event import PetEvent
from petnest.models.pet_package import (
    AnimationDefinition,
    Canvas,
    DisplaySettings,
    InteractionItemDefinition,
    PetPackage,
)
from petnest.ui.interaction_item_toolbox import INTERACTION_ITEM_MIME
from petnest.ui.pet_window import PetWindow, _prepare_translucent_frame, _visible_frame_union
from petnest.ui.tray_icon import PetTrayIcon, application_icon


def _package(tmp_path: Path, *, identifier: str = "cat", colour: tuple[int, int, int, int] = (255, 0, 0, 255)) -> PetPackage:
    animations: dict[str, AnimationDefinition] = {}
    for name, loop, priority, interruptible in (
        ("idle", True, 10, True),
        ("hover", True, 20, True),
        ("click", False, 30, False),
        ("drag", True, 40, False),
        ("drop", False, 35, False),
    ):
        frames: list[Path] = []
        for index, alpha in enumerate((colour[3], 255), start=1):
            path = tmp_path / f"{identifier}-{name}-{index}.png"
            Image.new("RGBA", (10, 8), (*colour[:3], alpha)).save(path)
            frames.append(path)
        animations[name] = AnimationDefinition(
            name=name,
            path=tmp_path,
            fps=10,
            loop=loop,
            next_animation=None,
            priority=priority,
            interruptible=interruptible,
            frames=tuple(frames),
        )
    return PetPackage(
        root=tmp_path,
        identifier=identifier,
        name=identifier,
        version="1",
        canvas=Canvas(10, 8),
        animations=animations,
        bindings={
            "mouse.enter": "hover",
            "mouse.leave": "idle",
            "mouse.click": "click",
            "mouse.drag_start": "drag",
            "mouse.drag_end": "drop",
        },
        fallbacks={},
        display=DisplaySettings(default_scale=1.5, alpha_hit_test_threshold=10),
    )


def _window(tmp_path: Path, **kwargs: object) -> PetWindow:
    package = _package(tmp_path)
    return PetWindow(
        package,
        player=AnimationPlayer(),
        state_machine=PetStateMachine(package.animations, package.bindings, package.fallbacks),
        **kwargs,
    )


def _interaction_package(tmp_path: Path, *, identifier: str = "cat") -> PetPackage:
    package = _package(tmp_path, identifier=identifier)
    icon = tmp_path / f"{identifier}-toy-ball.png"
    Image.new("RGBA", (8, 8), (217, 134, 99, 255)).save(icon)
    item = InteractionItemDefinition("toy_ball", "玩具球", icon)
    wave = replace(package.animations["hover"], name="wave", priority=25)
    transparent_then_opaque = Image.new("RGBA", (10, 8), (0, 0, 0, 0))
    transparent_then_opaque.paste((255, 0, 0, 255), (5, 0, 10, 8))
    transparent_then_opaque.save(package.animations["idle"].frames[0])
    return replace(
        package,
        animations={**package.animations, "wave": wave},
        bindings={**package.bindings, "interaction.item.toy_ball": "wave"},
        interaction_items=(item,),
    )


def _visible_anchor_package(tmp_path: Path) -> PetPackage:
    package = _interaction_package(tmp_path)
    first = Image.new("RGBA", (10, 8), (0, 0, 0, 0))
    first.paste((255, 0, 0, 255), (4, 1, 8, 6))
    second = Image.new("RGBA", (10, 8), (0, 0, 0, 0))
    second.paste((255, 0, 0, 255), (2, 2, 9, 7))
    first.save(package.animations["hover"].frames[0])
    second.save(package.animations["hover"].frames[1])
    return package


def _item_mime(identifier: str | bytes, *, format_name: str = INTERACTION_ITEM_MIME) -> QMimeData:
    mime = QMimeData()
    mime.setData(format_name, identifier.encode("utf-8") if isinstance(identifier, str) else identifier)
    return mime


def _drag_enter(mime: QMimeData, position: QPoint = QPoint(12, 2)) -> QDragEnterEvent:
    event = QDragEnterEvent(
        position,
        Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    event._test_mime = mime
    return event


def _drag_move_event(mime: QMimeData, position: QPoint) -> QDragMoveEvent:
    event = QDragMoveEvent(
        position,
        Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    event._test_mime = mime
    return event


def _drop_event(mime: QMimeData, position: QPoint) -> QDropEvent:
    event = QDropEvent(
        QPointF(position),
        Qt.DropAction.MoveAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    event._test_mime = mime
    return event


def _drag_move(window: PetWindow, x: int, y: int) -> None:
    point = QPointF(x, y)
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        point,
        QPointF(window.mapToGlobal(point.toPoint())),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QTest.qWait(1)
    from PySide6.QtWidgets import QApplication

    QApplication.sendEvent(window, event)


def _drag_move_global(window: PetWindow, point: QPoint) -> None:
    local = QPointF(window.rect().center())
    event = QMouseEvent(
        QEvent.Type.MouseMove,
        local,
        QPointF(point),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(window, event)


def test_window_is_transparent_frameless_topmost_and_uses_scaled_canvas(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    window.show()

    assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert window.windowFlags() & Qt.WindowType.Tool
    assert window.windowFlags() & Qt.WindowType.NoDropShadowWindowHint
    assert window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert window.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert window.size().width() == 15


def test_toggling_always_on_top_keeps_visible_window_position(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    window.show()
    window.move(120, 140)
    expected = QPoint(window.pos())

    window.set_always_on_top(False)
    qtbot.wait(10)

    assert window.isVisible()
    assert not window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert window.pos() == expected

    window.set_always_on_top(True)
    qtbot.wait(10)

    assert window.isVisible()
    assert window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert window.pos() == expected


def test_remote_interaction_bubble_can_be_shown_and_cleared(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)

    window.show_interaction_bubble("邻居送了你爱心")

    assert window.interaction_bubble_text == "邻居送了你爱心"
    assert window.interaction_bubble.isVisible()
    window.clear_interaction_bubble()
    assert window.interaction_bubble_text is None
    assert not window.interaction_bubble.isVisible()


def test_remote_interaction_bubble_paints_a_visible_background(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    window.show_interaction_bubble("测试文字")
    QApplication.processEvents()

    image = QImage(window.interaction_bubble.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    window.interaction_bubble.render(image)

    background_pixel = image.pixelColor(image.width() // 2, max(0, image.height() - 3))
    assert background_pixel.alpha() > 0


def test_codex_status_bubble_is_independent_from_remote_messages(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    window.show()
    window.show_interaction_bubble("局域网消息")

    window.show_codex_status(CodexLinkSnapshot("waiting", 1, 0, "Codex 正在等待你处理"))

    assert window.interaction_bubble_text == "局域网消息"
    assert window.codex_status_text == "Codex 正在等待你处理"
    assert window.codex_status_bubble.isVisible()

    window.clear_codex_status()
    assert window.interaction_bubble_text == "局域网消息"
    assert window.codex_status_text is None


def test_lan_firewall_notice_is_persistent_and_activates_independently(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    activated: list[bool] = []
    window.lan_firewall_notice_activated.connect(lambda: activated.append(True))
    window.show()

    window.show_lan_firewall_notice()

    assert window.lan_firewall_notice.isVisible()
    assert not hasattr(window.lan_firewall_notice, "dismiss_timer")
    window.lan_firewall_notice._activate()
    assert activated == [True]
    assert not window.lan_firewall_notice.isVisible()


def test_lan_firewall_notice_close_only_dismisses(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    activated: list[bool] = []
    dismissed: list[bool] = []
    window.lan_firewall_notice_activated.connect(lambda: activated.append(True))
    window.lan_firewall_notice_dismissed.connect(lambda: dismissed.append(True))
    window.show()
    window.show_lan_firewall_notice()

    window.lan_firewall_notice.close_button.click()

    assert activated == []
    assert dismissed == [True]
    assert not window.lan_firewall_notice.isVisible()


def test_remote_effect_exposes_its_requested_layer_and_can_be_cleared(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    frame = tmp_path / "effect.png"
    Image.new("RGBA", (10, 8), (255, 0, 0, 180)).save(frame)
    effect = SimpleNamespace(
        identifier="heart-burst",
        frames=(frame,),
        duration_ms=300,
        loop=False,
        layer="under",
    )

    window.play_effect(effect, loop=False)

    assert window.active_effect_id == "heart-burst"
    assert window.active_effect_layer == "under"
    window.clear_effect()
    assert window.active_effect_id is None
    assert window.size().height() == 12


def test_transparent_over_effect_keeps_pet_pixels_beneath_it(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    frame = tmp_path / "transparent-effect.png"
    effect_frame = Image.new("RGBA", (10, 8), (0, 0, 0, 0))
    effect_frame.paste((0, 0, 255, 255), (0, 0, 5, 8))
    effect_frame.save(frame)
    effect = SimpleNamespace(
        identifier="half-overlay",
        frames=(frame,),
        duration_ms=300,
        layer="over",
    )
    window.show()

    window.play_effect(effect)
    window.repaint()
    rendered = window.grab().toImage()

    covered_pet = rendered.pixelColor(window.width() // 4, window.height() // 2)
    uncovered_pet = rendered.pixelColor(window.width() * 3 // 4, window.height() // 2)
    assert covered_pet.alpha() == 255
    assert covered_pet.blue() > covered_pet.red()
    assert uncovered_pet.alpha() == 255
    assert uncovered_pet.red() > uncovered_pet.blue()


def test_visible_frame_union_ignores_padding_and_covers_every_frame() -> None:
    first = Image.new("RGBA", (100, 80), (0, 0, 0, 0))
    first.paste((255, 0, 0, 255), (30, 10, 70, 60))
    second = Image.new("RGBA", (100, 80), (0, 0, 0, 0))
    second.paste((255, 0, 0, 255), (20, 20, 80, 70))

    assert _visible_frame_union((first, second), QSize(100, 80)) == QRect(20, 10, 60, 60)


def test_visible_frame_union_falls_back_to_canvas_for_transparent_frames() -> None:
    transparent = Image.new("RGBA", (100, 80), (0, 0, 0, 0))

    assert _visible_frame_union((transparent,), QSize(100, 80)) == QRect(0, 0, 100, 80)


def test_under_effect_stays_behind_opaque_pet_pixels(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    package = _package(tmp_path)
    for path in package.animations["idle"].frames:
        pet_frame = Image.new("RGBA", (10, 8), (0, 0, 0, 0))
        pet_frame.paste((255, 0, 0, 255), (5, 0, 10, 8))
        pet_frame.save(path)
    window = PetWindow(package)
    qtbot.addWidget(window)
    frame = tmp_path / "under-effect.png"
    Image.new("RGBA", (10, 8), (0, 0, 255, 255)).save(frame)
    effect = SimpleNamespace(
        identifier="underlay",
        frames=(frame,),
        duration_ms=300,
        layer="under",
    )
    window.show()

    window.play_effect(effect)
    window.repaint()
    rendered = window.grab().toImage()

    transparent_pet_side = rendered.pixelColor(window.width() // 4, window.height() // 2)
    opaque_pet_side = rendered.pixelColor(window.width() * 3 // 4, window.height() // 2)
    assert transparent_pet_side.blue() > transparent_pet_side.red()
    assert opaque_pet_side.red() > opaque_pet_side.blue()


def test_frame_preparation_clears_old_pixels_and_restores_source_over_composition() -> None:
    image = QImage(3, 1, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.green)
    painter = QPainter(image)

    _prepare_translucent_frame(painter, image.rect())
    painter.fillRect(QRect(1, 0, 2, 1), Qt.GlobalColor.red)
    painter.fillRect(QRect(2, 0, 1, 1), QColor(0, 0, 255, 128))
    painter.end()

    cleared_old_pixel = image.pixelColor(0, 0)
    alpha_blended_pixel = image.pixelColor(2, 0)
    assert cleared_old_pixel.alpha() == 0
    assert alpha_blended_pixel.alpha() == 255
    assert alpha_blended_pixel.red() > 0
    assert alpha_blended_pixel.blue() > 0


def test_countdown_skins_can_be_loaded_from_a_verified_resource_directory(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    del qtbot
    skin_root = tmp_path / "resources" / "countdown"
    skin_root.mkdir(parents=True)
    for theme in ("cream", "night", "yarn"):
        Image.new("RGBA", (4, 4), (255, 255, 255, 255)).save(skin_root / f"{theme}.png")

    skins = PetWindow._load_countdown_skins(skin_root)

    assert all(not skins[theme].isNull() for theme in ("cream", "night", "yarn"))


def test_countdown_skin_update_waits_until_current_countdown_finishes(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    window_root = tmp_path / "window"
    window_root.mkdir()
    window = _window(window_root)
    qtbot.addWidget(window)
    old_root = tmp_path / "old" / "countdown"
    new_root = tmp_path / "new" / "countdown"
    old_root.mkdir(parents=True)
    new_root.mkdir(parents=True)
    for theme in ("cream", "night", "yarn"):
        Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(old_root / f"{theme}.png")
        Image.new("RGBA", (4, 4), (0, 255, 0, 255)).save(new_root / f"{theme}.png")
    window.reload_countdown_skins(old_root)
    window.set_countdown_text("00:01:00")
    old_key = window._countdown_skins["cream"].cacheKey()

    window.reload_countdown_skins(new_root)

    assert window._countdown_skins["cream"].cacheKey() == old_key
    assert window._pending_countdown_skins is not None
    window.set_countdown_text(None)
    assert window._countdown_skins["cream"].cacheKey() != old_key


def test_macos_tool_window_remains_visible_when_application_is_inactive(
    qtbot: pytest.QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("petnest.ui.pet_window.sys.platform", "darwin")
    window = _window(tmp_path)
    qtbot.addWidget(window)

    assert window.testAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)


def test_context_menu_is_requested_only_on_an_opaque_pet_pixel(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    opaque_root = tmp_path / "opaque"
    opaque_root.mkdir()
    opaque = _window(opaque_root)
    qtbot.addWidget(opaque)
    requested: list[QPoint] = []
    opaque.context_menu_requested.connect(requested.append)
    event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(1, 1), QPoint(50, 60))

    QApplication.sendEvent(opaque, event)

    assert requested == [QPoint(50, 60)]

    transparent_root = tmp_path / "transparent"
    transparent_root.mkdir()
    transparent = PetWindow(_package(transparent_root, colour=(255, 0, 0, 0)))
    qtbot.addWidget(transparent)
    transparent.context_menu_requested.connect(requested.append)
    transparent_event = QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(1, 1), QPoint(70, 80))

    QApplication.sendEvent(transparent, transparent_event)

    assert requested == [QPoint(50, 60)]


def test_idle_frame_is_rendered_and_alpha_hit_testing_uses_current_frame_cache(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    window.show()

    assert window.current_action == "idle"
    assert not window.current_pixmap.isNull()
    assert window.is_opaque_at(0, 0)
    assert window.is_opaque_at(0, 0)  # repeated access must use the same cached alpha mask


def test_repeated_render_of_same_frame_reuses_qpixmap(
    qtbot: pytest.QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Image.Image] = []

    def fake_pixmap(frame: Image.Image) -> QPixmap:
        calls.append(frame)
        return QPixmap(frame.width, frame.height)

    monkeypatch.setattr("petnest.ui.pet_window._pixmap_from_pillow", fake_pixmap)
    window = _window(tmp_path)
    qtbot.addWidget(window)

    window._set_current_frame()
    window._set_current_frame()

    assert len(calls) == 1


def test_countdown_top_caches_alpha_bounds_for_current_action(
    qtbot: pytest.QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    calls = 0
    original_getchannel = Image.Image.getchannel

    def counted_getchannel(frame: Image.Image, channel: str | int) -> Image.Image:
        nonlocal calls
        calls += 1
        return original_getchannel(frame, channel)

    monkeypatch.setattr(Image.Image, "getchannel", counted_getchannel)

    first = window._countdown_top()
    second = window._countdown_top()

    assert first == second
    assert calls == len(window.player.current_frames)


def test_countdown_card_is_below_centered_pet_and_uses_adjustable_geometry(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    window.set_countdown_appearance(gap=12, width=200, height=60)
    window.set_countdown_text("距离下班 01:23:45")
    window.show()

    assert window.size().width() >= 200
    assert window.size().height() == 84
    assert all(not skin.isNull() for skin in window._countdown_skins.values())
    pet_left = (window.width() - 15) // 2
    assert window.is_opaque_at(pet_left, 0)
    assert not window.is_opaque_at(window.width() // 2, window.height() - 1)


def test_countdown_card_requires_double_click_for_settings_request(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    window.set_countdown_appearance(gap=12, width=200, height=60)
    window.set_countdown_text("距离下班 01:23:45")
    window.show()
    clicks: list[bool] = []
    window.countdown_clicked.connect(lambda: clicks.append(True))

    QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=window._countdown_rect().center())
    assert clicks == []

    QTest.mouseDClick(window, Qt.MouseButton.LeftButton, pos=window._countdown_rect().center())

    assert clicks == [True]


def test_countdown_ignores_transparent_padding_below_visible_pet(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    package = _package(tmp_path)
    for path in package.animations["idle"].frames:
        frame = Image.new("RGBA", (10, 8), (0, 0, 0, 0))
        frame.paste((255, 0, 0, 255), (0, 0, 10, 4))
        frame.save(path)
    window = PetWindow(package)
    qtbot.addWidget(window)
    window.set_countdown_appearance(gap=0, width=132, height=30)
    window.set_countdown_text("下班啦")
    window.show()

    assert window.height() == 36  # 4 个可见像素 × 1.5 倍 + 30 像素卡片。


def test_countdown_auto_expands_for_text_and_applies_all_layout_settings(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    window.set_countdown_appearance(gap=7, width=110, height=26, theme="night")
    window.set_countdown_text("距离下班 100:59:59")
    window.show()

    assert window.width() > 110
    assert window._countdown_rect().height() == 26
    assert window._countdown_rect().top() == 19

    window.set_countdown_text("下班啦")
    window.set_countdown_appearance(gap=20, width=300, height=80, theme="yarn")

    assert window.width() == 300
    assert window._countdown_rect().size() == QSize(300, 80)
    assert window._countdown_rect().top() == 32


def test_follow_mode_temporarily_overrides_animation_and_hides_countdown(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    package = _package(tmp_path)
    walk = replace(package.animations["drag"], name="walk")
    package = replace(package, animations={**package.animations, "walk": walk})
    window = PetWindow(package)
    qtbot.addWidget(window)
    window.set_countdown_appearance(gap=12, width=200, height=60)
    window.set_countdown_text("距离下班 01:23:45")
    window.show()

    normal_scale = window.scale
    window.set_follow_mode(True, scale_multiplier=0.55)

    assert window.isVisible()
    assert window.scale == pytest.approx(normal_scale * 0.55)
    assert window.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert not window.countdown_is_visible
    assert window.size().width() < 200

    window.set_follow_motion(True)
    assert window.playing_action == "walk"
    window.handle_pet_event(PetEvent("mouse.click", source="test"))
    assert window.current_action == "click"
    assert window.playing_action == "walk"

    window.set_follow_motion(False)
    assert window.playing_action == "click"
    window.set_follow_mode(False, scale_multiplier=0.55)
    assert window.isVisible()
    assert window.scale == normal_scale
    assert window.countdown_is_visible


def test_follow_mode_falls_back_to_drag_when_walk_is_absent(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    window.show()

    window.set_follow_mode(True, scale_multiplier=0.55)
    window.set_follow_motion(True)

    assert window.playing_action == "drag"


def test_follow_motion_records_direction_for_directional_animation_or_mirroring(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    window.show()
    window.set_follow_mode(True, scale_multiplier=0.45)

    window.set_follow_motion(True, direction="left", facing_left=True)

    assert (window.follow_direction, window.follow_facing_left) == ("left", True)


def test_follow_mode_does_not_paint_a_hidden_countdown_card(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    package = _package(tmp_path)
    for path in package.animations["idle"].frames:
        frame = Image.new("RGBA", (10, 8), (0, 0, 0, 0))
        frame.paste((255, 0, 0, 255), (0, 0, 10, 4))
        frame.save(path)
    window = PetWindow(package)
    qtbot.addWidget(window)
    window.set_countdown_appearance(gap=0, width=132, height=37)
    window.set_countdown_text("距离下班 01:23:45")
    window.show()

    window.set_follow_mode(True, scale_multiplier=0.45)
    image = window.grab().toImage()

    assert image.pixelColor(window.width() // 2, window.height() - 1).alpha() == 0


def test_mouse_enter_and_click_drive_the_configured_state_machine(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    window.show()

    center = window.rect().center()
    enter = QEnterEvent(QPointF(center), QPointF(center), QPointF(window.mapToGlobal(center)))
    QApplication.sendEvent(window, enter)
    assert window.current_action == "hover"

    QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=window.rect().center())
    assert window.current_action == "click"


def test_drag_starts_only_after_threshold_moves_window_and_saves_position(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    positions: list[tuple[int, int]] = []
    window = _window(tmp_path, position_saved=lambda point: positions.append((point.x(), point.y())))
    qtbot.addWidget(window)
    window.move(100, 100)
    window.show()
    start = window.pos()
    center = window.rect().center()

    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=center)
    _drag_move(window, center.x() + window.drag_threshold - 1, center.y())
    assert window.current_action == "idle"
    assert window.pos() == start

    _drag_move(window, center.x() + window.drag_threshold + 2, center.y())
    assert window.current_action == "drag"
    assert window.pos() != start

    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=center)
    assert window.current_action == "drop"
    assert positions[-1] == (window.x(), window.y())


@pytest.mark.parametrize(
    ("available", "expected"),
    [
        (("drag_left", "walk_left", "drag", "walk"), "drag_left"),
        (("codex_running_left", "drag", "walk"), "codex_running_left"),
        (("walk_left", "drag", "walk"), "walk_left"),
        (("drag", "walk"), "drag"),
        (("walk",), "walk"),
        ((), "idle"),
    ],
)
def test_drag_action_uses_directional_then_generic_fallback_order(
    qtbot: pytest.QtBot,
    tmp_path: Path,
    available: tuple[str, ...],
    expected: str,
) -> None:
    package = _package(tmp_path)
    source = package.animations["drag"]
    animations = {"idle": package.animations["idle"]}
    animations.update({name: replace(source, name=name) for name in available})
    window = PetWindow(replace(package, animations=animations, bindings={}, fallbacks={}))
    qtbot.addWidget(window)

    assert window._drag_action("left") == expected


def test_drag_motion_switches_between_directional_actions(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    package = _package(tmp_path)
    source = package.animations["drag"]
    animations = {
        **package.animations,
        "drag_left": replace(source, name="drag_left"),
        "drag_right": replace(source, name="drag_right"),
        "walk_left": replace(source, name="walk_left"),
        "walk_right": replace(source, name="walk_right"),
    }
    window = PetWindow(replace(package, animations=animations))
    qtbot.addWidget(window)
    window.move(100, 100)
    window.show()
    center = window.rect().center()
    start_global = window.mapToGlobal(center)

    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=center)
    right_global = start_global + QPoint(window.drag_threshold + 2, 0)
    _drag_move_global(window, right_global)
    assert window.playing_action == "drag_right"

    _drag_move_global(window, right_global - QPoint(4, 0))
    assert window.playing_action == "drag_left"


def test_directional_drag_fallback_restores_context_action_on_release(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    package = _package(tmp_path)
    source = package.animations["drag"]
    animations = {
        "idle": package.animations["idle"],
        "walk_left": replace(source, name="walk_left"),
        "walk_right": replace(source, name="walk_right"),
    }
    package = replace(
        package,
        animations=animations,
        fallbacks={"drag": ("idle",), "drop": ("idle",)},
    )
    window = PetWindow(package)
    qtbot.addWidget(window)
    window.move(100, 100)
    window.show()
    center = window.rect().center()
    start_global = window.mapToGlobal(center)

    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=center)
    _drag_move_global(window, start_global + QPoint(window.drag_threshold + 2, 0))
    assert window.playing_action == "walk_right"

    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=center)
    assert window.playing_action == "idle"


def test_directional_drag_does_not_bypass_non_interruptible_action(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    package = _package(tmp_path)
    source = package.animations["drag"]
    protected = replace(
        package.animations["click"],
        priority=100,
        interruptible=False,
    )
    animations = {
        **package.animations,
        "click": protected,
        "drag_right": replace(source, name="drag_right"),
    }
    window = PetWindow(replace(package, animations=animations))
    qtbot.addWidget(window)
    window.move(100, 100)
    window.show()
    center = window.rect().center()
    window.handle_pet_event(PetEvent("mouse.click", source="test"))
    assert window.playing_action == "click"
    start_global = window.mapToGlobal(center)

    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=center)
    _drag_move_global(window, start_global + QPoint(window.drag_threshold + 2, 0))

    assert window.current_action == "click"
    assert window.playing_action == "click"


def test_directional_drag_stops_overriding_after_higher_priority_event(
    qtbot: pytest.QtBot,
    tmp_path: Path,
) -> None:
    package = _package(tmp_path)
    source = package.animations["drag"]
    urgent = replace(
        package.animations["click"],
        name="urgent",
        priority=100,
        interruptible=False,
    )
    animations = {
        **package.animations,
        "drag_right": replace(source, name="drag_right"),
        "urgent": urgent,
    }
    bindings = {**package.bindings, "agent.success": "urgent"}
    window = PetWindow(replace(package, animations=animations, bindings=bindings))
    qtbot.addWidget(window)
    window.move(100, 100)
    window.show()
    center = window.rect().center()
    start_global = window.mapToGlobal(center)

    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=center)
    right_global = start_global + QPoint(window.drag_threshold + 2, 0)
    _drag_move_global(window, right_global)
    assert window.playing_action == "drag_right"

    window.handle_pet_event(PetEvent("agent.success", source="test"))
    assert window.current_action == "urgent"
    assert window.playing_action == "urgent"
    _drag_move_global(window, right_global + QPoint(2, 0))

    assert window.current_action == "urgent"
    assert window.playing_action == "urgent"


def test_position_is_clamped_to_keep_part_of_pet_on_current_screen(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    window.show()
    screen = QApplication.primaryScreen()
    assert screen is not None
    available = screen.availableGeometry()

    right = window.clamp_position(QPoint(available.right() + 10_000, available.center().y()))
    left = window.clamp_position(QPoint(available.left() - 10_000, available.center().y()))

    visible_width = min(window.minimum_visible_pixels, window.width())
    assert right.x() == available.right() - visible_width + 1
    assert left.x() == available.left() - window.width() + visible_width


def test_scale_change_reclamps_an_offscreen_window(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    window.show()
    screen = QApplication.primaryScreen()
    assert screen is not None
    available = screen.availableGeometry()
    window.move(available.right() + 1, available.center().y())

    window.set_scale(2.0)

    visible_width = min(window.minimum_visible_pixels, window.width())
    assert window.x() == available.right() - visible_width + 1


def test_timer_advances_frames_and_pause_resume_stops_and_restarts_it(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    window.show()
    initial_index = window.player.current_frame_index

    window.animation_timer.timeout.emit()
    assert window.player.current_frame_index != initial_index

    window.set_paused(True)
    paused_index = window.player.current_frame_index
    assert not window.animation_timer.isActive()
    window.animation_timer.timeout.emit()
    assert window.player.current_frame_index == paused_index

    window.set_paused(False)
    assert window.animation_timer.isActive()
    window.animation_timer.timeout.emit()
    assert window.player.current_frame_index != paused_index


def test_timer_uses_the_duration_of_each_current_frame(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    package = _package(tmp_path)
    idle = replace(package.animations["idle"], frame_durations_ms=(200, 80))
    package = replace(package, animations={**package.animations, "idle": idle})
    window = PetWindow(package)
    qtbot.addWidget(window)
    window.show()

    assert window.animation_timer.interval() == 200
    window.animation_timer.timeout.emit()
    assert window.animation_timer.interval() == 80


def test_restoring_runtime_state_restarts_the_requested_action_and_restores_pause(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    window.show()
    window.handle_pet_event(PetEvent("mouse.enter", source="test"))
    window.animation_timer.timeout.emit()
    window.set_paused(True)

    window.restore_runtime_state("hover", paused=True)

    assert window.current_action == "hover"
    assert window.player.current_definition is not None
    assert window.player.current_definition.name == "hover"
    assert window.player.current_frame_index == 0
    assert window.player.is_paused
    assert not window.animation_timer.isActive()

    window.restore_runtime_state("missing", paused=False)

    assert window.current_action == "idle"
    assert not window.player.is_paused
    assert window.animation_timer.isActive()


def test_restoring_runtime_state_forces_low_priority_action_past_non_interruptible_idle(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    package = _package(tmp_path)
    animations = {
        **package.animations,
        "idle": replace(package.animations["idle"], priority=50, interruptible=False),
        "hover": replace(package.animations["hover"], priority=20),
    }
    window = PetWindow(replace(package, animations=animations))
    qtbot.addWidget(window)
    window.show()

    window.restore_runtime_state("hover", paused=True)

    assert window.current_action == "hover"
    assert window.player.current_frame_index == 0
    assert window.player.is_paused


def test_reloading_package_clears_old_animation_cache_and_starts_new_idle(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    first = _package(tmp_path, identifier="cat")
    player = AnimationPlayer()
    window = PetWindow(
        first,
        player=player,
        state_machine=PetStateMachine(first.animations, first.bindings, first.fallbacks),
    )
    qtbot.addWidget(window)
    window.show()
    old_frame = player.current_frame
    second = _package(tmp_path, identifier="dog", colour=(0, 255, 0, 255))

    window.load_package(second)

    assert window.package.identifier == "dog"
    assert window.current_action == "idle"
    assert player.current_frame is not old_frame
    assert player.current_frame.getpixel((0, 0)) == (0, 255, 0, 255)


def test_interaction_item_triggers_only_on_known_item_and_opaque_pet_pixel(
    qtbot: pytest.QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _interaction_package(tmp_path)
    window = PetWindow(package)
    qtbot.addWidget(window)
    window.show()
    handled: list[PetEvent] = []
    original_handle = window.state_machine.handle

    def record(event: PetEvent):
        handled.append(event)
        return original_handle(event)

    monkeypatch.setattr(window.state_machine, "handle", record)

    assert not window.trigger_interaction_item("toy_ball", QPoint(2, 2))
    assert not window.trigger_interaction_item("toy_ball", QPoint(100, 100))
    assert not window.trigger_interaction_item("missing", QPoint(12, 2))
    assert window.trigger_interaction_item("toy_ball", QPoint(12, 2))

    assert window.current_action == "wave"
    assert window.playing_action == "wave"
    assert len(handled) == 1
    assert handled[0].event_name == "interaction.item.toy_ball"
    assert handled[0].source == "interaction-item"
    assert handled[0].payload == {"item_id": "toy_ball"}


def test_interaction_item_respects_higher_priority_non_interruptible_action(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    package = _interaction_package(tmp_path)
    protected = replace(package.animations["click"], name="protected", priority=100)
    package = replace(
        package,
        animations={**package.animations, "protected": protected},
        bindings={**package.bindings, "agent.protected": "protected"},
    )
    window = PetWindow(package)
    qtbot.addWidget(window)
    window.show()
    window.handle_pet_event(PetEvent("agent.protected", source="test"))

    assert window.current_action == "protected"
    assert not window.trigger_interaction_item("toy_ball", QPoint(12, 2))
    assert window.current_action == "protected"
    assert window.playing_action == "protected"


def test_interaction_item_rejects_equal_priority_reentry_until_current_animation_finishes(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    package = _interaction_package(tmp_path)
    second_icon = tmp_path / "feather.png"
    Image.new("RGBA", (8, 8), (217, 134, 99, 255)).save(second_icon)
    second_item = InteractionItemDefinition("feather", "羽毛", second_icon)
    action_a = replace(
        package.animations["click"],
        name="item_action_a",
        priority=70,
        interruptible=False,
    )
    action_b = replace(
        package.animations["click"],
        name="item_action_b",
        priority=70,
        interruptible=False,
    )
    package = replace(
        package,
        animations={
            **package.animations,
            action_a.name: action_a,
            action_b.name: action_b,
        },
        bindings={
            **package.bindings,
            "interaction.item.toy_ball": action_a.name,
            "interaction.item.feather": action_b.name,
        },
        interaction_items=(*package.interaction_items, second_item),
    )
    window = PetWindow(package)
    qtbot.addWidget(window)
    window.show()

    assert window.trigger_interaction_item("toy_ball", QPoint(12, 2))
    assert window.current_action == action_a.name
    assert not window.trigger_interaction_item("feather", QPoint(12, 2))
    assert window.current_action == action_a.name

    window.animation_timer.timeout.emit()
    window.animation_timer.timeout.emit()

    assert window.current_action == "idle"
    assert window.trigger_interaction_item("feather", QPoint(12, 2))
    assert window.current_action == action_b.name


def test_interaction_toolbox_availability_and_opening_follow_window_modes_and_reload(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    empty = PetWindow(_package(empty_root))
    qtbot.addWidget(empty)
    empty.show()

    assert not empty.interaction_items_available
    assert not empty.open_interaction_toolbox()
    enter = QEnterEvent(QPointF(2, 2), QPointF(2, 2), QPointF(empty.mapToGlobal(QPoint(2, 2))))
    QApplication.sendEvent(empty, enter)
    assert empty.current_action == "hover"
    assert not empty.interaction_toolbox.isVisible()

    item_root = tmp_path / "items"
    item_root.mkdir()
    window = PetWindow(_interaction_package(item_root))
    qtbot.addWidget(window)
    assert window.acceptDrops()
    assert window.interaction_items_available
    assert not window.open_interaction_toolbox()
    window.show()
    assert window.open_interaction_toolbox()
    assert window.interaction_toolbox.isVisible()
    assert window.interaction_toolbox.is_expanded

    window.set_mouse_interaction_enabled(False)
    assert not window.interaction_toolbox.isVisible()
    window.set_mouse_interaction_enabled(True)
    assert not window.interaction_toolbox.isVisible()
    assert window.open_interaction_toolbox()

    window.set_follow_mode(True, scale_multiplier=0.45)
    assert not window.interaction_toolbox.isVisible()
    assert not window.open_interaction_toolbox()
    window.set_follow_mode(False, scale_multiplier=0.45)
    assert not window.interaction_toolbox.isVisible()
    assert window.open_interaction_toolbox()
    window._drop_highlight = True
    window._pet_hovered = True
    window._toolbox_hovered = True
    window._interaction_hide_timer.start()

    reloaded_root = tmp_path / "reloaded-empty"
    reloaded_root.mkdir()
    window.load_package(_package(reloaded_root, identifier="dog"))
    assert not window.interaction_items_available
    assert not window.interaction_toolbox.isVisible()
    assert not window._interaction_hide_timer.isActive()
    assert not window._drop_highlight
    assert not window._pet_hovered
    assert not window._toolbox_hovered


def test_interaction_item_qt_drag_events_validate_mime_hit_test_and_clear_highlight(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    window = PetWindow(_interaction_package(tmp_path))
    qtbot.addWidget(window)
    window.show()

    wrong_format = _drag_enter(_item_mime("toy_ball", format_name="text/plain"))
    window.dragEnterEvent(wrong_format)
    assert not wrong_format.isAccepted()
    malformed = _drag_enter(_item_mime(b"\xff"))
    window.dragEnterEvent(malformed)
    assert not malformed.isAccepted()
    unknown = _drag_enter(_item_mime("missing"))
    window.dragEnterEvent(unknown)
    assert not unknown.isAccepted()

    valid = _drag_enter(_item_mime("toy_ball"))
    window.dragEnterEvent(valid)
    assert valid.isAccepted()

    transparent = _drag_move_event(_item_mime("toy_ball"), QPoint(2, 2))
    window.dragMoveEvent(transparent)
    assert not transparent.isAccepted()
    assert not window._drop_highlight

    opaque = _drag_move_event(_item_mime("toy_ball"), QPoint(12, 2))
    window.dragMoveEvent(opaque)
    assert opaque.isAccepted()
    assert window._drop_highlight

    leave = QDragLeaveEvent()
    window.dragLeaveEvent(leave)
    assert leave.isAccepted()
    assert not window._drop_highlight

    window.dragMoveEvent(_drag_move_event(_item_mime("toy_ball"), QPoint(12, 2)))
    successful = _drop_event(_item_mime("toy_ball"), QPoint(12, 2))
    window.dropEvent(successful)
    assert successful.isAccepted()
    assert successful.dropAction() == Qt.DropAction.MoveAction
    assert window.current_action == "wave"
    assert not window._drop_highlight

    window._drop_highlight = True
    failed = _drop_event(_item_mime("missing"), QPoint(12, 2))
    window.dropEvent(failed)
    assert not failed.isAccepted()
    assert not window._drop_highlight


@pytest.mark.parametrize("mode", ["mouse-disabled", "follow"])
def test_interaction_item_qt_drag_events_reject_disallowed_window_modes(
    qtbot: pytest.QtBot, tmp_path: Path, mode: str
) -> None:
    window = PetWindow(_interaction_package(tmp_path))
    qtbot.addWidget(window)
    window.show()
    if mode == "mouse-disabled":
        window.set_mouse_interaction_enabled(False)
    else:
        window.set_follow_mode(True, scale_multiplier=0.45)

    window._drop_highlight = True
    enter = _drag_enter(_item_mime("toy_ball"))
    window.dragEnterEvent(enter)
    assert not enter.isAccepted()
    assert not window._drop_highlight

    window._drop_highlight = True
    move = _drag_move_event(_item_mime("toy_ball"), QPoint(12, 2))
    window.dragMoveEvent(move)
    assert not move.isAccepted()
    assert not window._drop_highlight

    window._drop_highlight = True
    drop = _drop_event(_item_mime("toy_ball"), QPoint(12, 2))
    window.dropEvent(drop)
    assert not drop.isAccepted()
    assert not window._drop_highlight


def test_interaction_drop_highlight_is_painted_around_pet(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    window = PetWindow(_interaction_package(tmp_path))
    qtbot.addWidget(window)
    window.show()
    window._drop_highlight = True
    window.repaint()

    rendered = window.grab().toImage()
    border = rendered.pixelColor(1, window._pet_height() // 2)

    assert border.alpha() > 0
    assert border.red() > border.blue()


def test_interaction_toolbox_hover_bridges_pet_leave_with_delayed_hide(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    window = PetWindow(_interaction_package(tmp_path))
    qtbot.addWidget(window)
    window.show()
    point = QPoint(12, 2)
    enter = QEnterEvent(QPointF(point), QPointF(point), QPointF(window.mapToGlobal(point)))

    QApplication.sendEvent(window, enter)

    assert window._pet_hovered
    assert window.interaction_toolbox.isVisible()
    assert not window.interaction_toolbox.is_expanded
    QApplication.sendEvent(window, QEvent(QEvent.Type.Leave))
    assert not window._pet_hovered
    assert window._interaction_hide_timer.isActive()
    assert window._interaction_hide_timer.interval() == 700
    assert window.interaction_toolbox.isVisible()

    qtbot.wait(250)
    assert window.interaction_toolbox.isVisible()

    window.interaction_toolbox.hover_changed.emit(True)
    assert window._toolbox_hovered
    assert not window._interaction_hide_timer.isActive()
    assert window.interaction_toolbox.isVisible()

    window._pet_hovered = False
    window.interaction_toolbox.hover_changed.emit(False)
    assert window._interaction_hide_timer.isActive()
    window._interaction_hide_timer.timeout.emit()
    assert not window.interaction_toolbox.isVisible()


def test_hover_tool_anchor_uses_hover_action_union_and_ignores_countdown_padding(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    window = PetWindow(_visible_anchor_package(tmp_path))
    qtbot.addWidget(window)
    window.set_countdown_text("距离下班 01:23:45")
    window.show()
    point = QPoint(window._pet_left() + 12, 2)
    enter = QEnterEvent(QPointF(point), QPointF(point), QPointF(window.mapToGlobal(point)))

    QApplication.sendEvent(window, enter)

    assert window.playing_action == "hover"
    assert window._frozen_hover_anchor_pet_rect == QRect(3, 1, 11, 10)
    expected = QRect(
        window.mapToGlobal(QPoint(window._pet_left() + 3, 1)),
        QSize(11, 10),
    )
    assert window.interaction_toolbox._pet_rect == expected


def test_hover_tool_anchor_stays_frozen_across_frames_and_tracks_window_move(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    window = PetWindow(_visible_anchor_package(tmp_path))
    qtbot.addWidget(window)
    window.show()
    point = QPoint(12, 2)
    enter = QEnterEvent(QPointF(point), QPointF(point), QPointF(window.mapToGlobal(point)))
    QApplication.sendEvent(window, enter)
    frozen = QRect(window._frozen_hover_anchor_pet_rect)
    before = QRect(window.interaction_toolbox._pet_rect)

    window.animation_timer.timeout.emit()
    assert window._frozen_hover_anchor_pet_rect == frozen

    window.move(window.pos() + QPoint(20, 10))
    QApplication.processEvents()
    assert window.interaction_toolbox._pet_rect.topLeft() == before.topLeft() + QPoint(20, 10)
    assert window.interaction_toolbox._pet_rect.size() == before.size()


def test_hover_tool_anchor_recomputes_for_new_scale(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = PetWindow(_visible_anchor_package(tmp_path))
    qtbot.addWidget(window)
    window.show()
    point = QPoint(12, 2)
    QApplication.sendEvent(
        window,
        QEnterEvent(QPointF(point), QPointF(point), QPointF(window.mapToGlobal(point))),
    )

    window.set_scale(2.0)

    assert window._frozen_hover_anchor_pet_rect == QRect(4, 2, 14, 12)
    assert window.interaction_toolbox._pet_rect.size() == QSize(14, 12)


def test_hover_tool_anchor_tracks_pet_recentering_when_countdown_appears(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    window = PetWindow(_visible_anchor_package(tmp_path))
    qtbot.addWidget(window)
    window.show()
    point = QPoint(12, 2)
    QApplication.sendEvent(
        window,
        QEnterEvent(QPointF(point), QPointF(point), QPointF(window.mapToGlobal(point))),
    )
    frozen = QRect(window._frozen_hover_anchor_pet_rect)

    window.set_countdown_text("距离下班 01:23:45")
    QApplication.processEvents()

    expected_top_left = window.mapToGlobal(
        QPoint(window._pet_left() + frozen.left(), frozen.top())
    )
    assert window._frozen_hover_anchor_pet_rect == frozen
    assert window.interaction_toolbox._pet_rect.topLeft() == expected_top_left


def test_pet_hover_shows_notebook_launcher_without_interaction_items(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    requests: list[bool] = []
    window.quick_notebook_requested.connect(lambda: requests.append(True))
    window.set_quick_notebook_enabled(True)
    window.show()
    point = QPoint(2, 2)
    enter = QEnterEvent(QPointF(point), QPointF(point), QPointF(window.mapToGlobal(point)))

    QApplication.sendEvent(window, enter)

    assert window.interaction_toolbox.isVisible()
    assert window.interaction_toolbox.notebook_launcher.isVisible()
    assert not window.interaction_toolbox.launcher.isVisible()
    window.interaction_toolbox.notebook_launcher.click()
    assert requests == [True]


def test_interaction_ui_cleans_up_on_modes_reload_hide_and_close(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    window = PetWindow(_interaction_package(tmp_path))
    qtbot.addWidget(window)
    window.show()
    assert window.open_interaction_toolbox()
    window._drop_highlight = True
    window._pet_hovered = True
    window._toolbox_hovered = True
    window._interaction_hide_timer.start()

    window.set_mouse_interaction_enabled(False)

    assert not window._interaction_hide_timer.isActive()
    assert not window._drop_highlight
    assert not window._pet_hovered
    assert not window._toolbox_hovered
    assert not window.interaction_toolbox.isVisible()

    window.set_mouse_interaction_enabled(True)
    assert not window.interaction_toolbox.isVisible()
    assert window.open_interaction_toolbox()
    previous_rect = QRect(window.interaction_toolbox._pet_rect)
    window.move(window.pos() + QPoint(20, 10))
    QApplication.processEvents()
    assert window.interaction_toolbox._pet_rect == window._hover_tool_anchor_global_rect()
    assert window.interaction_toolbox._pet_rect != previous_rect

    window.hide()
    QApplication.processEvents()
    assert not window.interaction_toolbox.isVisible()
    assert not window._interaction_hide_timer.isActive()

    window.show()
    assert window.open_interaction_toolbox()
    toolbox = window.interaction_toolbox
    window.close()
    QApplication.processEvents()
    assert not isValid(toolbox)


def test_interaction_toolbox_is_destroyed_when_host_is_deleted_without_close_event(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    del qtbot
    window = PetWindow(_interaction_package(tmp_path))
    window.show()
    assert window.open_interaction_toolbox()
    toolbox = window.interaction_toolbox

    window.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()

    assert not isValid(window)
    assert not isValid(toolbox)


def test_tray_does_not_expose_legacy_import_or_animation_actions(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    tray = PetTrayIcon(window)

    assert not hasattr(tray, "import_action")
    assert not hasattr(tray, "import_work_finish_action")
    assert not hasattr(tray, "edit_animations_action")


def test_tray_menu_groups_application_and_pet_library_actions(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    tray = PetTrayIcon(window, pet_names={"cat": "小猫"}, current_pet_name="小猫")

    assert tray.current_pet_action.text() == "当前宠物：小猫"
    assert tray.pet_library_menu.title() == "宠物库"
    labels = [
        action.text()
        for action in tray.pet_library_menu.actions()
        if not action.isSeparator()
    ]
    assert labels == [
        "宠物与动作…",
        "打开宠物文件夹",
        "刷新宠物列表",
        "重新加载当前宠物",
    ]
    assert "动画播放中" not in [action.text() for action in tray.menu.actions()]
    assert tray.toggle_always_on_top_action.isCheckable()
    tray.set_always_on_top_enabled(True)
    assert tray.toggle_always_on_top_action.isChecked()


def test_tray_submenus_use_the_same_glass_menu_skin(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    tray = PetTrayIcon(window, pet_names={"cat": "小猫"})

    assert tray.pet_menu.objectName() == "traySubmenu"
    assert tray.pet_library_menu.objectName() == "traySubmenu"
    assert tray.pet_menu.styleSheet() == tray.pet_library_menu.styleSheet()
    if __import__("sys").platform in {"win32", "darwin"}:
        assert tray.pet_menu.styleSheet() == ""
        assert not tray.pet_menu.testAttribute(__import__("PySide6").QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
    else:
        assert "QMenu#traySubmenu" in tray.pet_menu.styleSheet()
        assert "border-radius: 12px" in tray.pet_menu.styleSheet()


def test_tray_visibility_and_pause_callbacks_report_new_state(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    window.show()
    visibility: list[bool] = []
    pauses: list[bool] = []
    tray = PetTrayIcon(
        window,
        on_visibility_changed=visibility.append,
        on_toggle_pause=pauses.append,
    )

    tray.toggle_visibility_action.trigger()
    tray.toggle_visibility_action.trigger()
    tray.toggle_pause_action.trigger()

    assert visibility == [False, True]
    assert pauses == [True]


def test_tray_menu_uses_native_macos_skin_instead_of_translucent_qss(
    qtbot: pytest.QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("petnest.ui.tray_icon.sys.platform", "darwin")
    window = _window(tmp_path)
    qtbot.addWidget(window)
    tray = PetTrayIcon(window, pet_names={"cat": "小猫"})

    assert tray.menu.styleSheet() == ""
    assert not tray.menu.testAttribute(__import__("PySide6").QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
    assert tray.pet_menu.styleSheet() == ""


def test_tray_current_pet_title_can_follow_switches(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    tray = PetTrayIcon(window, current_pet_name="小猫")

    tray.set_current_pet_name("平安")

    assert tray.current_pet_action.text() == "当前宠物：平安"


def test_cursor_style_action_is_omitted_on_macos(
    qtbot: pytest.QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("petnest.ui.tray_icon.sys.platform", "darwin")
    window = _window(tmp_path)
    qtbot.addWidget(window)
    tray = PetTrayIcon(window)

    assert not hasattr(tray, "cursor_styles_action")
    assert all("鼠标样式" not in action.text() for action in tray.menu.actions())


def test_application_icon_uses_the_dedicated_app_asset(qtbot: pytest.QtBot) -> None:
    assert not application_icon().isNull()


def test_tray_exposes_pet_folder_and_refresh_actions(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    calls: list[str] = []
    tray = PetTrayIcon(window, on_open_pets_folder=lambda: calls.append("open"), on_refresh_pets=lambda: calls.append("refresh"))

    assert tray.open_pets_folder_action.text() == "打开宠物文件夹"
    assert tray.refresh_pets_action.text() == "刷新宠物列表"
    tray.open_pets_folder_action.trigger()
    tray.refresh_pets_action.trigger()
    assert calls == ["open", "refresh"]


def test_tray_exposes_lan_interaction_action(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    calls: list[str] = []
    tray = PetTrayIcon(window, on_lan_interactions=lambda: calls.append("lan"))

    assert tray.lan_interactions_action.text() == "互动…"
    tray.lan_interactions_action.trigger()
    assert calls == ["lan"]


def test_tray_hides_codex_usage_until_unlocked(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)
    calls: list[str] = []
    tray = PetTrayIcon(window, on_codex_usage=lambda: calls.append("usage"))

    assert tray.codex_usage_action.text() == "Codex 用量…"
    assert not tray.codex_usage_action.isVisible()

    tray.set_codex_usage_unlocked(True)

    assert tray.codex_usage_action.isVisible()
    tray.codex_usage_action.trigger()
    assert calls == ["usage"]


def test_tray_shows_codex_usage_for_previously_unlocked_user(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    window = _window(tmp_path)
    qtbot.addWidget(window)

    tray = PetTrayIcon(window, codex_usage_unlocked=True)

    assert tray.codex_usage_action.isVisible()


def test_system_idle_actions_have_safe_default_bindings(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    package = _package(tmp_path)
    machine = PetWindow._make_state_machine(package)

    assert machine.handle(PetEvent("system.sleep", source="system")).current_action == "idle"


def test_fullscreen_actions_are_excluded_from_desktop_pet_state_machine(tmp_path: Path) -> None:
    package = _package(tmp_path)
    fullscreen = replace(
        package.animations["idle"],
        name="work_finish_walk",
        scope="fullscreen",
        canvas=Canvas(24, 18),
    )
    package = replace(
        package,
        animations={**package.animations, "work_finish_walk": fullscreen},
        bindings={**package.bindings, "test.fullscreen": "work_finish_walk"},
    )

    machine = PetWindow._make_state_machine(package)

    assert "work_finish_walk" not in machine.animations
    assert machine.handle(PetEvent("test.fullscreen", source="test")).current_action == "idle"
