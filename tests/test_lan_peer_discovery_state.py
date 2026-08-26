from __future__ import annotations

import pytest

from petnest.core.lan_peer_discovery_protocol import PeerEndpointRecord
from petnest.core.lan_peer_discovery_state import (
    CandidateKey,
    CandidateQueue,
    DirectEndpointBook,
)


def test_endpoint_book_keeps_four_recent_addresses_and_projects_one_device() -> None:
    book = DirectEndpointBook(local_device_id="local")
    for index in range(5):
        book.observe(
            device_id="multi",
            ip_address=f"192.168.{index}.20",
            port=18487,
            extensions=("probe_token_v1",),
            verified_at=float(index),
            assisted=index == 4,
        )

    records = book.shareable_records(now=5.0)
    assert len(records) == 4
    assert {item.device_id for item in records} == {"multi"}
    assert book.preferred("multi").key.ip_address == "192.168.4.20"


def test_endpoint_book_only_shares_fresh_probe_capable_direct_endpoints() -> None:
    book = DirectEndpointBook(local_device_id="local")
    book.observe("old", "192.168.1.20", 18487, ("probe_token_v1",), 0.0, False)
    book.observe("legacy", "192.168.1.21", 18487, (), 23.0, False)
    book.observe("fresh", "192.168.1.22", 18487, ("probe_token_v1",), 23.0, False)

    assert book.shareable_records(now=24.5) == (
        PeerEndpointRecord("fresh", "192.168.1.22", 18487, 1),
    )


def test_endpoint_book_expires_direct_and_assisted_endpoints_at_different_ttls() -> None:
    book = DirectEndpointBook(local_device_id="local")
    direct = book.observe("direct", "10.0.0.2", 18487, (), 0.0, False).key
    assisted = book.observe("assisted", "10.0.0.3", 18487, (), 0.0, True).key

    assert book.expire(now=25.0) == (direct,)
    assert book.preferred("assisted") is not None
    assert book.expire(now=91.0) == (assisted,)


def test_ordinary_renewal_does_not_downgrade_an_assisted_endpoint() -> None:
    book = DirectEndpointBook(local_device_id="local")
    book.observe("peer", "10.0.0.3", 18487, ("probe_token_v1",), 0.0, True)

    renewed = book.observe(
        "peer", "10.0.0.3", 18487, ("probe_token_v1",), 8.0, False
    )

    assert renewed.assisted is True
    assert book.assisted_keys(now=8.0) == (renewed.key,)


def test_candidate_key_rejects_public_address_wrong_port_and_invalid_identity() -> None:
    with pytest.raises(ValueError):
        CandidateKey("peer", "8.8.8.8", 18487)
    with pytest.raises(ValueError):
        CandidateKey("peer", "192.168.1.20", 80)
    with pytest.raises(ValueError):
        CandidateKey("", "192.168.1.20", 18487)


def test_candidate_queue_deduplicates_limits_and_applies_exponential_backoff() -> None:
    queue = CandidateQueue(local_device_id="local", maximum=2)
    key = CandidateKey("peer", "192.168.20.85", 18487)
    assert queue.offer(key, referrer_device_id="bridge", now=0.0)
    assert not queue.offer(key, referrer_device_id="bridge", now=1.0)
    assert queue.take_ready(now=1.0, limit=1) == (key,)

    queue.mark_failed(key, now=5.0)
    assert not queue.offer(key, referrer_device_id="bridge", now=100.0)
    assert queue.offer(key, referrer_device_id="bridge", now=126.0)
    queue.take_ready(now=126.0, limit=1)
    queue.mark_failed(key, now=130.0)
    assert queue.backoff_until(key) == 370.0


def test_candidate_queue_rejects_local_existing_and_over_limit_candidates() -> None:
    queue = CandidateQueue(local_device_id="local", maximum=1)
    assert not queue.offer(CandidateKey("local", "192.168.1.20", 18487), "bridge", 0.0)
    assert not queue.offer(
        CandidateKey("verified", "192.168.1.19", 18487),
        "bridge",
        0.0,
        already_verified=True,
    )
    assert queue.offer(CandidateKey("one", "192.168.1.21", 18487), "bridge", 0.0)
    assert not queue.offer(CandidateKey("two", "192.168.1.22", 18487), "bridge", 0.0)


def test_candidate_success_clears_active_referrer_and_failure_history() -> None:
    queue = CandidateQueue(local_device_id="local")
    key = CandidateKey("peer", "172.16.1.20", 18487)
    assert queue.offer(key, "bridge", 0.0)
    assert queue.take_ready(now=0.0, limit=1) == (key,)
    assert queue.referrer(key) == "bridge"
    queue.mark_failed(key, now=1.0)
    assert queue.backoff_until(key) == 121.0

    assert queue.offer(key, "bridge-2", 122.0)
    queue.take_ready(now=122.0, limit=1)
    queue.mark_verified(key)

    assert queue.referrer(key) is None
    assert queue.backoff_until(key) is None
    assert queue.offer(key, "bridge-3", 123.0)
