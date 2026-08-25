"""平台事件能力的最小稳定接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StartupRegistrationResult:
    """修改当前用户登录启动项的结果。"""

    success: bool
    requires_approval: bool = False
    message: str = ""


class PlatformEventAdapter(ABC):
    """隔离系统空闲和开机启动等能力，不向核心状态机泄露平台细节。"""

    @abstractmethod
    def start(self) -> None:
        """启动适配器；不可用时不得使应用退出。"""

    @abstractmethod
    def stop(self) -> None:
        """释放适配器拥有的系统资源。"""

    @abstractmethod
    def get_idle_seconds(self) -> float | None:
        """返回系统空闲秒数；能力缺失时返回 ``None``。"""

    @property
    def startup_supported(self) -> bool:
        """当前运行环境是否可修改登录启动项。"""
        return False

    @abstractmethod
    def register_startup(self, enabled: bool) -> StartupRegistrationResult:
        """请求修改当前用户的登录启动项。"""
