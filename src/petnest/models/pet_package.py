"""宠物包的类型化配置模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


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


HoldPlayDirection = Literal["center", "left", "right", "up_left", "up_right"]


@dataclass(frozen=True, slots=True)
class HoldPlayTargetDefinition:
    """按住陪玩时一个目标方向对应的动作与接触校正。"""

    action: str
    contact_frame: int
    contact_point: tuple[int, int]
    max_correction: tuple[int, int]


@dataclass(frozen=True, slots=True)
class HoldPlayDefinition:
    """互动道具可选的按住拖拽陪玩配置。"""

    cursor: Path
    cursor_hotspot: tuple[int, int]
    ready_action: str
    attack_origin: tuple[int, int]
    settle_ms: int
    cooldown_ms: int
    rearm_distance: int
    targets: dict[HoldPlayDirection, HoldPlayTargetDefinition]


@dataclass(frozen=True, slots=True)
class InteractionItemDefinition:
    """宠物包声明的无动作语义互动道具。"""

    identifier: str
    label: str
    icon: Path
    hold_play: HoldPlayDefinition | None = None


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
    interaction_items: tuple[InteractionItemDefinition, ...] = field(default_factory=tuple)
