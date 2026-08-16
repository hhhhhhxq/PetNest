"""Tests for complete pet package import and update."""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest
from PIL import Image

from petnest.core.pet_package_importer import (
    PetImportOptions,
    PetPackageImportError,
    import_pet_package,
)


def write_png(path: Path, color: tuple[int, int, int, int] = (255, 128, 0, 255)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (8, 8), color).save(path)


def write_pet(root: Path, identifier: str = "pingan", actions: tuple[str, ...] = ("idle", "walk")) -> None:
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
                "id": identifier,
                "name": identifier,
                "version": "1.0.0",
                "canvas": {"width": 8, "height": 8},
                "animations": definitions,
                "bindings": {"mouse.enter": "walk"} if "walk" in actions else {},
            }
        ),
        encoding="utf-8",
    )


def test_import_new_pet_installs_validated_package(tmp_path: Path) -> None:
    source = tmp_path / "source"
    write_pet(source)
    pets_root = tmp_path / "pets"

    result = import_pet_package(source, pets_root)

    assert result.pet_id == "pingan"
    assert (pets_root / "pingan" / "pet.json").is_file()
    assert result.backup_path is None


def test_update_creates_backup_and_replaces_full_package(tmp_path: Path) -> None:
    source = tmp_path / "source"
    write_pet(source, actions=("idle", "walk"))
    pets_root = tmp_path / "pets"
    existing = pets_root / "pingan"
    write_pet(existing, actions=("idle", "walk", "local_dance"))
    (existing / "local-note.txt").write_text("old", encoding="utf-8")

    result = import_pet_package(source, pets_root)

    assert result.backup_path is not None and result.backup_path.is_file()
    assert not (existing / "animations" / "local_dance").exists()
    assert not (existing / "local-note.txt").exists()
    with ZipFile(result.backup_path) as archive:
        assert "pet.json" in archive.namelist()
        assert "animations/local_dance/001.png" in archive.namelist()


def test_update_can_preserve_local_only_actions(tmp_path: Path) -> None:
    source = tmp_path / "source"
    write_pet(source, actions=("idle", "walk"))
    pets_root = tmp_path / "pets"
    existing = pets_root / "pingan"
    write_pet(existing, actions=("idle", "walk", "local_dance"))

    import_pet_package(source, pets_root, PetImportOptions(preserve_local_actions=True))

    manifest = json.loads((existing / "pet.json").read_text(encoding="utf-8"))
    assert "local_dance" in manifest["animations"]
    assert (existing / "animations" / "local_dance" / "001.png").is_file()


def test_invalid_source_does_not_change_existing_pet(tmp_path: Path) -> None:
    source = tmp_path / "source"
    write_pet(source)
    source_config = json.loads((source / "pet.json").read_text(encoding="utf-8"))
    source_config["animations"]["idle"]["fps"] = 0
    (source / "pet.json").write_text(json.dumps(source_config), encoding="utf-8")
    pets_root = tmp_path / "pets"
    existing = pets_root / "pingan"
    write_pet(existing)
    before = {path.relative_to(existing).as_posix(): path.read_bytes() for path in existing.rglob("*") if path.is_file()}

    with pytest.raises(PetPackageImportError, match="校验"):
        import_pet_package(source, pets_root)

    after = {path.relative_to(existing).as_posix(): path.read_bytes() for path in existing.rglob("*") if path.is_file()}
    assert after == before


def test_backup_failure_does_not_start_update(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source"
    write_pet(source)
    pets_root = tmp_path / "pets"
    existing = pets_root / "pingan"
    write_pet(existing)

    monkeypatch.setattr("petnest.core.pet_package_importer._create_backup", lambda *_: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(PetPackageImportError, match="备份"):
        import_pet_package(source, pets_root)
    assert (existing / "pet.json").is_file()


def test_rejects_symlink_pet_destination(tmp_path: Path) -> None:
    source = tmp_path / "source"
    write_pet(source)
    pets_root = tmp_path / "pets"
    pets_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (pets_root / "pingan").symlink_to(outside, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"当前平台不允许创建目录符号链接：{error}")

    with pytest.raises(PetPackageImportError, match="符号链接"):
        import_pet_package(source, pets_root)
    assert not (outside / "pet.json").exists()


def test_rejects_unsafe_local_action_name_when_preserving(tmp_path: Path) -> None:
    source = tmp_path / "source"
    write_pet(source)
    pets_root = tmp_path / "pets"
    existing = pets_root / "pingan"
    write_pet(existing)
    config_path = existing / "pet.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["animations"]["../escape"] = {"path": "animations/idle", "fps": 8, "loop": True}
    config_path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(PetPackageImportError, match="动作名称"):
        import_pet_package(source, pets_root, PetImportOptions(preserve_local_actions=True))
