"""用图片制作动作内容组件的选择、排序、预览和草稿生命周期测试。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt

from petnest.core.action_slots import action_slots
from petnest.models.pet_package import Canvas
from petnest.ui.image_action_import_content import ImageActionImportContent
from petnest.ui import image_action_import_content as image_content_module
from tests.test_pet_window import _package


def _image(path: Path, size: tuple[int, int] = (10, 8)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", size, (50, 120, 240, 180)).save(path)
    return path


def _pet_package(root: Path, identifier: str = "cat"):
    root.mkdir(parents=True, exist_ok=True)
    return _package(root, identifier=identifier)


def _slot_keys(content: ImageActionImportContent) -> list[str]:
    return [
        str(content.slot_combo.itemData(index))
        for index in range(content.slot_combo.count())
        if isinstance(content.slot_combo.itemData(index), str)
    ]


def test_content_defaults_to_current_pet_and_lists_only_registered_slots(qtbot, tmp_path: Path) -> None:
    first = _pet_package(tmp_path / "first", identifier="first")
    second = _pet_package(tmp_path / "second", identifier="second")

    content = ImageActionImportContent((first, second), current_pet_id="second")
    qtbot.addWidget(content)

    assert content.target_combo.currentData() == "second"
    assert set(_slot_keys(content)) == {slot.key for slot in action_slots()}
    assert all("自定义" not in content.slot_combo.itemText(index) for index in range(content.slot_combo.count()))


def test_loading_and_moving_frames_updates_order_and_preview(qtbot, tmp_path: Path) -> None:
    content = ImageActionImportContent((_pet_package(tmp_path / "pet"),), current_pet_id="cat")
    qtbot.addWidget(content)
    images = [
        _image(tmp_path / "10.png"),
        _image(tmp_path / "2.png"),
        _image(tmp_path / "1.png"),
    ]

    content.load_files(images)
    assert [path.name for path in content.ordered_paths()] == ["1.png", "2.png", "10.png"]
    assert content.frame_list.count() == 3
    assert content.preview.frame_count == 3

    content.move_frame(2, 0)

    assert [path.name for path in content.ordered_paths()] == ["10.png", "1.png", "2.png"]
    assert content.frame_list.item(0).data(Qt.ItemDataRole.UserRole).name == "10.png"


def test_adding_more_images_preserves_current_order_and_appends_new_frames(qtbot, tmp_path: Path) -> None:
    content = ImageActionImportContent((_pet_package(tmp_path / "pet"),), current_pet_id="cat")
    qtbot.addWidget(content)
    first = _image(tmp_path / "1.png")
    second = _image(tmp_path / "2.png")
    content.load_files([first])

    content.add_files([second])

    assert content.ordered_paths() == (first.resolve(), second.resolve())


def test_existing_bound_action_uses_replace_label_and_current_preview(qtbot, tmp_path: Path) -> None:
    package = _pet_package(tmp_path / "pet")
    content = ImageActionImportContent((package,), current_pet_id=package.identifier)
    qtbot.addWidget(content)
    content.select_slot("mouse_click")
    content.load_files([_image(tmp_path / "new-click.png")])

    assert content.action_name() == "click"
    assert content.primary_text() == "替换动作"
    assert content.current_preview.frame_count == len(package.animations["click"].frames)


def test_current_binding_alias_is_the_actual_replacement_target(qtbot, tmp_path: Path) -> None:
    package = _pet_package(tmp_path / "pet")
    animations = dict(package.animations)
    animations["success"] = replace(animations["click"], name="success")
    package = replace(
        package,
        animations=animations,
        bindings={**package.bindings, "agent.success": "success"},
    )
    content = ImageActionImportContent((package,), current_pet_id=package.identifier)
    qtbot.addWidget(content)

    content.select_slot("agent_success")

    assert content.action_name() == "success"
    assert content.primary_text() == "替换动作"


def test_oversized_frame_requires_visible_fit_confirmation(qtbot, tmp_path: Path) -> None:
    package = _pet_package(tmp_path / "pet")
    content = ImageActionImportContent((package,), current_pet_id=package.identifier)
    qtbot.addWidget(content)
    content.select_slot("mouse_click")
    content.load_files([_image(tmp_path / "large.png", (40, 16))])

    assert not content.fit_oversized_checkbox.isHidden()
    assert content.can_install() is False

    content.fit_oversized_checkbox.setChecked(True)

    assert content.can_install() is True
    with content.build_pack() as pack:
        assert pack.actions["click"].asset_paths[0].is_file()


def test_success_clears_image_draft_but_failure_state_keeps_it(qtbot, tmp_path: Path) -> None:
    content = ImageActionImportContent((_pet_package(tmp_path / "pet"),), current_pet_id="cat")
    qtbot.addWidget(content)
    frame = _image(tmp_path / "1.png")
    content.load_files([frame])

    content.finish_failure("安装失败")
    assert content.ordered_paths() == (frame.resolve(),)
    assert "安装失败" in content.status_label.text()

    content.clear_after_success("动作已安装")
    assert content.ordered_paths() == ()
    assert content.frame_list.count() == 0
    assert content.preview.frame_count == 0
    assert content.status_label.text() == "动作已安装"


def test_changing_only_playback_speed_reuses_processed_preview_frames(
    qtbot, tmp_path: Path, monkeypatch
) -> None:
    calls: list[bool] = []
    real_builder = image_content_module.build_image_action_pack

    def counted_builder(*args, **kwargs):
        calls.append(True)
        return real_builder(*args, **kwargs)

    monkeypatch.setattr(image_content_module, "build_image_action_pack", counted_builder)
    content = ImageActionImportContent((_pet_package(tmp_path / "pet"),), current_pet_id="cat")
    qtbot.addWidget(content)
    content.load_files([_image(tmp_path / "1.png")])
    processed_count = len(calls)

    content.fps_input.setValue(content.fps_input.value() + 1)

    assert len(calls) == processed_count
    assert content.preview.frame_count == 1


def test_fullscreen_slots_show_pair_requirement_and_walk_direction(qtbot, tmp_path: Path) -> None:
    content = ImageActionImportContent((_pet_package(tmp_path / "pet"),), current_pet_id="cat")
    qtbot.addWidget(content)

    content.select_slot("work_finish_walk")

    assert not content.fullscreen_hint_label.isHidden()
    assert "进入画面" in content.fullscreen_hint_label.text()
    assert "躺下过渡" in content.fullscreen_hint_label.text()
    assert not content.entrance_direction_combo.isHidden()
    content.entrance_direction_combo.setCurrentIndex(
        content.entrance_direction_combo.findData("left")
    )
    content.load_files([_image(tmp_path / "walk.png")])
    with content.build_pack() as pack:
        assert pack.actions["work_finish_walk"].definition["entrance_direction"] == "left"

    content.select_slot("work_finish_lie_loop")
    assert "前两项齐全" in content.fullscreen_hint_label.text()
    assert content.entrance_direction_combo.isHidden()


def test_switching_target_pet_requires_fresh_oversized_confirmation(qtbot, tmp_path: Path) -> None:
    first = _pet_package(tmp_path / "first", identifier="first")
    second = _pet_package(tmp_path / "second", identifier="second")
    content = ImageActionImportContent((first, second), current_pet_id="first")
    qtbot.addWidget(content)
    content.select_slot("mouse_click")
    content.load_files([_image(tmp_path / "large.png", (40, 16))])
    content.fit_oversized_checkbox.setChecked(True)

    content.select_target("second")

    assert content.fit_oversized_checkbox.isChecked() is False
    assert content.can_install() is False
    assert "重新确认" in content.status_label.text()


def test_total_duration_is_clamped_to_the_selected_fps_range(qtbot, tmp_path: Path) -> None:
    content = ImageActionImportContent((_pet_package(tmp_path / "pet"),), current_pet_id="cat")
    qtbot.addWidget(content)
    content.load_files([_image(tmp_path / "1.png")])

    content.total_duration_input.setValue(600_000)

    assert content.fps() == 0.5
    assert content.total_duration_input.value() == 2_000


def test_preview_caches_scaled_pixmaps_instead_of_fullscreen_source_size(qtbot, tmp_path: Path) -> None:
    content = ImageActionImportContent((_pet_package(tmp_path / "pet"),), current_pet_id="cat")
    qtbot.addWidget(content)
    content.select_slot("work_finish_walk")

    content.load_files([_image(tmp_path / "fullscreen.png", (1200, 600))])

    assert content.preview.frame_count == 1
    assert content.preview._pixmaps[0].width() <= 360
    assert content.preview._pixmaps[0].height() <= 360


def test_current_fullscreen_action_preview_is_also_scaled(qtbot, tmp_path: Path) -> None:
    package = _pet_package(tmp_path / "pet")
    large = _image(tmp_path / "current-fullscreen.png", (1200, 600))
    current = replace(
        package.animations["click"],
        name="work_finish_walk",
        frames=(large,),
        scope="fullscreen",
        canvas=Canvas(1200, 600),
    )
    package = replace(package, animations={**package.animations, "work_finish_walk": current})
    content = ImageActionImportContent((package,), current_pet_id="cat")
    qtbot.addWidget(content)

    content.select_slot("work_finish_walk")

    assert content.current_preview.frame_count == 1
    assert content.current_preview._pixmaps[0].width() <= 360
    assert content.current_preview._pixmaps[0].height() <= 360


def test_inconsistent_existing_fullscreen_canvas_cannot_be_overridden_by_fit_checkbox(
    qtbot, tmp_path: Path
) -> None:
    package = _pet_package(tmp_path / "pet")
    walk = replace(
        package.animations["idle"],
        name="work_finish_walk",
        scope="fullscreen",
        canvas=Canvas(80, 60),
    )
    lie_down = replace(
        package.animations["click"],
        name="work_finish_lie_down",
        scope="fullscreen",
        canvas=Canvas(100, 60),
    )
    package = replace(
        package,
        animations={
            **package.animations,
            "work_finish_walk": walk,
            "work_finish_lie_down": lie_down,
        },
    )
    content = ImageActionImportContent((package,), current_pet_id="cat")
    qtbot.addWidget(content)
    content.select_slot("work_finish_lie_loop")
    content.load_files([_image(tmp_path / "loop.png", (40, 30))])

    assert content.can_install() is False
    assert "画布不一致" in content.status_label.text()
    content.fit_oversized_checkbox.setChecked(True)
    assert content.can_install() is False
