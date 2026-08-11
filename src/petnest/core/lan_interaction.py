"""局域网互动的无状态协议编码、解码与输入校验。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from typing import Any

from petnest.models.lan_interaction import InteractionDraft, InteractionKind

LAN_PROTOCOL_VERSION = 1
LAN_INTERACTION_PORT = 18_487
MAX_PACKET_BYTES = 8 * 1024
MAX_DISPLAY_NAME_LENGTH = 40
MAX_PET_NAME_LENGTH = 40


class LanProtocolError(ValueError):
    """收到的数据不是当前版本可接受的局域网互动消息。"""


@dataclass(frozen=True, slots=True)
class ReceivedInteraction:
    """已经通过校验的远程互动。"""

    sender_device_id: str
    sender_name: str
    draft: InteractionDraft


class LanPacketCodec:
    """集中管理协议字段，避免 UI 或网络层自行拼接不安全 JSON。"""

    capabilities = ("greeting", "heart", "text", "effect")

    @classmethod
    def hello(cls, *, device_id: str, display_name: str, pet_name: str, port: int) -> dict[str, Any]:
        return {
            "version": LAN_PROTOCOL_VERSION,
            "kind": "hello",
            "device_id": _identity(device_id, "设备 ID"),
            "display_name": _bounded_text(display_name, "显示名称", MAX_DISPLAY_NAME_LENGTH),
            "pet_name": _bounded_text(pet_name, "宠物名称", MAX_PET_NAME_LENGTH),
            "port": _port(port),
            "capabilities": list(cls.capabilities),
        }

    @classmethod
    def hello_ack(cls, *, device_id: str, display_name: str, pet_name: str, port: int) -> dict[str, Any]:
        packet = cls.hello(device_id=device_id, display_name=display_name, pet_name=pet_name, port=port)
        packet["kind"] = "hello_ack"
        return packet

    @classmethod
    def interaction(cls, draft: InteractionDraft, sender_id: str, sender_name: str) -> dict[str, Any]:
        packet = draft.to_payload(sender_id=sender_id, sender_name=sender_name)
        return {"version": LAN_PROTOCOL_VERSION, "kind": "interaction", **packet}

    @staticmethod
    def encode(packet: Mapping[str, Any]) -> bytes:
        try:
            data = json.dumps(packet, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise LanProtocolError(f"消息无法编码：{error}") from error
        if len(data) > MAX_PACKET_BYTES:
            raise LanProtocolError("消息超过安全大小限制")
        return data

    @classmethod
    def decode_presence(cls, data: bytes) -> dict[str, Any]:
        raw = cls._decode_envelope(data, expected_kind={"hello", "hello_ack"})
        device_id = _identity(raw.get("device_id"), "设备 ID")
        display_name = _bounded_text(raw.get("display_name"), "显示名称", MAX_DISPLAY_NAME_LENGTH)
        pet_name = _bounded_text(raw.get("pet_name"), "宠物名称", MAX_PET_NAME_LENGTH)
        port = _port(raw.get("port"))
        capabilities = raw.get("capabilities")
        if not isinstance(capabilities, list) or any(item not in LanPacketCodec.capabilities for item in capabilities):
            raise LanProtocolError("设备能力列表无效")
        return {
            "kind": raw["kind"],
            "device_id": device_id,
            "display_name": display_name,
            "pet_name": pet_name,
            "port": port,
            "capabilities": tuple(capabilities),
        }

    @classmethod
    def decode_interaction(cls, data: bytes, *, local_device_id: str) -> ReceivedInteraction:
        raw = cls._decode_envelope(data, expected_kind={"interaction"})
        sender_id = _identity(raw.get("sender_device_id"), "发送方设备 ID")
        if sender_id == local_device_id:
            raise LanProtocolError("忽略本机发出的消息")
        sender_name = _bounded_text(raw.get("sender_name"), "发送方名称", MAX_DISPLAY_NAME_LENGTH)
        target = _identity(raw.get("target_device_id"), "目标设备 ID")
        if target not in {local_device_id, "*"}:
            raise LanProtocolError("目标设备不是本机")
        kind_value = raw.get("type")
        try:
            kind = InteractionKind(kind_value)
        except (TypeError, ValueError) as error:
            raise LanProtocolError("互动类型无效") from error
        try:
            if kind in {InteractionKind.GREETING, InteractionKind.HEART}:
                draft = InteractionDraft.quick(local_device_id, kind)
            elif kind is InteractionKind.TEXT:
                draft = InteractionDraft.text_message(local_device_id, _bounded_text(raw.get("text"), "文字", 120))
            else:
                draft = InteractionDraft.effect(local_device_id, _bounded_text(raw.get("effect_id"), "动效编号", 64))
        except ValueError as error:
            raise LanProtocolError(str(error)) from error
        return ReceivedInteraction(sender_device_id=sender_id, sender_name=sender_name, draft=draft)

    @classmethod
    def _decode_envelope(cls, data: bytes, *, expected_kind: set[str]) -> dict[str, Any]:
        if not isinstance(data, (bytes, bytearray)) or len(data) > MAX_PACKET_BYTES:
            raise LanProtocolError("消息超过安全大小限制")
        try:
            raw = json.loads(bytes(data).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise LanProtocolError(f"JSON 消息无效：{error}") from error
        if not isinstance(raw, dict):
            raise LanProtocolError("JSON 根节点必须是对象")
        if raw.get("version") != LAN_PROTOCOL_VERSION:
            raise LanProtocolError("协议版本不兼容")
        if raw.get("kind") not in expected_kind:
            raise LanProtocolError("消息类型无效")
        return raw


def _identity(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise LanProtocolError(f"{label}无效")
    value = value.strip()
    if not value or len(value) > 64 or any(char in value for char in "\\/\r\n\x00"):
        raise LanProtocolError(f"{label}无效")
    return value


def _bounded_text(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise LanProtocolError(f"{label}无效")
    value = value.strip()
    if not value:
        raise LanProtocolError(f"{label}不能为空")
    if len(value) > maximum:
        raise LanProtocolError(f"{label}不能超过 {maximum} 个字符")
    return value


def _port(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65_535:
        raise LanProtocolError("端口无效")
    return value
