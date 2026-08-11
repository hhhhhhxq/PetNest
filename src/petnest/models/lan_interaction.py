"""局域网互动的可验证消息与附近设备显示模型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re


class InteractionKind(StrEnum):
    """一次互动只能选择一种类型。"""

    GREETING = "greeting"
    HEART = "heart"
    TEXT = "text"
    EFFECT = "effect"


@dataclass(frozen=True, slots=True)
class LanPeer:
    """发现到的局域网设备摘要；不携带远程文件或图片。"""

    device_id: str
    display_name: str
    pet_name: str | None = None
    ip_address: str | None = None
    port: int | None = None
    online: bool = True

    @property
    def subtitle(self) -> str:
        details: list[str] = []
        if self.pet_name:
            details.append(f"当前宠物：{self.pet_name}")
        if self.ip_address:
            details.append(self.ip_address)
        return " · ".join(details) or ("在线" if self.online else "离线")


_EFFECT_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_MAX_TEXT_LENGTH = 120


@dataclass(frozen=True, slots=True)
class InteractionDraft:
    """发送前的单一互动草稿，保证不会把三种内容拼成一条消息。"""

    target_device_id: str
    kind: InteractionKind
    text: str | None = None
    effect_id: str | None = None

    def __post_init__(self) -> None:
        target = self.target_device_id.strip()
        if not target:
            raise ValueError("目标设备不能为空")
        object.__setattr__(self, "target_device_id", target)
        if not isinstance(self.kind, InteractionKind):
            try:
                object.__setattr__(self, "kind", InteractionKind(self.kind))
            except ValueError as error:
                raise ValueError("互动类型无效") from error
        if self.kind in {InteractionKind.GREETING, InteractionKind.HEART}:
            if self.text is not None or self.effect_id is not None:
                raise ValueError("快捷互动不能同时携带文字或动效")
            return
        if self.kind is InteractionKind.TEXT:
            if self.effect_id is not None:
                raise ValueError("文字互动不能同时携带动效")
            value = (self.text or "").strip()
            if not value:
                raise ValueError("文字不能为空")
            if len(value) > _MAX_TEXT_LENGTH:
                raise ValueError(f"文字不能超过 {_MAX_TEXT_LENGTH} 个字符")
            object.__setattr__(self, "text", value)
            return
        if self.kind is InteractionKind.EFFECT:
            if self.text is not None:
                raise ValueError("动效互动不能同时携带文字")
            value = (self.effect_id or "").strip()
            if not _EFFECT_ID_RE.fullmatch(value):
                raise ValueError("动效编号只能使用小写字母、数字、下划线和连字符")
            object.__setattr__(self, "effect_id", value)

    @classmethod
    def quick(cls, target_device_id: str, kind: InteractionKind) -> "InteractionDraft":
        if kind not in {InteractionKind.GREETING, InteractionKind.HEART}:
            raise ValueError("快捷互动只能是打招呼或送爱心")
        return cls(target_device_id, kind)

    @classmethod
    def text_message(cls, target_device_id: str, text: str) -> "InteractionDraft":
        return cls(target_device_id, InteractionKind.TEXT, text=text)

    @classmethod
    def effect(cls, target_device_id: str, effect_id: str) -> "InteractionDraft":
        return cls(target_device_id, InteractionKind.EFFECT, effect_id=effect_id)

    def to_payload(self, *, sender_id: str, sender_name: str) -> dict[str, str | int]:
        """转成后续 UDP/TCP 层可以直接编码的最小 JSON 对象。"""
        sender_id = sender_id.strip()
        sender_name = sender_name.strip()
        if not sender_id or not sender_name:
            raise ValueError("发送方身份不能为空")
        payload: dict[str, str | int] = {
            "version": 1,
            "type": self.kind.value,
            "target_device_id": self.target_device_id,
            "sender_device_id": sender_id,
            "sender_name": sender_name,
        }
        if self.text is not None:
            payload["text"] = self.text
        if self.effect_id is not None:
            payload["effect_id"] = self.effect_id
        return payload
