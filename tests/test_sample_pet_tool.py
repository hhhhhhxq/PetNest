"""程序化样例宠物必须能被正式校验器接受。"""

from __future__ import annotations

from pathlib import Path

from petnest.core.package_validator import PackageValidator
from tools.create_sample_pet import create_sample_pet


def test_generated_sample_pet_has_all_documented_actions_and_is_valid(tmp_path: Path) -> None:
    root = create_sample_pet(tmp_path / "sample_pet")

    result = PackageValidator().validate(root)

    assert result.is_valid, result.errors
    assert {"idle", "hover", "click", "drag", "drop", "working", "waiting", "success", "error"} <= set(result.frames)
    assert all(frames for frames in result.frames.values())
