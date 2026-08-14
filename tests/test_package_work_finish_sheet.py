"""下班动画原始图集切帧工具测试。"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image
import pytest

from tools.package_work_finish_sheet import WorkFinishSheetError, _keep_largest_alpha_component, package_sheet


def _sheet(path: Path, size: tuple[int, int] = (2172, 724)) -> Path:
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    if size == (2172, 724):
        for row in range(3):
            for column in range(7):
                colour = (column * 20, row * 60, 120, 255)
                image.paste(
                    colour,
                    (
                        round(column * size[0] / 7),
                        round(row * size[1] / 3),
                        round((column + 1) * size[0] / 7),
                        round((row + 1) * size[1] / 3),
                    ),
                )
    image.save(path)
    return path


def test_package_sheet_exports_expected_phases_and_manifest(tmp_path: Path) -> None:
    output = tmp_path / "work-finish"

    package_sheet(_sheet(tmp_path / "source.png"), output)

    walk = sorted((output / "walk").glob("*.png"))
    lie_down = sorted((output / "lie-down").glob("*.png"))
    assert len(walk) == 7
    assert len(lie_down) == 14
    with Image.open(walk[6]) as frame:
        assert frame.mode == "RGBA"
        assert frame.size == (312, 242)
        assert frame.getpixel((10, 10)) == (120, 0, 120, 255)
    with Image.open(lie_down[7]) as frame:
        assert frame.getpixel((10, 10)) == (0, 120, 120, 255)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest == {
        "name": "平安下班",
        "canvas": {"width": 312, "height": 242},
        "walk": {"path": "walk", "fps": 10},
        "lie_down": {"path": "lie-down", "fps": 7},
    }
    with Image.open(output / "preview.png") as preview:
        assert preview.mode == "RGBA"
        assert preview.size == (1248, 1452)


def test_package_sheet_rejects_unexpected_dimensions_without_partial_output(tmp_path: Path) -> None:
    output = tmp_path / "work-finish"

    with pytest.raises(WorkFinishSheetError, match="2172×724"):
        package_sheet(_sheet(tmp_path / "wrong.png", (512, 512)), output)

    assert not output.exists()


def test_package_sheet_does_not_overwrite_a_nonempty_folder(tmp_path: Path) -> None:
    output = tmp_path / "work-finish"
    output.mkdir()
    marker = output / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(WorkFinishSheetError, match="非空"):
        package_sheet(_sheet(tmp_path / "source.png"), output)

    assert marker.read_text(encoding="utf-8") == "keep"


def test_detached_transparent_artifacts_are_removed_without_harming_subject() -> None:
    frame = Image.new("RGBA", (20, 20), (255, 0, 0, 0))
    frame.paste((255, 150, 0, 255), (5, 5, 15, 15))
    frame.putpixel((1, 1), (255, 255, 0, 255))

    cleaned = _keep_largest_alpha_component(frame)

    assert cleaned.getpixel((1, 1))[3] == 0
    assert cleaned.getpixel((10, 10)) == (255, 150, 0, 255)
