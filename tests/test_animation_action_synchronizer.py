"""动画动作目录同步器的行为测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from petnest.core.animation_action_synchronizer import (
    AnimationActionSyncError,
    AnimationActionSynchronizer,
    SyncedAction,
)
from tests.test_package_validator import _write_package, _write_png, _write_webp


def _config(root: Path) -> dict[str, object]:
    return json.loads((root / "pet.json").read_text(encoding="utf-8"))


def _try_create_file_symlink(link: Path, target: Path) -> bool:
    try:
        link.symlink_to(target)
    except OSError:
        return False
    return link.is_symlink()


def test_sync_adds_sorted_png_action_directories_and_reports_frame_counts(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "sync")
    _write_png(root / "animations" / "sleep" / "2.png")
    _write_png(root / "animations" / "sleep" / "10.png")
    _write_png(root / "animations" / "blink" / "1.PNG")

    result = AnimationActionSynchronizer().sync(root)

    assert result.added == (SyncedAction("blink", 1), SyncedAction("sleep", 2))
    animations = _config(root)["animations"]
    assert animations["sleep"] == {
        "path": "animations/sleep",
        "fps": 10,
        "loop": True,
        "priority": 20,
    }
    assert animations["blink"] == {
        "path": "animations/blink",
        "fps": 10,
        "loop": True,
        "priority": 20,
    }


def test_sync_adds_webp_action_directory_and_reports_frame_count(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "sync-webp")
    _write_webp(root / "animations" / "sleep" / "1.webp")
    _write_webp(root / "animations" / "sleep" / "2.webp")

    result = AnimationActionSynchronizer().sync(root)

    assert result.added == (SyncedAction("sleep", 2),)
    assert _config(root)["animations"]["sleep"]["path"] == "animations/sleep"


def test_sync_adds_non_looping_wake_with_context_transition(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "wake")
    _write_png(root / "animations" / "wake" / "1.png")

    result = AnimationActionSynchronizer().sync(root)

    assert result.added == (SyncedAction("wake", 1),)
    assert _config(root)["animations"]["wake"] == {
        "path": "animations/wake",
        "fps": 10,
        "loop": False,
        "priority": 20,
        "next": "context",
    }


def test_sync_preserves_existing_idle_definition_when_adding_sleep(tmp_path: Path) -> None:
    idle_definition = {
        "path": "animations/idle",
        "fps": 6,
        "loop": True,
        "priority": 4,
        "interruptible": False,
        "frame_durations_ms": [90, 110],
    }
    root = _write_package(tmp_path / "preserve-idle", animations={"idle": idle_definition})
    _write_png(root / "animations" / "sleep" / "1.png")

    result = AnimationActionSynchronizer().sync(root)

    animations = _config(root)["animations"]
    assert result.added == (SyncedAction("sleep", 1),)
    assert list(animations) == ["idle", "sleep"]
    assert animations["idle"] == idle_definition
    assert animations["sleep"] == {
        "path": "animations/sleep",
        "fps": 10,
        "loop": True,
        "priority": 20,
    }


def test_update_frame_durations_writes_a_shareable_timeline_to_pet_json(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "timing")

    AnimationActionSynchronizer().update_frame_durations(root, {"idle": (180, 90)})

    assert _config(root)["animations"]["idle"]["frame_durations_ms"] == [180, 90]


def test_sync_extends_a_registered_timeline_when_a_png_frame_is_added(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path / "added-frame",
        animations={
            "idle": {
                "path": "animations/idle", "fps": 8, "loop": True,
                "priority": 10, "frame_durations_ms": [90, 110],
            }
        },
    )
    _write_png(root / "animations" / "idle" / "11.png")

    result = AnimationActionSynchronizer().sync(root)

    assert result.added == ()
    assert _config(root)["animations"]["idle"]["frame_durations_ms"] == [90, 110, 110]


def test_sync_extends_a_registered_timeline_for_webp_only_frames(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path / "webp-timeline",
        animations={
            "idle": {
                "path": "animations/idle", "fps": 8, "loop": True,
                "priority": 10, "frame_durations_ms": [90, 110],
            }
        },
    )
    for frame in (root / "animations" / "idle").glob("*.png"):
        frame.unlink()
    for index in range(1, 4):
        _write_webp(root / "animations" / "idle" / f"{index:03d}.webp")

    AnimationActionSynchronizer().sync(root)

    assert _config(root)["animations"]["idle"]["frame_durations_ms"] == [90, 110, 110]


def test_sync_trims_a_registered_timeline_when_a_png_frame_is_removed(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path / "removed-frame",
        animations={
            "idle": {
                "path": "animations/idle", "fps": 8, "loop": True,
                "priority": 10, "frame_durations_ms": [90, 110, 130],
            }
        },
    )

    AnimationActionSynchronizer().sync(root)

    assert _config(root)["animations"]["idle"]["frame_durations_ms"] == [90, 110]


def test_sync_ignores_png_frames_nested_below_an_animation_directory(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "nested-frame")
    _write_png(root / "animations" / "outer" / "nested" / "001.png")

    result = AnimationActionSynchronizer().sync(root)

    assert result.added == ()
    assert "outer" not in _config(root)["animations"]


def test_sync_skips_registered_empty_and_non_png_directories_without_rewriting(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "unchanged")
    _write_png(root / "animations" / "idle" / "3.png")
    (root / "animations" / "empty").mkdir()
    non_png = root / "animations" / "notes"
    non_png.mkdir()
    (non_png / "readme.txt").write_text("not an animation", encoding="utf-8")
    config_path = root / "pet.json"
    before = config_path.read_bytes()
    before_mtime_ns = config_path.stat().st_mtime_ns

    result = AnimationActionSynchronizer().sync(root)

    assert result.added == ()
    assert config_path.read_bytes() == before
    assert config_path.stat().st_mtime_ns == before_mtime_ns


def test_sync_rejects_invalid_candidate_frames_without_changing_configuration(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "bad-candidate")
    _write_png(root / "animations" / "sleep" / "1.png", width=20, height=16)
    config_path = root / "pet.json"
    before = config_path.read_bytes()

    with pytest.raises(AnimationActionSyncError, match="画布尺寸"):
        AnimationActionSynchronizer().sync(root)

    assert config_path.read_bytes() == before


def test_sync_keeps_original_configuration_when_atomic_replace_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _write_package(tmp_path / "replace-failure")
    _write_png(root / "animations" / "sleep" / "1.png")
    config_path = root / "pet.json"
    before = config_path.read_bytes()

    def fail_replace(source: str | Path, destination: str | Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr("petnest.core.animation_action_synchronizer.os.replace", fail_replace)

    with pytest.raises(AnimationActionSyncError, match="replace failed"):
        AnimationActionSynchronizer().sync(root)

    assert config_path.read_bytes() == before


def test_sync_rejects_a_symlinked_pet_json_without_changing_its_external_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _write_package(tmp_path / "symlinked-config")
    _write_png(root / "animations" / "sleep" / "1.png")
    config_path = root / "pet.json"
    original = config_path.read_bytes()
    external_config = tmp_path / "external-pet.json"
    external_config.write_bytes(original)
    config_path.unlink()

    if _try_create_file_symlink(config_path, external_config):
        with pytest.raises(AnimationActionSyncError, match="pet.json"):
            AnimationActionSynchronizer().sync(root)

        assert external_config.read_bytes() == original
    else:
        config_path.write_bytes(original)
        original_is_symlink = Path.is_symlink

        def reported_as_symlink(path: Path) -> bool:
            return path == config_path or original_is_symlink(path)

        monkeypatch.setattr(Path, "is_symlink", reported_as_symlink)

        with pytest.raises(AnimationActionSyncError, match="pet.json"):
            AnimationActionSynchronizer().sync(root)

        assert config_path.read_bytes() == original


def test_sync_rejects_a_candidate_directory_with_an_external_png_symlink(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "symlinked-frame")
    external_frame = tmp_path / "external.png"
    _write_png(external_frame)
    frame_link = root / "animations" / "sleep" / "001.png"
    frame_link.parent.mkdir()
    if not _try_create_file_symlink(frame_link, external_frame):
        pytest.skip("当前平台不允许创建文件符号链接")
    config_path = root / "pet.json"
    before = config_path.read_bytes()

    with pytest.raises(AnimationActionSyncError, match="符号链接"):
        AnimationActionSynchronizer().sync(root)

    assert config_path.read_bytes() == before
    assert "sleep" not in _config(root)["animations"]


def test_sync_rejects_a_candidate_directory_with_a_dangling_webp_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _write_package(tmp_path / "dangling-webp-frame")
    _write_webp(root / "animations" / "sleep" / "001.webp")
    dangling = root / "animations" / "sleep" / "broken.webp"
    dangling.write_bytes(b"simulated dangling link")
    original_is_file = Path.is_file
    original_is_symlink = Path.is_symlink

    def simulated_is_file(path: Path) -> bool:
        return False if path == dangling else original_is_file(path)

    def simulated_is_symlink(path: Path) -> bool:
        return True if path == dangling else original_is_symlink(path)

    monkeypatch.setattr(Path, "is_file", simulated_is_file)
    monkeypatch.setattr(Path, "is_symlink", simulated_is_symlink)

    with pytest.raises(AnimationActionSyncError, match="符号链接"):
        AnimationActionSynchronizer().sync(root)


def test_sync_with_no_candidates_leaves_mtime_and_contents_unchanged(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "no-candidates")
    config_path = root / "pet.json"
    before = config_path.read_bytes()
    before_mtime_ns = config_path.stat().st_mtime_ns

    result = AnimationActionSynchronizer().sync(root)

    assert result.added == ()
    assert config_path.read_bytes() == before
    assert config_path.stat().st_mtime_ns == before_mtime_ns
