"""下班提醒临时隐藏桌宠的纯状态租约。"""

from __future__ import annotations

from petnest.core.pet_visibility_lease import PetVisibilityLease


def test_visible_pet_creates_one_restore_responsibility() -> None:
    lease = PetVisibilityLease()

    assert lease.acquire(was_visible=True)
    assert not lease.acquire(was_visible=False)
    assert lease.release()
    assert not lease.release()


def test_hidden_pet_never_creates_restore_responsibility() -> None:
    lease = PetVisibilityLease()

    assert not lease.acquire(was_visible=False)
    assert not lease.release()


def test_user_takeover_cancels_automatic_restore() -> None:
    lease = PetVisibilityLease()
    assert lease.acquire(was_visible=True)

    lease.user_took_control()

    assert not lease.release()


def test_cancel_for_shutdown_never_requests_show() -> None:
    lease = PetVisibilityLease()
    assert lease.acquire(was_visible=True)

    lease.cancel()

    assert not lease.is_active
    assert not lease.release()
