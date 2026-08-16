"""Tests for action conflict decisions and transactional installation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from petnest.core.action_installer import (
    ConflictDecision,
    install_actions,
)
from petnest.core.action_pack import ActionPack, SourcePetInfo
from petnest.core.action_transfer import TransferAction


def write_png(path: Path, color: tuple[int, int, int, int] = (255, 128, 0, 255)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (8, 8), color).save(path)


def write_pet(root: Path, actions: tuple[str, ...] = ("idle", "walk")) -> None:
    for action in actions:
        write_png(root / "animations" / action / "001.png")
    definitions = {
        action: {"path": f"animations/{action}", "fps": 8, "loop": True}
        for action in actions
    }
    (root / "pet.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "target",
                "name": "Target",
                "canvas": {"width": 8, "height": 8},
                "animations": definitions,
                "bindings": {"mouse.enter": "walk"},
            }
        ),
        encoding="utf-8",
    )


def build_pack(tmp_path: Path, action_name: str = "walk") -> ActionPack:
    source = tmp_path / "source"
    write_png(source / "animations" / action_name / "001.png", (0, 255, 0, 255))
    action = TransferAction(
        name=action_name,
        definition={"path": f"animations/{action_name}", "fps": 10, "loop": True, "next": "idle"},
        asset_paths=(source / "animations" / action_name / "001.png",),
        scope="pet",
        source_root=source,
    )
    return ActionPack(
        name="shared",
        source_pet=SourcePetInfo("source", "Source", "1.0.0"),
        actions={action_name: action},
        bindings={"mouse.enter": action_name},
        fallbacks={action_name: ["idle"]},
        root=source,
    )


@pytest.mark.parametrize(
    ("decision", "expected_name"),
    [
        (ConflictDecision.replace(), "walk"),
        (ConflictDecision.rename("shared_walk"), "shared_walk"),
        (ConflictDecision.skip(), None),
    ],
)
def test_install_action_conflict_decisions(tmp_path: Path, decision: ConflictDecision, expected_name: str | None) -> None:
    target = tmp_path / "target"
    write_pet(target)
    result = install_actions(target, build_pack(tmp_path), decisions={"walk": decision}, import_bindings=True)

    config = json.loads((target / "pet.json").read_text(encoding="utf-8"))
    if expected_name is None:
        assert result.skipped == ("walk",)
        assert set(config["animations"]) == {"idle", "walk"}
    else:
        assert expected_name in config["animations"]
        assert (target / "animations" / expected_name / "001.png").is_file()
        assert result.installed == (expected_name,)
        assert config["bindings"]["mouse.enter"] == (expected_name if expected_name != "walk" else "walk")


def test_install_failure_restores_target(tmp_path: Path) -> None:
    target = tmp_path / "target"
    write_pet(target)
    before = {path.relative_to(target).as_posix(): path.read_bytes() for path in target.rglob("*") if path.is_file()}
    pack = build_pack(tmp_path)
    pack.actions["walk"].definition["fps"] = 0

    with pytest.raises(ValueError, match="校验"):
        install_actions(target, pack, decisions={"walk": ConflictDecision.replace()})

    after = {path.relative_to(target).as_posix(): path.read_bytes() for path in target.rglob("*") if path.is_file()}
    assert after == before
