"""用图片制作动作内容组件的选择、排序、预览和草稿生命周期测试。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QListView

from petnest.core.action_slots import action_slots
from petnest.models.pet_package import Canvas
from petnest.ui.animation_preview_widget import CheckerboardLabel
from petnest.ui.image_action_import_content import ImageActionImportContent, ImageFrameCard
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
    assert content.slot_combo.count() == len(action_slots())
    assert content.slot_combo.maxVisibleItems() >= len(action_slots())
    assert all(isinstance(content.slot_combo.itemData(index), str) for index in range(content.slot_combo.count()))
    assert all("自定义" not in content.slot_combo.itemText(index) for index in range(content.slot_combo.count()))
    assert content.slot_combo.findData("system_sleep") < content.slot_combo.findData("move_walk")
    assert content.slot_combo.findData("work_finish_walk") < content.slot_combo.findData("move_walk")
    assert "系统空闲 ·" in content.slot_combo.itemText(content.slot_combo.findData("system_sleep"))
    assert "下班提醒 ·" in content.slot_combo.itemText(content.slot_combo.findData("work_finish_walk"))


def test_frames_use_wrapping_icon_grid_and_preview_comes_after_frames(qtbot, tmp_path: Path) -> None:
    content = ImageActionImportContent((_pet_package(tmp_path / "pet"),), current_pet_id="cat")
    qtbot.addWidget(content)

    assert content.frame_list.viewMode() == QListView.ViewMode.IconMode
    assert content.frame_list.resizeMode() == QListView.ResizeMode.Adjust
    assert content.frame_list.flow() == QListView.Flow.LeftToRight
    assert content.frame_list.isWrapping()
    assert content.layout().indexOf(content.frame_section) < content.layout().indexOf(content.preview_section)
    assert not hasattr(content, "preview_stack")
    assert not hasattr(content, "current_preview")


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


def test_each_frame_card_has_top_right_delete_and_updates_draft(qtbot, tmp_path: Path) -> None:
    content = ImageActionImportContent((_pet_package(tmp_path / "pet"),), current_pet_id="cat")
    qtbot.addWidget(content)
    first = _image(tmp_path / "1.png")
    second = _image(tmp_path / "2.png")
    content.load_files([first, second])
    card = content.frame_list.itemWidget(content.frame_list.item(0))

    assert isinstance(card, ImageFrameCard)
    assert card.height() == 82
    assert card.delete_button.objectName() == "frameDeleteButton"
    assert card.delete_button.size().width() == 20
    assert card.delete_button.size().height() == 20
    assert card.delete_button.parentWidget() is card
    assert isinstance(card.thumbnail, CheckerboardLabel)
    assert card.thumbnail.tile_size == 15

    card.delete_button.click()

    assert content.ordered_paths() == (second.resolve(),)
    assert content.frame_list.count() == 1


def test_image_workspace_keeps_prototype_compact_heights(qtbot, tmp_path: Path) -> None:
    content = ImageActionImportContent((_pet_package(tmp_path / "pet"),), current_pet_id="cat")
    qtbot.addWidget(content)

    assert content.drop_zone.maximumHeight() <= 32
    assert content.frame_list.minimumHeight() <= 110
    assert content.preview.preview_label.minimumHeight() <= 170


def test_image_mode_uses_v4_panel_geometry_icons_and_checkerboard(
    qtbot, tmp_path: Path
) -> None:
    content = ImageActionImportContent((_pet_package(tmp_path / "pet"),), current_pet_id="cat")
    qtbot.addWidget(content)

    assert content.action_section.objectName() == "actionImportPanel"
    assert content.frame_section.objectName() == "actionImportPanel"
    assert content.preview_section.objectName() == "actionImportPanel"
    assert content.action_section.layout().contentsMargins().left() == 11
    assert content.frame_section.layout().contentsMargins().left() == 11
    assert content.preview_section.layout().contentsMargins().left() == 11
    assert not content.action_icon.pixmap().isNull()
    assert not content.frame_icon.pixmap().isNull()
    assert not content.preview_icon.pixmap().isNull()
    assert not content.add_files_button.icon().isNull()
    assert not content.choose_folder_button.icon().isNull()
    assert content.frame_list.spacing() == 7
    assert content.preview.preview_label.minimumHeight() == 170
    assert content.preview.preview_label.tile_size == 20
    assert content.preview.preview_label.light_color.name() == "#fffaf7"
    assert content.preview.preview_label.dark_color.name() == "#f0e4de"
    assert (
        content.preview_section.maximumHeight()
        >= content.preview_section.minimumSizeHint().height()
    )


def test_adding_more_images_preserves_current_order_and_appends_new_frames(qtbot, tmp_path: Path) -> None:
    content = ImageActionImportContent((_pet_package(tmp_path / "pet"),), current_pet_id="cat")
    qtbot.addWidget(content)
    first = _image(tmp_path / "1.png")
    second = _image(tmp_path / "2.png")
    content.load_files([first])

    content.add_files([second])

    assert content.ordered_paths() == (first.resolve(), second.resolve())


def test_drop_zone_emits_local_image_paths_on_drop(qtbot, tmp_path: Path) -> None:
    content = ImageActionImportContent((_pet_package(tmp_path / "pet"),), current_pet_id="cat")
    qtbot.addWidget(content)
    frame = _image(tmp_path / "dropped.png")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(frame))])
    event = QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    dropped: list[tuple[Path, ...]] = []
    content.drop_zone.files_dropped.connect(dropped.append)

    content.drop_zone.dropEvent(event)

    assert event.isAccepted()
    assert dropped == [(frame,)]


def test_existing_bound_action_uses_replace_label_and_current_preview(qtbot, tmp_path: Path) -> None:
    package = _pet_package(tmp_path / "pet")
    content = ImageActionImportContent((package,), current_pet_id=package.identifier)
    qtbot.addWidget(content)
    content.select_slot("mouse_click")
    content.load_files([_image(tmp_path / "new-click.png")])

    assert content.action_name() == "click"
    assert content.primary_text() == "替换动作"
    assert content.action_target_label.text() == "将替换：click"


def test_selecting_existing_action_loads_original_frames_and_timing(
    qtbot, tmp_path: Path
) -> None:
    package = _pet_package(tmp_path / "pet")
    click = replace(
        package.animations["click"],
        fps=7.5,
        frame_durations_ms=tuple(
            90 + index * 10 for index, _frame in enumerate(package.animations["click"].frames)
        ),
    )
    package = replace(package, animations={**package.animations, "click": click})
    content = ImageActionImportContent((package,), current_pet_id=package.identifier)
    qtbot.addWidget(content)

    content.select_slot("mouse_click")

    assert [path.name for path in content.ordered_paths()] == [path.name for path in click.frames]
    assert all(
        loaded != source.resolve()
        for loaded, source in zip(content.ordered_paths(), click.frames, strict=True)
    )
    assert content.frame_list.count() == len(click.frames)
    assert content.preview.frame_count == len(click.frames)
    assert content.fps() == 7.5
    assert content.preview._durations == click.frame_durations_ms
    assert content.can_install() is False


def test_switching_actions_never_leaks_another_actions_frames_and_restores_draft(
    qtbot, tmp_path: Path
) -> None:
    package = _pet_package(tmp_path / "pet")
    content = ImageActionImportContent((package,), current_pet_id=package.identifier)
    qtbot.addWidget(content)
    custom = _image(tmp_path / "custom-click.png")

    content.select_slot("mouse_click")
    content.load_files([custom])
    content.select_slot("idle")

    assert [path.name for path in content.ordered_paths()] == [
        path.name for path in package.animations["idle"].frames
    ]

    content.select_slot("mouse_click")

    assert content.ordered_paths() == (custom.resolve(),)
    assert content.can_install() is True


def test_package_refresh_reloads_clean_original_frames_but_keeps_user_draft(
    qtbot, tmp_path: Path
) -> None:
    package = _pet_package(tmp_path / "pet")
    content = ImageActionImportContent((package,), current_pet_id=package.identifier)
    qtbot.addWidget(content)
    content.select_slot("mouse_click")
    replacement = _image(tmp_path / "replacement-click.png")
    refreshed_click = replace(package.animations["click"], frames=(replacement,))
    refreshed = replace(
        package,
        animations={**package.animations, "click": refreshed_click},
    )

    content.refresh_packages((refreshed,), refreshed.identifier)

    assert [path.name for path in content.ordered_paths()] == [replacement.name]

    custom = _image(tmp_path / "custom-draft.png")
    content.load_files([custom])
    content.refresh_packages((package,), package.identifier)

    assert content.ordered_paths() == (custom.resolve(),)


def test_existing_frame_workspace_survives_source_revision_cleanup(qtbot, tmp_path: Path) -> None:
    package = _pet_package(tmp_path / "pet")
    source_frames = package.animations["click"].frames
    content = ImageActionImportContent((package,), current_pet_id=package.identifier)
    qtbot.addWidget(content)
    content.select_slot("mouse_click")
    cached_frames = content.ordered_paths()

    for source in source_frames:
        source.unlink()
    content.fps_input.setValue(content.fps() + 1)

    assert all(path.is_file() for path in cached_frames)
    with content.build_pack() as pack:
        assert len(pack.actions["click"].asset_paths) == len(cached_frames)


def test_switching_to_missing_action_clears_cached_preview_and_fit_state(
    qtbot, tmp_path: Path
) -> None:
    package = _pet_package(tmp_path / "pet")
    content = ImageActionImportContent((package,), current_pet_id=package.identifier)
    qtbot.addWidget(content)
    content.select_slot("mouse_click")
    assert content.preview.frame_count > 0

    content.select_slot("agent_waiting")
    content.fps_input.setValue(content.fps() + 1)

    assert content.ordered_paths() == ()
    assert content.preview.frame_count == 0
    assert content.fit_oversized_checkbox.isHidden()


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


def test_missing_bound_action_is_created_instead_of_replacing_its_runtime_fallback(
    qtbot,
    tmp_path: Path,
) -> None:
    package = _pet_package(tmp_path / "pet")
    package = replace(
        package,
        bindings={**package.bindings, "system.bored": "bored"},
        fallbacks={"bored": ("idle",)},
    )
    content = ImageActionImportContent((package,), current_pet_id=package.identifier)
    qtbot.addWidget(content)

    content.select_slot("system_bored")

    assert content.action_name() == "bored"
    assert content.primary_text() == "安装动作"
    assert content.action_target_label.text() == "将创建：bored"


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
    assert content.frame_count_label.text() == "0 帧"
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
    large = _image(tmp_path / "large.png", (40, 16))
    content.load_files([large])
    content.fit_oversized_checkbox.setChecked(True)

    content.select_target("second")

    assert content.fit_oversized_checkbox.isChecked() is False
    assert content.can_install() is False
    assert [path.name for path in content.ordered_paths()] == [
        path.name for path in second.animations["click"].frames
    ]

    content.select_target("first")

    assert content.ordered_paths() == (large.resolve(),)
    assert content.fit_oversized_checkbox.isChecked() is False
    assert content.can_install() is False


def test_total_duration_is_clamped_to_the_selected_fps_range(qtbot, tmp_path: Path) -> None:
    content = ImageActionImportContent((_pet_package(tmp_path / "pet"),), current_pet_id="cat")
    qtbot.addWidget(content)
    content.load_files([_image(tmp_path / "1.png")])

    content.total_duration_input.setValue(600_000)

    assert content.fps() == 0.5
    assert content.total_duration_input.value() == 2_000


def test_existing_slow_frame_timeline_is_not_clamped_by_uniform_fps_range(
    qtbot, tmp_path: Path
) -> None:
    package = _pet_package(tmp_path / "pet")
    click = replace(
        package.animations["click"],
        frame_durations_ms=(10_000, 12_000),
    )
    package = replace(package, animations={**package.animations, "click": click})
    content = ImageActionImportContent((package,), current_pet_id=package.identifier)
    qtbot.addWidget(content)

    content.select_slot("mouse_click")

    assert content.total_duration_input.maximum() >= 22_000
    assert content.total_duration_input.value() == 22_000


def test_existing_timeline_above_qt_interval_limit_reports_error_instead_of_crashing(
    qtbot, tmp_path: Path
) -> None:
    package = _pet_package(tmp_path / "pet")
    click = replace(
        package.animations["click"],
        frame_durations_ms=(2_147_483_647, 1),
    )
    package = replace(package, animations={**package.animations, "click": click})
    content = ImageActionImportContent((package,), current_pet_id=package.identifier)
    qtbot.addWidget(content)

    content.select_slot("mouse_click")

    assert content.ordered_paths() == ()
    assert content.preview.frame_count == 0
    assert "时长" in content.status_label.text()
    assert "上限" in content.status_label.text()


def test_preview_caches_scaled_pixmaps_instead_of_fullscreen_source_size(qtbot, tmp_path: Path) -> None:
    content = ImageActionImportContent((_pet_package(tmp_path / "pet"),), current_pet_id="cat")
    qtbot.addWidget(content)
    content.select_slot("work_finish_walk")

    content.load_files([_image(tmp_path / "fullscreen.png", (1200, 600))])

    assert content.preview.frame_count == 1
    assert content.preview._pixmaps[0].width() <= 360
    assert content.preview._pixmaps[0].height() <= 360


def test_current_fullscreen_action_is_not_loaded_into_a_comparison_preview(qtbot, tmp_path: Path) -> None:
    package = _pet_package(tmp_path / "pet")
    large = _image(tmp_path / "current-fullscreen.png", (1200, 600))
    current = replace(
        package.animations["click"],
        name="work_finish_walk",
        frames=(large,),
        scope="fullscreen",
        canvas=Canvas(1200, 600),
        entrance_direction="left",
        frame_durations_ms=(137,),
    )
    package = replace(package, animations={**package.animations, "work_finish_walk": current})
    content = ImageActionImportContent((package,), current_pet_id="cat")
    qtbot.addWidget(content)

    content.select_slot("work_finish_walk")

    assert content.action_target_label.text() == "将替换：work_finish_walk"
    assert [path.name for path in content.ordered_paths()] == [large.name]
    assert content.preview.frame_count == 1
    assert content.entrance_direction_combo.currentData() == "left"
    content.entrance_direction_combo.setCurrentIndex(
        content.entrance_direction_combo.findData("none")
    )
    with content.build_pack() as pack:
        assert pack.actions["work_finish_walk"].definition["frame_durations_ms"] == [137]
    assert not hasattr(content, "current_preview")


def test_missing_fullscreen_action_resets_direction_to_slot_default(qtbot, tmp_path: Path) -> None:
    first = _pet_package(tmp_path / "first", identifier="first")
    frame = _image(tmp_path / "walk.png")
    walk = replace(
        first.animations["click"],
        name="work_finish_walk",
        frames=(frame,),
        scope="fullscreen",
        canvas=Canvas(1200, 600),
        entrance_direction="left",
    )
    first = replace(first, animations={**first.animations, "work_finish_walk": walk})
    second = _pet_package(tmp_path / "second", identifier="second")
    content = ImageActionImportContent((first, second), current_pet_id="first")
    qtbot.addWidget(content)
    content.select_slot("work_finish_walk")
    assert content.entrance_direction_combo.currentData() == "left"

    content.select_target("second")

    assert content.entrance_direction_combo.currentData() == "right"


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
