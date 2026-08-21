"""设置窗口中鼠标样式表单的交互测试。"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QRect, QSize, QTime, Qt
from PySide6.QtGui import QFont, QWheelEvent
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

from petnest.core.codex_plugin import CodexPluginStatus
from petnest.core.codex_discovery import (
    CodexAvailabilityState,
    CodexLinkAvailability,
)
from petnest.core.codex_session_log import CodexLogSourceStatus
from petnest.core.cursor_style_catalog import CursorStyle
from petnest.models.settings import Settings
from petnest.ui.settings_dialog import SettingsCenterDialog, SettingsDialog


def test_settings_dialog_is_the_shared_six_section_center(qtbot, tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    dialog = SettingsDialog(Settings(cursor_style_enabled=False), initial_section="mouse_behavior")
    qtbot.addWidget(dialog)

    assert isinstance(dialog, SettingsCenterDialog)
    assert dialog.section_list.currentRow() == 1
    assert dialog.page_title.text() == "鼠标与行为"
    assert dialog.cursor_scale_slider.value() == 100
    assert dialog.findChild(__import__("PySide6").QtWidgets.QFrame, "windowShell") is not None
    assert dialog.findChild(__import__("PySide6").QtWidgets.QFrame, "settingsSidebar") is not None
    assert dialog.findChild(__import__("PySide6").QtWidgets.QFrame, "statusCard") is not None
    assert dialog.section_list.count() == 6
    assert dialog.section_list.item(3).text() == "Codex 联动"


def test_resource_sections_emit_stable_keys_even_when_reselected(qtbot) -> None:
    dialog = SettingsDialog(Settings(), initial_section="display")
    qtbot.addWidget(dialog)
    opened: list[str] = []
    dialog.resource_section_opened.connect(opened.append)

    dialog.select_section("mouse_behavior")
    dialog.select_section("mouse_behavior")
    dialog.select_section("idle")
    dialog.select_section("countdown")

    assert opened == ["mouse_behavior", "mouse_behavior", "countdown"]


def test_resource_status_uses_precise_non_blocking_messages(qtbot) -> None:
    dialog = SettingsDialog(Settings(), initial_section="mouse_behavior")
    qtbot.addWidget(dialog)

    dialog.set_resource_checking()
    assert dialog.resource_status_label.text() == "正在获取最新资源信息…"
    assert not dialog.resource_status_label.isHidden()

    dialog.set_resource_downloading(43, resource_type="interaction_effect", display_name="星光")
    assert dialog.resource_status_label.text() == "正在获取互动动效「星光」… 43%"

    dialog.set_resource_downloading(44, archive=True)
    assert dialog.resource_status_label.text() == "正在获取初始资源包… 44%"

    dialog.set_resource_downloading(45, resource_type="countdown_background")
    assert dialog.resource_status_label.text() == "正在获取倒计时背景… 45%"

    dialog.set_resource_error()
    assert dialog.resource_status_label.text() == "新资源获取失败，将稍后自动重试"

    dialog.set_resource_ready()
    assert dialog.resource_status_label.text() == "新资源已就绪"
    assert dialog.resource_status_hide_timer.interval() == 3000
    assert dialog.resource_status_hide_timer.isActive()
    dialog.resource_status_hide_timer.timeout.emit()
    assert dialog.resource_status_label.isHidden()


def test_resource_status_is_hidden_outside_resource_sections(qtbot) -> None:
    dialog = SettingsDialog(Settings(), initial_section="mouse_behavior")
    qtbot.addWidget(dialog)
    dialog.set_resource_checking()

    dialog.select_section("display")

    assert dialog.resource_status_label.isHidden()


def test_refreshing_cursor_styles_preserves_the_unsaved_selection(qtbot, tmp_path: Path) -> None:
    def style(identifier: str, name: str) -> CursorStyle:
        root = tmp_path / identifier
        return CursorStyle(
            identifier,
            name,
            root / "preview.png",
            root / "arrow.cur",
            (0, 0),
            None,
            {"arrow": root / "arrow.cur"},
        )

    first = style("first", "第一套")
    second = style("second", "第二套")
    third = style("third", "第三套")
    dialog = SettingsDialog(
        Settings(cursor_style_enabled=True, cursor_style_id="first"),
        cursor_styles=[first, second],
        initial_section="mouse_behavior",
    )
    qtbot.addWidget(dialog)
    dialog.cursor_style_input.setCurrentIndex(dialog.cursor_style_input.findData("second"))

    dialog.set_cursor_styles([second, third])

    assert dialog.cursor_style_input.currentData() == "second"
    assert [dialog.cursor_style_input.itemData(index) for index in range(dialog.cursor_style_input.count())] == [
        None,
        "second",
        "third",
    ]


def test_codex_link_page_keeps_plain_controls_and_persists_preferences(qtbot) -> None:
    dialog = SettingsDialog(
        Settings(
            codex_link_enabled=False,
            codex_link_show_attention_bubbles=False,
            codex_link_show_review_bubbles=True,
            codex_link_log_fallback_enabled=True,
        ),
        codex_plugin_status=CodexPluginStatus.missing(),
        codex_link_source="log",
        codex_log_status=CodexLogSourceStatus("active", "已联动 · 本地日志回退"),
        codex_action_availability={
            "working": "working",
            "waiting": "idle（回退）",
            "error": "error",
            "review": "review",
        },
        initial_section="codex_link",
    )
    qtbot.addWidget(dialog)

    assert dialog.section_list.currentRow() == 3
    assert dialog.page_title.text() == "Codex 联动"
    assert "开启后保存即可使用" in dialog.codex_link_explanation_label.text()
    assert dialog.codex_link_runtime_label.text() == "联动已关闭"
    assert not dialog.codex_attention_bubbles_input.isEnabled()
    assert dialog.codex_review_bubbles_input.isChecked()
    assert dialog.codex_action_warning_label.isHidden()

    dialog.codex_link_enabled_input.setChecked(True)
    dialog.codex_attention_bubbles_input.setChecked(True)
    dialog.codex_review_bubbles_input.setChecked(False)
    dialog.codex_log_fallback_input.setChecked(False)
    updated = dialog.updated_settings()
    assert updated.codex_link_enabled is True
    assert updated.codex_link_show_attention_bubbles is True
    assert updated.codex_link_show_review_bubbles is False
    assert updated.codex_link_log_fallback_enabled is False


def test_codex_link_page_hides_technical_terms_but_explains_them_in_tips(qtbot) -> None:
    dialog = SettingsDialog(
        Settings(),
        codex_plugin_status=CodexPluginStatus.missing(),
        initial_section="codex_link",
    )
    qtbot.addWidget(dialog)

    ordinary_text = "\n".join(
        (
            dialog.codex_link_explanation_label.text(),
            dialog.codex_link_runtime_label.text(),
            dialog.codex_plugin_summary_label.text(),
            dialog.codex_plugin_guide_label.text(),
        )
    )
    for technical_term in ("JSONL", "Hook", "working", "review", "idle", "schema"):
        assert technical_term not in ordinary_text
    assert "Hook" in dialog.codex_link_info_button.toolTip()
    assert "本机会话日志" in dialog.codex_link_info_button.toolTip()
    assert "Codex 设置 → 插件" in dialog.codex_plugin_guide_label.text()
    assert "PetNest 状态联动" in dialog.codex_plugin_guide_label.text()
    assert "设置 → 钩子 → Plugin - PetNest" in dialog.codex_plugin_review_guide_label.text()
    assert dialog.codex_advanced_details_panel.isHidden()

    dialog.codex_advanced_details_button.click()
    assert not dialog.codex_advanced_details_panel.isHidden()


def test_codex_link_page_warns_when_current_pet_lacks_required_actions(qtbot) -> None:
    opened: list[str | bool] = []

    def open_actions(page: str | bool = "宠物与动作") -> None:
        opened.append(page)

    dialog = SettingsDialog(
        Settings(),
        codex_action_availability={
            "working": "idle（回退）",
            "waiting": "idle（回退）",
            "error": "idle（回退）",
            "review": "idle（回退）",
        },
        on_open_pet_actions=open_actions,
        initial_section="codex_link",
    )
    qtbot.addWidget(dialog)

    assert not dialog.codex_action_warning_label.isHidden()
    assert "当前宠物缺少“任务进行中”和“任务完成”动作" in dialog.codex_action_warning_label.text()
    assert "联动仍会运行" in dialog.codex_action_warning_label.text()
    qtbot.mouseClick(dialog.codex_open_pet_actions_button, Qt.MouseButton.LeftButton)
    assert opened == ["宠物与动作"]


def test_codex_link_diagnostic_and_animation_buttons_use_explicit_callbacks(qtbot) -> None:
    calls: list[str] = []
    dialog = SettingsDialog(
        Settings(),
        on_test_codex_animation=lambda: calls.append("animation") or "已播放本地测试",
        on_diagnose_codex_link=lambda: calls.append("diagnose") or "当前使用本地日志回退",
        initial_section="codex_link",
    )
    qtbot.addWidget(dialog)

    qtbot.mouseClick(dialog.codex_animation_test_button, Qt.MouseButton.LeftButton)
    assert calls == ["animation"]
    assert dialog.codex_diagnostic_result_label.text() == "已播放本地测试"

    qtbot.mouseClick(dialog.codex_diagnose_button, Qt.MouseButton.LeftButton)
    assert calls == ["animation", "diagnose"]
    assert dialog.codex_diagnostic_result_label.text() == "当前使用本地日志回退"


def test_codex_plugin_card_uses_one_state_aware_primary_action(qtbot) -> None:
    calls: list[str] = []
    button_labels_during_callback: list[str] = []

    def configure() -> CodexPluginStatus:
        calls.append("configure")
        button_labels_during_callback.append(dialog.codex_plugin_primary_button.text())
        return CodexPluginStatus.enabled()

    def remove() -> CodexPluginStatus:
        calls.append("remove")
        return CodexPluginStatus.missing()

    dialog = SettingsDialog(
        Settings(),
        codex_plugin_status=CodexPluginStatus.missing(),
        on_configure_codex_plugin=configure,
        on_remove_codex_plugin=remove,
        initial_section="codex_link",
    )
    qtbot.addWidget(dialog)

    assert dialog.codex_plugin_primary_button.text() == "启用精确连接"
    qtbot.mouseClick(dialog.codex_plugin_primary_button, Qt.MouseButton.LeftButton)
    assert calls == ["configure"]
    assert button_labels_during_callback == ["正在启用…"]
    assert dialog.codex_plugin_primary_button.text() == "已启用"
    assert not dialog.codex_plugin_primary_button.isEnabled()

    assert dialog.codex_plugin_remove_button.isHidden()
    dialog.codex_advanced_details_button.click()
    assert not dialog.codex_plugin_remove_button.isHidden()


def test_codex_plugin_pending_state_rechecks_instead_of_reinstalling(qtbot) -> None:
    calls: list[str] = []
    dialog = SettingsDialog(
        Settings(),
        codex_plugin_status=CodexPluginStatus.pending(),
        on_configure_codex_plugin=lambda: calls.append("configure") or CodexPluginStatus.pending(),
        on_recheck_codex_plugin=lambda: calls.append("recheck") or CodexPluginStatus.pending(),
        initial_section="codex_link",
    )
    qtbot.addWidget(dialog)

    assert dialog.codex_plugin_primary_button.text() == "我已完成，重新检查"
    qtbot.mouseClick(dialog.codex_plugin_primary_button, Qt.MouseButton.LeftButton)

    assert calls == ["recheck"]


def test_codex_link_page_shows_real_task_state_in_plain_language(qtbot) -> None:
    dialog = SettingsDialog(Settings(codex_link_enabled=True), initial_section="codex_link")
    qtbot.addWidget(dialog)

    dialog.set_codex_task_state("running")
    assert dialog.codex_link_runtime_label.text() == "Codex 正在工作"
    dialog.set_codex_task_state("waiting")
    assert dialog.codex_link_runtime_label.text() == "需要你处理"
    dialog.set_codex_task_state("review")
    assert dialog.codex_link_runtime_label.text() == "任务已完成"


def _codex_availability(
    state: CodexAvailabilityState,
    *,
    home: Path | None = None,
    manual: bool = False,
) -> CodexLinkAvailability:
    messages = {
        CodexAvailabilityState.NOT_DETECTED: "未检测到 Codex，安装或启动后会自动连接",
        CodexAvailabilityState.READY: "联动已准备好，等待新的任务",
    }
    return CodexLinkAvailability(
        state=state,
        message=messages[state],
        codex_detected=state is CodexAvailabilityState.READY,
        selected_home=home,
        sessions_path=home / "sessions" if home is not None else None,
        manual_override=manual,
        can_watch=state is CodexAvailabilityState.READY,
    )


def test_codex_page_shows_not_detected_without_claiming_link_is_normal(qtbot) -> None:
    availability = _codex_availability(CodexAvailabilityState.NOT_DETECTED)
    dialog = SettingsDialog(
        Settings(codex_link_enabled=True),
        codex_availability=availability,
        on_set_codex_home_override=lambda _home: availability,
        initial_section="codex_link",
    )
    qtbot.addWidget(dialog)

    assert dialog.codex_link_runtime_label.text() == availability.message
    assert "联动正常" not in dialog.codex_link_runtime_label.text()
    assert not dialog.codex_choose_home_button.isHidden()


def test_codex_page_hides_manual_choice_in_ready_main_flow(qtbot, tmp_path: Path) -> None:
    home = tmp_path / "codex-home"
    availability = _codex_availability(CodexAvailabilityState.READY, home=home)
    dialog = SettingsDialog(
        Settings(),
        codex_availability=availability,
        on_set_codex_home_override=lambda _home: availability,
        initial_section="codex_link",
    )
    qtbot.addWidget(dialog)

    assert dialog.codex_choose_home_button.isHidden()
    dialog.codex_advanced_details_button.click()
    assert not dialog.codex_reselect_home_button.isHidden()
    assert dialog.codex_restore_auto_home_button.isHidden()


def test_selecting_sessions_folder_passes_normalized_home_to_callback(
    qtbot,
    tmp_path: Path,
    monkeypatch,
) -> None:
    selected = tmp_path / ".codex" / "sessions"
    selected.mkdir(parents=True)
    calls: list[Path | None] = []
    ready = _codex_availability(CodexAvailabilityState.READY, home=selected.parent, manual=True)
    monkeypatch.setattr(
        "petnest.ui.settings_center_dialog.QFileDialog.getExistingDirectory",
        lambda *_args, **_kwargs: str(selected),
    )
    dialog = SettingsDialog(
        Settings(),
        codex_availability=_codex_availability(CodexAvailabilityState.NOT_DETECTED),
        on_set_codex_home_override=lambda home: calls.append(home) or ready,
        initial_section="codex_link",
    )
    qtbot.addWidget(dialog)

    qtbot.mouseClick(dialog.codex_choose_home_button, Qt.MouseButton.LeftButton)

    assert calls == [selected.parent.resolve()]
    assert dialog.updated_settings().codex_home_override == str(selected.parent.resolve())
    assert dialog.codex_link_runtime_label.text() == "联动已准备好，等待新的任务"


def test_restoring_auto_discovery_clears_manual_home(qtbot, tmp_path: Path) -> None:
    home = tmp_path / "manual-home"
    calls: list[Path | None] = []
    automatic = _codex_availability(CodexAvailabilityState.NOT_DETECTED)
    dialog = SettingsDialog(
        Settings(codex_home_override=str(home)),
        codex_availability=_codex_availability(
            CodexAvailabilityState.READY,
            home=home,
            manual=True,
        ),
        on_set_codex_home_override=lambda value: calls.append(value) or automatic,
        initial_section="codex_link",
    )
    qtbot.addWidget(dialog)
    dialog.codex_advanced_details_button.click()

    qtbot.mouseClick(dialog.codex_restore_auto_home_button, Qt.MouseButton.LeftButton)

    assert calls == [None]
    assert dialog.updated_settings().codex_home_override is None


def test_settings_center_keeps_preferred_layout_on_roomy_screen(qtbot) -> None:
    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)

    dialog._fit_to_available_geometry(QRect(0, 0, 1920, 1040))

    assert dialog.minimumSize() == QSize(1000, 680)
    assert dialog.size() == QSize(1180, 760)
    assert not dialog.status_title.isHidden()
    assert not dialog.status_card.isHidden()


def test_settings_center_keeps_status_card_when_only_width_is_constrained(qtbot) -> None:
    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)

    dialog._fit_to_available_geometry(QRect(0, 0, 960, 900))

    assert dialog.width() <= 928
    assert dialog.height() == 760
    assert not dialog.status_title.isHidden()
    assert not dialog.status_card.isHidden()


def test_settings_center_prioritizes_complete_navigation_on_short_screen(qtbot) -> None:
    dialog = SettingsDialog(Settings(), initial_section="mouse_behavior")
    qtbot.addWidget(dialog)

    available = QRect(0, 0, 960, 600)
    dialog._fit_to_available_geometry(available)
    dialog.show()
    qtbot.wait(20)

    assert dialog.width() <= available.width() - 32
    assert dialog.height() <= available.height() - 32
    assert dialog.status_title.isHidden()
    assert dialog.status_card.isHidden()
    last_row = dialog.section_list.visualItemRect(
        dialog.section_list.item(dialog.section_list.count() - 1)
    )
    assert last_row.bottom() < dialog.section_list.viewport().height()


def test_settings_center_navigation_height_follows_larger_system_font(qtbot) -> None:
    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)
    dialog.section_list.setFont(QFont("Microsoft YaHei UI", 16))

    dialog._fit_to_available_geometry(QRect(0, 0, 960, 640))
    dialog.show()
    qtbot.wait(20)

    last_row = dialog.section_list.visualItemRect(
        dialog.section_list.item(dialog.section_list.count() - 1)
    )
    assert last_row.bottom() < dialog.section_list.viewport().height()


def test_settings_dialog_persists_remote_partner_toggle(qtbot) -> None:
    dialog = SettingsDialog(Settings(remote_interaction_enabled=True))
    qtbot.addWidget(dialog)

    dialog.remote_interaction_input.setChecked(False)

    assert dialog.updated_settings().remote_interaction_enabled is False


def test_settings_dialog_preserves_group_chat_notification_toggle(qtbot) -> None:
    dialog = SettingsDialog(Settings(lan_group_chat_notifications_enabled=False))
    qtbot.addWidget(dialog)

    assert dialog.updated_settings().lan_group_chat_notifications_enabled is False


def test_mouse_follow_and_cursor_scale_controls_are_linked(qtbot) -> None:
    dialog = SettingsDialog(Settings(mouse_follow_enabled=True, cursor_style_enabled=True))
    qtbot.addWidget(dialog)

    dialog.mouse_follow_input.setChecked(False)
    assert not dialog.mouse_follow_scale_input.isEnabled()
    dialog.mouse_follow_input.setChecked(True)
    assert dialog.mouse_follow_scale_input.isEnabled()

    dialog.cursor_scale_slider.setValue(112)
    dialog.cursor_scale_slider.snap_to_node()
    assert dialog.cursor_scale_slider.value() in {80, 100, 125, 150}
    assert dialog.updated_settings().cursor_scale == dialog.cursor_scale_slider.value()


def test_keyboard_activity_card_defaults_off_and_persists(qtbot) -> None:
    dialog = SettingsDialog(
        Settings(),
        keyboard_activity_supported=True,
        keyboard_activity_status="已关闭",
        initial_section="mouse_behavior",
    )
    qtbot.addWidget(dialog)

    assert dialog.keyboard_working_input.isChecked() is False
    assert dialog.keyboard_working_input.isEnabled()
    dialog.keyboard_working_input.setChecked(True)

    assert dialog.updated_settings().keyboard_working_enabled is True


def test_keyboard_activity_card_is_disabled_outside_windows(qtbot) -> None:
    dialog = SettingsDialog(
        Settings(keyboard_working_enabled=True),
        keyboard_activity_supported=False,
        keyboard_activity_status="当前版本仅支持 Windows",
        initial_section="mouse_behavior",
    )
    qtbot.addWidget(dialog)

    assert not dialog.keyboard_working_input.isEnabled()
    assert dialog.keyboard_activity_status_label.text() == "当前版本仅支持 Windows"
    assert dialog.updated_settings().keyboard_working_enabled is True


def test_keyboard_activity_card_warns_when_working_falls_back_to_idle(qtbot) -> None:
    dialog = SettingsDialog(
        Settings(),
        keyboard_activity_supported=True,
        codex_action_availability={"working": "idle（回退）"},
        initial_section="mouse_behavior",
    )
    qtbot.addWidget(dialog)

    assert not dialog.keyboard_working_action_warning.isHidden()
    assert "缺少“任务进行中”动作" in dialog.keyboard_working_action_warning.text()


def test_mouse_behavior_switches_respond_when_painted_tracks_are_clicked(qtbot) -> None:
    dialog = SettingsDialog(
        Settings(mouse_follow_enabled=False, cursor_style_enabled=False),
        initial_section="mouse_behavior",
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(20)

    follow_switch = dialog.mouse_follow_input
    follow_track = QPoint(follow_switch.width() - 24, follow_switch.height() // 2)
    qtbot.mouseClick(follow_switch, Qt.MouseButton.LeftButton, pos=follow_track)

    assert follow_switch.isChecked()
    assert dialog.mouse_follow_scale_input.isEnabled()

    cursor_switch = dialog.cursor_style_enabled_input
    cursor_track = QPoint(cursor_switch.width() - 24, cursor_switch.height() // 2)
    qtbot.mouseClick(cursor_switch, Qt.MouseButton.LeftButton, pos=cursor_track)

    assert cursor_switch.isChecked()
    assert dialog.cursor_style_input.isEnabled()
    assert dialog.cursor_scale_slider.isEnabled()


def test_workday_choice_is_shared_by_fixed_and_elastic_modes(qtbot) -> None:
    dialog = SettingsDialog(Settings(), initial_section="countdown")
    qtbot.addWidget(dialog)

    assert len(dialog.workday_inputs) == 7
    dialog.workday_inputs["5"].setChecked(True)
    dialog.schedule_mode_input.setCurrentIndex(dialog.schedule_mode_input.findData("elastic"))
    dialog.clock_in_start_input.setTime(__import__("PySide6").QtCore.QTime(9, 30))
    dialog.clock_in_end_input.setTime(__import__("PySide6").QtCore.QTime(10, 0))

    updated = dialog.updated_settings()
    assert updated.work_schedule_mode == "elastic"
    assert updated.daily_work_end_times["5"] is not None
    assert updated.daily_work_end_times["6"] is None
    assert updated.clock_in_start_time == "09:30"


def test_invalid_clock_in_window_disables_apply_without_extra_persistent_notice(qtbot) -> None:
    dialog = SettingsDialog(Settings(), initial_section="countdown")
    qtbot.addWidget(dialog)

    dialog.schedule_mode_input.setCurrentIndex(dialog.schedule_mode_input.findData("elastic"))
    dialog.clock_in_start_input.setTime(__import__("PySide6").QtCore.QTime(10, 0))
    dialog.clock_in_end_input.setTime(__import__("PySide6").QtCore.QTime(9, 30))

    assert not dialog.button_box.button(__import__("PySide6").QtWidgets.QDialogButtonBox.StandardButton.Ok).isEnabled()
    assert "必须早于" in dialog.schedule_error_label.text()


def test_application_update_entry_is_opt_in_for_platform_owner(qtbot) -> None:
    called: list[bool] = []
    dialog = SettingsDialog(Settings(), on_check_app_update=lambda: called.append(True))
    qtbot.addWidget(dialog)

    assert dialog.app_update_button.text() == "检查程序更新"
    qtbot.mouseClick(dialog.app_update_button, __import__("PySide6").QtCore.Qt.MouseButton.LeftButton)
    assert called == [True]


def test_application_update_entry_is_absent_without_platform_support(qtbot) -> None:
    dialog = SettingsDialog(Settings())
    qtbot.addWidget(dialog)

    assert not hasattr(dialog, "app_update_button")


def test_settings_pages_have_content_titles_and_surface_cards(qtbot) -> None:
    dialog = SettingsDialog(Settings(), initial_section="display")
    qtbot.addWidget(dialog)

    assert dialog.findChild(__import__("PySide6").QtWidgets.QLabel, "contentTitle") is not None
    assert dialog.findChild(__import__("PySide6").QtWidgets.QFrame, "previewCard") is not None


def test_display_scale_is_a_percent_slider_with_live_preview(qtbot) -> None:
    dialog = SettingsDialog(Settings(scale=1.0), initial_section="display")
    qtbot.addWidget(dialog)

    assert dialog.scale_input.minimum() == 25
    assert dialog.scale_input.maximum() == 200
    assert dialog.scale_value_label.text() == "100%"
    assert dialog.always_on_top_input.objectName() == "toggleSwitch"
    assert dialog.mouse_interaction_input.objectName() == "toggleSwitch"


def test_display_page_renders_the_current_pet_preview(qtbot, tmp_path: Path) -> None:
    preview_path = tmp_path / "idle.png"
    preview = QPixmap(24, 24)
    preview.fill(QColor("#D98663"))
    assert preview.save(str(preview_path))

    dialog = SettingsDialog(Settings(), pet_preview_path=preview_path, initial_section="display")
    qtbot.addWidget(dialog)

    assert not dialog.pet_preview_label.pixmap().isNull()


def test_elastic_duration_uses_hours_and_explains_end_time_range(qtbot) -> None:
    dialog = SettingsDialog(Settings(work_schedule_mode="elastic", work_duration_minutes=540), initial_section="countdown")
    qtbot.addWidget(dialog)

    assert dialog.work_duration_input.suffix() == " 小时"
    assert dialog.work_duration_input.value() == 9.0
    assert "18:30" in dialog.elastic_end_range_label.text()
    assert "19:00" in dialog.elastic_end_range_label.text()

    dialog.work_duration_input.setValue(8.5)
    assert dialog.updated_settings().work_duration_minutes == 510


def test_elastic_schedule_can_edit_today_clock_in_time(qtbot) -> None:
    settings = Settings(
        work_schedule_mode="elastic",
        clock_in_start_time="09:30",
        clock_in_end_time="10:00",
        clock_in_date=date.today().isoformat(),
        clock_in_time="09:40",
        work_duration_minutes=540,
    )
    dialog = SettingsDialog(settings, initial_section="countdown")
    qtbot.addWidget(dialog)

    target = dialog.today_clock_in_input.minimumTime()
    dialog.today_clock_in_input.setTime(target)

    assert dialog.today_clock_in_input.minimumTime().toString("HH:mm") == "09:30"
    assert dialog.updated_settings().clock_in_time == target.toString("HH:mm")
    assert "18:30" in dialog.today_clock_in_hint.text()


def test_today_clock_in_editor_does_not_allow_a_future_minute(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(QTime, "currentTime", staticmethod(lambda: QTime(9, 45)))
    settings = Settings(
        work_schedule_mode="elastic",
        clock_in_start_time="09:30",
        clock_in_end_time="10:00",
        clock_in_date=date.today().isoformat(),
        clock_in_time="09:40",
    )
    dialog = SettingsDialog(settings, initial_section="countdown")
    qtbot.addWidget(dialog)

    assert dialog.today_clock_in_input.maximumTime().toString("HH:mm") == "09:45"


def test_countdown_time_editors_step_by_minute_and_allow_today_adjustment(qtbot) -> None:
    settings = Settings(
        work_schedule_mode="elastic",
        clock_in_start_time="09:30",
        clock_in_end_time="10:00",
        clock_in_date=date.today().isoformat(),
        clock_in_time="09:52",
    )
    dialog = SettingsDialog(settings, initial_section="countdown")
    qtbot.addWidget(dialog)

    dialog.clock_in_start_input.setTime(QTime(9, 30))
    dialog.clock_in_start_input.stepBy(1)
    assert dialog.clock_in_start_input.time().toString("HH:mm") == "09:31"

    # 本测试只验证分钟步进；显式固定可编辑上限，避免结果依赖测试运行时刻。
    dialog.today_clock_in_input.setMaximumTime(QTime(10, 0))
    dialog.today_clock_in_input.setTime(QTime(9, 52))
    dialog.today_clock_in_input.stepBy(-1)
    assert dialog.today_clock_in_input.time().toString("HH:mm") == "09:51"


def test_fixed_schedule_does_not_edit_today_clock_in_time(qtbot) -> None:
    settings = Settings(
        work_schedule_mode="fixed",
        clock_in_date=date.today().isoformat(),
        clock_in_time="09:40",
    )
    dialog = SettingsDialog(settings, initial_section="countdown")
    qtbot.addWidget(dialog)

    dialog.today_clock_in_input.setTime(QTime(9, 30))

    assert dialog.updated_settings().clock_in_time == "09:40"


def test_countdown_uses_one_workday_section_and_segmented_schedule_mode(qtbot) -> None:
    dialog = SettingsDialog(Settings(), initial_section="countdown")
    qtbot.addWidget(dialog)

    assert dialog.findChild(__import__("PySide6").QtWidgets.QFrame, "workdaySelector") is not None
    assert dialog.findChild(__import__("PySide6").QtWidgets.QFrame, "scheduleModeSwitch") is not None
    assert dialog.fixed_schedule_radio.text() == "固定时间"
    assert dialog.elastic_schedule_radio.text() == "弹性打卡"
    assert dialog.schedule_mode_input.isHidden()


def test_switching_settings_sections_resets_shared_scroll_position(qtbot) -> None:
    dialog = SettingsDialog(Settings(), initial_section="countdown")
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(20)

    scroll = dialog.findChild(__import__("PySide6").QtWidgets.QScrollArea, "settingsScroll")
    assert scroll is not None
    scroll.verticalScrollBar().setRange(0, 100)
    scroll.verticalScrollBar().setValue(80)

    dialog.section_list.setCurrentRow(1)

    assert scroll.verticalScrollBar().value() == 0


def test_settings_value_controls_ignore_wheel_without_focus(qtbot) -> None:
    dialog = SettingsDialog(Settings(work_schedule_mode="elastic"), initial_section="countdown")
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(20)

    event = QWheelEvent(
        QPointF(0, 0),
        QPointF(0, 0),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    before = dialog.work_duration_input.value()
    dialog.work_duration_input.wheelEvent(event)

    assert dialog.work_duration_input.value() == before
    assert not event.isAccepted()


def test_settings_value_controls_only_accept_focus_by_direct_click(qtbot) -> None:
    dialog = SettingsDialog(Settings(work_schedule_mode="elastic"), initial_section="countdown")
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.wait(20)

    value_controls = (
        dialog.scale_input,
        dialog.mouse_follow_scale_input,
        dialog.cursor_style_input,
        dialog.cursor_scale_slider,
        dialog.system_bored_input,
        dialog.system_sleep_input,
        dialog.countdown_gap_input,
        dialog.countdown_width_input,
        dialog.countdown_height_input,
        dialog.countdown_theme_input,
        dialog.work_start_input,
        dialog.work_end_input,
        dialog.clock_in_start_input,
        dialog.clock_in_end_input,
        dialog.work_duration_input,
        dialog.today_clock_in_input,
    )

    assert all(control.focusPolicy() == Qt.FocusPolicy.ClickFocus for control in value_controls)

    control = dialog.work_duration_input
    qtbot.mouseClick(control, Qt.MouseButton.LeftButton, pos=control.rect().center())
    assert control.hasFocus()

    before = control.value()
    event = QWheelEvent(
        QPointF(0, 0),
        QPointF(0, 0),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    control.wheelEvent(event)

    assert control.value() > before
    assert event.isAccepted()


def test_app_update_stays_in_settings_page_and_button_becomes_update(qtbot) -> None:
    checked: list[bool] = []
    downloaded: list[object] = []
    dialog = SettingsDialog(
        Settings(),
        on_check_app_update=lambda: checked.append(True),
        on_download_app_update=lambda info: downloaded.append(info),
    )
    qtbot.addWidget(dialog)

    assert dialog.app_update_button.text() == "检查程序更新"
    dialog.set_app_update_available(type("Update", (), {"version": "0.2.0", "release_notes": "更稳定"})())
    assert dialog.app_update_button.text() == "更新"
    dialog.app_update_button.click()
    assert downloaded


def test_clicking_version_seven_times_unlocks_codex_usage_once(qtbot) -> None:
    unlocked: list[bool] = []
    dialog = SettingsDialog(
        Settings(),
        initial_section="app_update",
        on_unlock_codex_usage=lambda: unlocked.append(True),
    )
    qtbot.addWidget(dialog)

    for _ in range(6):
        qtbot.mouseClick(dialog.current_version_label, Qt.MouseButton.LeftButton)
    assert unlocked == []
    assert dialog.updated_settings().codex_usage_unlocked is False

    qtbot.mouseClick(dialog.current_version_label, Qt.MouseButton.LeftButton)

    assert unlocked == [True]
    assert dialog.updated_settings().codex_usage_unlocked is True
    assert dialog.codex_unlock_status_label.text() == "Codex 用量入口已解锁"
    assert not dialog.codex_unlock_status_label.isHidden()

    qtbot.mouseClick(dialog.current_version_label, Qt.MouseButton.LeftButton)
    assert unlocked == [True]


def test_version_unlock_click_count_resets_with_each_settings_window(qtbot) -> None:
    unlocked: list[bool] = []
    first = SettingsDialog(
        Settings(),
        initial_section="app_update",
        on_unlock_codex_usage=lambda: unlocked.append(True),
    )
    qtbot.addWidget(first)
    for _ in range(6):
        qtbot.mouseClick(first.current_version_label, Qt.MouseButton.LeftButton)
    first.close()

    second = SettingsDialog(
        Settings(),
        initial_section="app_update",
        on_unlock_codex_usage=lambda: unlocked.append(True),
    )
    qtbot.addWidget(second)
    qtbot.mouseClick(second.current_version_label, Qt.MouseButton.LeftButton)

    assert unlocked == []
    assert second.updated_settings().codex_usage_unlocked is False
