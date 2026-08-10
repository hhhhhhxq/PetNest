"""鼠标跟随模式的采样与定位逻辑，不依赖窗口或平台钩子。"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize


class MouseFollowController:
    """将连续的全局光标采样转换为“是否仍在移动”和安全窗口位置。"""

    def __init__(self, *, stationary_ms: int = 150, offset: int = 8) -> None:
        self.stationary_ms = max(1, stationary_ms)
        self.offset = max(0, offset)
        self._last_cursor: QPoint | None = None
        self._last_moved_at: int | None = None
        self._direction = "right"
        self._facing_left = False

    @property
    def direction(self) -> str:
        """最近一次有效移动的主方向：left、right、up 或 down。"""
        return self._direction

    @property
    def facing_left(self) -> bool:
        """当前水平朝向；上下移动不会改变它。"""
        return self._facing_left

    def reset(self) -> None:
        """清除上一轮跟随状态，下一次采样从静止开始。"""
        self._last_cursor = None
        self._last_moved_at = None
        self._direction = "right"
        self._facing_left = False

    def sample(self, cursor: QPoint, *, now_ms: int) -> bool:
        """记录本次光标位置，并返回是否仍应播放移动动画。"""
        if self._last_cursor is None:
            self._last_cursor = QPoint(cursor)
            self._last_moved_at = now_ms
            return False
        if cursor != self._last_cursor:
            delta = cursor - self._last_cursor
            self._last_cursor = QPoint(cursor)
            self._last_moved_at = now_ms
            if abs(delta.x()) >= abs(delta.y()) and delta.x() != 0:
                self._direction = "left" if delta.x() < 0 else "right"
                self._facing_left = delta.x() < 0
            elif delta.y() != 0:
                self._direction = "up" if delta.y() < 0 else "down"
            return True
        return self._last_moved_at is not None and now_ms - self._last_moved_at < self.stationary_ms

    def target_position(self, cursor: QPoint, pet_size: QSize, screen: QRect) -> QPoint:
        """在光标右下方定位；边缘不足时翻转到左上并完整限制在当前屏幕。"""
        x = cursor.x() + self.offset
        y = cursor.y() + self.offset
        if x + pet_size.width() > screen.right() + 1:
            x = cursor.x() - self.offset - pet_size.width()
        if y + pet_size.height() > screen.bottom() + 1:
            y = cursor.y() - self.offset - pet_size.height()
        x = max(screen.left(), min(x, screen.right() - pet_size.width() + 1))
        y = max(screen.top(), min(y, screen.bottom() - pet_size.height() + 1))
        return QPoint(x, y)
