"""配置驱动的透明桌面宠物窗口。"""

from __future__ import annotations

from collections.abc import Callable
from math import hypot

from PIL import Image
from PySide6.QtCore import QEvent, QPoint, QSize, QTimer, Qt
from PySide6.QtGui import QEnterEvent, QGuiApplication, QMouseEvent, QPaintEvent, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from petnest.core.animation_player import AnimationPlayer
from petnest.core.state_machine import PetStateMachine
from petnest.models.event import PetEvent
from petnest.models.pet_package import PetPackage

PositionSaved = Callable[[QPoint], object]


class PetWindow(QWidget):
    """无边框、置顶且不获取键盘焦点的宠物帧显示窗口。

    窗口本身只把鼠标输入转成 :class:`PetEvent`，不会假设某个角色或动作名以外
    的具体素材；动作映射完全来自 ``PetPackage.bindings``。
    """

    drag_threshold = 6
    minimum_visible_pixels = 48

    def __init__(
        self,
        package: PetPackage,
        *,
        player: AnimationPlayer | None = None,
        state_machine: PetStateMachine | None = None,
        position_saved: PositionSaved | None = None,
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
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)

        self.package = package
        self._scale = package.display.default_scale
        self.player = player or AnimationPlayer()
        self.state_machine = state_machine or self._make_state_machine(package)
        self._position_saved = position_saved
        self._current_pixmap = QPixmap()
        self._alpha_cache: dict[int, tuple[int, int, bytes]] = {}
        self._press_global: QPoint | None = None
        self._window_origin: QPoint | None = None
        self._dragging = False
        self._mouse_interaction_enabled = True

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

    def is_opaque_at(self, x: int, y: int) -> bool:
        """按当前帧的 alpha 通道判断窗口局部坐标是否可交互。

        alpha 字节会按 Pillow 帧对象缓存，从而避免鼠标移动时重复解码图片。
        """
        frame = self.player.current_frame
        if frame is None:
            return False
        logical_x, logical_y = int(x / self.scale), int(y / self.scale)
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
        self._scale = scale
        self._set_current_frame()
        self._start_animation_timer()
        self.move(self.clamp_position(self.pos()))

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

    def handle_pet_event(self, event: PetEvent) -> None:
        """供应用事件总线传入统一事件，不暴露内部播放细节。"""
        transition = self.state_machine.handle(event)
        if transition.changed:
            self._play_current_action()

    def load_package(self, package: PetPackage) -> None:
        """切换宠物包，并释放旧动画缓存以避免积累图像内存。"""
        self.animation_timer.stop()
        self.player.clear()
        self._alpha_cache.clear()
        self.package = package
        self._scale = package.display.default_scale
        self.state_machine = self._make_state_machine(package)
        self._play_current_action()
        self.move(self.clamp_position(self.pos()))

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

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        if self._current_pixmap.isNull():
            return
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self._current_pixmap)

    def _handle_event(self, event_name: str) -> None:
        transition = self.state_machine.handle(PetEvent(event_name, source="mouse"))
        if transition.changed:
            self._play_current_action()

    def _play_current_action(self) -> None:
        definition = self.package.animations[self.state_machine.current_action]
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
        self._current_pixmap = _pixmap_from_pillow(frame)
        size = self._scaled_canvas_size()
        if self.size() != size:
            self.setFixedSize(size)
        self.update()

    def _scaled_canvas_size(self) -> QSize:
        return QSize(
            round(self.package.canvas.width * self.scale),
            round(self.package.canvas.height * self.scale),
        )

    def _is_interactive(self, event: QMouseEvent) -> bool:
        return self._mouse_interaction_enabled and self.is_opaque_at(int(event.position().x()), int(event.position().y()))

    @staticmethod
    def _make_state_machine(package: PetPackage) -> PetStateMachine:
        return PetStateMachine(package.animations, package.bindings, package.fallbacks)


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
