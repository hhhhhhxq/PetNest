"""Codex 标准精灵图到 PetNest PNG 序列帧的导入回归测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from petnest.core.package_loader import PackageLoader
from petnest.core.spritesheet_importer import (
    CODEX_STANDARD_LAYOUT,
    SpriteSheetImportError,
    SpriteSheetImporter,
)


def _spritesheet(path: Path) -> Path:
    """创建每一格都有可识别像素的最小标准 RGBA 图集。"""
    image = Image.new("RGBA", CODEX_STANDARD_LAYOUT.image_size, (0, 0, 0, 0))
    for row in range(CODEX_STANDARD_LAYOUT.rows):
        for column in range(CODEX_STANDARD_LAYOUT.columns):
            image.putpixel(
                (column * CODEX_STANDARD_LAYOUT.cell_width, row * CODEX_STANDARD_LAYOUT.cell_height),
                (row * 20, column * 20, 100, 255),
            )
    image.save(path)
    return path


def _sparse_spritesheet(path: Path) -> Path:
    """创建 idle 行第 1、2、3、5、6、7 格有内容的图集。"""
    image = Image.new("RGBA", CODEX_STANDARD_LAYOUT.image_size, (0, 0, 0, 0))
    for column in (0, 1, 2, 4, 5, 6):
        image.putpixel((column * CODEX_STANDARD_LAYOUT.cell_width, 0), (column * 20, 100, 50, 255))
    image.save(path)
    return path


def test_importer_splits_all_rows_and_generates_a_valid_configured_package(tmp_path: Path) -> None:
    source = _spritesheet(tmp_path / "codex-cat.png")

    result = SpriteSheetImporter().import_file(source, tmp_path / "pets", "codex_cat")

    package = PackageLoader().load(result.package_root)
    assert result.package_id == "codex_cat"
    assert package.canvas.width == 192
    assert package.canvas.height == 208
    assert len(package.animations["idle"].frames) == 8
    assert len(package.animations["working"].frames) == 8
    assert package.bindings["agent.success"] == "success"
    assert package.bindings["system.bored"] == "bored"
    assert package.fallbacks["success"] == ("idle",)
    assert package.fallbacks["sleep"] == ("idle",)
    assert (result.package_root / "animations" / "codex_running_left" / "008.png").is_file()


def test_importer_rejects_a_nonstandard_or_nontransparent_image(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.png"
    Image.new("RGB", (100, 100), "white").save(invalid)

    with pytest.raises(SpriteSheetImportError, match="1536 × 1872"):
        SpriteSheetImporter().inspect(invalid)


def test_importer_does_not_overwrite_an_existing_pet_id(tmp_path: Path) -> None:
    source = _spritesheet(tmp_path / "cat.png")
    importer = SpriteSheetImporter()
    importer.import_file(source, tmp_path / "pets", "cat")

    with pytest.raises(SpriteSheetImportError, match="已存在"):
        importer.import_file(source, tmp_path / "pets", "cat")


def test_auto_mode_skips_empty_cells_and_preserves_left_to_right_order(tmp_path: Path) -> None:
    result = SpriteSheetImporter().import_file(_sparse_spritesheet(tmp_path / "sparse.png"), tmp_path / "pets", "sparse")

    package = PackageLoader().load(result.package_root)
    assert len(package.animations["idle"].frames) == 6
    assert package.animations["idle"].frame_durations_ms == (280, 110, 110, 140, 320, 125)
    with Image.open(package.animations["idle"].frames[3]) as frame:
        assert frame.getpixel((0, 0)) == (80, 100, 50, 255)


def test_manual_mode_keeps_exactly_the_chosen_grid_cells(tmp_path: Path) -> None:
    source = _sparse_spritesheet(tmp_path / "sparse.png")
    result = SpriteSheetImporter().import_file(
        source, tmp_path / "pets", "manual", selected_columns_by_action={"idle": (0, 3, 6)}
    )

    package = PackageLoader().load(result.package_root)
    assert len(package.animations["idle"].frames) == 3
    assert package.animations["idle"].frame_durations_ms == (280, 140, 125)
    with Image.open(package.animations["idle"].frames[1]) as frame:
        assert frame.getbbox() is None
