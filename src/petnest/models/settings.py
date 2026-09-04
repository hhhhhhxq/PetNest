"""只包含非敏感用户偏好的设置模型。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import time
from typing import Any


def _default_daily_work_end_times() -> dict[str, str | None]:
    return {
        "0": "18:00",
        "1": "18:00",
        "2": "18:00",
        "3": "18:00",
        "4": "18:00",
        "5": None,
        "6": None,
    }


@dataclass(frozen=True, slots=True)
class AnimationOverride:
    """用户针对一个动作的本地播放覆盖，不修改宠物资源包。"""

    speed_multiplier: float = 1.0
    frame_durations_ms: tuple[int, ...] | None = None
    mode: str = "total"


@dataclass(frozen=True, slots=True)
class Settings:
    """可 JSON 序列化的用户设置，字段为第一阶段所需最小集合。"""

    SCHEMA_VERSION = 29
    CURSOR_SCALE_OPTIONS = (80, 100, 125, 150)
    WORK_SCHEDULE_MODES = ("fixed", "elastic")

    schema_version: int = SCHEMA_VERSION
    current_pet_id: str | None = None
    window_x: int | None = None
    window_y: int | None = None
    screen_id: str | None = None
    scale: float = 1.0
    always_on_top: bool = True
    quick_notebook_enabled: bool = False
    animation_paused: bool = False
    mouse_interaction_enabled: bool = True
    keyboard_working_enabled: bool = False
    external_event_server_enabled: bool = False
    external_event_port: int = 18486
    lan_interaction_enabled: bool = True
    lan_group_chat_notifications_enabled: bool = True
    lan_alert_group_joined: bool = False
    lan_firewall_dismissed_public_networks: tuple[str, ...] = ()
    codex_usage_unlocked: bool = False
    codex_link_enabled: bool = True
    codex_link_show_attention_bubbles: bool = True
    codex_link_show_review_bubbles: bool = True
    codex_link_log_fallback_enabled: bool = True
    codex_home_override: str | None = None
    remote_interaction_enabled: bool = True
    system_idle_enabled: bool = True
    system_idle_seconds: int = 300
    system_bored_seconds: int = 20
    system_sleep_seconds: int = 35
    run_at_startup: bool = False
    pets_root: str | None = None
    nickname: str = ""
    device_id: str = ""
    work_countdown_enabled: bool = True
    work_start_time: str = "09:00"
    work_end_time: str = "18:00"
    daily_work_end_times: dict[str, str | None] = field(
        default_factory=_default_daily_work_end_times
    )
    countdown_gap: int = 0
    countdown_width: int = 132
    countdown_height: int = 37
    countdown_theme: str = "cream"
    mouse_follow_enabled: bool = False
    mouse_follow_scale: float = 0.45
    cursor_style_enabled: bool = False
    cursor_style_id: str | None = None
    cursor_restore_pending: bool = False
    cursor_scale: int = 100
    work_schedule_mode: str = "fixed"
    clock_in_start_time: str = "09:30"
    clock_in_end_time: str = "10:00"
    work_duration_minutes: int = 540
    clock_in_date: str | None = None
    clock_in_time: str | None = None
    work_finish_state: dict[str, str | None] | None = None
    animation_overrides: dict[str, dict[str, AnimationOverride]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """返回适合 JSON 写入的纯数据，不再持久化已废弃的本地动画覆盖。"""
        values = asdict(self)
        values.pop("animation_overrides", None)
        return values

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Settings":
        """忽略未知键，避免未来版本设置使旧版本崩溃。"""
        fields = cls.__dataclass_fields__
        values = {name: raw[name] for name in fields if name in raw}
        values["daily_work_end_times"] = _daily_work_end_times(values.get("daily_work_end_times"))
        values["cursor_scale"] = _cursor_scale(values.get("cursor_scale", 100))
        values["work_schedule_mode"] = _work_schedule_mode(values.get("work_schedule_mode", "fixed"))
        values["work_duration_minutes"] = _work_duration_minutes(values.get("work_duration_minutes", 540))
        for name in ("clock_in_start_time", "clock_in_end_time"):
            if not isinstance(values.get(name), str) or not values[name]:
                values[name] = "09:30" if name == "clock_in_start_time" else "10:00"
        for name in ("clock_in_date", "clock_in_time"):
            if values.get(name) is not None and not isinstance(values[name], str):
                values[name] = None
        values["work_finish_state"] = _work_finish_state(values.get("work_finish_state"))
        values["lan_firewall_dismissed_public_networks"] = _string_history(
            values.get("lan_firewall_dismissed_public_networks")
        )
        for name, default in (
            ("quick_notebook_enabled", False),
            ("keyboard_working_enabled", False),
            ("codex_link_enabled", True),
            ("codex_link_show_attention_bubbles", True),
            ("codex_link_show_review_bubbles", True),
            ("codex_link_log_fallback_enabled", True),
        ):
            if not isinstance(values.get(name, default), bool):
                values[name] = default
        codex_home_override = values.get("codex_home_override")
        if not isinstance(codex_home_override, str) or not codex_home_override.strip():
            values["codex_home_override"] = None
        if "animation_overrides" in values:
            values["animation_overrides"] = _animation_overrides(values["animation_overrides"])
        return cls(**values)


def _string_history(value: object, *, limit: int = 20) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    unique: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            continue
        normalized = item.strip()
        if normalized in unique:
            unique.remove(normalized)
        unique.append(normalized)
    return tuple(unique[-limit:])


def _cursor_scale(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value not in Settings.CURSOR_SCALE_OPTIONS:
        return 100
    return value


def _work_schedule_mode(value: object) -> str:
    if value not in Settings.WORK_SCHEDULE_MODES:
        return "fixed"
    return str(value)


def _work_duration_minutes(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 24 * 60:
        return 540
    return value


def _daily_work_end_times(value: object) -> dict[str, str | None]:
    """宽容读取每周下班时间，避免损坏配置拖垮倒计时页面。"""
    defaults = _default_daily_work_end_times()
    if not isinstance(value, dict):
        return defaults
    normalized: dict[str, str | None] = {}
    for day in range(7):
        key = str(day)
        raw_time = value.get(key, defaults[key])
        if raw_time is None:
            normalized[key] = None
            continue
        if not isinstance(raw_time, str):
            normalized[key] = defaults[key]
            continue
        try:
            parsed = time.fromisoformat(raw_time)
        except ValueError:
            normalized[key] = defaults[key]
        else:
            normalized[key] = f"{parsed.hour:02d}:{parsed.minute:02d}"
    return normalized


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
            mode = raw_override.get("mode")
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
            if mode is None:
                mode = "per_frame" if parsed_durations is not None else "total"
            if mode not in {"total", "per_frame"}:
                continue
            action_overrides[action] = AnimationOverride(float(speed), parsed_durations, str(mode))
        if action_overrides:
            overrides[pet_id] = action_overrides
    return overrides


def _work_finish_state(value: object) -> dict[str, str | None] | None:
    """只保留状态模块认识的字符串字段，损坏值不会拖垮全部设置。"""
    if not isinstance(value, dict):
        return None
    required_keys = (
        "work_date",
        "end_at",
        "status",
        "prompt_kind",
        "prompt_started_at",
        "next_prompt_at",
    )
    if any(
        key not in value or value[key] is not None and not isinstance(value[key], str)
        for key in required_keys
    ):
        return None
    prompt_timing = value.get("prompt_timing")
    if prompt_timing is not None and not isinstance(prompt_timing, str):
        return None
    normalized = {key: value[key] for key in required_keys}
    if "prompt_timing" in value:
        normalized["prompt_timing"] = prompt_timing
    return normalized
