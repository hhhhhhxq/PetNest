"""Windows 平台适配器测试。"""

from petnest.platforms.base import StartupRegistrationResult
from petnest.platforms.windows import WindowsPlatformAdapter, _elapsed_milliseconds


class _StartupBackend:
    supported = True

    def __init__(self) -> None:
        self.calls: list[bool] = []

    def configure(self, enabled: bool) -> StartupRegistrationResult:
        self.calls.append(enabled)
        return StartupRegistrationResult(True)


def test_elapsed_milliseconds_handles_unsigned_tick_counter_wraparound() -> None:
    assert _elapsed_milliseconds(20, 0xFFFFFFF0) == 36


def test_windows_adapter_delegates_startup_registration() -> None:
    backend = _StartupBackend()
    adapter = WindowsPlatformAdapter(startup_task=backend)

    assert adapter.startup_supported is True
    assert adapter.register_startup(True).success is True
    assert backend.calls == [True]
