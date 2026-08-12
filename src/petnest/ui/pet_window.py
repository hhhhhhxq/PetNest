"""配置驱动的透明桌面宠物窗口。"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from math import hypot
from pathlib import Path
import sys

from PIL import Image
from PySide6.QtCore import QEvent, QPoint, QRect, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QContextMenuEvent, QEnterEvent, QFont, QFontMetrics, QGuiApplication, QMouseEvent, QPaintEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QWidget

from petnest.core.animation_player import AnimationPlayer
from petnest.core.state_machine import PetStateMachine
from petnest.models.event import PetEvent
from petnest.models.pet_package import PetPackage

PositionSaved = Callable[[QPoint], object]


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

        self.package = package
        self._scale = package.display.default_scale
        self.player = player or AnimationPlayer()
        self.state_machine = state_machine or self._make_state_machine(package)
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
        self._alpha_cache: dict[int, tuple[int, int, bytes]] = {}
        self._press_global: QPoint | None = None
        self._window_origin: QPoint | None = None
        self._dragging = False
        self._mouse_interaction_enabled = True
        self._countdown_text: str | None = None
        self._countdown_gap = 0
        self._countdown_width = 132
        self._countdown_card_height = 37
        self._countdown_theme = "cream"
        self._countdown_placement = "below"
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
        return self._countdown_text is not None and not self._follow_mode_enabled

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
        logical_y = int((y - self._pet_top()) / self.scale)
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
        self._scale = scale
        self._set_current_frame()
        self._start_animation_timer()
        self.move(self.clamp_position(self.pos()))

    def set_follow_mode(self, enabled: bool, *, scale_multiplier: float) -> None:
        """切换鼠标跟随显示层，并保留普通模式的缩放与倒计时内容。"""
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
        """即时切换置顶属性；Qt 需要重新 show 才会应用窗口旗标。"""
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        if self.isVisible():
            self.show()

    def set_mouse_interaction_enabled(self, enabled: bool) -> None:
        """关闭后忽略宠物鼠标事件，保留窗口显示和动画。"""
        self._mouse_interaction_enabled = enabled

    def set_countdown_text(self, text: str | None) -> None:
        """显示倒计时；空值会移除预留区域。"""
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

    def set_countdown_appearance(
        self,
        *,
        gap: int,
        width: int,
        height: int,
        theme: str = "cream",
        placement: str = "below",
    ) -> None:
        """更新倒计时卡片尺寸及它与宠物之间的垂直间距。"""
        pet_origin = self.pos() + QPoint(self._pet_left(), self._pet_top())
        self._countdown_gap = max(0, min(int(gap), 80))
        self._countdown_width = max(110, min(int(width), 420))
        self._countdown_card_height = max(26, min(int(height), 100))
        self._countdown_theme = theme if theme in {"cream", "night", "yarn"} else "cream"
        self._countdown_placement = placement if placement in {"above", "below"} else "above"
        if self.countdown_is_visible:
            self.setFixedSize(self._scaled_canvas_size())
            target = pet_origin - QPoint(self._pet_left(), self._pet_top())
            self.move(self.clamp_position(target))
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
        self.animation_timer.stop()
        self.clear_effect()
        self.clear_interaction_bubble()
        self.player.clear()
        self._pixmap_cache.clear()
        self._countdown_bottom_cache.clear()
        self._alpha_cache.clear()
        self.package = package
        self._scale = package.display.default_scale
        self.state_machine = self._make_state_machine(package)
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
        if self.is_opaque_at(int(event.position().x()), int(event.position().y())):
            self._handle_event("mouse.enter")
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:  # type: ignore[name-defined] # noqa: N802
        self._handle_event("mouse.leave")
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self._is_interactive(event):
            self._press_global = event.globalPosition().toPoint()
            self._window_origin = self.pos()
            self._dragging = False
            event.accept()
            return
        event.ignore()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._press_global is None or self._window_origin is None:
            event.ignore()
            return
        delta = event.globalPosition().toPoint() - self._press_global
        if not self._dragging and hypot(delta.x(), delta.y()) >= self.drag_threshold:
            self._dragging = True
            self._handle_event("mouse.drag_start")
        if self._dragging:
            self.move(self.clamp_position(self._window_origin + delta))
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or self._press_global is None:
            event.ignore()
            return
        was_dragging = self._dragging
        self._press_global = None
        self._window_origin = None
        self._dragging = False
        if was_dragging:
            self._handle_event("mouse.drag_end")
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
        super().moveEvent(event)  # type: ignore[arg-type]

    def closeEvent(self, event: object) -> None:  # noqa: N802 - Qt 覆盖名。
        self.clear_interaction_bubble()
        self.clear_effect()
        super().closeEvent(event)  # type: ignore[arg-type]

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        if self._current_pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        pet_rect = QRect(self._pet_left(), self._pet_top(), self._pet_width(), self._pet_height())
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

    def _handle_event(self, event_name: str) -> None:
        transition = self.state_machine.handle(PetEvent(event_name, source="mouse"))
        if transition.changed:
            self._play_current_action()

    def _play_current_action(self) -> None:
        action = self._follow_action() if self._follow_motion else self.state_machine.current_action
        self._play_action(action)

    def _play_action(self, action: str) -> None:
        definition = self.package.animations[action]
        if action != self._playing_action:
            self._pixmap_cache.clear()
        self._playing_action = action
        self.player.play(definition)
        self._set_current_frame()
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
            if self._countdown_placement == "above":
                height = self._pet_top() + height
            else:
                height = max(height, self._countdown_top() + self._countdown_card_height)
        return QSize(width, height)

    def _pet_width(self) -> int:
        return round(self.package.canvas.width * self.scale)

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
        return round(self.package.canvas.height * self.scale)

    def _pet_left(self) -> int:
        return max(0, (self.width() - self._pet_width()) // 2)

    def _pet_top(self) -> int:
        if self.countdown_is_visible and self._countdown_placement == "above":
            return self._countdown_card_height + self._countdown_gap
        return 0

    def _countdown_rect(self) -> QRect:
        width = self._effective_countdown_width()
        height = self._countdown_card_height
        left = (self.width() - width) // 2
        top = 0 if self._countdown_placement == "above" else self._countdown_top()
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
        return PetStateMachine(
            package.animations,
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
