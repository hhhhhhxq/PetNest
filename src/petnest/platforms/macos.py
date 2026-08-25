"""macOS 能力接口的保守实现。"""

from __future__ import annotations

import logging

from .base import PlatformEventAdapter, StartupRegistrationResult
from .macos_startup import MacOSLoginItem

LOGGER = logging.getLogger(__name__)


class MacOSPlatformAdapter(PlatformEventAdapter):
    """macOS 基础降级能力和 Service Management 登录项。"""

    def __init__(self, *, login_item: MacOSLoginItem | None = None) -> None:
        self._login_item = login_item or MacOSLoginItem()

    def start(self) -> None:
        LOGGER.info("macOS 系统事件适配器已启用基础降级模式")

    def stop(self) -> None:
        """第一阶段未创建后台资源。"""

    def get_idle_seconds(self) -> float | None:
        return None

    @property
    def startup_supported(self) -> bool:
        return self._login_item.supported

    def register_startup(self, enabled: bool) -> StartupRegistrationResult:
        return self._login_item.configure(enabled)
