"""LAN chat framing, image preparation, transport and UI tests."""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO
import os
from time import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QCoreApplication

from petnest.core.lan_chat import prepare_chat_image
from petnest.core.lan_interaction import LanPacketCodec, LanProtocolError
from petnest.core.lan_service import LanInteractionService
from petnest.models.lan_interaction import ChatDraft, ChatMessageKind, ChatScope, LanChatMessage, LanPeer
from petnest.models.settings import Settings
from petnest.ui.lan_interaction_dialog import LanInteractionDialog


def _jpeg_data() -> bytes:
    output = BytesIO()
    Image.new("RGB", (24, 16), (230, 100, 120)).save(output, format="JPEG")
    return output.getvalue()


def test_chat_codec_round_trips_text_emoji_and_image() -> None:
    drafts = (
        ChatDraft.text_message("receiver", "你好，局域网"),
        ChatDraft.emoji("receiver", "😊"),
        ChatDraft.image("receiver", _jpeg_data(), "photo.jpg"),
    )

    decoded = []
    for draft in drafts:
        message = draft.to_message(sender_device_id="sender", sender_name="发送方")
        frame = LanPacketCodec.encode_chat_frame(message)
        size = int.from_bytes(frame[:4], "big")
        assert size == len(frame) - 4
        decoded.append(LanPacketCodec.decode_chat_message(frame[4:], local_device_id="receiver"))

    assert [item.kind for item in decoded] == [
        ChatMessageKind.TEXT,
        ChatMessageKind.EMOJI,
        ChatMessageKind.IMAGE,
    ]
    assert decoded[0].text == "你好，局域网"
    assert decoded[2].image_data == _jpeg_data()


def test_chat_codec_rejects_a_message_for_another_device() -> None:
    message = ChatDraft.text_message("receiver", "hello").to_message(
        sender_device_id="sender",
        sender_name="Sender",
    )
    frame = LanPacketCodec.encode_chat_frame(message)

    try:
        LanPacketCodec.decode_chat_message(frame[4:], local_device_id="someone-else")
    except LanProtocolError as error:
        assert "目标设备" in str(error)
    else:
        raise AssertionError("message addressed to another device must be rejected")


def test_chat_codec_marks_a_room_message_for_the_receiving_device() -> None:
    room_message = ChatDraft.group_text_message("大家好").to_message(
        sender_device_id="sender",
        sender_name="Sender",
    )
    frame = LanPacketCodec.encode_chat_frame(
        replace(room_message, target_device_id="receiver")
    )

    decoded = LanPacketCodec.decode_chat_message(
        frame[4:],
        local_device_id="receiver",
    )

    assert decoded.is_group is True
    assert decoded.peer_device_id("receiver") == "*"
    assert decoded.text == "大家好"
    assert decoded.scope is ChatScope.LAN_ROOM


def test_chat_codec_round_trips_alert_group_without_changing_legacy_room_wire_scope() -> None:
    room_message = ChatDraft.group_text_message("普通群聊").to_message(
        sender_device_id="sender",
        sender_name="Sender",
    )
    assert LanPacketCodec.chat_message(replace(room_message, target_device_id="receiver"))["scope"] == "group"

    alert_message = ChatDraft.alert_group_text_message("预警组消息").to_message(
        sender_device_id="sender",
        sender_name="Sender",
    )
    frame = LanPacketCodec.encode_chat_frame(replace(alert_message, target_device_id="receiver"))
    decoded = LanPacketCodec.decode_chat_message(frame[4:], local_device_id="receiver")

    assert decoded.scope is ChatScope.ALERT_GROUP
    assert decoded.is_group is True
    assert decoded.peer_device_id("receiver") == "@lan-alert-group"


def test_service_fans_alert_group_chat_only_to_joined_compatible_peers(qtbot) -> None:
    service = LanInteractionService(
        device_id="sender",
        display_name="发送方",
        pet_name="平安",
        port=0,
        alert_group_joined=True,
        interface_provider=lambda: (),
    )
    sent: list[str] = []
    try:
        assert service.start()
        service._peers = {
            "joined": LanPeer(
                "joined",
                "甲",
                ip_address="127.0.0.1",
                port=19001,
                alert_group_supported=True,
                alert_group_joined=True,
            ),
            "left": LanPeer(
                "left",
                "乙",
                ip_address="127.0.0.1",
                port=19002,
                alert_group_supported=True,
                alert_group_joined=False,
            ),
            "legacy": LanPeer("legacy", "丙", ip_address="127.0.0.1", port=19003),
        }
        service._start_chat_send = lambda peer, _frame, _message: sent.append(peer.device_id)

        assert service.send_chat(ChatDraft.alert_group_text_message("注意安全"))

        assert sent == ["joined"]
    finally:
        service.stop()


def test_chat_codec_rejects_image_bytes_that_are_not_a_safe_jpeg() -> None:
    message = ChatDraft.image("receiver", b"not-an-image", "photo.jpg").to_message(
        sender_device_id="sender",
        sender_name="Sender",
    )
    frame = LanPacketCodec.encode_chat_frame(message)

    try:
        LanPacketCodec.decode_chat_message(frame[4:], local_device_id="receiver")
    except LanProtocolError as error:
        assert "图片" in str(error)
    else:
        raise AssertionError("invalid image bytes must be rejected")


def test_prepare_chat_image_resizes_and_encodes_a_bounded_jpeg(tmp_path) -> None:
    source = tmp_path / "假期 photo.png"
    Image.new("RGBA", (2_400, 1_800), (90, 140, 220, 180)).save(source)

    data, name = prepare_chat_image(source)

    assert name == "假期 photo.jpg"
    assert len(data) <= 1_500_000
    with Image.open(BytesIO(data)) as result:
        assert result.format == "JPEG"
        assert max(result.size) <= 1_600


def test_services_exchange_text_and_image_over_local_tcp(qtbot) -> None:
    app = QCoreApplication.instance() or QCoreApplication([])
    del app
    sender = LanInteractionService(
        device_id="sender",
        display_name="发送方",
        pet_name="平安",
        port=0,
    )
    receiver = LanInteractionService(
        device_id="receiver",
        display_name="接收方",
        pet_name="橘猫",
        port=0,
    )
    received = []
    receiver.chat_message_received.connect(received.append)
    try:
        assert sender.start()
        assert receiver.start()
        assert sender.probe_peer("127.0.0.1", receiver.port)
        qtbot.waitUntil(
            lambda: any(peer.device_id == "receiver" for peer in sender.peers())
            and any(peer.device_id == "sender" for peer in receiver.peers()),
            timeout=2_000,
        )

        assert sender.send_chat(ChatDraft.text_message("receiver", "你好"))
        qtbot.waitUntil(lambda: len(received) == 1, timeout=2_000)
        image_data = _jpeg_data()
        assert sender.send_chat(ChatDraft.image("receiver", image_data, "pet.jpg"))
        qtbot.waitUntil(lambda: len(received) == 2, timeout=2_000)

        assert [(item.kind, item.text) for item in received] == [
            (ChatMessageKind.TEXT, "你好"),
            (ChatMessageKind.IMAGE, None),
        ]
        assert received[1].image_data == image_data
        assert len(sender.chat_messages("receiver")) == 2
        assert len(receiver.chat_messages("sender")) == 2
        assert all(item.created_at <= int(time()) for item in received)
    finally:
        sender.stop()
        receiver.stop()


def test_service_fans_group_chat_out_to_all_current_lan_peers(qtbot) -> None:
    sender = LanInteractionService(
        device_id="sender",
        display_name="发送方",
        pet_name="平安",
        port=0,
    )
    first = LanInteractionService(
        device_id="first",
        display_name="甲",
        pet_name="橘猫",
        port=0,
    )
    second = LanInteractionService(
        device_id="second",
        display_name="乙",
        pet_name="白猫",
        port=0,
    )
    first_received = []
    second_received = []
    first.chat_message_received.connect(first_received.append)
    second.chat_message_received.connect(second_received.append)
    try:
        assert sender.start()
        assert first.start()
        assert second.start()
        assert sender.probe_peer("127.0.0.1", first.port)
        qtbot.waitUntil(
            lambda: any(peer.device_id == "first" for peer in sender.peers()),
            timeout=2_000,
        )
        assert sender.probe_peer("127.0.0.1", second.port)
        qtbot.waitUntil(
            lambda: any(peer.device_id == "second" for peer in sender.peers())
            and any(peer.device_id == "sender" for peer in second.peers()),
            timeout=2_000,
        )

        assert sender.send_chat(ChatDraft.group_text_message("局域网开会啦"))
        qtbot.waitUntil(
            lambda: len(first_received) == 1 and len(second_received) == 1,
            timeout=2_000,
        )

        assert first_received[0].is_group is True
        assert second_received[0].is_group is True
        assert first_received[0].message_id == second_received[0].message_id
        assert len(sender.chat_messages("*")) == 1
        assert len(first.chat_messages("*")) == 1
        assert len(second.chat_messages("*")) == 1
    finally:
        sender.stop()
        first.stop()
        second.stop()


def test_chat_page_sends_text_and_emoji_to_selected_lan_peer(qtbot) -> None:
    sent: list[ChatDraft] = []
    dialog = LanInteractionDialog(
        settings=Settings(device_id="local"),
        peers=[LanPeer("peer", "邻居", "橘猫", "192.168.1.20", 18_487)],
        on_chat_send=lambda draft: sent.append(draft) or True,
    )
    qtbot.addWidget(dialog)
    dialog.mode_tabs.setCurrentIndex(3)
    dialog.chat_input.setPlainText("今天好吗？")

    assert dialog.send_button.isEnabled()
    dialog.send_button.click()
    dialog.emoji_buttons[0].click()

    assert sent == [
        ChatDraft.text_message("peer", "今天好吗？"),
        ChatDraft.emoji("peer", "😊"),
    ]
    assert dialog.chat_input.toPlainText() == ""


def test_chat_page_sends_group_text_and_emoji_to_every_visible_peer(qtbot) -> None:
    sent: list[ChatDraft] = []
    dialog = LanInteractionDialog(
        settings=Settings(device_id="local"),
        peers=[
            LanPeer("first", "甲", "橘猫", "192.168.1.20", 18_487),
            LanPeer("second", "乙", "白猫", "192.168.1.21", 18_487),
        ],
        on_chat_send=lambda draft: sent.append(draft) or True,
    )
    qtbot.addWidget(dialog)

    assert dialog.peer_list.item(0).text().startswith("局域网群聊")
    dialog.peer_list.setCurrentRow(0)
    assert dialog.mode_tabs.currentIndex() == 3
    assert "2 台" in dialog.recipient_label.text()
    dialog.chat_input.setPlainText("大家好")
    dialog.send_button.click()
    dialog.emoji_buttons[0].click()

    assert sent == [
        ChatDraft.group_text_message("大家好"),
        ChatDraft.group_emoji("😊"),
    ]


def test_chat_page_keeps_group_and_private_conversations_separate(qtbot) -> None:
    dialog = LanInteractionDialog(
        settings=Settings(device_id="local"),
        peers=[LanPeer("peer", "邻居", "橘猫", "192.168.1.20", 18_487)],
        chat_messages=[
            LanChatMessage(
                "private-message",
                "peer",
                "邻居",
                "local",
                ChatMessageKind.TEXT,
                1,
                text="私聊内容",
            ),
            LanChatMessage(
                "group-message",
                "peer",
                "邻居",
                "local",
                ChatMessageKind.TEXT,
                2,
                text="群聊内容",
                is_group=True,
            ),
        ],
    )
    qtbot.addWidget(dialog)
    dialog.mode_tabs.setCurrentIndex(3)

    assert dialog.chat_list.count() == 1
    assert "私聊内容" in dialog.chat_list.item(0).text()

    dialog.peer_list.setCurrentRow(0)

    assert dialog.chat_list.count() == 1
    assert "群聊内容" in dialog.chat_list.item(0).text()


def test_chat_page_prepares_an_image_for_group_chat(tmp_path, qtbot, monkeypatch) -> None:
    source = tmp_path / "group.png"
    Image.new("RGB", (120, 80), (120, 170, 230)).save(source)
    sent: list[ChatDraft] = []
    monkeypatch.setattr(
        "petnest.ui.lan_interaction_dialog.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(source), ""),
    )
    dialog = LanInteractionDialog(
        settings=Settings(device_id="local"),
        peers=[LanPeer("peer", "邻居", "橘猫", "192.168.1.20", 18_487)],
        on_chat_send=lambda draft: sent.append(draft) or True,
    )
    qtbot.addWidget(dialog)
    dialog.peer_list.setCurrentRow(0)

    dialog.chat_image_button.click()

    assert len(sent) == 1
    assert sent[0].kind is ChatMessageKind.IMAGE
    assert sent[0].is_group is True


def test_chat_page_prepares_and_sends_selected_image(tmp_path, qtbot, monkeypatch) -> None:
    source = tmp_path / "pet.png"
    Image.new("RGB", (120, 80), (230, 100, 120)).save(source)
    sent: list[ChatDraft] = []
    monkeypatch.setattr(
        "petnest.ui.lan_interaction_dialog.QFileDialog.getOpenFileName",
        lambda *_args, **_kwargs: (str(source), ""),
    )
    dialog = LanInteractionDialog(
        settings=Settings(device_id="local"),
        peers=[LanPeer("peer", "邻居", "橘猫", "192.168.1.20", 18_487)],
        on_chat_send=lambda draft: sent.append(draft) or True,
    )
    qtbot.addWidget(dialog)
    dialog.mode_tabs.setCurrentIndex(3)

    dialog.chat_image_button.click()

    assert len(sent) == 1
    assert sent[0].kind is ChatMessageKind.IMAGE
    assert sent[0].image_name == "pet.jpg"
    assert sent[0].image_data
