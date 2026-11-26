"""Distributed roster anti-entropy synchronization tests."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QHostAddress

import petnest.core.lan_pool_sync as sync_module
from petnest.core.lan_pool_protocol import POOL_ID, LanPoolPacketCodec, PoolHeartbeat, PoolRecords, PoolSummary
from petnest.core.lan_pool_roster import MAX_POOL_RECORDS, PoolRosterStore
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


def _full_roster_records(device_id: str, unique_id: str) -> tuple[PoolMemberRecord, ...]:
    common = tuple(
        replace(record(f"shared-{index}", 1), ip_address=f"10.0.{index // 250}.{index % 250 + 1}")
        for index in range(MAX_POOL_RECORDS - 2)
    )
    owner_ip = "10.1.0.1" if device_id == "a" else "10.1.0.2"
    extra_ip = "10.2.0.1" if device_id == "a" else "10.2.0.2"
    return (replace(record(device_id, 1), ip_address=owner_ip), *common,
            replace(record(unique_id, 1), ip_address=extra_ip))


def test_full_divergent_rosters_do_not_generate_an_endless_sync_loop(qtbot, tmp_path) -> None:
    a = _sync_node(tmp_path / "a", "a", records=_full_roster_records("a", "only-a"))
    b = _sync_node(tmp_path / "b", "b", records=_full_roster_records("b", "only-b"))
    original_a, original_b = a.roster.records(), b.roster.records()
    a.sync.send_summary("b")

    delivered = 0
    while (a.lan.frames or b.lan.frames) and delivered < 40:
        sender, receiver = (a, b) if a.lan.frames else (b, a)
        target, frame = sender.lan.frames.pop(0)
        assert target == receiver.device_id
        receiver.sync.receive_frame(sender.device_id, LanPoolPacketCodec.decode_frame(frame))
        delivered += 1

    assert not a.lan.frames and not b.lan.frames
    assert delivered < 40
    assert a.roster.records() == original_a
    assert b.roster.records() == original_b
    assert PoolRosterStore(a.roster.path, local_device_id="a").records() == original_a
    assert PoolRosterStore(b.roster.path, local_device_id="b").records() == original_b


def test_full_divergent_rosters_stop_over_real_loopback_tcp(qtbot, tmp_path) -> None:
    nodes = []
    sent = []
    try:
        for device_id, unique_id in (("a", "only-a"), ("b", "only-b")):
            lan = LanInteractionService(
                device_id=device_id, display_name=device_id, pet_name="猫", port=0,
                interface_provider=lambda: (),
            )
            assert lan._tcp_server.listen(QHostAddress.SpecialAddress.LocalHost, 0)
            lan._port = lan._tcp_server.serverPort()
            lan._running = True
            roster = PoolRosterStore(tmp_path / device_id / "roster.json", local_device_id=device_id)
            roster.update_local(
                display_name=device_id, state=PoolMemberState.JOINED,
                ip_address="127.0.0.1", port=lan.port,
            )
            roster.merge(_full_roster_records(device_id, unique_id)[1:])
            sync = LanPoolSyncService(lan, roster, display_name=lambda value=device_id: value)
            original_send = lan.send_pool_frame

            def record_send(target, frame, original_send=original_send):
                sent.append((target, len(frame)))
                return original_send(target, frame)

            lan.send_pool_frame = record_send
            nodes.append(SimpleNamespace(device_id=device_id, lan=lan, roster=roster, sync=sync))
        a, b = nodes
        for local, remote in ((a, b), (b, a)):
            local.lan._peers[remote.device_id] = LanPeer(
                remote.device_id, remote.device_id, ip_address="127.0.0.1",
                port=remote.lan.port, online=True,
            )

        assert a.sync.send_summary("b")
        qtbot.waitUntil(lambda: len(sent) >= 5, timeout=3_000)
        qtbot.wait(250)

        assert len(sent) < 12
        assert not any(node.lan._outgoing_chat_sockets for node in nodes)
        assert not any(node.lan._incoming_chat_buffers for node in nodes)
        assert all(len(node.roster.records()) == MAX_POOL_RECORDS for node in nodes)
    finally:
        for node in nodes:
            node.sync.stop()
            node.lan.stop()


def test_duplicate_two_way_summaries_retry_and_react_to_changes(qtbot, tmp_path, monkeypatch) -> None:
    now = [0.0]
    monkeypatch.setattr(sync_module, "monotonic", lambda: now[0])
    a = _sync_node(tmp_path / "a", "a", records=(record("a", 1),))
    summary = PoolSummary("b", (("b", 1),))

    a.sync.receive_summary("b", summary)
    assert len(a.lan.frames) == 2
    a.sync.receive_summary("b", summary)
    assert len(a.lan.frames) == 2
    now[0] += sync_module._SUMMARY_RETRY_SECONDS
    a.sync.receive_summary("b", summary)
    assert len(a.lan.frames) == 4

    local = a.roster.records()["a"]
    a.roster.update_local(
        display_name="new name", state=local.state, ip_address=local.ip_address, port=local.port,
    )
    a.sync.receive_summary("b", summary)
    assert len(a.lan.frames) == 6
    a.sync.receive_summary("b", PoolSummary("b", (("b", 2),)))
    assert len(a.lan.frames) == 8


def test_failed_sync_send_is_not_suppressed_on_immediate_retry(qtbot, tmp_path) -> None:
    a = _sync_node(tmp_path / "a", "a", records=(record("a", 1),))
    summary = PoolSummary("b", (("b", 1),))
    a.lan.transport_available = False
    a.sync.receive_summary("b", summary)
    a.lan.transport_available = True

    a.sync.receive_summary("b", summary)

    assert len(a.lan.frames) == 2


def test_full_roster_still_updates_known_records_and_reports_missing_capacity(qtbot, tmp_path) -> None:
    a = _sync_node(tmp_path / "a", "a", records=_full_roster_records("a", "only-a"))
    statuses = []
    a.sync.sync_status_changed.connect(statuses.append)
    updated = replace(a.roster.records()["shared-1"], revision=2)
    unknown = replace(record("new-device", 1), ip_address="10.3.0.1")

    a.sync.receive_records("b", PoolRecords("b", (updated, unknown)))

    assert a.roster.records()[updated.device_id] == updated
    assert unknown.device_id not in a.roster.records()
    assert len(a.roster.records()) == MAX_POOL_RECORDS
    assert len(statuses) == 1 and "名单已满" in statuses[0]

    heartbeat = PoolHeartbeat(POOL_ID, "new-device", unknown, "0" * 64, 1)
    a.sync._on_heartbeat_context(SimpleNamespace(message=heartbeat, address=unknown.ip_address,
                                                 source_port=unknown.port))
    assert len(a.roster.records()) == MAX_POOL_RECORDS
    assert len(statuses) == 1


def test_nearly_full_roster_uses_remaining_slots_for_verified_sender(qtbot, tmp_path) -> None:
    almost_full = _full_roster_records("a", "only-a")[:-2]
    a = _sync_node(tmp_path / "a", "a", records=almost_full)
    assert len(a.roster.records()) == MAX_POOL_RECORDS - 2
    sender = replace(record("z-sender", 1), ip_address="10.3.0.1")
    first = replace(record("a-first", 1), ip_address="10.3.0.2")
    second = replace(record("b-second", 1), ip_address="10.3.0.3")

    a.sync.receive_records(sender.device_id, PoolRecords(sender.device_id, (sender, first, second)))

    assert set(a.roster.records()).issuperset({sender.device_id, first.device_id})
    assert second.device_id not in a.roster.records()
    assert len(a.roster.records()) == MAX_POOL_RECORDS


def test_summary_response_cache_is_bounded(qtbot, tmp_path) -> None:
    a = _sync_node(tmp_path / "a", "a", records=(record("a", 1),))
    for index in range(sync_module._MAX_SUMMARY_RESPONSE_CACHE + 10):
        sender = f"sender-{index}"
        a.sync.receive_summary(sender, PoolSummary(sender, ((sender, 1),)))
    assert len(a.sync._summary_response_cache) == sync_module._MAX_SUMMARY_RESPONSE_CACHE


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
