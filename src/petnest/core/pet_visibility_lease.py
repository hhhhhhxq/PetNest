"""记录下班提醒是否拥有恢复桌宠可见性的责任。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PetVisibilityLease:
    """只恢复由当前提醒临时隐藏、且未被用户接管的桌宠。"""

    is_active: bool = False
    _restore_required: bool = False

    def acquire(self, *, was_visible: bool) -> bool:
        """首次获取时记录原始状态，并返回调用方是否需要执行隐藏。"""
        if self.is_active:
            return False
        self.is_active = True
        self._restore_required = bool(was_visible)
        return self._restore_required

    def user_took_control(self) -> None:
        """用户通过托盘或二次启动接管后，自动恢复不再生效。"""
        self.cancel()

    def release(self) -> bool:
        """释放并返回是否应显示此前由提醒隐藏的桌宠。"""
        should_restore = self.is_active and self._restore_required
        self.cancel()
        return should_restore

    def cancel(self) -> None:
        """无恢复副作用地清空租约，供退出流程使用。"""
        self.is_active = False
        self._restore_required = False


__all__ = ["PetVisibilityLease"]
