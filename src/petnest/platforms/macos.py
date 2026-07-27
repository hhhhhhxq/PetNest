"""macOS 能力接口的保守实现。"""

from __future__ import annotations

import logging

from .base import PlatformEventAdapter

LOGGER = logging.getLogger(__name__)


class MacOSPlatformAdapter(PlatformEventAdapter):
    """保留 macOS 接口，避免未经验证的系统调用影响桌宠主流程。"""

    def start(self) -> None:
        LOGGER.info("macOS 系统事件适配器已启用基础降级模式")

    def stop(self) -> None:
        """第一阶段未创建后台资源。"""

    def get_idle_seconds(self) -> float | None:
        return None

    def register_startup(self, enabled: bool) -> bool:
        del enabled
        LOGGER.info("macOS 登录启动项尚未在第一阶段实现")
        return False
