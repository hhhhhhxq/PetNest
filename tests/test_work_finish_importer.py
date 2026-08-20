"""下班动画 ZIP/文件夹导入与安全边界。"""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from petnest.core.package_validator import PackageValidator
from petnest.core.work_finish_importer import WorkFinishImportError, WorkFinishImporter
from tests.test_package_validator import _write_package, _write_png


def _bundle(root: Path, *, include_loop: bool = False) -> Path:
    root.mkdir(parents=True)
    manifest = {
        "name": "平安下班",
        "canvas": {"width": 24, "height": 18},
        "walk": {"path": "walk", "fps": 10},
        "lie_down": {"path": "lie-down", "fps": 8, "frame_durations_ms": [100, 200]},
    }
    if include_loop:
        manifest["lie_loop"] = {
            "path": "lie-loop",
            "fps": 6,
            "frame_durations_ms": [120, 180, 240],
        }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for index in range(1, 4):
        _write_png(root / "walk" / f"{index:03d}.png", 24, 18)
    for index in range(1, 3):
        _write_png(root / "lie-down" / f"{index:03d}.png", 24, 18)
    if include_loop:
        for index in range(1, 4):
            _write_png(root / "lie-loop" / f"{index:03d}.png", 24, 18)
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
    assert (result.walk_frames, result.lie_down_frames, result.lie_loop_frames) == (3, 2, 0)
    assert config["animations"]["work_finish_walk"]["scope"] == "fullscreen"
    assert config["animations"]["work_finish_lie_down"]["frame_durations_ms"] == [100, 200]
    assert PackageValidator().validate(pet).is_valid


def test_import_installs_optional_lie_loop_as_fullscreen_loop(tmp_path: Path) -> None:
    pet = _write_package(tmp_path / "pet")
    source = _bundle(tmp_path / "bundle", include_loop=True)

    result = WorkFinishImporter().install(source, pet)
    config = json.loads((pet / "pet.json").read_text(encoding="utf-8"))

    assert result.lie_loop_frames == 3
    loop = config["animations"]["work_finish_lie_loop"]
    assert loop["scope"] == "fullscreen"
    assert loop["loop"] is True
    assert loop["frame_durations_ms"] == [120, 180, 240]
    assert PackageValidator().validate(pet).is_valid


def test_installing_legacy_pair_removes_a_previous_lie_loop(tmp_path: Path) -> None:
    pet = _write_package(tmp_path / "pet")
    importer = WorkFinishImporter()
    importer.install(_bundle(tmp_path / "with-loop", include_loop=True), pet)
    before = json.loads((pet / "pet.json").read_text(encoding="utf-8"))
    old_loop_path = pet / before["animations"]["work_finish_lie_loop"]["path"]
    assert old_loop_path.is_dir()

    result = importer.install(_bundle(tmp_path / "without-loop"), pet)
    after = json.loads((pet / "pet.json").read_text(encoding="utf-8"))

    assert result.lie_loop_frames == 0
    assert "work_finish_lie_loop" not in after["animations"]
    assert not old_loop_path.exists()


def test_inspect_returns_summary_without_installing(tmp_path: Path) -> None:
    pet = _write_package(tmp_path / "pet")
    source = _bundle(tmp_path / "bundle")

    summary = WorkFinishImporter().inspect(source)

    assert summary.name == "平安下班"
    assert summary.canvas == (24, 18)
    assert (summary.walk_frames, summary.lie_down_frames, summary.lie_loop_frames) == (3, 2, 0)
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


def test_present_but_empty_lie_loop_is_rejected_instead_of_treated_as_missing(tmp_path: Path) -> None:
    source = _bundle(tmp_path / "bundle")
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["lie_loop"] = {"path": "lie-loop", "fps": 8}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (source / "lie-loop").mkdir()

    with pytest.raises(WorkFinishImportError, match="lie_loop.*PNG"):
        WorkFinishImporter().inspect(source)
