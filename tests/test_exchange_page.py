from dataclasses import FrozenInstanceError

import pytest

from petnest.ui.exchange_page import ExchangeFooterState, ExchangePage


def test_exchange_page_publishes_status_and_footer_changes(qtbot: object) -> None:
    page = ExchangePage()
    qtbot.addWidget(page)
    assert page.footer_state() == ExchangeFooterState("", "继续", False)

    changes: list[ExchangeFooterState] = []
    page.footer_changed.connect(lambda: changes.append(page.footer_state()))

    page.set_footer(
        status="已读取来源",
        primary_text="下一步",
        primary_enabled=True,
        secondary_text="上一步",
    )

    assert changes[-1] == ExchangeFooterState(
        status="已读取来源",
        primary_text="下一步",
        primary_enabled=True,
        secondary_text="上一步",
        secondary_enabled=True,
    )
    assert page.request_leave() is True


def test_exchange_page_footer_state_is_frozen(qtbot: object) -> None:
    page = ExchangePage()
    qtbot.addWidget(page)
    state = page.footer_state()

    with pytest.raises(FrozenInstanceError):
        setattr(state, "status", "changed")


def test_exchange_page_requires_primary_command_override(qtbot: object) -> None:
    page = ExchangePage()
    qtbot.addWidget(page)

    with pytest.raises(NotImplementedError):
        page.trigger_primary()
