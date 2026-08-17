"""平安全屏动画素材构建工具的纯函数测试。"""

from __future__ import annotations

from tools.build_pingan_fullscreen import build_manifest, sample_indices, split_phase_indices


def test_sample_timeline_uses_12_fps_and_preserves_duration() -> None:
    indices = sample_indices(frame_count=240, source_fps=24.0, output_fps=12.0)

    assert len(indices) == 120
    assert indices[:3] == [0, 2, 4]
    assert indices[-1] == 238


def test_split_frames_uses_four_second_walk_boundary() -> None:
    walk, lie = split_phase_indices(list(range(120)), fps=12.0, walk_seconds=4.0)

    assert len(walk) == 48
    assert len(lie) == 72


def test_manifest_has_two_fullscreen_actions_and_left_entrance() -> None:
    manifest = build_manifest(name="平安全屏动画", canvas=(960, 540), walk_count=48, lie_count=72)

    assert manifest["animations"]["work_finish_walk"]["entrance_direction"] == "left"
    assert manifest["animations"]["work_finish_lie_down"]["scope"] == "fullscreen"
