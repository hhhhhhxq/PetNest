"""用户可写宠物库的首次初始化测试。"""

from pathlib import Path

from petnest.core.pet_library import prepare_pet_library
from tools.create_sample_pet import create_sample_pet


def test_bootstrap_copies_bundled_pet_when_target_library_is_empty(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    create_sample_pet(bundled / "sample_pet")
    target = tmp_path / "user-pets"

    active = prepare_pet_library(target, bundled)

    assert active == target
    assert (target / "sample_pet" / "pet.json").exists()


def test_bootstrap_does_not_overwrite_an_existing_user_library(tmp_path: Path) -> None:
    bundled = tmp_path / "bundled"
    create_sample_pet(bundled / "sample_pet")
    target = tmp_path / "user-pets"
    create_sample_pet(target / "my_pet")

    prepare_pet_library(target, bundled)

    assert (target / "my_pet" / "pet.json").exists()
    assert not (target / "sample_pet").exists()
