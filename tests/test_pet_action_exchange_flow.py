"""End-to-end exchange center workflows."""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from petnest.core.action_installer import ConflictDecision, install_actions
from petnest.core.action_pack import export_action_pack, load_action_pack
from petnest.core.package_loader import PackageLoader
from petnest.core.pet_package_importer import PetImportOptions, import_pet_package
from tests.test_package_validator import _write_package


def zip_folder(root: Path, archive_path: Path) -> Path:
    with ZipFile(archive_path, "w") as archive:
        for path in root.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(root).as_posix())
    return archive_path


def test_export_import_and_reload_flow(tmp_path: Path) -> None:
    source_root = _write_package(tmp_path / "source")
    target_root = _write_package(tmp_path / "target")
    archive = export_action_pack(source_root, ["idle"], tmp_path / "share.zip")

    with load_action_pack(archive) as pack:
        result = install_actions(
            target_root,
            pack,
            decisions={"idle": ConflictDecision.rename("shared_idle")},
        )

    loaded = PackageLoader().load(target_root)
    assert result.renamed == {"idle": "shared_idle"}
    assert "shared_idle" in loaded.animations


def test_complete_pet_zip_update_can_be_reimported_from_backup(tmp_path: Path) -> None:
    source = _write_package(tmp_path / "source")
    pets_root = tmp_path / "pets"
    existing = _write_package(pets_root / "test_pet")

    result = import_pet_package(zip_folder(source, tmp_path / "pet.zip"), pets_root)

    assert result.replaced_existing is True
    assert result.backup_path is not None
    restored = import_pet_package(result.backup_path, pets_root, PetImportOptions(create_backup=False))
    assert restored.pet_id == "test_pet"
    assert PackageLoader().load(existing).identifier == "test_pet"
