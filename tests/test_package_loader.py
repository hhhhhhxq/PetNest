"""宠物包加载器的行为测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from petnest.core.package_loader import PackageLoader
from petnest.core.package_validator import PackageValidationError
from tests.test_package_validator import _write_package, _write_png


def test_loader_builds_typed_package_with_resolved_frames(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "loaded")

    package = PackageLoader().load(root)

    assert package.identifier == "test_pet"
    assert package.canvas.width == 16
    assert package.animations["idle"].fps == 8
    assert [frame.name for frame in package.animations["idle"].frames] == ["2.png", "10.png"]
    assert all(frame.is_relative_to(package.root) for frame in package.animations["idle"].frames)


def test_loader_rejects_invalid_package(tmp_path: Path) -> None:
    root = _write_package(tmp_path / "broken", animations={})

    with pytest.raises(PackageValidationError, match="idle"):
        PackageLoader().load(root)


def test_discover_returns_only_valid_packages(tmp_path: Path) -> None:
    root = tmp_path / "pets"
    _write_package(root / "valid")
    _write_package(root / "invalid", animations={})
    (root / "not-a-package").mkdir()

    packages = PackageLoader().discover(root)

    assert [package.identifier for package in packages] == ["test_pet"]


def test_loader_rejects_malformed_json(tmp_path: Path) -> None:
    root = tmp_path / "malformed"
    root.mkdir()
    (root / "pet.json").write_text("{not-json", encoding="utf-8")

    with pytest.raises(PackageValidationError, match="JSON"):
        PackageLoader().load(root)


def test_loader_preserves_fullscreen_scope_and_action_canvas(tmp_path: Path) -> None:
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

    package = PackageLoader().load(root)
    definition = package.animations["work_finish_walk"]

    assert definition.scope == "fullscreen"
    assert definition.canvas is not None
    assert (definition.canvas.width, definition.canvas.height) == (24, 18)
