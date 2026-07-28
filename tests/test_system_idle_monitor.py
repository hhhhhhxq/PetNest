"""系统空闲阈值到一次性状态事件的转换测试。"""

from __future__ import annotations

from petnest.core.system_idle_monitor import SystemIdleMonitor


def test_monitor_emits_bored_sleep_and_wake_only_when_crossing_boundaries() -> None:
    monitor = SystemIdleMonitor(bored_seconds=30, sleep_seconds=180)

    assert monitor.update(0) is None
    assert monitor.update(30) == "system.bored"
    assert monitor.update(90) is None
    assert monitor.update(180) == "system.sleep"
    assert monitor.update(250) is None
    assert monitor.update(1) == "system.wake"
    assert monitor.update(0) is None


def test_monitor_rejects_invalid_threshold_order() -> None:
    import pytest

    with pytest.raises(ValueError, match="睡眠阈值"):
        SystemIdleMonitor(bored_seconds=30, sleep_seconds=30)
