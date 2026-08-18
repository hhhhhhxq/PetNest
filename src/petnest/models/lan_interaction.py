"""局域网互动的可验证消息与附近设备显示模型。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from time import time
import uuid


class InteractionKind(StrEnum):
    """一次互动只能选择一种类型。"""

    GREETING = "greeting"
    HEART = "heart"
    TEXT = "text"
    EFFECT = "effect"


class ChatMessageKind(StrEnum):
    TEXT = "text"
    EMOJI = "emoji"
    IMAGE = "image"


class ChatScope(StrEnum):
    DIRECT = "direct"
    LAN_ROOM = "lan_room"
    ALERT_GROUP = "alert_group"


LAN_ROOM_DEVICE_ID = "*"
ALERT_GROUP_DEVICE_ID = "@lan-alert-group"


MAX_CHAT_TEXT_LENGTH = 2_000
MAX_CHAT_IMAGE_BYTES = 1_500_000


@dataclass(frozen=True, slots=True)
class LanPeer:
    """可互动设备摘要；不携带远程文件或图片。"""

    device_id: str
    display_name: str
    pet_name: str | None = None
    ip_address: str | None = None
    port: int | None = None
    online: bool = True
    transport: str = "lan"
    saved: bool = False
    connection_state: str = "online"
    alert_group_supported: bool = False
    alert_group_joined: bool = False

    @property
    def subtitle(self) -> str:
        details: list[str] = []
        if self.pet_name:
            details.append(f"当前宠物：{self.pet_name}")
        if self.ip_address:
            details.append(self.ip_address)
        elif self.transport == "remote":
            details.append("远程伙伴")
        return " · ".join(details) or ("在线" if self.online else "离线")


@dataclass(frozen=True, slots=True)
class DangerAlert:
    alert_id: str
    sender_device_id: str
    sender_name: str
    target_device_id: str
    created_at: int
    message: str = ""


@dataclass(frozen=True, slots=True)
class DangerAlertAck:
    alert_id: str
    sender_device_id: str
    target_device_id: str


@dataclass(frozen=True, slots=True)
class DangerAlertDeliveryResult:
    alert_id: str
    target_device_ids: tuple[str, ...]
    acknowledged_device_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ChatDraft:
    """A validated direct or current-LAN-room chat payload."""

    target_device_id: str
    kind: ChatMessageKind
    text: str | None = None
    image_data: bytes | None = None
    image_name: str | None = None
    is_group: bool = False
    scope: ChatScope | None = None

    def __post_init__(self) -> None:
        target = str(self.target_device_id).strip()
        if not target or len(target) > 64:
            raise ValueError("聊天目标设备无效")
        if not isinstance(self.is_group, bool):
            raise ValueError("聊天会话类型无效")
        try:
            scope = (
                ChatScope.LAN_ROOM if self.is_group else ChatScope.DIRECT
            ) if self.scope is None else ChatScope(self.scope)
        except (TypeError, ValueError) as error:
            raise ValueError("聊天会话类型无效") from error
        is_group = scope is not ChatScope.DIRECT
        if not is_group and target in {LAN_ROOM_DEVICE_ID, ALERT_GROUP_DEVICE_ID}:
            raise ValueError("群聊目标必须使用群聊消息")
        object.__setattr__(self, "target_device_id", target)
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "is_group", is_group)
        try:
            kind = self.kind if isinstance(self.kind, ChatMessageKind) else ChatMessageKind(self.kind)
        except (TypeError, ValueError) as error:
            raise ValueError("聊天消息类型无效") from error
        object.__setattr__(self, "kind", kind)
        if kind is ChatMessageKind.IMAGE:
            data = self.image_data
            if not isinstance(data, bytes) or not data:
                raise ValueError("图片内容为空")
            if len(data) > MAX_CHAT_IMAGE_BYTES:
                raise ValueError("图片超过 1.5 MB 传输上限")
            name = str(self.image_name or "image.jpg").strip()
            if not name or len(name) > 100 or any(char in name for char in "\\/\r\n\x00"):
                raise ValueError("图片名称无效")
            object.__setattr__(self, "image_name", name)
            object.__setattr__(self, "text", None)
            return
        value = str(self.text or "").strip()
        maximum = 16 if kind is ChatMessageKind.EMOJI else MAX_CHAT_TEXT_LENGTH
        if not value:
            raise ValueError("聊天内容不能为空")
        if len(value) > maximum:
            raise ValueError(f"聊天内容不能超过 {maximum} 个字符")
        object.__setattr__(self, "text", value)
        object.__setattr__(self, "image_data", None)
        object.__setattr__(self, "image_name", None)

    @classmethod
    def text_message(cls, target_device_id: str, text: str) -> "ChatDraft":
        return cls(target_device_id, ChatMessageKind.TEXT, text=text)

    @classmethod
    def emoji(cls, target_device_id: str, emoji: str) -> "ChatDraft":
        return cls(target_device_id, ChatMessageKind.EMOJI, text=emoji)

    @classmethod
    def image(cls, target_device_id: str, data: bytes, name: str) -> "ChatDraft":
        return cls(target_device_id, ChatMessageKind.IMAGE, image_data=data, image_name=name)

    @classmethod
    def group_text_message(cls, text: str) -> "ChatDraft":
        return cls(LAN_ROOM_DEVICE_ID, ChatMessageKind.TEXT, text=text, is_group=True, scope=ChatScope.LAN_ROOM)

    @classmethod
    def group_emoji(cls, emoji: str) -> "ChatDraft":
        return cls(LAN_ROOM_DEVICE_ID, ChatMessageKind.EMOJI, text=emoji, is_group=True, scope=ChatScope.LAN_ROOM)

    @classmethod
    def group_image(cls, data: bytes, name: str) -> "ChatDraft":
        return cls(
            LAN_ROOM_DEVICE_ID,
            ChatMessageKind.IMAGE,
            image_data=data,
            image_name=name,
            is_group=True,
            scope=ChatScope.LAN_ROOM,
        )

    @classmethod
    def alert_group_text_message(cls, text: str) -> "ChatDraft":
        return cls(
            ALERT_GROUP_DEVICE_ID,
            ChatMessageKind.TEXT,
            text=text,
            is_group=True,
            scope=ChatScope.ALERT_GROUP,
        )

    @classmethod
    def alert_group_emoji(cls, emoji: str) -> "ChatDraft":
        return cls(
            ALERT_GROUP_DEVICE_ID,
            ChatMessageKind.EMOJI,
            text=emoji,
            is_group=True,
            scope=ChatScope.ALERT_GROUP,
        )

    @classmethod
    def alert_group_image(cls, data: bytes, name: str) -> "ChatDraft":
        return cls(
            ALERT_GROUP_DEVICE_ID,
            ChatMessageKind.IMAGE,
            image_data=data,
            image_name=name,
            is_group=True,
            scope=ChatScope.ALERT_GROUP,
        )

    def to_message(self, *, sender_device_id: str, sender_name: str) -> "LanChatMessage":
        return LanChatMessage(
            message_id=uuid.uuid4().hex,
            sender_device_id=str(sender_device_id).strip(),
            sender_name=str(sender_name).strip(),
            target_device_id=self.target_device_id,
            kind=self.kind,
            created_at=int(time()),
            text=self.text,
            image_data=self.image_data,
            image_name=self.image_name,
            is_group=self.is_group,
            scope=self.scope,
        )


@dataclass(frozen=True, slots=True)
class LanChatMessage:
    message_id: str
    sender_device_id: str
    sender_name: str
    target_device_id: str
    kind: ChatMessageKind
    created_at: int
    text: str | None = None
    image_data: bytes | None = None
    image_name: str | None = None
    is_group: bool = False
    scope: ChatScope | None = None

    def __post_init__(self) -> None:
        try:
            scope = (
                ChatScope.LAN_ROOM if self.is_group else ChatScope.DIRECT
            ) if self.scope is None else ChatScope(self.scope)
        except (TypeError, ValueError) as error:
            raise ValueError("聊天会话类型无效") from error
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "is_group", scope is not ChatScope.DIRECT)

    def peer_device_id(self, local_device_id: str) -> str:
        if self.scope is ChatScope.LAN_ROOM:
            return LAN_ROOM_DEVICE_ID
        if self.scope is ChatScope.ALERT_GROUP:
            return ALERT_GROUP_DEVICE_ID
        return self.target_device_id if self.sender_device_id == local_device_id else self.sender_device_id


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
