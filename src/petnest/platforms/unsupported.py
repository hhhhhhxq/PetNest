"""未知平台的显式安全降级实现。"""

from __future__ import annotations

import logging

from .base import PlatformEventAdapter, StartupRegistrationResult

LOGGER = logging.getLogger(__name__)


class UnsupportedPlatformAdapter(PlatformEventAdapter):
    """不伪造系统事件，只在首次使用时记录一次能力缺失。"""

    def __init__(self, platform_name: str) -> None:
        self.platform_name = platform_name
        self._warned = False

    def start(self) -> None:
        self._warn_once()

    def stop(self) -> None:
        """无资源需要释放。"""

    def get_idle_seconds(self) -> float | None:
        self._warn_once()
        return None

    def register_startup(self, enabled: bool) -> StartupRegistrationResult:
        del enabled
        self._warn_once()
        return StartupRegistrationResult(False, message=f"平台 {self.platform_name} 不支持自动启动")

    def _warn_once(self) -> None:
        if not self._warned:
            self._warned = True
            LOGGER.warning("平台 %s 暂不支持系统空闲检测或开机启动", self.platform_name)
