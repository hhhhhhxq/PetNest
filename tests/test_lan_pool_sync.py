"""Distributed roster anti-entropy synchronization tests."""

from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal

from petnest.core.lan_pool_protocol import LanPoolPacketCodec, PoolRecords
from petnest.core.lan_pool_roster import PoolRosterStore
from petnest.core.lan_pool_sync import LanPoolSyncService
from petnest.core.lan_service import LanInteractionService
from petnest.models.lan_pool import PoolMemberRecord, PoolMemberState
from petnest.models.lan_interaction import LanPeer


class FakeLanService(QObject):
    pool_heartbeat_received = Signal(object)
    pool_frame_received = Signal(object)
    peer_changed = Signal(object)
    manual_probe_succeeded = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.heartbeats: list[bytes] = []
        self.frames: list[tuple[str, bytes]] = []
        self.probes: list[tuple[str, int, str | None]] = []
        self.peer_values = ()
        self.transport_available = True

    def send_pool_heartbeat(self, packet: bytes, targets=()) -> bool:
        if not self.transport_available:
            return False
        self.heartbeats.append(packet)
        return True

    def send_pool_frame(self, target_device_id: str, frame: bytes) -> bool:
        if not self.transport_available:
            return False
        self.frames.append((target_device_id, frame))
        return True

    def probe_peer(self, ip_address: str, port: int = 18487, *, expected_device_id=None) -> bool:
        if not self.transport_available:
            return False
        self.probes.append((ip_address, port, expected_device_id))
        return True

    def peers(self):
        return self.peer_values


def record(device_id: str, revision: int, *, state=PoolMemberState.JOINED) -> PoolMemberRecord:
    octet = sum(ord(char) for char in device_id) % 200 + 20
    return PoolMemberRecord(
        device_id,
        device_id,
        state,
        revision,
        f"192.168.1.{octet}",
        18487,
        1,
    )


def _sync_node(root, device_id: str, records=()):
    roster = PoolRosterStore(root / "roster.json", local_device_id=device_id)
    records = tuple(records)
    own = next((item for item in records if item.device_id == device_id), None)
    if own is not None:
        roster.update_local(
            display_name=own.display_name,
            state=own.state,
            ip_address=own.ip_address,
            port=own.port,
        )
    remote = tuple(item for item in records if item.device_id != device_id)
    roster.merge(remote, directly_verified_ids={item.device_id for item in remote})
    lan = FakeLanService()
    candidates: list[tuple[str, str, int, str]] = []
    sync = LanPoolSyncService(
        lan,
        roster,
        display_name=lambda: device_id,
        offer_candidate=lambda target_id, ip, port, referrer: (
            candidates.append((target_id, ip, port, referrer)) or True
        ),
    )
    return SimpleNamespace(
        device_id=device_id,
        roster=roster,
        lan=lan,
        sync=sync,
        candidates=candidates,
    )


def _deliver_pending_frames(sender, receiver) -> None:
    while sender.lan.frames:
        target, frame = sender.lan.frames.pop(0)
        assert target == receiver.device_id
        receiver.sync.receive_frame(sender.device_id, LanPoolPacketCodec.decode_frame(frame))


def _exchange(left, right, rounds: int = 4) -> None:
    left.sync.send_summary(right.device_id)
    right.sync.send_summary(left.device_id)
    for _round in range(rounds):
        _deliver_pending_frames(left, right)
        _deliver_pending_frames(right, left)


def test_sync_exchanges_only_missing_or_older_records(qtbot, tmp_path) -> None:
    a = _sync_node(tmp_path / "a", "a", records=(record("a", 1), record("b", 2)))
    d = _sync_node(tmp_path / "d", "d", records=(record("a", 1), record("d", 1)))

    _exchange(a, d)

    expected = {"a": 1, "b": 2, "d": 1}
    assert a.roster.revisions() == expected
    assert d.roster.revisions() == expected


def test_bridge_syncs_member_that_joins_while_other_side_is_offline(qtbot, tmp_path) -> None:
    a = _sync_node(tmp_path / "a", "a", records=(record("a", 1), record("d", 1)))
    d = _sync_node(tmp_path / "d", "d", records=(record("a", 1), record("d", 1)))
    a.roster.merge((record("b", 1),), directly_verified_ids={"b"})
    d.lan.transport_available = False

    a.sync.send_summary("d")
    assert "b" not in d.roster.records()

    d.lan.transport_available = True
    _exchange(a, d)

    assert d.roster.records()["b"].state is PoolMemberState.JOINED


def test_received_third_party_records_are_merged_and_queued_for_direct_verification(qtbot, tmp_path) -> None:
    a = _sync_node(tmp_path / "a", "a", records=(record("a", 1),))
    third_party = record("b", 1)

    a.sync.receive_records("d", PoolRecords("d", (third_party,)))

    assert a.roster.records()["b"] == third_party
    assert a.candidates == [("b", third_party.ip_address, third_party.port, "d")]
    assert a.lan.probes == []


def test_left_third_party_record_is_synced_but_not_offered_for_endpoint_verification(
    qtbot, tmp_path
) -> None:
    a = _sync_node(tmp_path / "a", "a", records=(record("a", 1),))
    left = record("b", 2, state=PoolMemberState.LEFT)

    a.sync.receive_records("d", PoolRecords("d", (left,)))

    assert a.roster.records()["b"] == left
    assert a.candidates == []


def test_sync_does_not_restore_a_foreign_identity_at_the_local_endpoint(qtbot, tmp_path) -> None:
    local = record("a", 1)
    a = _sync_node(tmp_path / "a", "a", records=(local,))
    ghost = PoolMemberRecord(
        "ghost",
        "用户-GHOST",
        PoolMemberState.JOINED,
        1,
        local.ip_address,
        local.port,
        1,
    )

    a.sync.receive_records("d", PoolRecords("d", (ghost,)))

    assert set(a.roster.records()) == {"a"}
    assert a.lan.probes == []


def test_local_join_and_leave_increment_revision_and_emit_heartbeat(qtbot, tmp_path) -> None:
    a = _sync_node(tmp_path / "a", "a")

    joined = a.sync.set_local_joined(True, ip_address="192.168.1.20", port=18487)
    left = a.sync.set_local_joined(False, ip_address="192.168.1.20", port=18487)

    assert (joined.revision, left.revision) == (1, 2)
    assert len(a.lan.heartbeats) == 2
    assert a.roster.records()["a"].state is PoolMemberState.LEFT


def test_periodic_sync_rotates_across_more_than_three_reachable_peers(qtbot, tmp_path) -> None:
    a = _sync_node(tmp_path / "a", "a", records=(record("a", 1),))
    a.lan.peer_values = tuple(
        LanPeer(
            f"peer-{index}", f"成员{index}", ip_address=f"192.168.1.{index + 20}",
            port=18487, online=True,
        )
        for index in range(5)
    )

    a.sync.sync_reachable_peers()
    first = {target for target, _frame in a.lan.frames}
    a.lan.frames.clear()
    a.sync.sync_reachable_peers()
    second = {target for target, _frame in a.lan.frames}

    assert len(first) <= 3
    assert len(second) <= 3
    assert first | second == {f"peer-{index}" for index in range(5)}


def test_real_services_sync_members_joining_after_the_bridge(qtbot, tmp_path) -> None:
    nodes = []

    def start_chat_service(service: LanInteractionService) -> None:
        for _attempt in range(5):
            assert service.start()
            if service.chat_is_available:
                return
            service.stop()
            qtbot.wait(50)
        raise AssertionError("TCP chat port did not become available after 5 retries")

    try:
        for device_id in ("a", "d"):
            lan = LanInteractionService(
                device_id=device_id,
                display_name=device_id.upper(),
                pet_name="平安",
                port=0,
                interface_provider=lambda: (),
            )
            start_chat_service(lan)
            roster = PoolRosterStore(tmp_path / device_id / "roster.json", local_device_id=device_id)
            roster.update_local(
                display_name=device_id.upper(), state=PoolMemberState.JOINED,
                ip_address="127.0.0.1", port=lan.port,
            )
            sync = LanPoolSyncService(lan, roster, display_name=lambda value=device_id: value.upper())
            sync.start()
            nodes.append(SimpleNamespace(device_id=device_id, lan=lan, roster=roster, sync=sync))
        a, d = nodes
        assert a.lan.probe_peer("127.0.0.1", d.lan.port)
        qtbot.waitUntil(
            lambda: set(a.roster.joined_device_ids()) == {"a", "d"}
            and set(d.roster.joined_device_ids()) == {"a", "d"},
            timeout=3_000,
        )

        for device_id, entry in (("b", a), ("e", d)):
            lan = LanInteractionService(
                device_id=device_id,
                display_name=device_id.upper(),
                pet_name="平安",
                port=0,
                interface_provider=lambda: (),
            )
            start_chat_service(lan)
            roster = PoolRosterStore(tmp_path / device_id / "roster.json", local_device_id=device_id)
            roster.update_local(
                display_name=device_id.upper(), state=PoolMemberState.JOINED,
                ip_address="127.0.0.1", port=lan.port,
            )
            sync = LanPoolSyncService(lan, roster, display_name=lambda value=device_id: value.upper())
            sync.start()
            node = SimpleNamespace(device_id=device_id, lan=lan, roster=roster, sync=sync)
            nodes.append(node)
            assert node.lan.probe_peer("127.0.0.1", entry.lan.port)

        qtbot.waitUntil(
            lambda: all(
                set(node.roster.joined_device_ids()) == {"a", "b", "d", "e"}
                for node in nodes
            ),
            timeout=6_000,
        )
    finally:
        for node in reversed(nodes):
            node.sync.stop()
            node.lan.stop()
        qtbot.wait(50)
