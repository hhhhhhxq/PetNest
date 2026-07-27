"""平台事件能力的最小稳定接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod


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

    @abstractmethod
    def register_startup(self, enabled: bool) -> bool:
        """请求修改开机启动；成功时返回 ``True``。"""
