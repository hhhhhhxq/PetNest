"""配置驱动的透明桌面宠物窗口。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from math import ceil, floor, hypot
from pathlib import Path
import sys
from time import monotonic

from PIL import Image
from PySide6.QtCore import QEvent, QMimeData, QPoint, QRect, QSize, QTimer, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QEnterEvent,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QLabel, QWidget

from petnest.core.animation_player import AnimationPlayer
from petnest.core.codex_link import CodexLinkSnapshot
from petnest.core.interaction_items import InteractionItemResolver, ResolvedInteractionItem
from petnest.core.interaction_play import HoldPlayController, HoldPlayPhase
from petnest.core.state_machine import PetStateMachine, StateTransition
from petnest.models.event import PetEvent
from petnest.models.pet_package import Canvas, PetPackage
from petnest.ui.codex_status_bubble import CodexStatusBubble
from petnest.ui.drag_cursor_overlay import DragCursorOverlay
from petnest.ui.interaction_item_toolbox import INTERACTION_ITEM_MIME, InteractionItemToolbox
from petnest.ui.lan_firewall_notice import LanFirewallNoticeBubble

PositionSaved = Callable[[QPoint], object]


def _visible_frame_union(frames: tuple[Image.Image, ...], fallback_size: QSize) -> QRect:
    """返回一组动画帧的 Alpha 可见边界并集。"""
    bounds = [frame.getchannel("A").getbbox() for frame in frames]
    visible = [value for value in bounds if value is not None]
    if not visible:
        return QRect(0, 0, max(1, fallback_size.width()), max(1, fallback_size.height()))
    left = min(value[0] for value in visible)
    top = min(value[1] for value in visible)
    right = max(value[2] for value in visible)
    bottom = max(value[3] for value in visible)
    return QRect(left, top, max(1, right - left), max(1, bottom - top))


def _prepare_translucent_frame(painter: QPainter, rect: QRect) -> None:
    """清除上一帧的透明窗口像素，再恢复正常 alpha 叠加。"""
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    painter.fillRect(rect, Qt.GlobalColor.transparent)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)


class InteractionBubble(QLabel):
    """可在透明顶层窗口中稳定绘制背景的互动气泡。"""

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt 覆盖名。
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#efcdbd"), 1))
        painter.setBrush(QColor("#fffaf5"))
        painter.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 12, 12)
        super().paintEvent(event)


class PetWindow(QWidget):
    """无边框、置顶且不获取键盘焦点的宠物帧显示窗口。

    窗口本身只把鼠标输入转成 :class:`PetEvent`，不会假设某个角色或动作名以外
    的具体素材；动作映射完全来自 ``PetPackage.bindings``。
    """

    drag_threshold = 6
    minimum_visible_pixels = 48
    context_menu_requested = Signal(QPoint)
    countdown_clicked = Signal()
    codex_status_activated = Signal()
    lan_firewall_notice_activated = Signal()
    lan_firewall_notice_dismissed = Signal()
    position_changed = Signal()
    quick_notebook_requested = Signal()

    def __init__(
        self,
        package: PetPackage,
        *,
        player: AnimationPlayer | None = None,
        state_machine: PetStateMachine | None = None,
        position_saved: PositionSaved | None = None,
        countdown_root: Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint
        )
        super().__init__(parent, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        if sys.platform == "darwin":
            # Qt.Tool 在 macOS 上映射为 NSPanel，默认会随应用失去焦点而
            # 隐藏。桌宠需要跨应用保持可见，才能让 WindowStaysOnTopHint
            # 真正符合“始终置顶”的用户预期。
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)

        self.package = package
        self._scale = package.display.default_scale
        self.player = player or AnimationPlayer()
        self.state_machine = state_machine or self._make_state_machine(package)
        self._interaction_item_resolver = InteractionItemResolver()
        self._interaction_items: tuple[ResolvedInteractionItem, ...] = (
            self._interaction_item_resolver.resolve(package)
        )
        self._drop_highlight = False
        self._pet_hovered = False
        self._toolbox_hovered = False
        self._interaction_hide_timer = QTimer(self)
        self._interaction_hide_timer.setSingleShot(True)
        self._interaction_hide_timer.setInterval(700)
        self._interaction_hide_timer.timeout.connect(self._hide_interaction_toolbox_if_unhovered)
        self.interaction_toolbox = InteractionItemToolbox(None)
        self.interaction_toolbox.set_items(self._interaction_items)
        self.interaction_toolbox.hover_changed.connect(self._on_interaction_toolbox_hover_changed)
        self.interaction_toolbox.notebook_requested.connect(self.quick_notebook_requested)
        self.interaction_toolbox.item_drag_finished.connect(self._on_item_drag_finished)
        self._hold_play_controller: HoldPlayController | None = None
        self._hold_play_item: ResolvedInteractionItem | None = None
        self._hold_play_pending_item: ResolvedInteractionItem | None = None
        self._hold_play_restore_action: str | None = None
        self._hold_play_timer = QTimer(self)
        self._hold_play_timer.setSingleShot(True)
        self._hold_play_timer.timeout.connect(self._on_hold_play_deadline)
        self._drag_cursor_overlay = DragCursorOverlay()
        toolbox = self.interaction_toolbox
        toolbox_disposed = False

        def mark_toolbox_disposed(_destroyed: object | None = None) -> None:
            nonlocal toolbox_disposed
            toolbox_disposed = True

        def dispose_toolbox(_destroyed: object | None = None) -> None:
            nonlocal toolbox_disposed
            if toolbox_disposed:
                return
            toolbox_disposed = True
            toolbox.close()
            toolbox.deleteLater()

        toolbox.destroyed.connect(mark_toolbox_disposed)
        self._dispose_interaction_toolbox: Callable[[], None] = dispose_toolbox
        self.destroyed.connect(dispose_toolbox)
        self._position_saved = position_saved
        self._current_pixmap = QPixmap()
        self._playing_action = "idle"
        # Pillow 帧会在 AnimationPlayer 中复用；按帧缓存 Qt 像素图，避免
        # 动画每次换帧都重复做 Pillow -> QImage -> QPixmap 的转换。
        # 只保留当前动作的像素图，避免切换大量动作后额外占用不必要的内存。
        self._pixmap_cache: dict[int, QPixmap] = {}
        # 倒计时卡片只需要当前动作的可见底边；透明边界不会随循环帧改变，
        # 因此将 alpha 扫描结果按动作缓存，避免每个渲染 tick 重复 getbbox。
        self._countdown_bottom_cache: dict[str, int] = {}
        self._hover_action_bounds_cache: dict[str, QRect] = {}
        self._frozen_hover_anchor_pet_rect: QRect | None = None
        self._alpha_cache: dict[int, tuple[int, int, bytes]] = {}
        self._press_global: QPoint | None = None
        self._window_origin: QPoint | None = None
        self._dragging = False
        self._last_drag_global: QPoint | None = None
        self._drag_direction: str | None = None
        self._drag_action_override = False
        self._drag_context_action: str | None = None
        self._countdown_pressed = False
        self._mouse_interaction_enabled = True
        self._countdown_text: str | None = None
        self._countdown_gap = 0
        self._countdown_width = 132
        self._countdown_card_height = 37
        self._countdown_theme = "cream"
        self._countdown_skins = self._load_countdown_skins(countdown_root)
        self._pending_countdown_skins: dict[str, QPixmap] | None = None
        self._follow_mode_enabled = False
        self._follow_motion = False
        self._normal_scale: float | None = None
        self._normal_position: QPoint | None = None
        self._follow_scale_multiplier = 0.45
        self._follow_direction = "right"
        self._follow_facing_left = False
        self.interaction_bubble = InteractionBubble(None)
        self.interaction_bubble.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.interaction_bubble.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.interaction_bubble.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.interaction_bubble.setStyleSheet(
            "QLabel { color: #684d45; padding: 7px 11px; font-size: 12px; }"
        )
        self.interaction_bubble.setWordWrap(True)
        self.interaction_bubble.setMaximumWidth(260)
        self._interaction_bubble_text: str | None = None
        self._interaction_bubble_timer = QTimer(self)
        self._interaction_bubble_timer.setSingleShot(True)
        self._interaction_bubble_timer.timeout.connect(self.clear_interaction_bubble)
        self.codex_status_bubble = CodexStatusBubble(None)
        self.codex_status_bubble.activated.connect(self.codex_status_activated)
        self.lan_firewall_notice = LanFirewallNoticeBubble(None)
        self.lan_firewall_notice.activated.connect(self.lan_firewall_notice_activated)
        self.lan_firewall_notice.dismissed.connect(self.lan_firewall_notice_dismissed)
        self._active_effect_id: str | None = None
        self._active_effect_layer = "over"
        self._effect_pixmaps: tuple[QPixmap, ...] = ()
        self._effect_frame_index = 0
        self._effect_loop = False
        self._effect_timer = QTimer(self)
        self._effect_timer.timeout.connect(self._on_effect_tick)

        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self._on_animation_tick)
        self._play_current_action()

    @property
    def current_action(self) -> str:
        """状态机当前选择的包内动作。"""
        return self.state_machine.current_action

    @property
    def current_pixmap(self) -> QPixmap:
        """当前已缩放帧，供绘制和测试使用。"""
        return self._current_pixmap

    @property
    def scale(self) -> float:
        """当前包声明的显示倍率。"""
        return self._scale

    @property
    def playing_action(self) -> str:
        """当前实际渲染的动作；跟随移动时可临时覆盖状态机动作。"""
        return self._playing_action

    @property
    def countdown_is_visible(self) -> bool:
        """倒计时在跟随模式中保留内容但不显示，以免影响鼠标操作。"""
        return (
            self._countdown_text is not None
            and not self._follow_mode_enabled
            and self._hold_play_controller is None
        )

    @property
    def follow_direction(self) -> str:
        """当前跟随移动的主方向，供方向动作选择与测试读取。"""
        return self._follow_direction

    @property
    def follow_facing_left(self) -> bool:
        """当前应当水平镜像的朝向。"""
        return self._follow_facing_left

    @property
    def interaction_bubble_text(self) -> str | None:
        return self._interaction_bubble_text

    @property
    def interaction_items_available(self) -> bool:
        """当前宠物包是否有已经解析到可播放动作的互动道具。"""
        return bool(self._interaction_items)

    @property
    def codex_status_text(self) -> str | None:
        if not self.codex_status_bubble.isVisible():
            return None
        return self.codex_status_bubble.text()

    @property
    def active_effect_id(self) -> str | None:
        return self._active_effect_id

    @property
    def active_effect_layer(self) -> str | None:
        return self._active_effect_layer if self._active_effect_id is not None else None

    def is_opaque_at(self, x: int, y: int) -> bool:
        """按当前帧的 alpha 通道判断窗口局部坐标是否可交互。

        alpha 字节会按 Pillow 帧对象缓存，从而避免鼠标移动时重复解码图片。
        """
        frame = self.player.current_frame
        if frame is None:
            return False
        logical_x = int((x - self._pet_left()) / self.scale)
        logical_y = int(y / self.scale)
        if logical_x < 0 or logical_y < 0 or logical_x >= frame.width or logical_y >= frame.height:
            return False
        cache_key = id(frame)
        cached = self._alpha_cache.get(cache_key)
        if cached is None:
            alpha = frame.getchannel("A").tobytes()
            cached = (frame.width, frame.height, alpha)
            self._alpha_cache[cache_key] = cached
        width, _height, alpha = cached
        return alpha[logical_y * width + logical_x] >= self.package.display.alpha_hit_test_threshold

    def set_paused(self, paused: bool) -> None:
        """暂停或继续动画计时器，保留当前已预加载帧。"""
        if paused:
            self.player.pause()
            self.animation_timer.stop()
        else:
            self.player.resume()
            self._start_animation_timer()

    def set_scale(self, scale: float) -> None:
        """更新显示倍率并重建当前帧的命中坐标关系。"""
        if not self.package.display.min_scale <= scale <= self.package.display.max_scale:
            raise ValueError("缩放比例不在宠物包允许范围内")
        if self._follow_mode_enabled:
            self._normal_scale = scale
            scale = self._follow_scale(scale)
        reposition_hover_tools = self.interaction_toolbox.isVisible()
        if reposition_hover_tools:
            self._frozen_hover_anchor_pet_rect = None
        self._scale = scale
        self._set_current_frame()
        self._start_animation_timer()
        self.move(self.clamp_position(self.pos()))
        if reposition_hover_tools:
            self._freeze_hover_tool_anchor()
            self.interaction_toolbox.reposition(self._hover_tool_anchor_global_rect())

    def set_follow_mode(self, enabled: bool, *, scale_multiplier: float) -> None:
        """切换鼠标跟随显示层，并保留普通模式的缩放与倒计时内容。"""
        if enabled:
            self._cancel_hold_play(restore=True)
            self._clear_interaction_item_ui()
        multiplier = max(0.25, min(float(scale_multiplier), 1.0))
        if enabled:
            if not self._follow_mode_enabled:
                self._normal_scale = self._scale
                self._normal_position = QPoint(self.pos())
            self._follow_mode_enabled = True
            self._follow_scale_multiplier = multiplier
            self._scale = self._follow_scale(self._normal_scale or self.package.display.default_scale)
        else:
            was_following = self._follow_mode_enabled
            self._follow_mode_enabled = False
            self._follow_motion = False
            self._scale = self._normal_scale or self._scale
            self._normal_scale = None
            if was_following:
                self._play_current_action()
        self._set_follow_input_transparent(enabled)
        self._set_current_frame()
        target = self._normal_position if not enabled and self._normal_position is not None else self.pos()
        self.move(self.clamp_position(target))
        if not enabled:
            self._normal_position = None

    def set_follow_motion(self, moving: bool, *, direction: str = "right", facing_left: bool = False) -> None:
        """在鼠标实际移动期间播放临时移动动作，静止后恢复状态机动作。"""
        if not self._follow_mode_enabled:
            return
        direction = direction if direction in {"left", "right", "up", "down"} else "right"
        direction_changed = (self._follow_direction, self._follow_facing_left) != (direction, facing_left)
        if self._follow_motion == moving and not direction_changed:
            return
        self._follow_motion = moving
        self._follow_direction = direction
        self._follow_facing_left = facing_left
        action = self._follow_action() if moving else self.state_machine.current_action
        if action != self._playing_action:
            self._play_action(action)
        else:
            self.update()

    def _follow_scale(self, normal_scale: float) -> float:
        display = self.package.display
        return min(display.max_scale, max(display.min_scale, normal_scale * self._follow_scale_multiplier))

    def _set_follow_input_transparent(self, enabled: bool) -> None:
        was_visible = self.isVisible()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, enabled)
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, enabled)
        if was_visible:
            self.show()

    def clamp_position(self, position: QPoint) -> QPoint:
        """将窗口位置限制在显示器可用区域内，始终保留可拖回的可见部分。

        当目标点位于另一块显示器时优先使用该屏幕；目标完全落在所有
        屏幕外时则保留在当前屏幕，避免用户把无标题栏桌宠拖丢。
        """
        target_center = position + QPoint(self.width() // 2, self.height() // 2)
        screen = QGuiApplication.screenAt(target_center) or self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return position
        available = screen.availableGeometry()
        visible_width = min(self.minimum_visible_pixels, self.width())
        visible_height = min(self.minimum_visible_pixels, self.height())
        minimum_x = available.left() - self.width() + visible_width
        maximum_x = available.right() - visible_width + 1
        minimum_y = available.top() - self.height() + visible_height
        maximum_y = available.bottom() - visible_height + 1
        if minimum_x > maximum_x:
            minimum_x = maximum_x = available.center().x() - self.width() // 2
        if minimum_y > maximum_y:
            minimum_y = maximum_y = available.center().y() - self.height() // 2
        return QPoint(
            max(minimum_x, min(position.x(), maximum_x)),
            max(minimum_y, min(position.y(), maximum_y)),
        )

    def set_always_on_top(self, enabled: bool) -> None:
        """即时切换置顶属性，同时保留无边框窗口所在屏幕和坐标。"""
        position = QPoint(self.pos())
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if not was_visible:
            return
        self.show()
        self._restore_after_window_flag_change(position)
        # macOS 会在 NSPanel 层级切换后的下一轮事件循环再次调整窗口位置，
        # 因此同步恢复一次后还需延迟重放，避免窗口跳到另一块显示器。
        QTimer.singleShot(0, lambda saved=QPoint(position): self._restore_after_window_flag_change(saved))

    def _restore_after_window_flag_change(self, position: QPoint) -> None:
        if not self.isVisible():
            self.show()
        self.move(self.clamp_position(position))
        self.raise_()

    def set_mouse_interaction_enabled(self, enabled: bool) -> None:
        """关闭后忽略宠物鼠标事件，保留窗口显示和动画。"""
        self._mouse_interaction_enabled = enabled
        if not enabled:
            self._cancel_hold_play(restore=True)
            self._clear_interaction_item_ui()

    def set_quick_notebook_enabled(self, enabled: bool) -> None:
        self.interaction_toolbox.set_notebook_enabled(enabled)
        if not enabled and not self.interaction_items_available:
            self._clear_interaction_item_ui()

    def set_quick_notebook_open(self, opened: bool) -> None:
        self.interaction_toolbox.set_notebook_open(opened)

    def quick_notebook_anchor_rect(self) -> QRect:
        return self._global_window_rect()

    def open_interaction_toolbox(self) -> bool:
        """在宠物旁显示并展开当前可用的互动道具。"""
        if not self._interaction_can_show():
            return False
        self._interaction_hide_timer.stop()
        self._freeze_hover_tool_anchor()
        self.interaction_toolbox.show_for(self._hover_tool_anchor_global_rect())
        self.interaction_toolbox.open_panel()
        return True

    def trigger_interaction_item(self, item_id: str, position: QPoint) -> bool:
        """在不透明宠物像素上通过状态机触发一个已解析道具。"""
        if not self._interaction_can_show():
            return False
        item = next(
            (candidate for candidate in self._interaction_items if candidate.definition.identifier == item_id),
            None,
        )
        if item is None or not self.is_opaque_at(position.x(), position.y()):
            return False
        current = self.package.animations[self.state_machine.current_action]
        target = self.package.animations[item.action_name]
        if not current.interruptible and target.priority <= current.priority:
            return False
        transition = self.state_machine.handle(
            PetEvent(
                item.event_name,
                source="interaction-item",
                payload={"item_id": item_id},
            )
        )
        if not transition.changed:
            return False
        self._play_current_action()
        self._clear_interaction_item_ui()
        return True

    def set_countdown_text(self, text: str | None) -> None:
        """在宠物下方显示倒计时；空值会移除预留区域。"""
        normalized = text or None
        if normalized is None and self._pending_countdown_skins is not None:
            self._countdown_skins = self._pending_countdown_skins
            self._pending_countdown_skins = None
        self._countdown_text = normalized
        target_size = self._scaled_canvas_size()
        if self.size() != target_size:
            self.setFixedSize(target_size)
            self.move(self.clamp_position(self.pos()))
        self.update()

    def set_countdown_appearance(self, *, gap: int, width: int, height: int, theme: str = "cream") -> None:
        """更新倒计时卡片尺寸及它与宠物之间的垂直间距。"""
        self._countdown_gap = max(0, min(int(gap), 80))
        self._countdown_width = max(110, min(int(width), 420))
        self._countdown_card_height = max(26, min(int(height), 100))
        self._countdown_theme = theme if theme in {"cream", "night", "yarn"} else "cream"
        if self.countdown_is_visible:
            self.setFixedSize(self._scaled_canvas_size())
            self.move(self.clamp_position(self.pos()))
        self.update()

    def reload_countdown_skins(self, directory: Path | None = None) -> None:
        """加载新皮肤；当前倒计时显示期间延迟到下一次显示再切换。"""
        skins = self._load_countdown_skins(directory)
        if self.countdown_is_visible:
            self._pending_countdown_skins = skins
        else:
            self._countdown_skins = skins
            self._pending_countdown_skins = None
        self.update()

    def show_interaction_bubble(self, text: str, *, duration_ms: int = 3_200) -> None:
        """在宠物旁边显示一条短暂的远程互动提示。"""
        normalized = " ".join(str(text).split())[:160]
        if not normalized:
            return
        self._interaction_bubble_text = normalized
        self.interaction_bubble.setText(normalized)
        self.interaction_bubble.adjustSize()
        if self.isVisible():
            anchor = self.mapToGlobal(QPoint(self.width() + 8, max(0, self.height() // 3)))
            self.interaction_bubble.move(anchor)
        else:
            self.interaction_bubble.move(0, 0)
        self.interaction_bubble.show()
        self.interaction_bubble.raise_()
        self._interaction_bubble_timer.start(max(500, int(duration_ms)))

    def clear_interaction_bubble(self) -> None:
        self._interaction_bubble_timer.stop()
        self._interaction_bubble_text = None
        self.interaction_bubble.hide()

    def show_codex_status(self, snapshot: CodexLinkSnapshot) -> None:
        """显示独立 Codex 状态，不占用局域网消息气泡。"""
        self.codex_status_bubble.show_snapshot(snapshot, self._global_window_rect())

    def clear_codex_status(self) -> None:
        self.codex_status_bubble.clear()

    def show_lan_firewall_notice(self) -> None:
        self.lan_firewall_notice.show_notice(self._global_window_rect())

    def clear_lan_firewall_notice(self) -> None:
        self.lan_firewall_notice.clear()

    def play_effect(self, effect: object, *, loop: bool = False) -> bool:
        """在宠物画布中播放本地动效；``layer`` 决定绘制顺序。"""
        frames = tuple(getattr(effect, "frames", ()))
        pixmaps = tuple(QPixmap(str(path)) for path in frames)
        pixmaps = tuple(pixmap for pixmap in pixmaps if not pixmap.isNull())
        if not pixmaps:
            return False
        self.clear_effect()
        layer = str(getattr(effect, "layer", "over"))
        self._active_effect_id = str(getattr(effect, "identifier", "effect"))
        self._active_effect_layer = layer if layer in {"under", "over"} else "over"
        self._effect_pixmaps = pixmaps
        self._effect_frame_index = 0
        self._effect_loop = bool(loop)
        duration_ms = max(1, int(getattr(effect, "duration_ms", 1_000)))
        interval = max(1, round(duration_ms / len(pixmaps)))
        self._effect_timer.start(interval)
        self.update()
        return True

    def clear_effect(self) -> None:
        self._effect_timer.stop()
        self._active_effect_id = None
        self._active_effect_layer = "over"
        self._effect_pixmaps = ()
        self._effect_frame_index = 0
        self.update()

    def _on_effect_tick(self) -> None:
        if not self._effect_pixmaps:
            self.clear_effect()
            return
        next_index = self._effect_frame_index + 1
        if next_index >= len(self._effect_pixmaps):
            if not self._effect_loop:
                self.clear_effect()
                return
            next_index = 0
        self._effect_frame_index = next_index
        self.update()

    def handle_pet_event(self, event: PetEvent) -> None:
        """供应用事件总线传入统一事件，不暴露内部播放细节。"""
        transition = self.state_machine.handle(event)
        if transition.changed:
            self._play_current_action()

    def load_package(self, package: PetPackage) -> None:
        """切换宠物包，并释放旧动画缓存以避免积累图像内存。"""
        self._cancel_hold_play(restore=False)
        self._clear_interaction_item_ui()
        self.animation_timer.stop()
        self.clear_effect()
        self.clear_interaction_bubble()
        self.player.clear()
        self._pixmap_cache.clear()
        self._countdown_bottom_cache.clear()
        self._hover_action_bounds_cache.clear()
        self._alpha_cache.clear()
        self.package = package
        self._scale = package.display.default_scale
        self.state_machine = self._make_state_machine(package)
        self._interaction_items = self._interaction_item_resolver.resolve(package)
        self.interaction_toolbox.set_items(self._interaction_items)
        self._play_current_action()
        self.move(self.clamp_position(self.pos()))

    def restore_runtime_state(self, action: str, *, paused: bool) -> None:
        """恢复指定动作的首帧及暂停状态；缺失动作安全回退至 idle。"""
        target = action if action in self.package.animations else "idle"
        self.state_machine = self._make_state_machine(
            self.package,
            extra_bindings={"runtime.restore": target},
        )
        self.handle_pet_event(
            PetEvent(
                "runtime.restore",
                source="runtime",
                priority=self.package.animations["idle"].priority + 1,
            )
        )
        self.set_paused(paused)

    def enterEvent(self, event: QEnterEvent) -> None:  # noqa: N802 - Qt 覆盖名。
        self._pet_hovered = True
        self._interaction_hide_timer.stop()
        opaque = self.is_opaque_at(int(event.position().x()), int(event.position().y()))
        if opaque:
            self._handle_event("mouse.enter")
        if self._hover_tools_can_show():
            self._freeze_hover_tool_anchor()
            self.interaction_toolbox.show_for(self._hover_tool_anchor_global_rect())
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:  # type: ignore[name-defined] # noqa: N802
        self._pet_hovered = False
        self._schedule_interaction_toolbox_hide()
        self._handle_event("mouse.leave")
        super().leaveEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 - Qt 覆盖名。
        item = self._interaction_item(event.mimeData())
        if self._interaction_can_show() and item is not None and item.definition.hold_play is not None:
            self._begin_hold_play(item, event.position().toPoint())
            event.acceptProposedAction()
            return
        if self._interaction_can_show() and item is not None:
            event.acceptProposedAction()
            return
        self._set_drop_highlight(False)
        event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802 - Qt 覆盖名。
        position = event.position().toPoint()
        item = self._interaction_item(event.mimeData())
        if self._hold_play_controller is not None and item == self._hold_play_item:
            self._update_hold_play_target(position, now_ms=self._hold_play_now_ms())
            self._drag_cursor_overlay.move_hotspot(self.mapToGlobal(position))
            event.acceptProposedAction()
            return
        accepted = (
            self._interaction_can_show()
            and self._interaction_item_id(event.mimeData()) is not None
            and self.is_opaque_at(position.x(), position.y())
        )
        self._set_drop_highlight(accepted)
        if accepted:
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:  # noqa: N802 - Qt 覆盖名。
        self._cancel_hold_play(restore=True)
        self._set_drop_highlight(False)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 - Qt 覆盖名。
        try:
            if not self._interaction_can_show():
                event.ignore()
                return
            item_id = self._interaction_item_id(event.mimeData())
            if (
                item_id is not None
                and self._hold_play_controller is not None
                and self._hold_play_item is not None
                and self._hold_play_item.definition.identifier == item_id
            ):
                item = self._hold_play_item
                update = self._hold_play_controller.release_inside(
                    has_drop_action=item.action_name is not None
                )
                if update.finish_drop:
                    self._finish_hold_play_drop(item)
                elif update.phase in {HoldPlayPhase.ATTACKING, HoldPlayPhase.PENDING_DROP}:
                    self._hold_play_pending_item = item
                    self._drag_cursor_overlay.clear()
                else:
                    self._cancel_hold_play(restore=True)
                event.setDropAction(Qt.DropAction.MoveAction)
                event.accept()
                return
            if item_id is not None and self.trigger_interaction_item(item_id, event.position().toPoint()):
                event.setDropAction(Qt.DropAction.MoveAction)
                event.accept()
                return
            event.ignore()
        finally:
            self._set_drop_highlight(False)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._is_countdown_at(event.position().toPoint()):
            self._countdown_pressed = True
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._is_interactive(event):
            self._press_global = event.globalPosition().toPoint()
            self._window_origin = self.pos()
            self._dragging = False
            self._last_drag_global = self._press_global
            self._drag_direction = None
            self._drag_action_override = False
            self._drag_context_action = None
            event.accept()
            return
        event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._countdown_pressed:
            event.accept()
            return
        if self._press_global is None or self._window_origin is None:
            event.ignore()
            return
        current_global = event.globalPosition().toPoint()
        delta = current_global - self._press_global
        if self._last_drag_global is not None:
            horizontal_step = current_global.x() - self._last_drag_global.x()
            if horizontal_step < 0:
                self._drag_direction = "left"
            elif horizontal_step > 0:
                self._drag_direction = "right"
        self._last_drag_global = current_global
        started_dragging = False
        if not self._dragging and hypot(delta.x(), delta.y()) >= self.drag_threshold:
            self._dragging = True
            transition = self._handle_event("mouse.drag_start")
            current = self.package.animations[self.state_machine.current_action]
            self._drag_action_override = transition.changed or (
                transition.reason == "already-current" and current.interruptible
            )
            self._drag_context_action = self.state_machine.current_action if self._drag_action_override else None
            started_dragging = True
        if self._dragging:
            if self.state_machine.current_action != self._drag_context_action:
                self._drag_action_override = False
            if self._drag_action_override:
                action = self._drag_action(self._drag_direction)
                if action != self._playing_action:
                    self._play_action(action)
            if started_dragging:
                # Commit the final direction-specific transparent frame before
                # the native macOS window starts moving. Otherwise WindowServer
                # can briefly composite the previous surface behind it.
                self.repaint()
            self.move(self.clamp_position(self._window_origin + delta))
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._is_countdown_at(event.position().toPoint()):
            self._countdown_pressed = False
            self.countdown_clicked.emit()
            event.accept()
            return
        event.ignore()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._countdown_pressed:
            self._countdown_pressed = False
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton or self._press_global is None:
            event.ignore()
            return
        was_dragging = self._dragging
        self._press_global = None
        self._window_origin = None
        self._dragging = False
        self._last_drag_global = None
        self._drag_direction = None
        self._drag_action_override = False
        self._drag_context_action = None
        if was_dragging:
            self._handle_event("mouse.drag_end")
            if self._playing_action != self.state_machine.current_action:
                self._play_current_action()
            if self._position_saved is not None:
                self._position_saved(self.pos())
        elif self._is_interactive(event):
            self._handle_event("mouse.click")
        event.accept()

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802 - Qt 覆盖名。
        """仅在宠物当前可见像素上请求快捷菜单。"""
        position = event.pos()
        if self._mouse_interaction_enabled and self.is_opaque_at(position.x(), position.y()):
            self.context_menu_requested.emit(event.globalPos())
            event.accept()
            return
        event.ignore()

    def moveEvent(self, event: object) -> None:  # noqa: N802 - Qt 覆盖名。
        if self.interaction_bubble.isVisible():
            self.interaction_bubble.move(self.mapToGlobal(QPoint(self.width() + 8, max(0, self.height() // 3))))
        self.codex_status_bubble.reposition(self._global_window_rect())
        self.lan_firewall_notice.reposition(self._global_window_rect())
        if self.interaction_toolbox.isVisible():
            self.interaction_toolbox.reposition(self._hover_tool_anchor_global_rect())
        super().moveEvent(event)  # type: ignore[arg-type]
        self.position_changed.emit()

    def hideEvent(self, event: object) -> None:  # noqa: N802 - Qt 覆盖名。
        self._cancel_hold_play(restore=False)
        self._clear_interaction_item_ui()
        super().hideEvent(event)  # type: ignore[arg-type]

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt 覆盖名。
        self._cancel_hold_play(restore=False)
        self._drag_cursor_overlay.close()
        self._drag_cursor_overlay.deleteLater()
        self._clear_interaction_item_ui()
        self._dispose_interaction_toolbox()
        self.clear_interaction_bubble()
        self.clear_codex_status()
        self.clear_lan_firewall_notice()
        self.clear_effect()
        super().closeEvent(event)  # type: ignore[arg-type]

    def _global_window_rect(self) -> QRect:
        return QRect(self.mapToGlobal(QPoint(0, 0)), self.size())

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        if self._current_pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        # Clear the translucent backing store first so macOS cannot retain pixels
        # from the previous frame while moving the window. Draw the actual layers
        # with SourceOver so transparent effect pixels preserve the pet beneath.
        _prepare_translucent_frame(painter, self.rect())
        pet_rect = QRect(self._pet_left(), 0, self._pet_width(), self._pet_height())
        if self._hold_play_controller is not None:
            correction = self._hold_play_controller.correction_for_frame(
                self.player.current_frame_index + 1
            )
            pet_rect.translate(
                round(correction[0] * self.scale),
                round(correction[1] * self.scale),
            )
        if self._active_effect_layer == "under":
            self._draw_active_effect(painter, pet_rect)
        if self._follow_motion and self._follow_facing_left and self._playing_action in {"walk", "drag"}:
            painter.save()
            painter.translate(pet_rect.left() + pet_rect.width(), 0)
            painter.scale(-1, 1)
            painter.drawPixmap(QRect(0, pet_rect.top(), pet_rect.width(), pet_rect.height()), self._current_pixmap)
            painter.restore()
        else:
            painter.drawPixmap(pet_rect, self._current_pixmap)
        if self._active_effect_layer == "over":
            self._draw_active_effect(painter, pet_rect)
        if self._drop_highlight:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#D98663"), 2))
            painter.drawRoundedRect(pet_rect.adjusted(1, 1, -1, -1), 8, 8)
        if self.countdown_is_visible:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            bubble = self._countdown_rect()
            skin = self._countdown_skins.get(self._countdown_theme)
            if skin is not None and not skin.isNull():
                self._draw_countdown_skin(painter, bubble, skin)
            font = self._countdown_font(bubble.height())
            painter.setFont(font)
            text_colours = {"cream": "#754453", "night": "#FFF9FF", "yarn": "#69483D"}
            painter.setPen(QColor(text_colours[self._countdown_theme]))
            left_inset, right_inset = self._countdown_text_insets(bubble.height())
            text_rect = bubble.adjusted(left_inset, 0, -right_inset, 0)
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, self._countdown_text)

    def _draw_active_effect(self, painter: QPainter, pet_rect: QRect) -> None:
        if not self._effect_pixmaps:
            return
        source = self._effect_pixmaps[self._effect_frame_index]
        scaled = source.scaled(
            pet_rect.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        target = QRect(
            pet_rect.center().x() - scaled.width() // 2,
            pet_rect.center().y() - scaled.height() // 2,
            scaled.width(),
            scaled.height(),
        )
        painter.drawPixmap(target, scaled)

    def _handle_event(self, event_name: str) -> StateTransition:
        transition = self.state_machine.handle(PetEvent(event_name, source="mouse"))
        if transition.changed:
            self._play_current_action()
        return transition

    def _interaction_can_show(self) -> bool:
        return (
            self.interaction_items_available
            and self._mouse_interaction_enabled
            and not self._follow_mode_enabled
            and self.isVisible()
        )

    def _hover_tools_can_show(self) -> bool:
        return (
            (self.interaction_items_available or self.interaction_toolbox.notebook_enabled)
            and self._mouse_interaction_enabled
            and not self._follow_mode_enabled
            and self.isVisible()
        )

    def _action_visible_pet_rect(self) -> QRect:
        bounds = self._hover_action_bounds_cache.get(self._playing_action)
        if bounds is None:
            bounds = _visible_frame_union(
                self.player.current_frames,
                QSize(self.package.canvas.width, self.package.canvas.height),
            )
            self._hover_action_bounds_cache[self._playing_action] = QRect(bounds)
        left = floor(bounds.left() * self.scale)
        top = floor(bounds.top() * self.scale)
        right = ceil((bounds.right() + 1) * self.scale)
        bottom = ceil((bounds.bottom() + 1) * self.scale)
        return QRect(left, top, max(1, right - left), max(1, bottom - top))

    def _freeze_hover_tool_anchor(self) -> None:
        self._frozen_hover_anchor_pet_rect = self._action_visible_pet_rect()

    def _hover_tool_anchor_global_rect(self) -> QRect:
        anchor = self._frozen_hover_anchor_pet_rect
        if anchor is None:
            anchor = QRect(0, 0, self._pet_width(), self._pet_height())
        local_top_left = QPoint(self._pet_left() + anchor.left(), anchor.top())
        return QRect(self.mapToGlobal(local_top_left), anchor.size())

    def _on_interaction_toolbox_hover_changed(self, hovered: bool) -> None:
        self._toolbox_hovered = hovered
        if hovered:
            self._interaction_hide_timer.stop()
        else:
            self._schedule_interaction_toolbox_hide()

    def _schedule_interaction_toolbox_hide(self) -> None:
        if self._pet_hovered or self._toolbox_hovered or not self.interaction_toolbox.isVisible():
            self._interaction_hide_timer.stop()
            return
        self._interaction_hide_timer.start()

    def _hide_interaction_toolbox_if_unhovered(self) -> None:
        if self._pet_hovered or self._toolbox_hovered:
            return
        self.interaction_toolbox.hide_all()
        self._frozen_hover_anchor_pet_rect = None

    def _clear_interaction_item_ui(self) -> None:
        self._interaction_hide_timer.stop()
        self._pet_hovered = False
        self._toolbox_hovered = False
        self._set_drop_highlight(False)
        self.interaction_toolbox.hide_all()
        self._frozen_hover_anchor_pet_rect = None

    def _set_drop_highlight(self, highlighted: bool) -> None:
        if self._drop_highlight == highlighted:
            return
        self._drop_highlight = highlighted
        self.update()

    def _interaction_item_id(self, mime_data: QMimeData) -> str | None:
        if not mime_data.hasFormat(INTERACTION_ITEM_MIME):
            return None
        try:
            item_id = bytes(mime_data.data(INTERACTION_ITEM_MIME)).decode("utf-8")
        except UnicodeDecodeError:
            return None
        if any(item.definition.identifier == item_id for item in self._interaction_items):
            return item_id
        return None

    def _interaction_item(self, mime_data: QMimeData) -> ResolvedInteractionItem | None:
        item_id = self._interaction_item_id(mime_data)
        if item_id is None:
            return None
        return next(
            (item for item in self._interaction_items if item.definition.identifier == item_id),
            None,
        )

    @staticmethod
    def _hold_play_now_ms() -> int:
        return round(monotonic() * 1000)

    def _begin_hold_play(self, item: ResolvedInteractionItem, position: QPoint) -> None:
        configured = item.definition.hold_play
        if configured is None:
            return
        if self._hold_play_controller is None:
            self._hold_play_restore_action = self.state_machine.current_action
            self._hold_play_controller = HoldPlayController(configured)
            self._hold_play_item = item
        update = self._hold_play_controller.enter(now_ms=self._hold_play_now_ms())
        if update.action is not None:
            self._play_action(update.action)
        self._drag_cursor_overlay.show_at(
            self.mapToGlobal(position),
            configured.cursor,
            hotspot=configured.cursor_hotspot,
        )

    def _update_hold_play_target(self, position: QPoint, *, now_ms: int) -> None:
        controller = self._hold_play_controller
        if controller is None:
            return
        point = (
            round((position.x() - self._pet_left()) / self.scale),
            round(position.y() / self.scale),
        )
        update = controller.move(point, now_ms=now_ms)
        if update.deadline_ms is not None:
            self._hold_play_timer.start(max(1, update.deadline_ms - now_ms))

    def _on_hold_play_deadline(self, *, now_ms: int | None = None) -> None:
        controller = self._hold_play_controller
        if controller is None:
            return
        current = self._hold_play_now_ms() if now_ms is None else now_ms
        update = controller.tick(now_ms=current)
        if update.action is not None:
            self._play_action(update.action)
        if update.deadline_ms is not None and update.deadline_ms > current:
            self._hold_play_timer.start(update.deadline_ms - current)

    def _on_item_drag_finished(self, item_id: str, result: object) -> None:
        if (
            self._hold_play_item is not None
            and self._hold_play_item.definition.identifier == item_id
            and result != Qt.DropAction.MoveAction
        ):
            self._cancel_hold_play(restore=True)

    def _finish_hold_play_drop(self, item: ResolvedInteractionItem) -> None:
        self._cancel_hold_play(restore=False)
        if item.event_name is None or item.action_name is None:
            self._play_current_action()
            return
        transition = self.state_machine.handle(
            PetEvent(item.event_name, source="interaction-item", payload={"item_id": item.definition.identifier})
        )
        if transition.changed:
            self._play_current_action()

    def _cancel_hold_play(self, *, restore: bool) -> None:
        if self._hold_play_controller is None and self._hold_play_item is None:
            return
        self._hold_play_timer.stop()
        self._drag_cursor_overlay.clear()
        restore_action = self._hold_play_restore_action
        self._hold_play_controller = None
        self._hold_play_item = None
        self._hold_play_pending_item = None
        self._hold_play_restore_action = None
        if restore:
            if restore_action in self.package.animations:
                self._play_action(restore_action)
            else:
                self._play_current_action()

    def _play_current_action(self) -> None:
        action = self._follow_action() if self._follow_motion else self.state_machine.current_action
        self._play_action(action)

    def _play_action(self, action: str) -> None:
        previous_canvas = self._current_pet_canvas()
        definition = self.package.animations[action]
        canvas_changes = (definition.canvas or self.package.canvas) != previous_canvas
        bottom_center = (
            self._pet_bottom_center_global()
            if self.isVisible() and canvas_changes
            else None
        )
        if action != self._playing_action:
            self._pixmap_cache.clear()
        self._playing_action = action
        self.player.play(definition)
        self._set_current_frame()
        current_bottom_center = self._pet_bottom_center_global()
        if bottom_center is not None and current_bottom_center != bottom_center:
            self.move(self.clamp_position(self.pos() + bottom_center - current_bottom_center))
        self._start_animation_timer()

    def _start_animation_timer(self) -> None:
        if self.player.is_paused:
            return
        interval = self.player.frame_interval_seconds
        if interval is not None:
            self.animation_timer.start(max(1, round(interval * 1000)))

    def _on_animation_tick(self) -> None:
        self.player.advance()
        if self.player.is_finished:
            if self._hold_play_controller is not None and self._hold_play_controller.phase in {
                HoldPlayPhase.ATTACKING,
                HoldPlayPhase.PENDING_DROP,
            }:
                update = self._hold_play_controller.attack_completed(
                    now_ms=self._hold_play_now_ms()
                )
                if update.finish_drop and self._hold_play_pending_item is not None:
                    self._finish_hold_play_drop(self._hold_play_pending_item)
                    return
                if update.phase is HoldPlayPhase.INACTIVE:
                    self._cancel_hold_play(restore=True)
                    return
                if update.action is not None:
                    self._play_action(update.action)
                    if update.deadline_ms is not None:
                        self._hold_play_timer.start(
                            max(1, update.deadline_ms - self._hold_play_now_ms())
                        )
                    return
            if self._follow_motion:
                self._play_current_action()
                return
            transition = self.state_machine.complete_current_animation()
            if transition.changed:
                self._play_current_action()
                return
        self._set_current_frame()
        self._start_animation_timer()

    def _set_current_frame(self) -> None:
        frame = self.player.current_frame
        if frame is None:
            self._current_pixmap = QPixmap()
            self.update()
            return
        cache_key = id(frame)
        pixmap = self._pixmap_cache.get(cache_key)
        if pixmap is None:
            pixmap = _pixmap_from_pillow(frame)
            self._pixmap_cache[cache_key] = pixmap
        self._current_pixmap = pixmap
        size = self._scaled_canvas_size()
        if self.size() != size:
            self.setFixedSize(size)
        self.update()

    def _scaled_canvas_size(self) -> QSize:
        width = self._pet_width()
        height = self._pet_height()
        if self.countdown_is_visible:
            width = max(width, self._effective_countdown_width())
            height = max(height, self._countdown_top() + self._countdown_card_height)
        return QSize(width, height)

    def _pet_width(self) -> int:
        return round(self._current_pet_canvas().width * self.scale)

    def _drag_action(self, direction: str | None) -> str:
        """按当前水平拖动方向选择专用动作，并逐级回退到通用动作。"""
        candidates: list[str] = []
        if direction in {"left", "right"}:
            candidates.append(f"drag_{direction}")
        candidates.append("drag")
        if direction in {"left", "right"}:
            candidates.append(f"walk_{direction}")
            if direction == "left":
                candidates.append("codex_running_left")
        candidates.extend(("walk", "idle"))
        return next(name for name in candidates if name in self.package.animations)

    def _follow_action(self) -> str:
        """优先方向专用帧；普通宠物包安全回退到 walk 或 drag。"""
        for base in ("walk", "drag"):
            directional = f"{base}_{self._follow_direction}"
            if directional in self.package.animations:
                return directional
        if self._follow_direction in {"up", "down"}:
            horizontal = "left" if self._follow_facing_left else "right"
            for base in ("walk", "drag"):
                directional = f"{base}_{horizontal}"
                if directional in self.package.animations:
                    return directional
        return next((name for name in ("walk", "drag") if name in self.package.animations), self.state_machine.current_action)

    def _pet_height(self) -> int:
        return round(self._current_pet_canvas().height * self.scale)

    def _current_pet_canvas(self) -> Canvas:
        definition = self.package.animations[self._playing_action]
        return definition.canvas or self.package.canvas

    def _pet_bottom_center_global(self) -> QPoint:
        return self.mapToGlobal(
            QPoint(self._pet_left() + self._pet_width() // 2, self._pet_height())
        )

    def _pet_left(self) -> int:
        return max(0, (self.width() - self._pet_width()) // 2)

    def _countdown_rect(self) -> QRect:
        width = self._effective_countdown_width()
        height = self._countdown_card_height
        left = (self.width() - width) // 2
        top = self._countdown_top()
        return QRect(left, top, width, height)

    def _effective_countdown_width(self) -> int:
        if self._countdown_text is None:
            return self._countdown_width
        font = self._countdown_font(self._countdown_card_height)
        text_width = QFontMetrics(font).horizontalAdvance(self._countdown_text)
        left, right = self._countdown_text_insets(self._countdown_card_height)
        return max(self._countdown_width, text_width + left + right + 8)

    def _countdown_font(self, height: int) -> QFont:
        font = self.font()
        font.setPixelSize(max(9, min(14, height // 3)))
        font.setBold(True)
        return font

    def _countdown_text_insets(self, height: int) -> tuple[int, int]:
        base = {"cream": (30, 8), "night": (29, 21), "yarn": (31, 23)}[self._countdown_theme]
        scale = height / 37
        return max(5, round(base[0] * scale)), max(5, round(base[1] * scale))

    def _draw_countdown_skin(self, painter: QPainter, target: QRect, skin: QPixmap) -> None:
        """固定两侧装饰，仅横向拉伸空白中段，保证设置尺寸真实生效。"""
        source_caps = {"cream": (235, 75), "night": (205, 95), "yarn": (245, 145)}
        source_left, source_right = source_caps[self._countdown_theme]
        vertical_scale = target.height() / skin.height()
        target_left = max(1, round(source_left * vertical_scale))
        target_right = max(1, round(source_right * vertical_scale))
        if target_left + target_right >= target.width():
            ratio = target.width() / (target_left + target_right + 1)
            target_left = max(1, round(target_left * ratio))
            target_right = max(1, round(target_right * ratio))
        target_middle = target.width() - target_left - target_right
        source_middle = skin.width() - source_left - source_right
        painter.drawPixmap(
            QRect(target.left(), target.top(), target_left, target.height()),
            skin,
            QRect(0, 0, source_left, skin.height()),
        )
        painter.drawPixmap(
            QRect(target.left() + target_left, target.top(), target_middle, target.height()),
            skin,
            QRect(source_left, 0, source_middle, skin.height()),
        )
        painter.drawPixmap(
            QRect(target.right() - target_right + 1, target.top(), target_right, target.height()),
            skin,
            QRect(skin.width() - source_right, 0, source_right, skin.height()),
        )

    def _countdown_top(self) -> int:
        """按当前动作全部帧的实际 alpha 底边定位，忽略素材透明留白。"""
        if self._playing_action not in self._countdown_bottom_cache:
            visible_bottom = 0
            for frame in self.player.current_frames:
                bounds = frame.getchannel("A").getbbox()
                if bounds is not None:
                    visible_bottom = max(visible_bottom, bounds[3])
            if visible_bottom == 0:
                visible_bottom = self.package.canvas.height
            self._countdown_bottom_cache[self._playing_action] = visible_bottom
        visible_bottom = self._countdown_bottom_cache[self._playing_action]
        return round(visible_bottom * self.scale) + self._countdown_gap

    @staticmethod
    def _load_countdown_skins(directory: Path | None = None) -> dict[str, QPixmap]:
        if directory is None:
            root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
            directory = root / "assets" / "countdown"
        return {theme: QPixmap(str(directory / f"{theme}.png")) for theme in ("cream", "night", "yarn")}

    def _is_interactive(self, event: QMouseEvent) -> bool:
        return self._mouse_interaction_enabled and self.is_opaque_at(int(event.position().x()), int(event.position().y()))

    def _is_countdown_at(self, position: QPoint) -> bool:
        return self._mouse_interaction_enabled and self.countdown_is_visible and self._countdown_rect().contains(position)

    @staticmethod
    def _make_state_machine(
        package: PetPackage,
        *,
        extra_bindings: Mapping[str, str] | None = None,
    ) -> PetStateMachine:
        standard_bindings = {
            "system.bored": "bored",
            "system.sleep": "sleep",
            "system.wake": "wake",
        }
        standard_fallbacks = {
            "bored": ("idle",),
            "sleep": ("idle",),
            "wake": ("idle",),
        }
        desktop_animations = {
            name: definition
            for name, definition in package.animations.items()
            if definition.scope == "pet"
        }
        return PetStateMachine(
            desktop_animations,
            {**standard_bindings, **package.bindings, **(extra_bindings or {})},
            {**standard_fallbacks, **package.fallbacks},
        )


def _pixmap_from_pillow(frame: Image.Image) -> QPixmap:
    """将内存 RGBA Pillow 帧复制为 Qt 像素图，不保留临时字节引用。"""
    from PySide6.QtGui import QImage

    rgba = frame.convert("RGBA")
    image = QImage(
        rgba.tobytes("raw", "RGBA"),
        rgba.width,
        rgba.height,
        QImage.Format.Format_RGBA8888,
    ).copy()
    return QPixmap.fromImage(image)
