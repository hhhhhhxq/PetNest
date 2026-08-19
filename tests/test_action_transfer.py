"""Tests for source detection and pet action extraction."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from petnest.core.action_transfer import (
    AmbiguousExchangeSourceError,
    SourceKind,
    detect_source_kind,
    extract_pet_actions,
    load_legacy_work_finish_pack,
)


def write_png(path: Path, size: tuple[int, int] = (8, 8)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, (255, 128, 0, 255)).save(path)


def write_pet(root: Path) -> None:
    write_png(root / "animations" / "idle" / "001.png")
    write_png(root / "animations" / "walk" / "001.png")
    (root / "pet.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "pingan",
                "name": "平安",
                "canvas": {"width": 8, "height": 8},
                "animations": {
                    "idle": {"path": "animations/idle", "fps": 8, "loop": True},
                    "walk": {
                        "path": "animations/walk",
                        "fps": 10,
                        "loop": True,
                        "next": "idle",
                        "scope": "fullscreen",
                        "canvas": {"width": 8, "height": 8},
                        "frame_durations_ms": [80, 120],
                        "entrance_direction": "left",
                    },
                },
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("marker", "kind"),
    [
        ("pet.json", SourceKind.PET_PACKAGE),
        ("petnest-action-pack.json", SourceKind.ACTION_PACK),
        ("manifest.json", SourceKind.LEGACY_WORK_FINISH),
    ],
)
def test_detects_manifest_type(tmp_path: Path, marker: str, kind: SourceKind) -> None:
    root = tmp_path / "source"
    root.mkdir()
    (root / marker).write_text("{}", encoding="utf-8")

    assert detect_source_kind(root) is kind


@pytest.mark.parametrize("suffix", [".png", ".webp"])
def test_detects_supported_image_as_spritesheet(tmp_path: Path, suffix: str) -> None:
    source = tmp_path / f"pet{suffix}"
    write_png(source)

    assert detect_source_kind(source) is SourceKind.SPRITESHEET


def test_detects_directory_with_one_webp_as_spritesheet(tmp_path: Path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    write_png(root / "pet.webp")

    assert detect_source_kind(root) is SourceKind.SPRITESHEET


def test_rejects_ambiguous_source(tmp_path: Path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    (root / "pet.json").write_text("{}", encoding="utf-8")
    (root / "manifest.json").write_text("{}", encoding="utf-8")

    with pytest.raises(AmbiguousExchangeSourceError):
        detect_source_kind(root)


def test_extract_actions_preserves_supported_animation_fields(tmp_path: Path) -> None:
    root = tmp_path / "pet"
    write_pet(root)

    actions = extract_pet_actions(root)

    assert actions["walk"].definition["next"] == "idle"
    assert actions["walk"].definition["frame_durations_ms"] == [80, 120]
    assert actions["walk"].definition["entrance_direction"] == "left"
    assert actions["walk"].scope == "fullscreen"
    assert actions["walk"].source_root == root.resolve()
    assert all(path.is_relative_to(root.resolve()) for path in actions["walk"].asset_paths)


def test_extract_actions_rejects_path_escape(tmp_path: Path) -> None:
    root = tmp_path / "pet"
    write_pet(root)
    config_path = root / "pet.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["animations"]["walk"]["path"] = "../outside"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ValueError, match="路径"):
        extract_pet_actions(root)


def test_legacy_work_finish_pack_adapts_to_transfer_actions(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    root.mkdir()
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "name": "平安下班",
                "canvas": {"width": 8, "height": 8},
                "walk": {"path": "walk", "fps": 10},
                "lie_down": {"path": "lie-down", "fps": 8, "frame_durations_ms": [100, 200]},
            }
        ),
        encoding="utf-8",
    )
    write_png(root / "walk" / "001.png")
    write_png(root / "lie-down" / "001.png")
    write_png(root / "lie-down" / "002.png")

    pack = load_legacy_work_finish_pack(root)

    assert set(pack.actions) == {"work_finish_walk", "work_finish_lie_down"}
    assert pack.actions["work_finish_lie_down"].definition["scope"] == "fullscreen"
    assert pack.actions["work_finish_lie_down"].definition["frame_durations_ms"] == [100, 200]
    pack.close()


def test_extract_actions_rejects_non_png_action_assets(tmp_path: Path) -> None:
    root = tmp_path / "pet"
    write_pet(root)
    (root / "animations" / "walk" / "notes.txt").write_text("not a frame", encoding="utf-8")

    with pytest.raises(ValueError, match="PNG"):
        extract_pet_actions(root)


def test_extract_actions_rejects_nested_frames(tmp_path: Path) -> None:
    root = tmp_path / "pet"
    write_pet(root)
    nested = root / "animations" / "walk" / "nested" / "001.png"
    nested.parent.mkdir()
    (root / "animations" / "walk" / "001.png").replace(nested)

    with pytest.raises(ValueError, match="直接"):
        extract_pet_actions(root)
