"""Tests for the embedded animation timing editor page."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMessageBox, QSizePolicy

from tests.test_pet_window import _package
from petnest.ui.animation_editor_page import AnimationEditorPage, AnimationSaveResult


def _page(
    tmp_path: Path,
    *,
    save_timelines=None,
    is_pet_locked=None,
    packages=None,
    current_pet_id: str = "cat",
) -> AnimationEditorPage:
    packages = tuple(packages or (_package(tmp_path, identifier="cat"),))
    if save_timelines is None:
        save_timelines = lambda package, timelines: AnimationSaveResult(
            True, "已保存并重载", package
        )
    return AnimationEditorPage(
        packages,
        current_pet_id=current_pet_id,
        save_timelines=save_timelines,
        is_pet_locked=is_pet_locked,
    )


def test_save_passes_current_pet_and_changed_timelines_and_clears_dirty(
    qtbot: object, tmp_path: Path
) -> None:
    calls: list[tuple[str, dict[str, tuple[int, ...]]]] = []
    package = _package(tmp_path, identifier="cat")

    def save_timelines(current, timelines):
        calls.append((current.identifier, timelines))
        return AnimationSaveResult(True, "已保存并重载", current)

    page = _page(tmp_path, packages=(package,), save_timelines=save_timelines)
    qtbot.addWidget(page)
    page.editor.total_duration_spin.setValue(100)

    assert page.editor.is_dirty()
    page.trigger_primary()

    assert calls == [("cat", {"idle": (50, 50)})]
    assert not page.editor.is_dirty()
    assert page.footer_state().status == "已保存并重载"


def test_save_failure_keeps_draft_and_reports_error(qtbot: object, tmp_path: Path) -> None:
    package = _package(tmp_path, identifier="cat")

    def save_timelines(current, timelines):
        return AnimationSaveResult(False, "保存失败：磁盘不可写")

    page = _page(tmp_path, packages=(package,), save_timelines=save_timelines)
    qtbot.addWidget(page)
    page.editor.total_duration_spin.setValue(100)
    page.trigger_primary()

    assert page.editor.is_dirty()
    assert page.editor.updated_frame_durations()["idle"] == (50, 50)
    assert page.footer_state().status == "保存失败：磁盘不可写"


def test_secondary_restores_only_current_action(qtbot: object, tmp_path: Path) -> None:
    page = _page(tmp_path)
    qtbot.addWidget(page)
    page.editor.total_duration_spin.setValue(100)
    assert page.editor.is_dirty()

    page.trigger_secondary()

    assert not page.editor.is_dirty()
    assert page.editor.total_duration_spin.value() == 200
    assert page.footer_state().status == "已恢复当前动作"


def test_locked_pet_blocks_save_without_calling_callback(qtbot: object, tmp_path: Path) -> None:
    calls: list[object] = []

    def save_timelines(current, timelines):
        calls.append((current, timelines))
        return AnimationSaveResult(True, "不应调用", current)

    page = _page(
        tmp_path,
        save_timelines=save_timelines,
        is_pet_locked=lambda identifier: identifier == "cat",
    )
    qtbot.addWidget(page)
    page.editor.total_duration_spin.setValue(100)
    page.trigger_primary()

    assert calls == []
    assert page.editor.is_dirty()
    assert page.footer_state().status == "下班提醒显示中，请先结束提醒。"


def test_request_leave_cancel_keeps_dirty_draft(
    qtbot: object, tmp_path: Path, monkeypatch: object
) -> None:
    page = _page(tmp_path)
    qtbot.addWidget(page)
    page.editor.total_duration_spin.setValue(100)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *_args, **_kwargs: QMessageBox.StandardButton.Cancel),
    )

    assert page.request_leave() is False
    assert page.editor.is_dirty()


def test_request_leave_discard_clears_draft_without_saving(
    qtbot: object, tmp_path: Path, monkeypatch: object
) -> None:
    calls: list[object] = []
    page = _page(tmp_path, save_timelines=lambda *args: calls.append(args))
    qtbot.addWidget(page)
    page.editor.total_duration_spin.setValue(100)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *_args, **_kwargs: QMessageBox.StandardButton.No),
    )

    assert page.request_leave() is True
    assert calls == []
    assert not page.editor.is_dirty()


def test_request_leave_save_returns_only_after_successful_save(
    qtbot: object, tmp_path: Path, monkeypatch: object
) -> None:
    page = _page(tmp_path)
    qtbot.addWidget(page)
    page.editor.total_duration_spin.setValue(100)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes),
    )

    assert page.request_leave() is True
    assert not page.editor.is_dirty()


def test_switch_and_refresh_are_guarded_when_editor_is_dirty(
    qtbot: object, tmp_path: Path, monkeypatch: object
) -> None:
    cat_root = tmp_path / "cat"
    dog_root = tmp_path / "dog"
    cat_root.mkdir()
    dog_root.mkdir()
    cat = _package(cat_root, identifier="cat")
    dog = _package(dog_root, identifier="dog")
    page = _page(tmp_path, packages=(cat, dog))
    qtbot.addWidget(page)
    page.editor.total_duration_spin.setValue(100)
    monkeypatch.setattr(page, "request_leave", lambda: False)

    assert page.set_current_pet("dog") is False
    assert page.current_package() is cat
    assert page.refresh_packages((dog,), "dog") is False
    assert page.current_package() is cat


def test_deactivate_stops_editor_preview(qtbot: object, tmp_path: Path, monkeypatch: object) -> None:
    page = _page(tmp_path)
    qtbot.addWidget(page)
    stopped: list[bool] = []
    monkeypatch.setattr(page.editor, "stop_preview", lambda: stopped.append(True))

    page.deactivate()

    assert stopped == [True]


def test_success_without_reloaded_package_preserves_timings_across_switch_and_refresh(
    qtbot: object, tmp_path: Path
) -> None:
    cat_root = tmp_path / "cat"
    dog_root = tmp_path / "dog"
    cat_root.mkdir()
    dog_root.mkdir()
    cat = _package(cat_root, identifier="cat")
    dog = _package(dog_root, identifier="dog")

    page = _page(
        tmp_path,
        packages=(cat, dog),
        save_timelines=lambda *_args: AnimationSaveResult(True, "已保存并重载"),
    )
    qtbot.addWidget(page)
    page.editor.total_duration_spin.setValue(100)
    page.trigger_primary()

    assert page.current_package() is not None
    assert page.current_package().animations["idle"].frame_durations_ms == (50, 50)
    page.set_current_pet("dog")
    page.set_current_pet("cat")
    assert page.editor.total_duration_spin.value() == 100
    page.refresh_packages((page.current_package(), dog), "cat")
    assert page.editor.total_duration_spin.value() == 100


def test_editor_page_places_pet_selector_in_compact_header(qtbot: object, tmp_path: Path) -> None:
    page = _page(tmp_path)
    qtbot.addWidget(page)

    assert page.pet_combo.maximumWidth() == 260
    assert page.editor_stack.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Expanding
