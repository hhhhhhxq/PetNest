"""PetNest 运行时可真实触发的动作槽位和默认动画语义。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PureWindowsPath
import re

from petnest.models.pet_package import PetPackage
from petnest.core.fallback_resolver import FallbackResolver, GLOBAL_PLACEHOLDER


_SAFE_ACTION_NAME = re.compile(r'^[^\\/:*?"<>|\x00-\x1f]+$')
_WINDOWS_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


@dataclass(frozen=True, slots=True)
class ActionSlot:
    key: str
    label: str
    category: str
    canonical_action: str
    binding_event: str | None
    fps: float
    loop: bool
    priority: int
    interruptible: bool
    next_animation: str | None = None
    scope: str = "pet"
    entrance_direction: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedActionSlot:
    slot: ActionSlot
    action_name: str
    binding: tuple[str, str] | None


def _slot(
    key: str,
    label: str,
    category: str,
    canonical_action: str,
    *,
    binding_event: str | None = None,
    fps: float = 10,
    loop: bool = True,
    priority: int = 40,
    interruptible: bool = True,
    next_animation: str | None = None,
    scope: str = "pet",
    entrance_direction: str | None = None,
) -> ActionSlot:
    return ActionSlot(
        key,
        label,
        category,
        canonical_action,
        binding_event,
        fps,
        loop,
        priority,
        interruptible,
        next_animation,
        scope,
        entrance_direction,
    )


_ACTION_SLOTS = (
    _slot("idle", "默认待机", "基础", "idle", fps=8, priority=10),
    _slot("mouse_hover", "鼠标移入", "鼠标", "hover", binding_event="mouse.enter", priority=30),
    _slot(
        "mouse_click",
        "鼠标点击",
        "鼠标",
        "click",
        binding_event="mouse.click",
        fps=12,
        loop=False,
        priority=50,
        interruptible=False,
        next_animation="context",
    ),
    _slot(
        "mouse_drag",
        "拖动宠物",
        "鼠标",
        "drag",
        binding_event="mouse.drag_start",
        priority=80,
        interruptible=False,
    ),
    _slot(
        "mouse_drop",
        "结束拖动",
        "鼠标",
        "drop",
        binding_event="mouse.drag_end",
        fps=12,
        loop=False,
        priority=70,
        interruptible=False,
        next_animation="context",
    ),
    _slot("move_walk", "跟随移动", "移动", "walk"),
    _slot("move_walk_left", "向左移动", "移动", "walk_left"),
    _slot("move_walk_right", "向右移动", "移动", "walk_right"),
    _slot("move_walk_up", "向上移动", "移动", "walk_up"),
    _slot("move_walk_down", "向下移动", "移动", "walk_down"),
    _slot("move_drag_left", "向左拖动", "移动", "drag_left", priority=80, interruptible=False),
    _slot("move_drag_right", "向右拖动", "移动", "drag_right", priority=80, interruptible=False),
    _slot("move_drag_up", "向上拖动", "移动", "drag_up", priority=80, interruptible=False),
    _slot("move_drag_down", "向下拖动", "移动", "drag_down", priority=80, interruptible=False),
    _slot(
        "agent_working",
        "任务进行中",
        "Codex",
        "working",
        binding_event="agent.working",
        priority=60,
    ),
    _slot(
        "agent_waiting",
        "等待处理",
        "Codex",
        "waiting",
        binding_event="agent.waiting",
        fps=8,
        priority=60,
    ),
    _slot(
        "agent_success",
        "任务完成",
        "Codex",
        "review",
        binding_event="agent.success",
        fps=12,
        loop=False,
        priority=100,
        interruptible=False,
        next_animation="context",
    ),
    _slot(
        "agent_error",
        "执行失败",
        "Codex",
        "error",
        binding_event="agent.error",
        fps=12,
        loop=False,
        priority=100,
        interruptible=False,
        next_animation="context",
    ),
    _slot(
        "system_bored",
        "长时间无输入",
        "系统空闲",
        "bored",
        binding_event="system.bored",
        fps=8,
        priority=20,
    ),
    _slot(
        "system_sleep",
        "无人操作更久",
        "系统空闲",
        "sleep",
        binding_event="system.sleep",
        fps=6,
        priority=20,
    ),
    _slot(
        "system_wake",
        "恢复输入",
        "系统空闲",
        "wake",
        binding_event="system.wake",
        loop=False,
        priority=50,
        next_animation="context",
    ),
    _slot(
        "work_finish_walk",
        "全屏下班提醒 · 走路循环",
        "下班提醒",
        "work_finish_walk",
        fps=12,
        priority=20,
        scope="fullscreen",
        entrance_direction="right",
    ),
    _slot(
        "work_finish_lie_down",
        "全屏下班提醒 · 躺下过渡",
        "下班提醒",
        "work_finish_lie_down",
        fps=12,
        loop=False,
        priority=20,
        scope="fullscreen",
        entrance_direction="none",
    ),
    _slot(
        "work_finish_lie_loop",
        "全屏下班提醒 · 躺下循环",
        "下班提醒",
        "work_finish_lie_loop",
        fps=8,
        priority=20,
        scope="fullscreen",
        entrance_direction="none",
    ),
)

_SLOTS_BY_KEY = {slot.key: slot for slot in _ACTION_SLOTS}
_COMPATIBILITY_TRIGGER_LABELS = {
    "codex_running_left": "旧版 Codex 左向拖动动作",
    "look_directions": "V2 环视方向 000°–337.5°",
}


def action_slots() -> tuple[ActionSlot, ...]:
    return _ACTION_SLOTS


def action_slot(key: str) -> ActionSlot:
    try:
        return _SLOTS_BY_KEY[key]
    except KeyError as error:
        raise ValueError(f"未知 PetNest 动作槽位：{key}") from error


def resolve_slot(package: PetPackage, slot: ActionSlot) -> ResolvedActionSlot:
    bound = package.bindings.get(slot.binding_event) if slot.binding_event is not None else None
    if bound is not None:
        try:
            requested = validate_action_name(bound)
            resolved = FallbackResolver(package.fallbacks).resolve(requested, package.animations)
            bound = validate_action_name(resolved) if resolved != GLOBAL_PLACEHOLDER else None
        except ValueError:
            bound = None
    action_name = validate_action_name(bound or slot.canonical_action)
    binding = (
        (slot.binding_event, action_name)
        if slot.binding_event is not None and bound is None
        else None
    )
    return ResolvedActionSlot(slot, action_name, binding)


def action_trigger_label(package: PetPackage, action_name: str) -> str:
    for slot in _ACTION_SLOTS:
        if resolve_slot(package, slot).action_name == action_name:
            return slot.label
    return _COMPATIBILITY_TRIGGER_LABELS.get(action_name, "未绑定到 PetNest 触发时机")


def validate_action_name(name: str) -> str:
    stem = name.split(".", 1)[0].casefold() if isinstance(name, str) else ""
    if (
        not isinstance(name, str)
        or not _SAFE_ACTION_NAME.fullmatch(name)
        or name in {".", ".."}
        or name != name.rstrip(" .")
        or stem in _WINDOWS_RESERVED_NAMES
        or PureWindowsPath(name).drive
    ):
        raise ValueError(f"动作名称不安全：{name}")
    return name


__all__ = [
    "ActionSlot",
    "ResolvedActionSlot",
    "action_slot",
    "action_slots",
    "action_trigger_label",
    "resolve_slot",
    "validate_action_name",
]
