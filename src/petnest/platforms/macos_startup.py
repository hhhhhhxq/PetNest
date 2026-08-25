"""macOS 13+ 主应用登录项封装。"""

from __future__ import annotations

import logging
import platform
import sys
from collections.abc import Callable
from typing import Protocol

from .base import StartupRegistrationResult

LOGGER = logging.getLogger(__name__)


class LoginItemService(Protocol):
    def status(self) -> str: ...

    def register(self) -> None: ...

    def unregister(self) -> None: ...


def _macos_version() -> tuple[int, int]:
    version = platform.mac_ver()[0]
    try:
        major, minor, *_ = (int(part) for part in version.split("."))
    except (TypeError, ValueError):
        return (0, 0)
    return (major, minor)


def _error_message(error: object | None) -> str:
    if error is None:
        return "Service Management 未返回详细错误"
    description = getattr(error, "localizedDescription", None)
    if callable(description):
        return str(description())
    return str(error)


def _check_service_result(result: object, action: str) -> None:
    if isinstance(result, tuple):
        success = bool(result[0])
        error = result[1] if len(result) > 1 else None
    else:
        success = bool(result)
        error = None
    if not success:
        raise RuntimeError(f"{action}失败：{_error_message(error)}")


class _PyObjCLoginItemService:
    def __init__(self) -> None:
        from ServiceManagement import (  # type: ignore[import-not-found]
            SMAppService,
            SMAppServiceStatusEnabled,
            SMAppServiceStatusNotFound,
            SMAppServiceStatusNotRegistered,
            SMAppServiceStatusRequiresApproval,
        )

        self._service = SMAppService.mainAppService()
        self._statuses = {
            SMAppServiceStatusNotRegistered: "not_registered",
            SMAppServiceStatusEnabled: "enabled",
            SMAppServiceStatusRequiresApproval: "requires_approval",
            SMAppServiceStatusNotFound: "not_found",
        }

    def status(self) -> str:
        return self._statuses.get(self._service.status(), "unknown")

    def register(self) -> None:
        _check_service_result(self._service.registerAndReturnError_(None), "登记自动启动")

    def unregister(self) -> None:
        _check_service_result(self._service.unregisterAndReturnError_(None), "取消自动启动")


class MacOSLoginItem:
    """通过 ``SMAppService.mainAppService`` 管理已打包主应用。"""

    def __init__(
        self,
        *,
        frozen: bool | None = None,
        macos_version: tuple[int, int] | None = None,
        service_loader: Callable[[], LoginItemService] | None = None,
    ) -> None:
        self.frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
        self.macos_version = _macos_version() if macos_version is None else macos_version
        self._service_loader = service_loader or _PyObjCLoginItemService
        self._service: LoginItemService | None = None
        self._service_loaded = False
        self._load_error = ""

    @property
    def supported(self) -> bool:
        if not self.frozen or self.macos_version < (13, 0):
            return False
        return self._load_service() is not None

    def configure(self, enabled: bool) -> StartupRegistrationResult:
        if not self.supported:
            message = self._load_error or "仅 macOS 13 及更高版本的已打包应用支持自动启动"
            return StartupRegistrationResult(False, message=message)
        service = self._service
        assert service is not None
        try:
            status = service.status()
            if enabled:
                if status == "enabled":
                    return StartupRegistrationResult(True)
                if status != "requires_approval":
                    service.register()
                status = service.status()
                if status == "requires_approval":
                    return StartupRegistrationResult(True, requires_approval=True)
                if status == "enabled":
                    return StartupRegistrationResult(True)
                return StartupRegistrationResult(False, message=f"登记后状态异常：{status}")

            if status in {"not_registered", "not_found"}:
                return StartupRegistrationResult(True)
            service.unregister()
            return StartupRegistrationResult(True)
        except Exception as error:  # PyObjC 可能抛出 Objective-C 异常类型
            LOGGER.warning("无法修改 macOS 自动启动项", exc_info=True)
            return StartupRegistrationResult(False, message=str(error))

    def _load_service(self) -> LoginItemService | None:
        if self._service_loaded:
            return self._service
        self._service_loaded = True
        try:
            self._service = self._service_loader()
        except Exception as error:  # PyObjC 桥接不完整时也只禁用该能力
            self._load_error = str(error)
            LOGGER.info("macOS Service Management 不可用：%s", error)
        return self._service


__all__ = ["MacOSLoginItem"]
