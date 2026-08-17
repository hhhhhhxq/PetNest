"""Tests for generic action share packages."""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from PIL import Image

from petnest.core.action_pack import (
    ACTION_PACK_MANIFEST,
    ActionPackError,
    export_action_pack,
    load_action_pack,
)


def write_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (8, 8), (255, 128, 0, 255)).save(path)


def build_pet(tmp_path: Path) -> Path:
    root = tmp_path / "pingan"
    for action in ("idle", "walk", "sleep"):
        write_png(root / "animations" / action / "001.png")
    animations = {
        action: {
            "path": f"animations/{action}",
            "fps": 8,
            "loop": True,
            **({"next": "idle"} if action != "idle" else {}),
        }
        for action in ("idle", "walk", "sleep")
    }
    (root / "pet.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "pingan",
                "name": "平安",
                "version": "2.0.0",
                "author": "PetNest",
                "description": "分享测试",
                "canvas": {"width": 8, "height": 8},
                "animations": animations,
                "bindings": {"mouse.enter": "walk", "system.sleep": "sleep"},
                "fallbacks": {"walk": ["idle"], "sleep": ["idle"]},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return root


def test_export_selected_actions_round_trips(tmp_path: Path) -> None:
    pet_root = build_pet(tmp_path)
    output = tmp_path / "分享动作.zip"

    export_action_pack(pet_root, ["walk", "sleep"], output)

    with load_action_pack(output) as pack:
        assert set(pack.actions) == {"walk", "sleep"}
        assert pack.source_pet.identifier == "pingan"
        assert pack.actions["walk"].definition["path"] == "animations/walk"


def test_export_only_copies_selected_assets_and_omits_bindings_by_default(tmp_path: Path) -> None:
    pet_root = build_pet(tmp_path)
    output = tmp_path / "share.zip"

    export_action_pack(pet_root, ["walk"], output)

    with ZipFile(output) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read(ACTION_PACK_MANIFEST))
    assert "animations/walk/001.png" in names
    assert "animations/sleep/001.png" not in names
    assert "bindings" not in manifest
    assert "fallbacks" not in manifest


def test_export_can_include_only_bindings_and_fallbacks_for_selected_actions(tmp_path: Path) -> None:
    pet_root = build_pet(tmp_path)
    output = tmp_path / "share-with-bindings.zip"

    export_action_pack(pet_root, ["walk"], output, include_bindings=True)

    with ZipFile(output) as archive:
        manifest = json.loads(archive.read(ACTION_PACK_MANIFEST))
    assert manifest["bindings"] == {"mouse.enter": "walk"}
    assert manifest["fallbacks"] == {"walk": ["idle"]}


def test_export_is_atomic_when_selection_is_invalid(tmp_path: Path) -> None:
    pet_root = build_pet(tmp_path)
    output = tmp_path / "share.zip"
    output.write_bytes(b"old")

    with pytest.raises(ActionPackError):
        export_action_pack(pet_root, ["missing"], output)

    assert output.read_bytes() == b"old"


def test_fullscreen_entrance_direction_round_trips_in_action_pack(tmp_path: Path) -> None:
    pet_root = build_pet(tmp_path)
    config_path = pet_root / "pet.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["animations"]["walk"].update(
        {
            "scope": "fullscreen",
            "canvas": {"width": 8, "height": 8},
            "entrance_direction": "left",
        }
    )
    config_path.write_text(json.dumps(config), encoding="utf-8")
    output = tmp_path / "direction.zip"

    export_action_pack(pet_root, ["walk"], output)

    with load_action_pack(output) as pack:
        assert pack.actions["walk"].definition["entrance_direction"] == "left"


def test_action_pack_rejects_invalid_fullscreen_entrance_direction(tmp_path: Path) -> None:
    root = tmp_path / "invalid-pack"
    write_png(root / "animations/walk/001.png")
    (root / "petnest-action-pack.json").write_text(
        json.dumps(
            {
                "type": "petnest-action-pack",
                "schema_version": 1,
                "name": "invalid",
                "source_pet": {"id": "source", "name": "Source", "version": "1.0.0"},
                "animations": {
                    "walk": {
                        "path": "animations/walk",
                        "scope": "fullscreen",
                        "canvas": {"width": 8, "height": 8},
                        "fps": 8,
                        "loop": True,
                        "entrance_direction": "up",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ActionPackError, match="entrance_direction"):
        load_action_pack(root)
