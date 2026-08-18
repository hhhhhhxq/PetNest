"""Tests for action conflict decisions and transactional installation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from petnest.core import action_installer as action_installer_module
from petnest.core.action_installer import (
    ActionInstallError,
    ConflictDecision,
    InstallResult,
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
        installed_path = target / config["animations"][expected_name]["path"]
        assert (installed_path / "001.png").is_file()
        assert result.installed == (expected_name,)
        assert config["bindings"]["mouse.enter"] == (expected_name if expected_name != "walk" else "walk")


def test_install_replaces_action_without_renaming_pet_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    write_pet(target)
    old_action = target / "animations" / "walk"
    original_rename = Path.rename

    def reject_root_rename(path: Path, destination: Path) -> Path:
        if path == target:
            raise AssertionError("动作安装不得改名宠物根目录")
        return original_rename(path, destination)

    monkeypatch.setattr(Path, "rename", reject_root_rename)

    result = install_actions(target, build_pack(tmp_path))
    config = json.loads((target / "pet.json").read_text(encoding="utf-8"))
    action_path = config["animations"]["walk"]["path"]

    assert action_path.startswith("animations/.revisions/walk-")
    assert (target / action_path / "001.png").is_file()
    assert old_action.is_dir()
    assert result.created_revision_dirs == (target / action_path,)


def test_install_result_rollback_restores_config_and_removes_new_revisions(tmp_path: Path) -> None:
    target = tmp_path / "target"
    write_pet(target)
    before = (target / "pet.json").read_bytes()

    result = install_actions(target, build_pack(tmp_path))
    created = result.created_revision_dirs
    warnings = result.rollback()

    assert warnings == ()
    assert (target / "pet.json").read_bytes() == before
    assert all(not path.exists() for path in created)
    assert (target / "animations" / "walk" / "001.png").is_file()


def test_rollback_refuses_to_overwrite_config_changed_after_install(tmp_path: Path) -> None:
    target = tmp_path / "target"
    write_pet(target)
    result = install_actions(target, build_pack(tmp_path))
    config_path = target / "pet.json"
    changed = json.loads(config_path.read_text(encoding="utf-8"))
    changed["description"] = "changed concurrently"
    config_path.write_text(json.dumps(changed), encoding="utf-8")

    with pytest.raises(ActionInstallError, match="安装后发生变化"):
        result.rollback()

    assert json.loads(config_path.read_text(encoding="utf-8"))["description"] == "changed concurrently"
    assert all(path.is_dir() for path in result.created_revision_dirs)


def test_install_result_finalize_removes_only_unreferenced_old_action(tmp_path: Path) -> None:
    target = tmp_path / "target"
    write_pet(target)

    result = install_actions(target, build_pack(tmp_path))
    warnings = result.finalize()

    assert warnings == ()
    assert not (target / "animations" / "walk").exists()
    assert (target / "animations" / "idle" / "001.png").is_file()
    assert all(path.is_dir() for path in result.created_revision_dirs)


def test_finalize_keeps_old_directory_still_referenced_by_another_action(tmp_path: Path) -> None:
    target = tmp_path / "target"
    write_pet(target)
    config_path = target / "pet.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["animations"]["idle"]["path"] = "animations/walk"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    result = install_actions(target, build_pack(tmp_path))
    warnings = result.finalize()

    assert warnings == ()
    assert (target / "animations" / "walk" / "001.png").is_file()


def test_finalize_keeps_old_directory_when_referenced_action_is_nested_inside(tmp_path: Path) -> None:
    target = tmp_path / "target"
    write_pet(target)
    nested = target / "animations" / "walk" / "shared_idle"
    write_png(nested / "001.png")
    config_path = target / "pet.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["animations"]["idle"]["path"] = "animations/walk/shared_idle"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    result = install_actions(target, build_pack(tmp_path))
    warnings = result.finalize()

    assert warnings == ()
    assert (nested / "001.png").is_file()


def test_finalize_refuses_to_delete_directory_outside_animations(tmp_path: Path) -> None:
    target = tmp_path / "target"
    write_pet(target)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep", encoding="utf-8")
    config_bytes = (target / "pet.json").read_bytes()
    result = InstallResult(target, (), (), {}, config_bytes, config_bytes, (), (outside,))

    warnings = result.finalize()

    assert warnings and "范围外" in warnings[0]
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_config_replace_failure_keeps_original_and_cleans_new_revisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    write_pet(target)
    before = (target / "pet.json").read_bytes()

    def fail_replace(_source: Path, _target: Path) -> None:
        raise PermissionError("config locked")

    monkeypatch.setattr(action_installer_module.os, "replace", fail_replace)

    with pytest.raises(ActionInstallError, match="原配置未改动"):
        install_actions(target, build_pack(tmp_path))

    assert (target / "pet.json").read_bytes() == before
    revisions = target / "animations" / ".revisions"
    assert not revisions.exists() or not any(revisions.iterdir())
    assert (target / "animations" / "walk" / "001.png").is_file()


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


def test_skipped_action_does_not_overwrite_bindings_or_fallbacks(tmp_path: Path) -> None:
    target = tmp_path / "target"
    write_pet(target)
    config_path = target / "pet.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["bindings"]["agent.working"] = "walk"
    config["fallbacks"] = {"walk": ["idle"]}
    config_path.write_text(json.dumps(config), encoding="utf-8")
    pack = build_pack(tmp_path, "idle")
    pack.bindings["agent.working"] = "idle"
    pack.fallbacks["idle"] = ["walk"]

    install_actions(
        target,
        pack,
        decisions={"idle": ConflictDecision.skip()},
        import_bindings=True,
    )

    updated = json.loads(config_path.read_text(encoding="utf-8"))
    assert updated["bindings"]["agent.working"] == "walk"
    assert updated["fallbacks"] == {"walk": ["idle"]}


def test_case_insensitive_action_collision_replaces_existing_name(tmp_path: Path) -> None:
    target = tmp_path / "target"
    write_pet(target)
    pack = build_pack(tmp_path, "IDLE")

    result = install_actions(target, pack)

    assert result.installed == ("idle",)
    config = json.loads((target / "pet.json").read_text(encoding="utf-8"))
    assert set(config["animations"]) == {"idle", "walk"}
    assert (target / config["animations"]["idle"]["path"] / "001.png").is_file()


def test_rejects_existing_action_path_outside_animations(tmp_path: Path) -> None:
    target = tmp_path / "target"
    write_pet(target)
    config_path = target / "pet.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["animations"]["walk"]["path"] = "../outside"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(ActionInstallError, match="必须位于 animations"):
        install_actions(target, build_pack(tmp_path))


def test_rejects_windows_ambiguous_renamed_action(tmp_path: Path) -> None:
    target = tmp_path / "target"
    write_pet(target)
    pack = build_pack(tmp_path, "dance")

    with pytest.raises(ActionInstallError, match="动作名称不安全"):
        install_actions(target, pack, decisions={"dance": ConflictDecision.rename("foo.")})
