"""下班动画 ZIP/文件夹导入与安全边界。"""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from petnest.core.package_validator import PackageValidator
from petnest.core.work_finish_importer import WorkFinishImportError, WorkFinishImporter
from tests.test_package_validator import _write_package, _write_png


def _bundle(root: Path) -> Path:
    root.mkdir(parents=True)
    manifest = {
        "name": "平安下班",
        "canvas": {"width": 24, "height": 18},
        "walk": {"path": "walk", "fps": 10},
        "lie_down": {"path": "lie-down", "fps": 8, "frame_durations_ms": [100, 200]},
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for index in range(1, 4):
        _write_png(root / "walk" / f"{index:03d}.png", 24, 18)
    for index in range(1, 3):
        _write_png(root / "lie-down" / f"{index:03d}.png", 24, 18)
    return root


def _zip_folder(folder: Path, target: Path) -> Path:
    with ZipFile(target, "w") as archive:
        for path in folder.rglob("*"):
            if path.is_file():
                archive.write(path, Path("work-finish") / path.relative_to(folder))
    return target


@pytest.mark.parametrize("source_kind", ["folder", "zip"])
def test_import_installs_two_scoped_actions_atomically(tmp_path: Path, source_kind: str) -> None:
    pet = _write_package(tmp_path / "pet")
    folder = _bundle(tmp_path / "bundle")
    source = folder if source_kind == "folder" else _zip_folder(folder, tmp_path / "bundle.zip")

    result = WorkFinishImporter().install(source, pet)
    config = json.loads((pet / "pet.json").read_text(encoding="utf-8"))

    assert result.name == "平安下班"
    assert (result.walk_frames, result.lie_down_frames) == (3, 2)
    assert config["animations"]["work_finish_walk"]["scope"] == "fullscreen"
    assert config["animations"]["work_finish_lie_down"]["frame_durations_ms"] == [100, 200]
    assert PackageValidator().validate(pet).is_valid


def test_inspect_returns_summary_without_installing(tmp_path: Path) -> None:
    pet = _write_package(tmp_path / "pet")
    source = _bundle(tmp_path / "bundle")

    summary = WorkFinishImporter().inspect(source)

    assert summary.name == "平安下班"
    assert summary.canvas == (24, 18)
    assert (summary.walk_frames, summary.lie_down_frames) == (3, 2)
    assert not (pet / "animations" / "work_finish_walk").exists()


def test_zip_path_traversal_is_rejected_without_changing_pet(tmp_path: Path) -> None:
    pet = _write_package(tmp_path / "pet")
    before = (pet / "pet.json").read_bytes()
    source = tmp_path / "bad.zip"
    with ZipFile(source, "w") as archive:
        archive.writestr("../escape.png", b"bad")
        archive.writestr("manifest.json", "{}")

    with pytest.raises(WorkFinishImportError, match="路径"):
        WorkFinishImporter().install(source, pet)

    assert (pet / "pet.json").read_bytes() == before
    assert not (tmp_path / "escape.png").exists()


def test_invalid_bundle_keeps_existing_actions_and_config_bytes(tmp_path: Path) -> None:
    pet = _write_package(tmp_path / "pet")
    existing = pet / "animations" / "work_finish_walk"
    _write_png(existing / "001.png")
    before = (pet / "pet.json").read_bytes()
    existing_bytes = (existing / "001.png").read_bytes()
    source = _bundle(tmp_path / "bundle")
    (source / "walk" / "001.png").write_bytes(b"not-png")

    with pytest.raises(WorkFinishImportError, match="PNG"):
        WorkFinishImporter().install(source, pet)

    assert (pet / "pet.json").read_bytes() == before
    assert (existing / "001.png").read_bytes() == existing_bytes
