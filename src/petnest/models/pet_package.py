"""宠物包的类型化配置模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Canvas:
    """所有动画帧共用的逻辑画布。"""

    width: int
    height: int


@dataclass(frozen=True, slots=True)
class DisplaySettings:
    """宠物包提供的默认显示参数。"""

    default_scale: float = 1.0
    min_scale: float = 0.25
    max_scale: float = 2.0
    alpha_hit_test_threshold: int = 10


@dataclass(frozen=True, slots=True)
class AnimationDefinition:
    """一个动作的配置与已校验 PNG 帧路径。"""

    name: str
    path: Path
    fps: float
    loop: bool
    next_animation: str | None
    priority: int
    interruptible: bool
    restart_on_reenter: bool = False
    frame_durations_ms: tuple[int, ...] | None = None
    speed_multiplier: float = 1.0
    frames: tuple[Path, ...] = field(default_factory=tuple)
    scope: str = "pet"
    canvas: Canvas | None = None
    entrance_direction: str = "right"


@dataclass(frozen=True, slots=True)
class PetPackage:
    """已通过校验、可安全加载的宠物包。"""

    root: Path
    identifier: str
    name: str
    version: str
    canvas: Canvas
    animations: dict[str, AnimationDefinition]
    bindings: dict[str, str]
    fallbacks: dict[str, tuple[str, ...]]
    display: DisplaySettings = field(default_factory=DisplaySettings)
    author: str | None = None
    description: str | None = None
