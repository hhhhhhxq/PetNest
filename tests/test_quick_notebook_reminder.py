from __future__ import annotations

from PySide6.QtCore import QRect, QTimer, Qt

from petnest.ui.quick_notebook_reminder import QuickNotebookReminderCard


def test_reminder_card_is_persistent_and_exposes_actions(qtbot) -> None:
    card = QuickNotebookReminderCard()
    qtbot.addWidget(card)
    completed: list[str] = []
    snoozed: list[str] = []
    opened: list[str] = []
    card.completed.connect(completed.append)
    card.snoozed.connect(snoozed.append)
    card.open_requested.connect(opened.append)

    card.show_reminder("r1", "把方案发给小林", QRect(100, 100, 80, 80))

    assert card.isVisible()
    assert card.message_label.text() == "把方案发给小林"
    assert card.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert card.findChild(QTimer, "dismissTimer") is None
    card.complete_button.click()
    assert completed == ["r1"]


def test_reminder_card_snooze_and_open_emit_current_identifier(qtbot) -> None:
    card = QuickNotebookReminderCard()
    qtbot.addWidget(card)
    snoozed: list[str] = []
    opened: list[str] = []
    card.snoozed.connect(snoozed.append)
    card.open_requested.connect(opened.append)
    card.show_reminder("r2", "整理项目周报", QRect(100, 100, 80, 80))

    card.snooze_button.click()
    card.show_reminder("r2", "整理项目周报", QRect(100, 100, 80, 80))
    card.open_button.click()

    assert snoozed == ["r2"]
    assert opened == ["r2"]


def test_reminder_card_does_not_accept_focus_until_clicked(qtbot) -> None:
    card = QuickNotebookReminderCard()
    qtbot.addWidget(card)

    assert card.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert not card.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
