"""宠物与动作中心页面的统一底部命令协议。"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget


@dataclass(frozen=True, slots=True)
class ExchangeFooterState:
    status: str
    primary_text: str
    primary_enabled: bool = True
    secondary_text: str | None = None
    secondary_enabled: bool = True


class ExchangePage(QWidget):
    footer_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._footer_state = ExchangeFooterState("", "继续", False)

    def footer_state(self) -> ExchangeFooterState:
        return self._footer_state

    def set_footer(
        self,
        *,
        status: str,
        primary_text: str,
        primary_enabled: bool = True,
        secondary_text: str | None = None,
        secondary_enabled: bool = True,
    ) -> None:
        self._footer_state = ExchangeFooterState(
            status, primary_text, primary_enabled, secondary_text, secondary_enabled
        )
        self.footer_changed.emit()

    def trigger_primary(self) -> None:
        raise NotImplementedError

    def trigger_secondary(self) -> None:
        return

    def request_leave(self) -> bool:
        return True

    def request_close(self) -> bool:
        return self.request_leave()

    def deactivate(self) -> None:
        return


__all__ = ["ExchangeFooterState", "ExchangePage"]
