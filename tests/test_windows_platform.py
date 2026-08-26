"""Windows 平台适配器测试。"""

from subprocess import CompletedProcess

from petnest.platforms.base import StartupRegistrationResult
from petnest.platforms.windows import (
    WECHAT_PROCESS_NAMES,
    WECHAT_TERMINATION_LOCAL_IP,
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


def test_windows_login_start_force_terminates_legacy_and_current_wechat(
    tmp_path, monkeypatch
) -> None:
    windows_root = tmp_path / "Windows"
    monkeypatch.setenv("SystemRoot", str(windows_root))
    commands: list[list[str]] = []

    def run(arguments: list[str]) -> CompletedProcess[str]:
        commands.append(arguments)
        return CompletedProcess(arguments, 0, stdout="SUCCESS", stderr="")

    terminated = terminate_wechat_processes(
        platform_name="win32",
        runner=run,
        local_ipv4_addresses={WECHAT_TERMINATION_LOCAL_IP},
    )

    assert terminated == WECHAT_PROCESS_NAMES
    assert commands == [
        [str(windows_root / "System32" / "taskkill.exe"), "/F", "/T", "/IM", "WeChat.exe"],
        [str(windows_root / "System32" / "taskkill.exe"), "/F", "/T", "/IM", "Weixin.exe"],
    ]


def test_wechat_termination_is_inert_outside_windows() -> None:
    def fail_if_called(_arguments: list[str]) -> CompletedProcess[str]:
        raise AssertionError("非 Windows 平台不应调用 taskkill")

    assert terminate_wechat_processes(platform_name="darwin", runner=fail_if_called) == ()


def test_wechat_termination_is_inert_on_other_windows_ip() -> None:
    def fail_if_called(_arguments: list[str]) -> CompletedProcess[str]:
        raise AssertionError("其他 Windows IP 不应调用 taskkill")

    assert (
        terminate_wechat_processes(
            platform_name="win32",
            runner=fail_if_called,
            local_ipv4_addresses={"192.168.101.15"},
        )
        == ()
    )
