"""只包含非敏感用户偏好的设置模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Settings:
    """可 JSON 序列化的用户设置，字段为第一阶段所需最小集合。"""

    SCHEMA_VERSION = 2

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

    def to_dict(self) -> dict[str, Any]:
        """返回适合 JSON 写入的纯数据。"""
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Settings":
        """忽略未知键，避免未来版本设置使旧版本崩溃。"""
        fields = cls.__dataclass_fields__
        values = {name: raw[name] for name in fields if name in raw}
        return cls(**values)
