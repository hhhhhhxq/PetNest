"""macOS 平台适配器测试。"""

from petnest.platforms.base import StartupRegistrationResult
from petnest.platforms.macos import MacOSPlatformAdapter


class _StartupBackend:
    supported = True

    def __init__(self) -> None:
        self.calls: list[bool] = []

    def configure(self, enabled: bool) -> StartupRegistrationResult:
        self.calls.append(enabled)
        return StartupRegistrationResult(True, requires_approval=True)


def test_macos_adapter_delegates_login_item_registration() -> None:
    backend = _StartupBackend()
    adapter = MacOSPlatformAdapter(login_item=backend)

    assert adapter.startup_supported is True
    assert adapter.register_startup(True).requires_approval is True
    assert backend.calls == [True]
