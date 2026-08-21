"""宠物包校验器的行为测试。"""

from __future__ import annotations

import json
import struct
import sys
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from petnest.core.package_validator import PackageValidator


def _png(width: int, height: int, *, alpha: bool = True) -> bytes:
    """Create a minimal valid RGB/RGBA PNG without a test dependency on Pillow."""
    colour_type = 6 if alpha else 2
    channels = 4 if alpha else 3
    raw = b"".join(b"\x00" + (b"\x80" * width * channels) for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(
        b"IHDR", struct.pack(">IIBBBBB", width, height, 8, colour_type, 0, 0, 0)
    ) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def _write_png(path: Path, width: int = 16, height: int = 16, *, alpha: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_png(width, height, alpha=alpha))


def _package_data(**overrides: object) -> dict[str, object]:
    package: dict[str, object] = {
        "schema_version": 1,
        "id": "test_pet",
        "name": "Test Pet",
        "version": "1.0.0",
        "canvas": {"width": 16, "height": 16},
        "animations": {
            "idle": {
                "path": "animations/idle",
                "fps": 8,
                "loop": True,
                "priority": 10,
                "interruptible": True,
            }
        },
        "fallbacks": {},
    }
    package.update(overrides)
    return package


def _write_package(root: Path, **overrides: object) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pet.json").write_text(json.dumps(_package_data(**overrides)), encoding="utf-8")
    _write_png(root / "animations" / "idle" / "10.png")
    _write_png(root / "animations" / "idle" / "2.png")
    return root


def test_valid_package_is_accepted_and_frames_use_natural_sorting(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "valid")

    result = PackageValidator().validate(root)

    assert result.is_valid
    assert result.errors == []
    assert [frame.name for frame in result.frames["idle"]] == ["2.png", "10.png"]


def test_missing_idle_makes_package_invalid(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "no-idle", animations={})

    result = PackageValidator().validate(root)

    assert not result.is_valid
    assert any("idle" in error for error in result.errors)


def test_animation_path_cannot_escape_package_directory(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path / "escape",
        animations={
            "idle": {
                "path": "../outside",
                "fps": 8,
                "loop": True,
                "priority": 10,
                "interruptible": True,
            }
        },
    )

    result = PackageValidator().validate(root)

    assert not result.is_valid
    assert any("包目录之外" in error for error in result.errors)


def test_zero_fps_is_invalid(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path / "bad-fps",
        animations={
            "idle": {
                "path": "animations/idle",
                "fps": 0,
                "loop": True,
                "priority": 10,
                "interruptible": True,
            }
        },
    )

    result = PackageValidator().validate(root)

    assert not result.is_valid
    assert any("FPS" in error for error in result.errors)


def test_frame_duration_timeline_must_match_png_frames_and_be_positive(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path / "bad-timeline",
        animations={
            "idle": {
                "path": "animations/idle", "fps": 8, "loop": True,
                "frame_durations_ms": [120, 0, 120],
            }
        },
    )

    result = PackageValidator().validate(root)

    assert not result.is_valid
    assert any("数量" in error or "正整数" in error for error in result.errors)


def test_frame_duration_timeline_must_fit_qt_timer_interval(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "oversized-timeline")
    config_path = root / "pet.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["animations"]["idle"]["frame_durations_ms"] = [2_147_483_647, 1]
    config_path.write_text(json.dumps(config), encoding="utf-8")

    result = PackageValidator().validate(root)

    assert not result.is_valid
    assert any("时长" in error and "上限" in error for error in result.errors)


def test_empty_animation_directory_is_invalid(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "empty")
    for frame in (root / "animations" / "idle").glob("*.png"):
        frame.unlink()

    result = PackageValidator().validate(root)

    assert not result.is_valid
    assert any("没有 PNG 帧" in error for error in result.errors)


def test_frames_must_match_declared_canvas_and_have_alpha(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "bad-images")
    _write_png(root / "animations" / "idle" / "10.png", width=20, height=16)
    _write_png(root / "animations" / "idle" / "3.png", alpha=False)

    result = PackageValidator().validate(root)

    assert not result.is_valid
    assert any("画布尺寸" in error for error in result.errors)
    assert any("透明通道" in error for error in result.errors)


def test_fullscreen_animation_can_use_its_own_canvas(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "fullscreen")
    config_path = root / "pet.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["animations"]["work_finish_walk"] = {
        "path": "animations/work_finish_walk",
        "scope": "fullscreen",
        "canvas": {"width": 24, "height": 18},
        "fps": 10,
        "loop": True,
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    _write_png(root / "animations" / "work_finish_walk" / "001.png", 24, 18)

    result = PackageValidator().validate(root)

    assert result.is_valid
    assert result.errors == []


def test_fullscreen_animation_accepts_entrance_direction(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "direction")
    config_path = root / "pet.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["animations"]["work_finish_walk"] = {
        "path": "animations/work_finish_walk",
        "scope": "fullscreen",
        "canvas": {"width": 24, "height": 18},
        "fps": 10,
        "loop": True,
        "entrance_direction": "left",
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    _write_png(root / "animations/work_finish_walk/001.png", 24, 18)

    result = PackageValidator().validate(root)

    assert result.is_valid


@pytest.mark.parametrize("direction", ["up", "", 1, None])
def test_animation_rejects_invalid_entrance_direction(tmp_path: Path, direction: object) -> None:
    root = _write_package(tmp_path / "invalid-direction")
    config_path = root / "pet.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["animations"]["idle"]["entrance_direction"] = direction
    config_path.write_text(json.dumps(config), encoding="utf-8")

    result = PackageValidator().validate(root)

    assert not result.is_valid
    assert any("entrance_direction" in error for error in result.errors)


def test_pet_scope_cannot_declare_entrance_direction(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "pet-scope-direction")
    config_path = root / "pet.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["animations"]["idle"]["entrance_direction"] = "left"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    result = PackageValidator().validate(root)

    assert not result.is_valid
    assert any("全屏" in error and "entrance_direction" in error for error in result.errors)


def test_pet_scope_animation_cannot_override_package_canvas(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "pet-canvas-override")
    config_path = root / "pet.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["animations"]["wrong"] = {
        "path": "animations/wrong",
        "scope": "pet",
        "canvas": {"width": 24, "height": 18},
        "fps": 10,
        "loop": True,
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    _write_png(root / "animations" / "wrong" / "001.png", 24, 18)

    result = PackageValidator().validate(root)

    assert not result.is_valid
    assert any("只有全屏动画" in error for error in result.errors)


def test_animation_scope_must_be_pet_or_fullscreen(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "invalid-scope")
    config_path = root / "pet.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["animations"]["wrong"] = {
        "path": "animations/wrong",
        "scope": "overlay",
        "fps": 10,
        "loop": True,
    }
    config_path.write_text(json.dumps(config), encoding="utf-8")
    _write_png(root / "animations" / "wrong" / "001.png")

    result = PackageValidator().validate(root)

    assert not result.is_valid
    assert any("scope 必须是 pet 或 fullscreen" in error for error in result.errors)


def test_fallback_cycles_are_invalid(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path / "cycle",
        fallbacks={"hover": ["click"], "click": ["hover"]},
    )

    result = PackageValidator().validate(root)

    assert not result.is_valid
    assert any("fallback" in error.lower() and "循环" in error for error in result.errors)


def test_missing_optional_animation_only_emits_warning(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "optional", bindings={"mouse.enter": "hover"})

    result = PackageValidator().validate(root)

    assert result.is_valid
    assert any("hover" in warning for warning in result.warnings)


def test_missing_bound_animation_with_a_valid_fallback_does_not_emit_warning(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path / "fallback-bound-action",
        bindings={"agent.success": "success"},
        fallbacks={"success": ["idle"]},
    )

    result = PackageValidator().validate(root)

    assert result.is_valid
    assert not result.warnings
