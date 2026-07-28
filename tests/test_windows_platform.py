"""Windows 32 位 tick 计数的回绕计算测试。"""

from petnest.platforms.windows import _elapsed_milliseconds


def test_elapsed_milliseconds_handles_unsigned_tick_counter_wraparound() -> None:
    assert _elapsed_milliseconds(20, 0xFFFFFFF0) == 36
