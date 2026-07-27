"""预加载 PNG 帧、与 UI 工具包无关的动画播放实例。"""

from __future__ import annotations

from collections.abc import Callable
import logging
from pathlib import Path

from PIL import Image

from petnest.models.pet_package import AnimationDefinition

CompletionHandler = Callable[[AnimationDefinition], object]
ImageLoader = Callable[[Path], Image.Image]

LOGGER = logging.getLogger(__name__)


class AnimationPlayer:
    """维护当前播放实例和帧缓存，而不承担宠物逻辑状态的决策。"""

    def __init__(
        self,
        *,
        speed_multiplier: float = 1.0,
        image_loader: ImageLoader | None = None,
        warning_frame_limit: int = 500,
    ) -> None:
        if speed_multiplier <= 0:
            raise ValueError("动画速度倍率必须大于 0")
        if warning_frame_limit <= 0:
            raise ValueError("帧数警告上限必须大于 0")
        self._speed_multiplier = speed_multiplier
        self._image_loader = image_loader or _load_rgba_image
        self._warning_frame_limit = warning_frame_limit
        self._cache: dict[AnimationDefinition, tuple[Image.Image, ...]] = {}
        self._current_definition: AnimationDefinition | None = None
        self._current_frames: tuple[Image.Image, ...] = ()
        self._current_frame_index = 0
        self._paused = False
        self._finished = False
        self._completion_handlers: list[CompletionHandler] = []

    @property
    def current_definition(self) -> AnimationDefinition | None:
        """当前播放的动作定义；尚未播放时为 ``None``。"""
        return self._current_definition

    @property
    def current_frame(self) -> Image.Image | None:
        """当前内存帧，不会在每次读取时访问磁盘。"""
        if not self._current_frames:
            return None
        return self._current_frames[self._current_frame_index]

    @property
    def current_frame_index(self) -> int:
        """当前帧的从零开始索引。"""
        return self._current_frame_index

    @property
    def is_paused(self) -> bool:
        """播放器是否因全局暂停而停止前进。"""
        return self._paused

    @property
    def is_finished(self) -> bool:
        """单次动画到达末帧后为真；循环动画始终为假。"""
        return self._finished

    @property
    def frame_interval_seconds(self) -> float | None:
        """给 UI 计时器使用的当前帧间隔。"""
        if self._current_definition is None:
            return None
        return 1.0 / (self._current_definition.fps * self._speed_multiplier)

    def preload(self, definition: AnimationDefinition) -> tuple[Image.Image, ...]:
        """将一个动作的所有 PNG 复制到内存，并复用已有的缓存。"""
        cached = self._cache.get(definition)
        if cached is not None:
            return cached
        if not definition.frames:
            raise ValueError(f"动画 {definition.name!r} 没有可播放帧")
        if len(definition.frames) > self._warning_frame_limit:
            LOGGER.warning("动画 %s 有 %d 帧，预加载可能占用较多内存", definition.name, len(definition.frames))
        loaded: list[Image.Image] = []
        try:
            for path in definition.frames:
                loaded.append(self._image_loader(path))
        except (OSError, ValueError) as error:
            for frame in loaded:
                frame.close()
            raise ValueError(f"无法加载动画 {definition.name!r} 的 PNG 帧: {error}") from error
        frames = tuple(loaded)
        self._cache[definition] = frames
        return frames

    def play(self, definition: AnimationDefinition) -> Image.Image:
        """开始一个新的播放实例；暂停状态由调用方显式恢复。"""
        self._current_definition = definition
        self._current_frames = self.preload(definition)
        self._current_frame_index = 0
        self._finished = False
        return self._current_frames[0]

    def advance(self) -> Image.Image | None:
        """前进一帧；一次动画完成时保留末帧并仅发出一次通知。"""
        frame = self.current_frame
        definition = self._current_definition
        if frame is None or definition is None or self._paused or self._finished:
            return frame
        if self._current_frame_index < len(self._current_frames) - 1:
            self._current_frame_index += 1
        elif definition.loop:
            self._current_frame_index = 0
        else:
            self._finished = True
            self._emit_completed(definition)
        return self.current_frame

    def pause(self) -> None:
        """暂停帧推进，不清除预加载数据。"""
        self._paused = True

    def resume(self) -> None:
        """恢复帧推进。"""
        self._paused = False

    def set_speed_multiplier(self, multiplier: float) -> None:
        """设置正的动画速度倍率。"""
        if multiplier <= 0:
            raise ValueError("动画速度倍率必须大于 0")
        self._speed_multiplier = multiplier

    def subscribe_completed(self, handler: CompletionHandler) -> Callable[[], None]:
        """订阅单次动画结束信号，并返回幂等取消函数。"""
        self._completion_handlers.append(handler)
        active = True

        def unsubscribe() -> None:
            nonlocal active
            if active:
                active = False
                try:
                    self._completion_handlers.remove(handler)
                except ValueError:
                    pass

        return unsubscribe

    def clear(self) -> None:
        """释放当前帧引用与 Pillow 图像缓存，供宠物切换时调用。"""
        self._current_definition = None
        self._current_frames = ()
        self._current_frame_index = 0
        self._finished = False
        for frames in self._cache.values():
            for frame in frames:
                frame.close()
        self._cache.clear()

    def _emit_completed(self, definition: AnimationDefinition) -> None:
        for handler in tuple(self._completion_handlers):
            try:
                handler(definition)
            except Exception:  # noqa: BLE001 - 回调失败不应中断动画计时器。
                LOGGER.exception("动画完成回调失败: %s", definition.name)


def _load_rgba_image(path: Path) -> Image.Image:
    """在文件句柄关闭前复制像素，避免长期占用 PNG 文件。"""
    with Image.open(path) as source:
        return source.convert("RGBA").copy()
