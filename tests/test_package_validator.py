"""宠物包校验器的行为测试。"""

from __future__ import annotations

import json
import struct
import sys
import zlib
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from petnest.core import package_validator as package_validator_module
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


def _write_webp(path: Path, width: int = 16, height: int = 16) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (width, height), (128, 128, 128, 128)).save(
        path,
        format="WEBP",
        lossless=True,
    )


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


def test_valid_package_accepts_webp_frames_in_natural_order(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "valid-webp")
    _write_webp(root / "animations" / "idle" / "1.webp")

    result = PackageValidator().validate(root)

    assert result.is_valid
    assert [frame.name for frame in result.frames["idle"]] == ["1.webp", "2.png", "10.png"]


def test_animation_rejects_png_and_webp_with_the_same_stem(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "duplicate-frame-stem")
    _write_webp(root / "animations" / "idle" / "2.webp")

    result = PackageValidator().validate(root)

    assert not result.is_valid
    assert any("2.png" in error and "2.webp" in error for error in result.errors)


def test_animation_reports_every_png_webp_stem_conflict(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "multiple-frame-conflicts")
    _write_webp(root / "animations" / "idle" / "2.webp")
    _write_webp(root / "animations" / "idle" / "10.webp")

    result = PackageValidator().validate(root)

    assert not result.is_valid
    assert any("2.png" in error and "2.webp" in error for error in result.errors)
    assert any("10.png" in error and "10.webp" in error for error in result.errors)


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


def test_pet_scope_animation_can_declare_independent_canvas(tmp_path: Path) -> None:
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

    assert result.is_valid, result.errors
    assert result.frames["wrong"][0].name == "001.png"


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


def test_interaction_items_isolate_duplicate_invalid_id_and_escaping_icon(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path / "interaction-items",
        interaction_items=[
            {"id": "ball", "label": " Ball ", "icon": "items/ball.png"},
            {"id": "ball", "label": "Duplicate", "icon": "items/duplicate.png"},
            {"id": "Bad ID", "label": "Invalid", "icon": "items/invalid.png"},
            {"id": "wand", "label": "Wand", "icon": "../outside.png"},
        ],
    )
    _write_png(root / "items" / "ball.png")
    _write_png(root / "items" / "duplicate.png")
    _write_png(root / "items" / "invalid.png")

    result = PackageValidator().validate(root)

    assert result.is_valid
    assert result.errors == []
    assert result.interaction_item_icons == {"ball": (root / "items" / "ball.png").resolve()}
    assert any("ball" in warning and "重复" in warning for warning in result.warnings)
    assert any("Bad ID" in warning and "id" in warning.lower() for warning in result.warnings)
    assert any("wand" in warning and "包目录之外" in warning for warning in result.warnings)


def test_interaction_item_duplicate_id_is_reserved_before_icon_validation(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path / "duplicate-after-missing-icon",
        interaction_items=[
            {"id": "ball", "label": "Missing", "icon": "items/missing.png"},
            {"id": "ball", "label": "Existing", "icon": "items/ball.png"},
        ],
    )
    _write_png(root / "items" / "ball.png")

    result = PackageValidator().validate(root)

    assert result.is_valid
    assert result.interaction_item_icons == {}
    assert any("ball" in warning and "不存在" in warning for warning in result.warnings)
    assert any("ball" in warning and "重复" in warning for warning in result.warnings)


def test_interaction_item_icons_require_alpha_and_safe_dimensions(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path / "bad-interaction-icons",
        interaction_items=[
            {"id": "opaque", "label": "Opaque", "icon": "items/opaque.png"},
            {"id": "large", "label": "Large", "icon": "items/large.png"},
        ],
    )
    _write_png(root / "items" / "opaque.png", alpha=False)
    _write_png(root / "items" / "large.png", width=513, height=16)

    result = PackageValidator().validate(root)

    assert result.is_valid
    assert result.errors == []
    assert result.interaction_item_icons == {}
    assert len(result.warnings) == 2
    assert any("opaque" in warning and "透明通道" in warning for warning in result.warnings)
    assert any("large" in warning and "512" in warning for warning in result.warnings)


def test_interaction_item_icon_with_invalid_path_characters_is_isolated(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path / "invalid-icon-path",
        interaction_items=[
            {"id": "broken", "label": "Broken", "icon": "items/broken\x00.png"},
        ],
    )

    result = PackageValidator().validate(root)

    assert result.is_valid
    assert result.interaction_item_icons == {}
    assert any("broken" in warning and "路径" in warning for warning in result.warnings)


def test_interaction_item_icon_rejects_non_png_content_with_png_suffix(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path / "disguised-icon",
        interaction_items=[
            {"id": "disguised", "label": "Disguised", "icon": "items/disguised.png"},
        ],
    )
    icon = root / "items" / "disguised.png"
    icon.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (16, 16)).save(icon, format="TIFF")

    result = PackageValidator().validate(root)

    assert result.is_valid
    assert result.interaction_item_icons == {}
    assert any("disguised" in warning and "PNG" in warning for warning in result.warnings)


def test_interaction_item_icon_rejects_oversized_header_before_loading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _write_package(
        tmp_path / "oversized-icon-header",
        interaction_items=[
            {"id": "large", "label": "Large", "icon": "items/large.png"},
        ],
    )
    _write_png(root / "items" / "large.png")
    original_open = package_validator_module.Image.open

    class OversizedImage:
        format = "PNG"
        size = (513, 16)

        def __enter__(self) -> OversizedImage:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def load(self) -> None:
            raise AssertionError("oversized icons must be rejected before pixel decoding")

        def getbands(self) -> tuple[str, ...]:
            return ("R", "G", "B", "A")

    def open_image(path: object) -> object:
        if Path(path) == (root / "items" / "large.png"):
            return OversizedImage()
        return original_open(path)

    monkeypatch.setattr(package_validator_module.Image, "open", open_image)

    result = PackageValidator().validate(root)

    assert result.is_valid
    assert result.interaction_item_icons == {}
    assert any("large" in warning and "512" in warning for warning in result.warnings)


def test_interaction_item_decompression_bomb_error_is_isolated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _write_package(
        tmp_path / "decompression-bomb-icon",
        interaction_items=[
            {"id": "bomb", "label": "Bomb", "icon": "items/bomb.png"},
        ],
    )
    _write_png(root / "items" / "bomb.png")
    original_open = package_validator_module.Image.open

    def open_image(path: object) -> object:
        if Path(path) == (root / "items" / "bomb.png"):
            raise Image.DecompressionBombError("unsafe image dimensions")
        return original_open(path)

    monkeypatch.setattr(package_validator_module.Image, "open", open_image)

    result = PackageValidator().validate(root)

    assert result.is_valid
    assert result.interaction_item_icons == {}
    assert any("bomb" in warning and "无法读取" in warning for warning in result.warnings)


def test_interaction_item_decompression_bomb_warning_as_error_is_isolated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _write_package(
        tmp_path / "decompression-bomb-warning-icon",
        interaction_items=[
            {"id": "bomb", "label": "Bomb", "icon": "items/bomb.png"},
        ],
    )
    _write_png(root / "items" / "bomb.png")
    original_open = package_validator_module.Image.open

    def open_image(path: object) -> object:
        if Path(path) == (root / "items" / "bomb.png"):
            raise Image.DecompressionBombWarning("unsafe image dimensions")
        return original_open(path)

    monkeypatch.setattr(package_validator_module.Image, "open", open_image)

    result = PackageValidator().validate(root)

    assert result.is_valid
    assert result.interaction_item_icons == {}
    assert any("bomb" in warning and "无法读取" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    ("interaction_items", "warning_text"),
    [
        ({"id": "ball"}, "数组"),
        ([{"id": "ball", "label": "   ", "icon": "items/ball.png"}], "label"),
    ],
)
def test_invalid_interaction_item_shapes_are_warnings(
    tmp_path: Path,
    interaction_items: object,
    warning_text: str,
) -> None:
    root = _write_package(tmp_path / "invalid-interaction-items", interaction_items=interaction_items)
    _write_png(root / "items" / "ball.png")

    result = PackageValidator().validate(root)

    assert result.is_valid
    assert result.interaction_item_icons == {}
    assert any(warning_text in warning for warning in result.warnings)


def test_interaction_items_warns_and_only_reads_first_eight_entries(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path / "too-many-interaction-items",
        interaction_items=[
            {"id": f"item-{index}", "label": f"Item {index}", "icon": f"items/{index}.png"}
            for index in range(9)
        ],
    )
    for index in range(9):
        _write_png(root / "items" / f"{index}.png")

    result = PackageValidator().validate(root)

    assert result.is_valid
    assert tuple(result.interaction_item_icons) == tuple(f"item-{index}" for index in range(8))
    assert any("最多" in warning and "8" in warning for warning in result.warnings)


def test_invalid_hold_play_is_warning_and_keeps_normal_interaction_item(tmp_path: Path) -> None:
    root = _write_package(
        tmp_path / "invalid-hold-play",
        bindings={"interaction.item.toy_wand": "idle"},
        interaction_items=[
            {
                "id": "toy_wand",
                "label": "逗猫棒",
                "icon": "items/toy_wand.png",
                "hold_play": {
                    "cursor": "items/toy_wand.png",
                    "cursor_hotspot": [10, 11],
                    "ready_action": "missing_ready",
                    "attack_origin": [12, 15],
                    "settle_ms": 140,
                    "cooldown_ms": 350,
                    "rearm_distance": 4,
                    "targets": {
                        "center": {
                            "action": "idle",
                            "contact_frame": 1,
                            "contact_point": [12, 8],
                            "max_correction": [2, 3],
                        }
                    },
                },
            }
        ],
    )
    _write_png(root / "items" / "toy_wand.png")

    result = PackageValidator().validate(root)

    assert result.is_valid
    assert "toy_wand" in result.interaction_item_icons
    assert "toy_wand" not in result.interaction_hold_play
    assert any("toy_wand" in warning and "missing_ready" in warning for warning in result.warnings)
