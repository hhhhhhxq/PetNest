"""本机互动显示名称的稳定回退规则。"""

from __future__ import annotations

from petnest.models.settings import Settings


def display_name_for(settings: Settings) -> str:
    """优先使用用户昵称，否则显示可读的短设备码。"""
    nickname = settings.nickname.strip()
    if nickname:
        return nickname
    device_id = "".join(char for char in settings.device_id.upper() if char.isalnum())
    return f"用户-{device_id[-4:] if device_id else '本机'}"


def initials_for(label: str) -> str:
    """为中英文名称生成适合小圆头像的 1～2 个字符。"""
    value = label.strip()
    if not value:
        return "·"
    compact = "".join(value.split())
    return compact[:2] if any("\u4e00" <= char <= "\u9fff" for char in compact) else compact[:1].upper()
