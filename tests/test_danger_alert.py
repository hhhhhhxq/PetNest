"""Danger alert confirmation and full-screen overlay tests."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from petnest.models.lan_interaction import LanPeer
from petnest.ui.danger_alert import DangerAlertConfirmDialog, DangerAlertOverlay


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


def _local_peaks(values: list[int]) -> int:
    return sum(
        1
        for index in range(1, len(values) - 1)
        if values[index] > values[index - 1] and values[index] > values[index + 1]
    )


def test_confirm_dialog_lists_online_and_unavailable_recipients(qtbot) -> None:
    dialog = DangerAlertConfirmDialog(
        online=(LanPeer("one", "小林"), LanPeer("two", "小陈")),
        unavailable=(LanPeer("three", "小周", online=False, saved=True),),
    )
    qtbot.addWidget(dialog)

    assert "小林" in dialog.online_label.text()
    assert "小陈" in dialog.online_label.text()
    assert "小周" in dialog.unavailable_label.text()
    assert dialog.send_button.text() == "立即发送"
    assert dialog.send_button.isEnabled()
    assert dialog.message_input.placeholderText() == "留空则只显示红色警示"
    dialog.message_input.setText("  请立即撤离  ")
    assert dialog.alert_message() == "请立即撤离"
    assert dialog.message_input.maxLength() == 30


def test_confirm_dialog_disables_send_when_no_recipient_is_online(qtbot) -> None:
    dialog = DangerAlertConfirmDialog(
        online=(),
        unavailable=(LanPeer("three", "小周", online=False, saved=True),),
    )
    qtbot.addWidget(dialog)

    assert "当前没有其他在线成员" in dialog.online_label.text()
    assert not dialog.send_button.isEnabled()


def test_overlay_uses_target_geometry_three_peaks_and_mouse_passthrough(qtbot) -> None:
    clock = FakeClock()
    overlay = DangerAlertOverlay(clock=clock)
    qtbot.addWidget(overlay)
    geometry = QRect(100, 200, 1920, 1080)

    overlay.show_alert("alert-1", "小林", geometry)

    assert overlay.geometry() == geometry
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert overlay.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert overlay.sender_name == "小林"
    assert overlay.alert_message == ""

    observed: list[int] = []
    for elapsed in (0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.49):
        clock.value = elapsed
        overlay._refresh()
        observed.append(overlay.red_alpha)
    assert _local_peaks(observed) == 3

    clock.value = 1.5
    overlay._refresh()
    assert not overlay.isVisible()


def test_overlay_deduplicates_the_same_alert_id(qtbot) -> None:
    clock = FakeClock()
    overlay = DangerAlertOverlay(clock=clock)
    qtbot.addWidget(overlay)
    geometry = QRect(0, 0, 800, 600)
    overlay.show_alert("alert-1", "小林", geometry)
    first_started_at = overlay.started_at

    clock.value = 0.4
    overlay.show_alert("alert-1", "其他人", geometry)

    assert overlay.started_at == first_started_at
    assert overlay.sender_name == "小林"


def test_overlay_keeps_optional_message_for_center_display(qtbot) -> None:
    overlay = DangerAlertOverlay(clock=FakeClock())
    qtbot.addWidget(overlay)

    overlay.show_alert("alert-custom", "小林", QRect(0, 0, 800, 600), "请立即撤离")

    assert overlay.alert_message == "请立即撤离"


def test_overlay_renders_darker_edges_and_corners_than_the_center(qtbot) -> None:
    overlay = DangerAlertOverlay(clock=FakeClock())
    qtbot.addWidget(overlay)
    overlay.resize(600, 400)
    overlay.red_alpha = 160
    image = QImage(600, 400, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    overlay._paint_warning_background(painter)
    painter.end()

    center = QColor(image.pixelColor(300, 200))
    edge = QColor(image.pixelColor(8, 200))
    corner = QColor(image.pixelColor(8, 8))
    assert edge.alpha() >= center.alpha() + 40
    assert corner.alpha() >= edge.alpha()
    assert edge.red() > edge.green() * 2


def test_overlay_edge_glow_fades_continuously_without_solid_bands(qtbot) -> None:
    overlay = DangerAlertOverlay(clock=FakeClock())
    qtbot.addWidget(overlay)
    overlay.resize(600, 400)
    overlay.red_alpha = 160
    image = QImage(600, 400, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    overlay._paint_warning_background(painter)
    painter.end()

    alphas = [image.pixelColor(x, 200).alpha() for x in (1, 3, 6, 10, 16)]
    assert all(outer > inner for outer, inner in zip(alphas, alphas[1:]))
