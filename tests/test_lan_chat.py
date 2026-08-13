"""LAN chat framing, image preparation, transport and UI tests."""

from __future__ import annotations

from io import BytesIO
import os
from time import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QCoreApplication

from petnest.core.lan_chat import prepare_chat_image
from petnest.core.lan_interaction import LanPacketCodec, LanProtocolError
from petnest.core.lan_service import LanInteractionService
from petnest.models.lan_interaction import ChatDraft, ChatMessageKind, LanPeer
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
