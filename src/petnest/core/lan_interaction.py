"""局域网互动的无状态协议编码、解码与输入校验。"""

from __future__ import annotations

from collections.abc import Mapping
import base64
import binascii
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import re
from typing import Any

from petnest.core.codex_usage import CodexDeviceUsageSnapshot, CodexModelUsage
from petnest.core.lan_chat import LanChatImageError, validate_chat_image_data
from petnest.models.lan_interaction import (
    ChatDraft,
    ChatMessageKind,
    InteractionDraft,
    InteractionKind,
    LanChatMessage,
    MAX_CHAT_IMAGE_BYTES,
)

LAN_PROTOCOL_VERSION = 1
LAN_INTERACTION_PORT = 18_487
MAX_PACKET_BYTES = 8 * 1024
MAX_CHAT_PACKET_BYTES = 2_100_000
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


@dataclass(frozen=True, slots=True)
class ReceivedCodexUsageSync:
    """A validated direct-device Codex usage contribution."""

    kind: str
    request_id: str
    target_device_id: str
    snapshot: CodexDeviceUsageSnapshot


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

    @classmethod
    def codex_usage_sync(
        cls,
        *,
        kind: str,
        request_id: str,
        target_device_id: str,
        snapshot: CodexDeviceUsageSnapshot,
    ) -> dict[str, Any]:
        if kind not in {"codex_usage_sync_request", "codex_usage_sync_response"}:
            raise LanProtocolError("Codex 用量同步类型无效")
        if not _valid_account_key(snapshot.account_key):
            raise LanProtocolError("Codex 账号标识无效")
        try:
            updated = datetime.fromisoformat(snapshot.updated_at)
        except (TypeError, ValueError) as error:
            raise LanProtocolError("Codex 用量更新时间无效") from error
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        duration = snapshot.window_duration_minutes
        if duration is not None and (not isinstance(duration, int) or not 0 < duration <= 525_600):
            raise LanProtocolError("Codex 额度窗口无效")
        usage = {
            "input_tokens": _sync_counter(snapshot.input_tokens),
            "cached_input_tokens": _sync_counter(snapshot.cached_input_tokens),
            "cache_write_input_tokens": _sync_counter(snapshot.cache_write_input_tokens),
            "output_tokens": _sync_counter(snapshot.output_tokens),
            "reasoning_output_tokens": _sync_counter(snapshot.reasoning_output_tokens),
            "total_tokens": _sync_counter(snapshot.total_tokens),
            "requests": _sync_counter(snapshot.requests),
            "fast_uses": _sync_counter(snapshot.fast_uses),
            "standard_uses": _sync_counter(snapshot.standard_uses),
            "files_scanned": _sync_counter(snapshot.files_scanned),
            "files_skipped": _sync_counter(snapshot.files_skipped),
            "scan_status": _sync_scan_status(snapshot.scan_status),
            "models": [
                {
                    "model": _bounded_text(item.model, "Codex 模型名称", 80),
                    "uses": _sync_counter(item.uses),
                    "total_tokens": _sync_counter(item.total_tokens),
                }
                for item in snapshot.model_usage[:20]
            ],
        }
        return {
            "version": LAN_PROTOCOL_VERSION,
            "kind": kind,
            "request_id": _identity(request_id, "同步请求 ID"),
            "target_device_id": _identity(target_device_id, "目标设备 ID"),
            "sender_device_id": _identity(snapshot.device_id, "发送方设备 ID"),
            "sender_name": _bounded_text(snapshot.device_label, "发送方名称", MAX_DISPLAY_NAME_LENGTH),
            "account_key": snapshot.account_key,
            "account_label": _optional_bounded_text(snapshot.account_label, 100),
            "plan_type": _optional_bounded_text(snapshot.plan_type, 40),
            "account_used_percent": _sync_percent(snapshot.account_used_percent),
            "window_resets_at": _sync_epoch(snapshot.window_resets_at),
            "window_duration_minutes": duration,
            "updated_at": _sync_epoch(int(updated.timestamp())),
            "usage": usage,
        }

    @classmethod
    def chat_message(cls, message: LanChatMessage) -> dict[str, Any]:
        sender_id = _identity(message.sender_device_id, "发送方设备 ID")
        target = _identity(message.target_device_id, "目标设备 ID")
        sender_name = _bounded_text(message.sender_name, "发送方名称", MAX_DISPLAY_NAME_LENGTH)
        draft = ChatDraft(
            target_device_id=target,
            kind=message.kind,
            text=message.text,
            image_data=message.image_data,
            image_name=message.image_name,
            is_group=message.is_group,
        )
        packet: dict[str, Any] = {
            "version": LAN_PROTOCOL_VERSION,
            "kind": "chat",
            "message_id": _identity(message.message_id, "聊天消息 ID"),
            "sender_device_id": sender_id,
            "sender_name": sender_name,
            "target_device_id": target,
            "type": draft.kind.value,
            "scope": "group" if draft.is_group else "direct",
            "created_at": _sync_epoch(message.created_at),
        }
        if draft.kind is ChatMessageKind.IMAGE:
            packet["image_name"] = draft.image_name
            packet["image_data"] = base64.b64encode(draft.image_data or b"").decode("ascii")
        else:
            packet["text"] = draft.text
        return packet

    @classmethod
    def encode_chat_frame(cls, message: LanChatMessage) -> bytes:
        packet = cls.chat_message(message)
        try:
            payload = json.dumps(packet, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as error:
            raise LanProtocolError(f"聊天消息无法编码：{error}") from error
        if len(payload) > MAX_CHAT_PACKET_BYTES:
            raise LanProtocolError("聊天消息超过安全大小限制")
        return len(payload).to_bytes(4, "big") + payload

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
    def decode_codex_usage_sync(
        cls,
        data: bytes,
        *,
        local_device_id: str,
    ) -> ReceivedCodexUsageSync:
        raw = cls._decode_envelope(
            data,
            expected_kind={"codex_usage_sync_request", "codex_usage_sync_response"},
        )
        sender_id = _identity(raw.get("sender_device_id"), "发送方设备 ID")
        if sender_id == local_device_id:
            raise LanProtocolError("忽略本机发出的用量同步")
        target = _identity(raw.get("target_device_id"), "目标设备 ID")
        if target != local_device_id:
            raise LanProtocolError("用量同步的目标设备不是本机")
        request_id = _identity(raw.get("request_id"), "同步请求 ID")
        account_key = raw.get("account_key")
        if not _valid_account_key(account_key):
            raise LanProtocolError("Codex 账号标识无效")
        sender_name = _bounded_text(raw.get("sender_name"), "发送方名称", MAX_DISPLAY_NAME_LENGTH)
        reset_at = _sync_epoch(raw.get("window_resets_at"))
        updated_at = _sync_epoch(raw.get("updated_at"))
        duration = raw.get("window_duration_minutes")
        if duration is not None and (
            isinstance(duration, bool)
            or not isinstance(duration, int)
            or not 0 < duration <= 525_600
        ):
            raise LanProtocolError("Codex 额度窗口无效")
        usage = raw.get("usage")
        if not isinstance(usage, dict):
            raise LanProtocolError("Codex Token 用量无效")
        snapshot = CodexDeviceUsageSnapshot(
            account_key=account_key,
            device_id=sender_id,
            device_label=sender_name,
            window_resets_at=reset_at,
            window_duration_minutes=duration,
            updated_at=datetime.fromtimestamp(updated_at, UTC).isoformat(),
            input_tokens=_sync_counter(usage.get("input_tokens")),
            cached_input_tokens=_sync_counter(usage.get("cached_input_tokens")),
            cache_write_input_tokens=_sync_counter(usage.get("cache_write_input_tokens")),
            output_tokens=_sync_counter(usage.get("output_tokens")),
            reasoning_output_tokens=_sync_counter(usage.get("reasoning_output_tokens")),
            total_tokens=_sync_counter(usage.get("total_tokens")),
            requests=_sync_counter(usage.get("requests")),
            model_usage=_sync_model_usage(usage.get("models")),
            account_label=_optional_bounded_text(raw.get("account_label"), 100),
            plan_type=_optional_bounded_text(raw.get("plan_type"), 40),
            account_used_percent=_sync_percent(raw.get("account_used_percent")),
            fast_uses=_sync_counter(usage.get("fast_uses", 0)),
            standard_uses=_sync_counter(usage.get("standard_uses", 0)),
            files_scanned=_sync_counter(usage.get("files_scanned", 0)),
            files_skipped=_sync_counter(usage.get("files_skipped", 0)),
            scan_status=_sync_scan_status(usage.get("scan_status")),
        )
        return ReceivedCodexUsageSync(
            kind=str(raw["kind"]),
            request_id=request_id,
            target_device_id=target,
            snapshot=snapshot,
        )

    @classmethod
    def decode_chat_message(cls, data: bytes, *, local_device_id: str) -> LanChatMessage:
        raw = cls._decode_envelope(
            data,
            expected_kind={"chat"},
            maximum=MAX_CHAT_PACKET_BYTES,
        )
        sender_id = _identity(raw.get("sender_device_id"), "发送方设备 ID")
        if sender_id == local_device_id:
            raise LanProtocolError("忽略本机发出的聊天消息")
        target = _identity(raw.get("target_device_id"), "目标设备 ID")
        if target != local_device_id:
            raise LanProtocolError("聊天消息的目标设备不是本机")
        sender_name = _bounded_text(raw.get("sender_name"), "发送方名称", MAX_DISPLAY_NAME_LENGTH)
        message_id = _identity(raw.get("message_id"), "聊天消息 ID")
        created_at = _sync_epoch(raw.get("created_at"))
        try:
            kind = ChatMessageKind(raw.get("type"))
        except (TypeError, ValueError) as error:
            raise LanProtocolError("聊天消息类型无效") from error
        scope = raw.get("scope", "direct")
        if scope not in {"direct", "group"}:
            raise LanProtocolError("聊天会话类型无效")
        is_group = scope == "group"
        if kind is ChatMessageKind.IMAGE:
            encoded = raw.get("image_data")
            if not isinstance(encoded, str) or len(encoded) > 2_000_000:
                raise LanProtocolError("聊天图片数据无效")
            try:
                image_data = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as error:
                raise LanProtocolError("聊天图片编码无效") from error
            if not image_data or len(image_data) > MAX_CHAT_IMAGE_BYTES:
                raise LanProtocolError("聊天图片超过大小限制")
            try:
                validate_chat_image_data(image_data)
            except LanChatImageError as error:
                raise LanProtocolError(str(error)) from error
            draft = ChatDraft(
                target,
                kind,
                image_data=image_data,
                image_name=str(raw.get("image_name") or ""),
                is_group=is_group,
            )
        elif kind is ChatMessageKind.EMOJI:
            draft = ChatDraft(target, kind, text=str(raw.get("text") or ""), is_group=is_group)
        else:
            draft = ChatDraft(target, kind, text=str(raw.get("text") or ""), is_group=is_group)
        return LanChatMessage(
            message_id=message_id,
            sender_device_id=sender_id,
            sender_name=sender_name,
            target_device_id=target,
            kind=kind,
            created_at=created_at,
            text=draft.text,
            image_data=draft.image_data,
            image_name=draft.image_name,
            is_group=draft.is_group,
        )

    @classmethod
    def _decode_envelope(
        cls,
        data: bytes,
        *,
        expected_kind: set[str],
        maximum: int = MAX_PACKET_BYTES,
    ) -> dict[str, Any]:
        if not isinstance(data, (bytes, bytearray)) or len(data) > maximum:
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


def _optional_bounded_text(value: object, maximum: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise LanProtocolError("可选文字无效")
    value = value.strip()
    if len(value) > maximum or any(char in value for char in "\r\n\x00"):
        raise LanProtocolError("可选文字无效")
    return value


def _port(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65_535:
        raise LanProtocolError("端口无效")
    return value


def _valid_account_key(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{24}", value) is not None


def _sync_epoch(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1_500_000_000 <= value <= 4_102_444_800:
        raise LanProtocolError("Codex 用量时间无效")
    return value


def _sync_counter(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10**18:
        raise LanProtocolError("Codex Token 计数无效")
    return value


def _sync_percent(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
        raise LanProtocolError("Codex 额度百分比无效")
    return float(value)


def _sync_scan_status(value: object) -> str:
    normalized = str(value or "unknown")
    if normalized not in {
        "unknown",
        "matched",
        "no_matching_events",
        "unreadable_files",
        "no_session_files",
    }:
        raise LanProtocolError("Codex 日志扫描状态无效")
    return normalized


def _sync_model_usage(value: object) -> tuple[CodexModelUsage, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > 20:
        raise LanProtocolError("Codex 模型用量无效")
    models: list[CodexModelUsage] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            raise LanProtocolError("Codex 模型用量无效")
        model = _bounded_text(raw.get("model"), "Codex 模型名称", 80)
        if model in seen:
            raise LanProtocolError("Codex 模型用量重复")
        seen.add(model)
        models.append(
            CodexModelUsage(
                model=model,
                uses=_sync_counter(raw.get("uses")),
                total_tokens=_sync_counter(raw.get("total_tokens")),
            )
        )
    models.sort(key=lambda item: (-item.uses, -item.total_tokens, item.model.casefold()))
    return tuple(models)
