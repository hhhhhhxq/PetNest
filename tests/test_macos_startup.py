from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from petnest.platforms.base import StartupRegistrationResult
from petnest.platforms.macos_startup import MacOSLoginItem, _PyObjCLoginItemService


class _Service:
    def __init__(self, status: str = "not_registered", *, next_status: str = "enabled") -> None:
        self.current_status = status
        self.next_status = next_status
        self.registered = 0
        self.unregistered = 0

    def status(self) -> str:
        return self.current_status

    def register(self) -> None:
        self.registered += 1
        self.current_status = self.next_status

    def unregister(self) -> None:
        self.unregistered += 1
        self.current_status = "not_registered"


def test_macos_login_item_registers_the_main_app() -> None:
    service = _Service()
    item = MacOSLoginItem(frozen=True, macos_version=(15, 0), service_loader=lambda: service)

    assert item.supported is True
    assert item.configure(True) == StartupRegistrationResult(True)
    assert service.registered == 1


def test_macos_login_item_surfaces_required_approval() -> None:
    service = _Service(next_status="requires_approval")
    item = MacOSLoginItem(frozen=True, macos_version=(15, 0), service_loader=lambda: service)

    assert item.configure(True) == StartupRegistrationResult(True, requires_approval=True)


def test_macos_login_item_does_not_register_twice() -> None:
    service = _Service(status="enabled")
    item = MacOSLoginItem(frozen=True, macos_version=(15, 0), service_loader=lambda: service)

    assert item.configure(True).success is True
    assert service.registered == 0


def test_macos_login_item_unregisters_and_is_idempotent() -> None:
    enabled_service = _Service(status="enabled")
    enabled = MacOSLoginItem(
        frozen=True,
        macos_version=(15, 0),
        service_loader=lambda: enabled_service,
    )
    disabled_service = _Service()
    disabled = MacOSLoginItem(
        frozen=True,
        macos_version=(15, 0),
        service_loader=lambda: disabled_service,
    )

    assert enabled.configure(False).success is True
    assert enabled_service.unregistered == 1
    assert disabled.configure(False).success is True
    assert disabled_service.unregistered == 0


def test_macos_login_item_rejects_old_macos_and_source_mode() -> None:
    loads: list[bool] = []
    loader = lambda: loads.append(True)  # type: ignore[return-value]

    assert MacOSLoginItem(frozen=True, macos_version=(12, 6), service_loader=loader).supported is False
    assert MacOSLoginItem(frozen=False, macos_version=(15, 0), service_loader=loader).supported is False
    assert loads == []


def test_macos_login_item_reports_bridge_import_failure() -> None:
    def loader() -> _Service:
        raise ImportError("ServiceManagement unavailable")

    item = MacOSLoginItem(frozen=True, macos_version=(15, 0), service_loader=loader)

    assert item.supported is False
    result = item.configure(True)
    assert result.success is False
    assert "ServiceManagement unavailable" in result.message


def test_macos_login_item_safely_handles_an_incomplete_bridge() -> None:
    def loader() -> _Service:
        raise AttributeError("mainAppService is missing")

    item = MacOSLoginItem(frozen=True, macos_version=(15, 0), service_loader=loader)

    assert item.supported is False
    assert "mainAppService is missing" in item.configure(True).message


def test_macos_login_item_reports_service_failure() -> None:
    class _FailingService(_Service):
        def register(self) -> None:
            raise RuntimeError("approval database unavailable")

    item = MacOSLoginItem(
        frozen=True,
        macos_version=(15, 0),
        service_loader=_FailingService,
    )

    result = item.configure(True)

    assert result.success is False
    assert "approval database unavailable" in result.message


class _NativeService:
    def __init__(self) -> None:
        self.current_status = 0
        self.register_result: object = (True, None)
        self.unregister_result: object = (True, None)

    def status(self) -> int:
        return self.current_status

    def registerAndReturnError_(self, _error: object) -> object:
        return self.register_result

    def unregisterAndReturnError_(self, _error: object) -> object:
        return self.unregister_result


def _install_fake_service_management(monkeypatch, native: _NativeService) -> None:
    bridge = SimpleNamespace(
        SMAppService=SimpleNamespace(mainAppService=lambda: native),
        SMAppServiceStatusNotRegistered=0,
        SMAppServiceStatusEnabled=1,
        SMAppServiceStatusRequiresApproval=2,
        SMAppServiceStatusNotFound=3,
    )
    monkeypatch.setitem(sys.modules, "ServiceManagement", bridge)


def test_pyobjc_bridge_maps_all_native_statuses(monkeypatch) -> None:
    native = _NativeService()
    _install_fake_service_management(monkeypatch, native)
    service = _PyObjCLoginItemService()

    expected = {
        0: "not_registered",
        1: "enabled",
        2: "requires_approval",
        3: "not_found",
        99: "unknown",
    }
    for native_status, status in expected.items():
        native.current_status = native_status
        assert service.status() == status


def test_pyobjc_bridge_raises_the_native_error_description(monkeypatch) -> None:
    class _Error:
        def localizedDescription(self) -> str:
            return "login item database unavailable"

    native = _NativeService()
    native.register_result = (False, _Error())
    _install_fake_service_management(monkeypatch, native)

    with pytest.raises(RuntimeError, match="login item database unavailable"):
        _PyObjCLoginItemService().register()


def test_pyobjc_bridge_accepts_successful_register_and_unregister(monkeypatch) -> None:
    native = _NativeService()
    _install_fake_service_management(monkeypatch, native)
    service = _PyObjCLoginItemService()

    service.register()
    service.unregister()
