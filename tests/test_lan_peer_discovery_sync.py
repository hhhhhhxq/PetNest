from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from petnest.core.lan_peer_discovery_protocol import (
    PeerDirectory,
    PeerDirectoryCodec,
    PeerEndpointRecord,
)
from petnest.core.lan_peer_discovery_sync import LanPeerDiscoverySyncService
from petnest.core.lan_service import VerifiedPresenceContext
from petnest.models.lan_interaction import LanPeer


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class TokenFactory:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"{self.value:032x}"


class FakeLanService(QObject):
    presence_verified = Signal(object)
    candidate_probe_succeeded = Signal(object)
    peer_directory_received = Signal(object)
    peer_changed = Signal(object)
    peer_removed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.peer_values: tuple[LanPeer, ...] = ()
        self.directories: list[tuple[str, bytes]] = []
        self.probes: list[tuple[str, str, int, str]] = []
        self.cancelled: list[str] = []
        self.renewals: list[tuple[str, int]] = []

    def peers(self) -> tuple[LanPeer, ...]:
        return self.peer_values

    def send_peer_directory(self, target: str, frame: bytes) -> bool:
        self.directories.append((target, frame))
        return True

    def probe_candidate(
        self, device_id: str, ip: str, port: int, *, token: str
    ) -> bool:
        self.probes.append((device_id, ip, port, token))
        return True

    def cancel_candidate_probe(self, token: str) -> None:
        self.cancelled.append(token)

    def send_direct_hello(self, ip: str, port: int) -> bool:
        self.renewals.append((ip, port))
        return True


def peer(device_id: str, ip_address: str) -> LanPeer:
    return LanPeer(
        device_id=device_id,
        display_name=device_id.upper(),
        pet_name="猫",
        ip_address=ip_address,
        port=18487,
        online=True,
    )


def context(
    device_id: str,
    ip_address: str,
    *,
    token: str | None = None,
    assisted: bool = False,
) -> VerifiedPresenceContext:
    return VerifiedPresenceContext(
        peer=peer(device_id, ip_address),
        address=ip_address,
        source_port=18487,
        extensions=("peer_directory_v1", "probe_token_v1"),
        probe_token=token,
        assisted=assisted,
    )


def started_sync() -> tuple[
    LanPeerDiscoverySyncService, FakeLanService, FakeClock, TokenFactory
]:
    lan = FakeLanService()
    clock = FakeClock()
    tokens = TokenFactory()
    sync = LanPeerDiscoverySyncService(
        lan,
        local_device_id="a",
        clock=clock,
        token_factory=tokens,
    )
    sync.start()
    return sync, lan, clock, tokens


def test_bridge_directory_candidate_stays_hidden_until_direct_probe_succeeds(qtbot) -> None:
    sync, lan, _clock, _tokens = started_sync()
    try:
        lan.presence_verified.emit(context("b", "192.168.101.65"))
        directory = PeerDirectory(
            "b", (PeerEndpointRecord("c", "192.168.20.85", 18487, 0),)
        )

        sync.receive_directory("b", directory)

        assert lan.probes == []
        assert sync.endpoint_book.preferred("c") is None

        sync.pump_candidates()
        assert lan.probes == [("c", "192.168.20.85", 18487, f"{1:032x}")]
        token = lan.probes[0][3]
        lan.candidate_probe_succeeded.emit(
            context("c", "192.168.20.85", token="f" * 32, assisted=True)
        )
        assert sync.endpoint_book.preferred("c") is None
        assert token in sync.pending_tokens()

        lan.candidate_probe_succeeded.emit(
            context("c", "192.168.20.85", token=token, assisted=True)
        )
        discovered = sync.endpoint_book.preferred("c")
        assert discovered is not None and discovered.assisted is True
        assert sync.pending_tokens() == ()
        assert sync.candidates.active_keys() == ()
    finally:
        sync.stop()


def test_sync_never_republishes_an_unverified_received_candidate(qtbot) -> None:
    sync, lan, _clock, _tokens = started_sync()
    try:
        lan.peer_values = (peer("b", "192.168.101.65"),)
        lan.presence_verified.emit(context("b", "192.168.101.65"))
        sync.receive_directory(
            "b",
            PeerDirectory(
                "b", (PeerEndpointRecord("c", "192.168.20.85", 18487, 0),)
            ),
        )

        sync.sync_reachable_peers()

        assert len(lan.directories) == 1
        published = PeerDirectoryCodec.decode_frame(lan.directories[0][1])
        assert all(record.device_id != "c" for record in published.records)
    finally:
        sync.stop()


def test_probe_pump_caps_start_rate_and_concurrency(qtbot) -> None:
    sync, lan, clock, _tokens = started_sync()
    try:
        for index in range(12):
            assert sync.offer_candidate(
                f"peer-{index}",
                f"10.0.0.{index + 1}",
                18487,
                referrer_device_id="bridge",
            )

        for _ in range(8):
            sync.pump_candidates()
        assert len(lan.probes) == 4
        assert len(sync.pending_tokens()) == 4

        clock.advance(1.01)
        for _ in range(8):
            sync.pump_candidates()
        assert len(lan.probes) == 8
        assert len(sync.pending_tokens()) == 8

        clock.advance(1.01)
        sync.pump_candidates()
        assert len(lan.probes) == 8
    finally:
        sync.stop()


def test_probe_timeout_enters_backoff_and_cancels_service_token(qtbot) -> None:
    sync, lan, clock, _tokens = started_sync()
    try:
        assert sync.offer_candidate(
            "c", "192.168.20.85", 18487, referrer_device_id="b"
        )
        sync.pump_candidates()
        token = lan.probes[0][3]

        clock.advance(4.0)
        sync.expire_pending()

        assert lan.cancelled == [token]
        assert sync.pending_tokens() == ()
        assert not sync.offer_candidate(
            "c", "192.168.20.85", 18487, referrer_device_id="b"
        )
        clock.advance(121.0)
        assert sync.offer_candidate(
            "c", "192.168.20.85", 18487, referrer_device_id="b"
        )
    finally:
        sync.stop()


def test_periodic_directory_sync_rotates_three_online_peers(qtbot) -> None:
    sync, lan, _clock, _tokens = started_sync()
    try:
        lan.peer_values = tuple(
            peer(device_id, f"10.0.0.{index + 1}")
            for index, device_id in enumerate(("b", "c", "d", "e", "f"))
        )
        for item in lan.peer_values:
            lan.presence_verified.emit(context(item.device_id, str(item.ip_address)))

        sync.sync_reachable_peers()
        assert [target for target, _frame in lan.directories] == ["b", "c", "d"]

        lan.directories.clear()
        sync.sync_reachable_peers()
        assert [target for target, _frame in lan.directories] == ["e", "f", "b"]
    finally:
        sync.stop()


def test_renewal_round_sends_at_most_sixteen_assisted_endpoints(qtbot) -> None:
    sync, lan, clock, _tokens = started_sync()
    try:
        for index in range(20):
            sync.endpoint_book.observe(
                f"peer-{index}",
                f"172.16.0.{index + 1}",
                18487,
                ("probe_token_v1",),
                clock(),
                True,
            )

        sync.renew_assisted_peers()

        assert len(lan.renewals) == 16
        assert len(set(lan.renewals)) == 16
    finally:
        sync.stop()


def test_stop_clears_timers_pending_tokens_and_transient_state(qtbot) -> None:
    sync, lan, _clock, _tokens = started_sync()
    assert sync.offer_candidate(
        "c", "192.168.20.85", 18487, referrer_device_id="b"
    )
    sync.pump_candidates()
    token = lan.probes[0][3]

    sync.stop()

    assert lan.cancelled == [token]
    assert sync.pending_tokens() == ()
    assert sync.candidates.queued_keys() == ()
    assert sync.candidates.active_keys() == ()
    assert sync.endpoint_book.endpoints() == ()
    assert all(not timer.isActive() for timer in sync.timers())


def test_malicious_bridge_cannot_make_unverified_candidates_visible(qtbot) -> None:
    sync, lan, _clock, _tokens = started_sync()
    try:
        lan.peer_values = (peer("bridge", "192.168.101.65"),)
        lan.presence_verified.emit(context("bridge", "192.168.101.65"))
        sync.receive_directory(
            "bridge",
            PeerDirectory(
                "bridge",
                (PeerEndpointRecord("phantom", "192.168.20.85", 18487, 0),),
            ),
        )

        sync.pump_candidates()

        assert len(lan.probes) == 1
        assert lan.probes[0][:3] == ("phantom", "192.168.20.85", 18487)
        assert sync.endpoint_book.preferred("phantom") is None
        assert [item.device_id for item in lan.peers()] == ["bridge"]
    finally:
        sync.stop()


def test_directory_with_64_candidates_never_creates_more_than_8_pending_probes(
    qtbot,
) -> None:
    sync, lan, clock, _tokens = started_sync()
    try:
        records = tuple(
            PeerEndpointRecord(
                f"peer-{index}",
                f"10.0.{index // 250}.{index % 250 + 1}",
                18487,
                0,
            )
            for index in range(64)
        )
        sync.receive_directory("bridge", PeerDirectory("bridge", records))

        for _ in range(10):
            sync.pump_candidates()
        clock.advance(1.01)
        for _ in range(10):
            sync.pump_candidates()
        clock.advance(1.01)
        for _ in range(10):
            sync.pump_candidates()

        assert len(lan.probes) == 8
        assert len(sync.pending_tokens()) == 8
        assert len(set(sync.pending_tokens())) == 8
    finally:
        sync.stop()


def test_same_endpoint_from_directory_and_pool_is_only_probed_once(qtbot) -> None:
    sync, lan, _clock, _tokens = started_sync()
    try:
        endpoint = PeerEndpointRecord("c", "192.168.20.85", 18487, 0)
        sync.receive_directory("bridge", PeerDirectory("bridge", (endpoint,)))

        assert not sync.offer_candidate(
            "c",
            "192.168.20.85",
            18487,
            referrer_device_id="pool-bridge",
        )
        sync.pump_candidates()

        assert len(lan.probes) == 1
        assert lan.probes[0][:3] == ("c", "192.168.20.85", 18487)
    finally:
        sync.stop()


def test_same_device_with_two_verified_subnet_addresses_projects_one_peer(qtbot) -> None:
    sync, lan, _clock, _tokens = started_sync()
    try:
        first = peer("multi", "192.168.101.65")
        second = peer("multi", "192.168.20.65")
        lan.peer_values = (second,)
        lan.presence_verified.emit(context("multi", "192.168.101.65"))
        lan.presence_verified.emit(context("multi", "192.168.20.65"))

        endpoints = tuple(
            item
            for item in sync.endpoint_book.endpoints()
            if item.key.device_id == "multi"
        )
        assert {item.key.ip_address for item in endpoints} == {
            "192.168.101.65",
            "192.168.20.65",
        }
        assert [item.device_id for item in lan.peers()] == ["multi"]
        assert first.device_id == second.device_id
    finally:
        sync.stop()


def test_bridge_shutdown_does_not_break_already_verified_a_c_renewal(qtbot) -> None:
    sync, lan, clock, _tokens = started_sync()
    try:
        assert sync.offer_candidate(
            "c", "192.168.20.85", 18487, referrer_device_id="bridge"
        )
        sync.pump_candidates()
        token = lan.probes[0][3]
        lan.candidate_probe_succeeded.emit(
            context("c", "192.168.20.85", token=token, assisted=True)
        )
        lan.peer_removed.emit("bridge")

        clock.advance(8.0)
        sync.renew_assisted_peers()
        assert lan.renewals == [("192.168.20.85", 18487)]

        clock.advance(83.0)
        sync.renew_assisted_peers()
        assert lan.renewals == [("192.168.20.85", 18487)]
        assert sync.endpoint_book.preferred("c") is None
    finally:
        sync.stop()


def test_probe_rate_limits_each_referrer_to_twenty_attempts_per_minute(qtbot) -> None:
    sync, lan, clock, _tokens = started_sync()
    try:
        for index in range(21):
            assert sync.offer_candidate(
                f"peer-{index}",
                f"10.1.0.{index + 1}",
                18487,
                referrer_device_id="bridge",
            )

        for index in range(21):
            sync.pump_candidates()
            if index < 20:
                device_id, ip, _port, token = lan.probes[-1]
                lan.candidate_probe_succeeded.emit(
                    context(device_id, ip, token=token, assisted=True)
                )
            clock.advance(0.251)

        assert len(lan.probes) == 20
        assert len(sync.candidates.queued_keys()) == 1
        assert sync.pending_tokens() == ()
    finally:
        sync.stop()
