"""动画播放器的纯 Python 行为测试。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PIL import Image

from petnest.core.animation_player import AnimationPlayer
from petnest.models.pet_package import AnimationDefinition


def _animation(tmp_path: Path, *, loop: bool) -> AnimationDefinition:
    frames: list[Path] = []
    for index, colour in enumerate(((255, 0, 0, 255), (0, 255, 0, 255)), start=1):
        path = tmp_path / f"{index}.png"
        Image.new("RGBA", (2, 2), colour).save(path)
        frames.append(path)
    return AnimationDefinition(
        name="wave",
        path=tmp_path,
        fps=10,
        loop=loop,
        next_animation=None,
        priority=1,
        interruptible=True,
        frames=tuple(frames),
    )


def test_preload_keeps_frames_in_memory_and_exposes_current_frame(tmp_path: Path) -> None:
    animation = _animation(tmp_path, loop=True)
    player = AnimationPlayer()

    loaded = player.preload(animation)
    player.play(animation)

    assert len(loaded) == 2
    assert player.current_frame is loaded[0]
    assert player.current_frame.getpixel((0, 0)) == (255, 0, 0, 255)


def test_pause_and_resume_control_frame_advancement(tmp_path: Path) -> None:
    animation = _animation(tmp_path, loop=True)
    player = AnimationPlayer()
    player.play(animation)
    player.pause()

    assert player.is_paused
    assert player.advance() is player.current_frame
    assert player.current_frame_index == 0

    player.resume()
    player.advance()

    assert not player.is_paused
    assert player.current_frame_index == 1


def test_looping_animation_wraps_without_completion_signal(tmp_path: Path) -> None:
    animation = _animation(tmp_path, loop=True)
    player = AnimationPlayer()
    completed: list[str] = []
    player.subscribe_completed(lambda definition: completed.append(definition.name))
    player.play(animation)

    player.advance()
    player.advance()

    assert player.current_frame_index == 0
    assert completed == []


def test_one_shot_animation_emits_completion_once_and_holds_last_frame(tmp_path: Path) -> None:
    animation = _animation(tmp_path, loop=False)
    player = AnimationPlayer()
    completed: list[str] = []
    player.subscribe_completed(lambda definition: completed.append(definition.name))
    player.play(animation)

    player.advance()
    player.advance()
    player.advance()

    assert player.is_finished
    assert player.current_frame_index == 1
    assert completed == ["wave"]


def test_per_frame_durations_override_fps_and_respect_action_speed(tmp_path: Path) -> None:
    animation = replace(_animation(tmp_path, loop=True), frame_durations_ms=(200, 80), speed_multiplier=2.0)
    player = AnimationPlayer(speed_multiplier=1.25)

    player.play(animation)
    assert player.frame_interval_seconds == 0.08
    player.advance()
    assert player.frame_interval_seconds == 0.032
