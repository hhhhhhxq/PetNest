"""Codex 标准精灵图到 PetNest PNG 序列帧的导入回归测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from petnest.core.package_loader import PackageLoader
from petnest.core.spritesheet_importer import (
    CODEX_STANDARD_LAYOUT,
    CODEX_V2_LAYOUT,
    SpriteSheetImportError,
    SpriteSheetImporter,
    SpriteSheetLayout,
)


def _spritesheet(path: Path, layout: SpriteSheetLayout = CODEX_STANDARD_LAYOUT) -> Path:
    """创建每一格都有可识别像素的最小标准 RGBA 图集。"""
    image = Image.new("RGBA", layout.image_size, (0, 0, 0, 0))
    for row in range(layout.rows):
        for column in range(layout.columns):
            image.putpixel(
                (column * layout.cell_width, row * layout.cell_height),
                (row * 20, column * 20, 100, 255),
            )
    if path.suffix.lower() == ".webp":
        image.save(path, format="WEBP", lossless=True)
    else:
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
    assert len(package.animations) == 9
    assert package.canvas.width == 192
    assert package.canvas.height == 208
    assert len(package.animations["idle"].frames) == 8
    assert len(package.animations["working"].frames) == 8
    assert package.bindings["agent.success"] == "review"
    assert package.bindings["mouse.enter"] == "hover"
    assert package.bindings["mouse.drag_start"] == "drag"
    assert "mouse.drag_end" not in package.bindings
    assert "drop" not in package.animations
    assert "drag" not in package.animations
    assert "codex_running_left" not in package.animations
    assert len(package.animations["drag_right"].frames) == 8
    assert len(package.animations["drag_left"].frames) == 8
    assert len(package.animations["hover"].frames) == 8
    assert len(package.animations["review"].frames) == 8
    assert package.bindings["system.bored"] == "bored"
    assert package.fallbacks["review"] == ("idle",)
    assert package.fallbacks["drag"] == ("drag_right", "drag_left", "idle")
    assert package.fallbacks["sleep"] == ("idle",)
    assert (result.package_root / "animations" / "drag_right" / "008.png").is_file()
    assert (result.package_root / "animations" / "drag_left" / "008.png").is_file()


def test_importer_accepts_a_static_webp_spritesheet(tmp_path: Path) -> None:
    source = _spritesheet(tmp_path / "codex-cat.webp")

    result = SpriteSheetImporter().import_file(source, tmp_path / "pets", "webp_cat")

    package = PackageLoader().load(result.package_root)
    assert result.inspection.source == source.resolve()
    assert len(package.animations["idle"].frames) == 8
    assert all(frame.suffix == ".png" for frame in package.animations["idle"].frames)


@pytest.mark.parametrize("suffix", [".png", ".webp"])
def test_importer_accepts_v2_and_preserves_look_rows(tmp_path: Path, suffix: str) -> None:
    source = _spritesheet(tmp_path / f"codex-v2{suffix}", CODEX_V2_LAYOUT)

    result = SpriteSheetImporter().import_file(source, tmp_path / "pets", "webp_v2")

    package = PackageLoader().load(result.package_root)
    config = json.loads((result.package_root / "pet.json").read_text(encoding="utf-8"))
    assert result.inspection.layout == CODEX_V2_LAYOUT
    assert len(package.animations) == 10
    assert "look_directions_a" not in package.animations
    assert "look_directions_b" not in package.animations
    assert len(package.animations["look_directions"].frames) == 16
    assert not package.animations["look_directions"].loop
    assert package.animations["look_directions"].next_animation == "context"
    assert (result.package_root / "animations" / "look_directions" / "016.png").is_file()
    assert {"drag_right", "drag_left"} <= set(package.animations)
    assert "codex_running_left" not in package.animations
    assert config["import_metadata"]["source_format"] == "codex_8x11"


def test_v2_manual_look_rows_merge_in_clockwise_source_order(tmp_path: Path) -> None:
    source = _spritesheet(tmp_path / "codex-v2.png", CODEX_V2_LAYOUT)

    result = SpriteSheetImporter().import_file(
        source,
        tmp_path / "pets",
        "manual_v2",
        selected_columns_by_action={
            "idle": (0,),
            "look_directions_a": (0, 4),
            "look_directions_b": (0, 4),
        },
    )

    package = PackageLoader().load(result.package_root)
    look = package.animations["look_directions"]
    assert len(look.frames) == 4
    with Image.open(look.frames[0]) as first, Image.open(look.frames[2]) as third:
        assert first.getpixel((0, 0)) == (180, 0, 100, 255)
        assert third.getpixel((0, 0)) == (200, 0, 100, 255)


def test_importer_rejects_an_animated_webp_spritesheet(tmp_path: Path) -> None:
    source = tmp_path / "animated.webp"
    frames = [
        Image.new("RGBA", (16, 16), (255, 0, 0, 255)),
        Image.new("RGBA", (16, 16), (0, 0, 255, 255)),
    ]
    frames[0].save(
        source,
        format="WEBP",
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
        lossless=True,
    )

    with pytest.raises(SpriteSheetImportError, match="动画 WebP"):
        SpriteSheetImporter().inspect(source)


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
