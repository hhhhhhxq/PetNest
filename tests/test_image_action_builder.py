"""图片动作来源检查、自然排序和安全限制测试。"""

from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import subprocess

from PIL import Image
import pytest

from petnest.core.image_action_builder import (
    MAX_FRAME_COUNT,
    MAX_FRAME_EDGE,
    ImageActionSourceError,
    OversizedFrameConfirmationRequired,
    build_image_action_pack,
    inspect_image_files,
    inspect_image_folder,
)
from petnest.core.action_installer import ConflictDecision, install_actions
from petnest.core.action_slots import action_slot
from petnest.models.pet_package import AnimationDefinition, Canvas, PetPackage


def _image(path: Path, size: tuple[int, int] = (16, 12), mode: str = "RGBA") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    color: tuple[int, ...] = (255, 80, 40, 180) if mode == "RGBA" else (255, 80, 40)
    Image.new(mode, size, color).save(path)
    return path


def _package(
    root: Path,
    *,
    canvas: tuple[int, int] = (64, 48),
    bindings: dict[str, str] | None = None,
    animations: tuple[str, ...] = (),
) -> PetPackage:
    definitions = {
        name: AnimationDefinition(name, root, 8, True, None, 10, True)
        for name in animations
    }
    return PetPackage(
        root,
        "pet",
        "Pet",
        "1.0.0",
        Canvas(*canvas),
        definitions,
        bindings or {},
        {},
    )


def test_inspect_files_naturally_sorts_png_and_webp(tmp_path: Path) -> None:
    frames = [
        _image(tmp_path / "10.webp"),
        _image(tmp_path / "2.png"),
        _image(tmp_path / "1.png"),
    ]

    draft = inspect_image_files(frames)

    assert [frame.path.name for frame in draft.frames] == ["1.png", "2.png", "10.webp"]
    assert draft.source_label == "3 张图片"
    assert draft.frames[0].size == (16, 12)
    assert draft.frames[0].has_alpha is True


def test_folder_reads_only_supported_direct_images_and_ignores_metadata_files(tmp_path: Path) -> None:
    _image(tmp_path / "002.png")
    _image(tmp_path / "001.webp")
    (tmp_path / "Thumbs.db").write_bytes(b"metadata")

    draft = inspect_image_folder(tmp_path)

    assert [frame.path.name for frame in draft.frames] == ["001.webp", "002.png"]
    assert draft.source_label == tmp_path.name


def test_folder_rejects_nested_directories(tmp_path: Path) -> None:
    _image(tmp_path / "1.png")
    (tmp_path / "another-action").mkdir()

    with pytest.raises(ImageActionSourceError, match="具体动作文件夹"):
        inspect_image_folder(tmp_path)


@pytest.mark.parametrize("manifest", ["pet.json", "petnest-action-pack.json", "manifest.json"])
def test_folder_with_resource_manifest_points_to_resource_mode(tmp_path: Path, manifest: str) -> None:
    (tmp_path / manifest).write_text("{}", encoding="utf-8")
    _image(tmp_path / "1.png")

    with pytest.raises(ImageActionSourceError, match="从资源包提取动作"):
        inspect_image_folder(tmp_path)


def test_damaged_image_reports_the_specific_file(tmp_path: Path) -> None:
    damaged = tmp_path / "broken.png"
    damaged.write_bytes(b"not an image")

    with pytest.raises(ImageActionSourceError, match="broken.png"):
        inspect_image_files([damaged])


def test_duplicate_file_is_rejected(tmp_path: Path) -> None:
    frame = _image(tmp_path / "1.png")

    with pytest.raises(ImageActionSourceError, match="重复"):
        inspect_image_files([frame, frame])


def test_frame_count_limit_is_checked_before_decoding(tmp_path: Path) -> None:
    paths = [tmp_path / f"{index}.png" for index in range(MAX_FRAME_COUNT + 1)]

    with pytest.raises(ImageActionSourceError, match=str(MAX_FRAME_COUNT)):
        inspect_image_files(paths)


def test_empty_or_unsupported_source_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "readme.txt").write_text("none", encoding="utf-8")

    with pytest.raises(ImageActionSourceError, match="PNG 或 WebP"):
        inspect_image_folder(tmp_path)


def test_symlinked_frame_is_rejected_without_reading_target(tmp_path: Path) -> None:
    target = _image(tmp_path / "target.png")
    link = tmp_path / "link.png"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("当前平台不能创建文件符号链接")

    with pytest.raises(ImageActionSourceError, match="链接"):
        inspect_image_files([link])


def test_build_centers_small_frames_on_target_canvas_and_cleans_temporary_files(tmp_path: Path) -> None:
    draft = inspect_image_files([_image(tmp_path / "small.png", (16, 12))])
    materialized_root: Path | None = None

    with build_image_action_pack(
        _package(tmp_path / "pet"),
        action_slot("mouse_click"),
        draft,
        fps=12,
    ) as pack:
        action = pack.actions["click"]
        materialized_root = action.source_root
        with Image.open(action.asset_paths[0]) as frame:
            assert frame.mode == "RGBA"
            assert frame.size == (64, 48)
            assert frame.getpixel((0, 0))[3] == 0
            assert frame.getpixel((32, 24))[3] > 0
        assert action.definition["loop"] is False
        assert action.definition["next"] == "context"

    assert materialized_root is not None
    assert not materialized_root.exists()


def test_oversized_frame_requires_explicit_fit_and_then_scales_proportionally(tmp_path: Path) -> None:
    draft = inspect_image_files([_image(tmp_path / "large.png", (128, 48))])
    package = _package(tmp_path / "pet", canvas=(64, 48))

    with pytest.raises(OversizedFrameConfirmationRequired, match="large.png"):
        with build_image_action_pack(package, action_slot("mouse_click"), draft, fps=12):
            pass

    with build_image_action_pack(
        package,
        action_slot("mouse_click"),
        draft,
        fps=12,
        fit_oversized=True,
    ) as pack:
        with Image.open(pack.actions["click"].asset_paths[0]) as frame:
            assert frame.size == (64, 48)
            alpha = frame.getchannel("A").getbbox()
            assert alpha is not None
            assert alpha[2] - alpha[0] == 64
            assert alpha[3] - alpha[1] == 24


def test_missing_binding_is_included_but_existing_alias_is_preserved(tmp_path: Path) -> None:
    draft = inspect_image_files([_image(tmp_path / "done.png", (64, 48))])

    with build_image_action_pack(
        _package(tmp_path / "unbound"),
        action_slot("agent_success"),
        draft,
        fps=12,
    ) as pack:
        assert set(pack.actions) == {"review"}
        assert pack.bindings == {"agent.success": "review"}

    with build_image_action_pack(
        _package(
            tmp_path / "bound",
            bindings={"agent.success": "success"},
            animations=("success",),
        ),
        action_slot("agent_success"),
        draft,
        fps=12,
    ) as pack:
        assert set(pack.actions) == {"success"}
        assert pack.bindings == {}


def test_fullscreen_frames_use_one_maximum_canvas_and_slot_direction_defaults(tmp_path: Path) -> None:
    draft = inspect_image_files(
        [
            _image(tmp_path / "1.png", (80, 40)),
            _image(tmp_path / "2.png", (64, 60)),
        ]
    )

    with build_image_action_pack(
        _package(tmp_path / "pet"),
        action_slot("work_finish_lie_down"),
        draft,
        fps=10,
    ) as pack:
        action = pack.actions["work_finish_lie_down"]
        assert action.definition["scope"] == "fullscreen"
        assert action.definition["canvas"] == {"width": 80, "height": 60}
        assert action.definition["entrance_direction"] == "none"
        assert all(Image.open(path).size == (80, 60) for path in action.asset_paths)


def test_built_pack_installs_with_real_transaction_and_binding(tmp_path: Path) -> None:
    target = tmp_path / "target"
    _image(target / "animations" / "idle" / "001.png", (8, 8))
    (target / "pet.json").write_text(
        __import__("json").dumps(
            {
                "schema_version": 1,
                "id": "target",
                "name": "Target",
                "canvas": {"width": 8, "height": 8},
                "animations": {"idle": {"path": "animations/idle", "fps": 8, "loop": True}},
                "bindings": {},
            }
        ),
        encoding="utf-8",
    )
    draft = inspect_image_files([_image(tmp_path / "click.png", (8, 8))])

    with build_image_action_pack(
        _package(target, canvas=(8, 8)),
        action_slot("mouse_click"),
        draft,
        fps=12,
    ) as pack:
        result = install_actions(
            target,
            pack,
            decisions={"click": ConflictDecision.replace()},
            import_bindings=True,
        )

    config = __import__("json").loads((target / "pet.json").read_text(encoding="utf-8"))
    assert result.installed == ("click",)
    assert config["bindings"]["mouse.click"] == "click"
    assert (target / config["animations"]["click"]["path"] / "0001.png").is_file()


def test_build_rechecks_source_limits_after_initial_inspection(tmp_path: Path) -> None:
    source = _image(tmp_path / "changed.png", (16, 16))
    draft = inspect_image_files([source])
    _image(source, (MAX_FRAME_EDGE + 1, 1))

    with pytest.raises(ImageActionSourceError, match=str(MAX_FRAME_EDGE)):
        with build_image_action_pack(
            _package(tmp_path / "pet"),
            action_slot("mouse_click"),
            draft,
            fps=12,
            fit_oversized=True,
        ):
            pass


def test_fullscreen_output_canvas_budget_is_checked_before_rendering(tmp_path: Path) -> None:
    paths = [
        _image(tmp_path / f"{index:02d}.png", (MAX_FRAME_EDGE, 1) if index % 2 else (1, MAX_FRAME_EDGE))
        for index in range(10)
    ]
    draft = inspect_image_files(paths)

    with pytest.raises(ImageActionSourceError, match="输出画布"):
        with build_image_action_pack(
            _package(tmp_path / "pet"),
            action_slot("work_finish_walk"),
            draft,
            fps=12,
        ):
            pass


def test_image_install_target_rejects_linked_animation_tree(tmp_path: Path) -> None:
    target = tmp_path / "pet"
    external = tmp_path / "external"
    external.mkdir()
    target.mkdir()
    try:
        (target / "animations").symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("当前平台不能创建目录符号链接")
    draft = inspect_image_files([_image(tmp_path / "1.png", (16, 16))])

    with pytest.raises(ImageActionSourceError, match="链接"):
        with build_image_action_pack(
            _package(target),
            action_slot("mouse_click"),
            draft,
            fps=12,
        ):
            pass


def test_fullscreen_action_reuses_existing_companion_canvas_and_explicit_direction(tmp_path: Path) -> None:
    package = _package(tmp_path / "pet")
    companion = AnimationDefinition(
        "work_finish_lie_down",
        tmp_path,
        8,
        False,
        None,
        20,
        True,
        scope="fullscreen",
        canvas=Canvas(80, 60),
    )
    package = replace(package, animations={"work_finish_lie_down": companion})
    draft = inspect_image_files([_image(tmp_path / "walk.png", (40, 30))])

    with build_image_action_pack(
        package,
        action_slot("work_finish_walk"),
        draft,
        fps=12,
        entrance_direction="left",
    ) as pack:
        action = pack.actions["work_finish_walk"]
        assert action.definition["canvas"] == {"width": 80, "height": 60}
        assert action.definition["entrance_direction"] == "left"
        with Image.open(action.asset_paths[0]) as frame:
            assert frame.size == (80, 60)


def test_selected_image_beneath_junction_directory_is_rejected(tmp_path: Path) -> None:
    external = tmp_path / "external"
    source = _image(external / "1.png")
    linked = tmp_path / "linked"
    if os.name == "nt":
        completed = subprocess.run(
            ("cmd.exe", "/d", "/c", "mklink", "/J", str(linked), str(external)),
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            pytest.skip("当前平台不能创建目录 junction")
    else:
        try:
            linked.symlink_to(external, target_is_directory=True)
        except OSError:
            pytest.skip("当前平台不能创建目录符号链接")

    with pytest.raises(ImageActionSourceError, match="祖先"):
        inspect_image_files([linked / source.name])
