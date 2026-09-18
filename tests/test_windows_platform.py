"""Windows 平台适配器测试。"""

from subprocess import CompletedProcess

import pytest

from petnest.platforms.base import StartupRegistrationResult
from petnest.platforms.windows import (
    WindowsPlatformAdapter,
    _elapsed_milliseconds,
    terminate_wechat_processes,
)


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


@pytest.mark.parametrize("platform_name", ["win32", "darwin", "linux", None])
@pytest.mark.parametrize("addresses", [None, set(), {"192.168.101.15"}])
def test_disabled_compatibility_entry_never_runs_commands(platform_name, addresses, monkeypatch) -> None:
    def fail_if_called(*_args, **_kwargs) -> CompletedProcess[str]:
        raise AssertionError("停用的兼容入口不应执行任何外部命令")

    monkeypatch.setattr("petnest.platforms.windows.subprocess.run", fail_if_called)
    assert (
        terminate_wechat_processes(
            platform_name=platform_name,
            runner=fail_if_called,
            local_ipv4_addresses=addresses,
        )
        == ()
    )
    assert terminate_wechat_processes(platform_name=platform_name, local_ipv4_addresses=addresses) == ()
