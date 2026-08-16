"""Tests for the reusable animation preview widget."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from petnest.ui.animation_preview_widget import AnimationPreviewWidget


def write_png(path: Path, color: tuple[int, int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (16, 12), color).save(path)


def test_preview_uses_frame_durations_when_present(qtbot: object, tmp_path: Path) -> None:
    first = tmp_path / "001.png"
    second = tmp_path / "002.png"
    write_png(first, (255, 0, 0, 255))
    write_png(second, (0, 255, 0, 255))
    widget = AnimationPreviewWidget()
    qtbot.addWidget(widget)

    widget.set_frames((first, second), frame_durations_ms=(80, 120))

    assert widget.next_delay_ms() == 80
    assert widget.preview_frame_index == 0
    widget._advance_preview()
    assert widget.preview_frame_index == 1
    assert widget.next_delay_ms() == 120


def test_preview_emits_frame_changed_from_real_timer_tick(qtbot: object, tmp_path: Path) -> None:
    first = tmp_path / "001.png"
    second = tmp_path / "002.png"
    write_png(first, (255, 0, 0, 255))
    write_png(second, (0, 255, 0, 255))
    widget = AnimationPreviewWidget()
    qtbot.addWidget(widget)
    changed: list[int] = []
    widget.frame_changed.connect(changed.append)

    widget.set_frames((first, second), frame_durations_ms=(25, 25))
    qtbot.waitUntil(lambda: bool(changed), timeout=1000)

    assert changed[0] == 1


def test_preview_can_load_definition_relative_to_root_and_pause(qtbot: object, tmp_path: Path) -> None:
    root = tmp_path / "pet"
    first = root / "animations" / "idle" / "001.png"
    second = root / "animations" / "idle" / "002.png"
    write_png(first, (255, 0, 0, 255))
    write_png(second, (0, 255, 0, 255))
    widget = AnimationPreviewWidget()
    qtbot.addWidget(widget)

    widget.set_animation(
        {"path": "animations/idle", "fps": 10, "loop": True, "frame_durations_ms": [70, 130]},
        root,
    )
    widget.set_playing(False)

    assert widget.next_delay_ms() == 70
    assert not widget.preview_timer.isActive()
    assert not widget.preview_label.pixmap().isNull()


def test_preview_missing_frame_stops_timer_and_shows_error(qtbot: object, tmp_path: Path) -> None:
    widget = AnimationPreviewWidget()
    qtbot.addWidget(widget)

    widget.set_frames((tmp_path / "missing.png",), frame_durations_ms=(100,))

    assert not widget.preview_timer.isActive()
    assert "无法读取" in widget.preview_label.text()
