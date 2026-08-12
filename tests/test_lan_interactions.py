"""局域网互动模型与对话框的行为测试。"""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from petnest.core.device_identity import display_name_for
from petnest.models.lan_interaction import InteractionDraft, InteractionKind, LanPeer
from petnest.models.settings import Settings
from petnest.ui.lan_interaction_dialog import LanInteractionDialog, ManualPeerDialog, RemotePairDialog


def test_quick_interaction_payload_contains_only_one_action() -> None:
    draft = InteractionDraft.quick("peer-1", InteractionKind.HEART)

    assert draft.to_payload(sender_id="local-1", sender_name="用户-AB12") == {
        "version": 1,
        "type": "heart",
        "target_device_id": "peer-1",
        "sender_device_id": "local-1",
        "sender_name": "用户-AB12",
    }


def test_text_and_effect_payloads_validate_their_content() -> None:
    text = InteractionDraft.text_message("peer-1", "  你好呀  ")
    effect = InteractionDraft.effect("peer-1", "heart_burst")

    assert text.to_payload(sender_id="local-1", sender_name="小平安")["text"] == "你好呀"
    assert effect.to_payload(sender_id="local-1", sender_name="小平安")["effect_id"] == "heart_burst"

    with pytest.raises(ValueError, match="文字不能为空"):
        InteractionDraft.text_message("peer-1", "   ")

    with pytest.raises(ValueError, match="动效编号"):
        InteractionDraft.effect("peer-1", "../secret")


def test_default_display_name_uses_nickname_or_short_device_id() -> None:
    assert display_name_for(Settings(nickname="  小平安  ", device_id="abcdef123456")) == "小平安"
    assert display_name_for(Settings(device_id="abcdef123456")) == "用户-3456"


def test_dialog_quick_actions_are_mutually_exclusive(qtbot) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    dialog = LanInteractionDialog(
        settings=Settings(nickname="小平安", device_id="local-1"),
        peers=[LanPeer("peer-1", "邻居", "橘猫", "192.168.1.20")],
    )
    qtbot.addWidget(dialog)

    assert dialog.greeting_button.isChecked()
    assert not dialog.heart_button.isChecked()
    dialog.heart_button.click()

    assert not dialog.greeting_button.isChecked()
    assert dialog.heart_button.isChecked()
    assert dialog.interaction_draft() == InteractionDraft.quick("peer-1", InteractionKind.HEART)
    assert dialog.send_button.text() == "发送爱心"


def test_dialog_has_explicit_empty_states_for_peers_and_effects(qtbot) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    dialog = LanInteractionDialog(settings=Settings(device_id="local-1"), peers=[])
    qtbot.addWidget(dialog)

    assert dialog.peer_list.count() == 1
    assert "没有发现" in dialog.peer_list.item(0).text()
    dialog.mode_tabs.setCurrentIndex(2)
    assert "暂无可用动效" in dialog.effect_list.item(0).text()


def test_dialog_updates_nearby_devices_without_losing_selected_target(qtbot) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    first = LanPeer("peer-1", "邻居", "橘猫", "192.168.1.20")
    second = LanPeer("peer-2", "小林", "平安", "192.168.1.21")
    dialog = LanInteractionDialog(settings=Settings(device_id="local-1"), peers=[first])
    qtbot.addWidget(dialog)
    dialog.set_peers([first, second])
    dialog.peer_list.setCurrentRow(1)

    dialog.set_peers([first, second])

    assert dialog.peer_list.count() == 2
    assert dialog.interaction_draft().target_device_id == "peer-2"


def test_dialog_peer_rows_keep_avatar_initials_out_of_display_name(qtbot) -> None:
    dialog = LanInteractionDialog(
        settings=Settings(device_id="local-1"),
        peers=[LanPeer("peer-1", "用户-AB12", "平安", "192.168.1.20")],
    )
    qtbot.addWidget(dialog)

    item = dialog.peer_list.item(0)

    assert item.text().splitlines()[0] == "用户-AB12"
    assert not item.icon().isNull()


def test_dialog_can_disable_local_lan_presence(qtbot) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    dialog = LanInteractionDialog(settings=Settings(device_id="local-1"), peers=[])
    qtbot.addWidget(dialog)

    dialog.lan_enabled_input.setChecked(False)

    assert dialog.settings.lan_interaction_enabled is False


def test_dialog_previews_selected_effect_on_local_pet_and_clears_on_close(qtbot) -> None:
    effect = SimpleNamespace(
        identifier="heart-burst",
        name="Heart Burst",
        duration_ms=800,
        frames=(),
        layer="over",
    )
    previews: list[object] = []
    clears: list[bool] = []
    dialog = LanInteractionDialog(
        settings=Settings(device_id="local-1"),
        effects=[effect],
        on_preview=previews.append,
        on_preview_clear=lambda: clears.append(True),
    )
    qtbot.addWidget(dialog)
    dialog.mode_tabs.setCurrentIndex(2)

    assert not dialog.preview_button.isEnabled()
    dialog.effect_list.setCurrentRow(0)
    assert dialog.preview_button.isEnabled()
    dialog.preview_button.click()
    assert previews == [effect]

    dialog.reject()
    assert clears == [True]


def test_dialog_chooses_a_visible_sample_frame_for_effect_preview(tmp_path, qtbot) -> None:
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    transparent = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    transparent.save(frames_dir / "0001.png")
    Image.new("RGBA", (32, 32), (255, 80, 120, 255)).save(frames_dir / "0002.png")
    effect = SimpleNamespace(
        identifier="sample-effect",
        name="Sample effect",
        duration_ms=800,
        frames=(frames_dir / "0001.png", frames_dir / "0002.png"),
        layer="over",
    )

    dialog = LanInteractionDialog(settings=Settings(device_id="local-1"), effects=[effect])
    qtbot.addWidget(dialog)
    dialog.mode_tabs.setCurrentIndex(2)
    dialog.effect_list.setCurrentRow(0)

    assert dialog._preview_frame_path(effect) == frames_dir / "0002.png"


def test_dialog_exposes_manual_ip_entry_and_normalizes_input(qtbot) -> None:
    app = QApplication.instance() or QApplication([])
    del app
    dialog = LanInteractionDialog(settings=Settings(device_id="local-1"), peers=[])
    qtbot.addWidget(dialog)

    assert dialog.manual_ip_button.text() == "手动添加 IP"
    manual = ManualPeerDialog(parent=dialog)
    qtbot.addWidget(manual)
    manual.ip_input.setText(" 192.168.21.146 ")

    assert manual.ip_address() == "192.168.21.146"


def test_dialog_routes_remote_partner_through_remote_sender(qtbot) -> None:
    remote = LanPeer("remote-1", "小林", "橘猫", transport="remote")
    sent: list[InteractionDraft] = []
    dialog = LanInteractionDialog(
        settings=Settings(device_id="local-1"),
        remote_peers=[remote],
        on_remote_send=lambda draft: sent.append(draft) or True,
        remote_pair_code="23456789AB",
        remote_status="远程伙伴已连接",
    )
    qtbot.addWidget(dialog)

    dialog.device_tabs.setCurrentIndex(1)
    dialog.remote_peer_list.setCurrentRow(0)
    dialog.send_button.click()

    assert dialog.device_tabs.tabText(1) == "远程伙伴"
    assert dialog.pair_code_label.text() == "我的码：2345-6789-AB"
    assert sent == [InteractionDraft.quick("remote-1", InteractionKind.GREETING)]


def test_dialog_shows_transient_success_and_restores_default_prompt(qtbot) -> None:
    sent: list[InteractionDraft] = []
    dialog = LanInteractionDialog(
        settings=Settings(device_id="local-1"),
        peers=[LanPeer("peer-1", "邻居", "平安", "192.168.1.20")],
        on_send=lambda draft: sent.append(draft) or True,
    )
    qtbot.addWidget(dialog)
    dialog._success_feedback_timeout_ms = 20

    dialog.send_button.click()

    assert sent
    assert dialog.status_label.text() == "已发送 ✓"
    assert dialog.send_button.isEnabled()
    qtbot.wait(40)
    assert dialog.status_label.text() == "选择一个互动方式后发送"


def test_dialog_keeps_remote_send_pending_until_result(qtbot) -> None:
    dialog = LanInteractionDialog(
        settings=Settings(device_id="local-1"),
        remote_peers=[LanPeer("remote-1", "小林", "橘猫", transport="remote")],
        on_remote_send=lambda _draft: True,
        remote_send_async=True,
    )
    qtbot.addWidget(dialog)
    dialog.device_tabs.setCurrentIndex(1)
    dialog.remote_peer_list.setCurrentRow(0)

    dialog.send_button.click()

    assert dialog.status_label.text() == "正在发送…"
    assert not dialog.send_button.isEnabled()
    pending = dialog._pending_send_draft
    assert pending is not None
    dialog.remote_send_succeeded(pending)

    assert dialog.status_label.text() == "已发送 ✓"
    assert dialog.send_button.isEnabled()
    assert dialog.send_button.text() == "发送招呼"


def test_dialog_reports_send_failure_and_restores_default_prompt(qtbot) -> None:
    dialog = LanInteractionDialog(
        settings=Settings(device_id="local-1"),
        peers=[LanPeer("peer-1", "邻居", "平安", "192.168.1.20")],
        on_send=lambda _draft: False,
    )
    qtbot.addWidget(dialog)
    dialog._failure_feedback_timeout_ms = 20

    dialog.send_button.click()

    assert dialog.status_label.text() == "发送失败，请稍后重试"
    qtbot.wait(40)
    assert dialog.status_label.text() == "选择一个互动方式后发送"


def test_dialog_does_not_treat_an_unknown_send_result_as_success(qtbot) -> None:
    dialog = LanInteractionDialog(
        settings=Settings(device_id="local-1"),
        peers=[LanPeer("peer-1", "邻居", "平安", "192.168.1.20")],
        on_send=lambda _draft: None,
    )
    qtbot.addWidget(dialog)

    dialog.send_button.click()

    assert dialog.status_label.text() == "发送失败，请稍后重试"


def test_remote_pair_dialog_normalizes_display_separators(qtbot) -> None:
    dialog = RemotePairDialog()
    qtbot.addWidget(dialog)
    dialog.code_input.setText(" 2345-6789-ab ")

    assert dialog.pair_code() == "23456789AB"
