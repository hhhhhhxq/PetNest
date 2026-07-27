"""只包含非敏感用户偏好的设置模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class AnimationOverride:
    """用户针对一个动作的本地播放覆盖，不修改宠物资源包。"""

    speed_multiplier: float = 1.0
    frame_durations_ms: tuple[int, ...] | None = None


@dataclass(frozen=True, slots=True)
class Settings:
    """可 JSON 序列化的用户设置，字段为第一阶段所需最小集合。"""

    SCHEMA_VERSION = 3

    schema_version: int = SCHEMA_VERSION
    current_pet_id: str | None = None
    window_x: int | None = None
    window_y: int | None = None
    screen_id: str | None = None
    scale: float = 1.0
    always_on_top: bool = True
    animation_paused: bool = False
    mouse_interaction_enabled: bool = True
    external_event_server_enabled: bool = False
    external_event_port: int = 18486
    system_idle_enabled: bool = False
    system_idle_seconds: int = 300
    run_at_startup: bool = False
    animation_overrides: dict[str, dict[str, AnimationOverride]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """返回适合 JSON 写入的纯数据。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Settings":
        """忽略未知键，避免未来版本设置使旧版本崩溃。"""
        fields = cls.__dataclass_fields__
        values = {name: raw[name] for name in fields if name in raw}
        if "animation_overrides" in values:
            values["animation_overrides"] = _animation_overrides(values["animation_overrides"])
        return cls(**values)


def _animation_overrides(value: object) -> dict[str, dict[str, AnimationOverride]]:
    """宽容读取设置文件中每宠物、每动作的本地播放覆盖。"""
    if not isinstance(value, dict):
        return {}
    overrides: dict[str, dict[str, AnimationOverride]] = {}
    for pet_id, actions in value.items():
        if not isinstance(pet_id, str) or not isinstance(actions, dict):
            continue
        action_overrides: dict[str, AnimationOverride] = {}
        for action, raw_override in actions.items():
            if not isinstance(action, str) or not isinstance(raw_override, dict):
                continue
            speed = raw_override.get("speed_multiplier", 1.0)
            durations = raw_override.get("frame_durations_ms")
            if isinstance(speed, bool) or not isinstance(speed, (int, float)) or speed <= 0:
                continue
            if durations is not None:
                if not isinstance(durations, list) or any(
                    isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in durations
                ):
                    continue
                parsed_durations: tuple[int, ...] | None = tuple(durations)
            else:
                parsed_durations = None
            action_overrides[action] = AnimationOverride(float(speed), parsed_durations)
        if action_overrides:
            overrides[pet_id] = action_overrides
    return overrides
