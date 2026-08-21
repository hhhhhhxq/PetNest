"""Distributed LAN alert-pool roster model and storage tests."""

from __future__ import annotations

from dataclasses import replace
import json

import pytest

from petnest.core.lan_pool_roster import PoolRosterStore
from petnest.models.lan_pool import PoolMemberRecord, PoolMemberState


def _record(
    device_id: str = "peer",
    *,
    state: PoolMemberState = PoolMemberState.JOINED,
    revision: int = 1,
    display_name: str = "小林",
    ip_address: str = "192.168.1.20",
    port: int = 18487,
) -> PoolMemberRecord:
    return PoolMemberRecord(
        device_id=device_id,
        display_name=display_name,
        state=state,
        revision=revision,
        ip_address=ip_address,
        port=port,
        protocol_version=1,
    )


def test_newer_revision_wins_and_left_tombstone_blocks_old_joined(tmp_path) -> None:
    store = PoolRosterStore(tmp_path / "roster.json", local_device_id="local")
    joined = _record(revision=1)
    left = replace(joined, state=PoolMemberState.LEFT, revision=2)

    assert store.merge((joined,)).changed_device_ids == ("peer",)
    assert store.merge((left,)).changed_device_ids == ("peer",)
    assert store.merge((joined,)).changed_device_ids == ()
    assert store.records()["peer"].state is PoolMemberState.LEFT
    assert store.joined_device_ids() == ()


def test_equal_revision_conflict_waits_for_direct_owner(tmp_path) -> None:
    store = PoolRosterStore(tmp_path / "roster.json", local_device_id="local")
    first = _record(revision=3)
    conflict = replace(first, display_name="伪造昵称")
    store.merge((first,), directly_verified_ids={"peer"})

    unverified = store.merge((conflict,))
    assert unverified.conflicted_device_ids == ("peer",)
    assert store.records()["peer"] == first

    verified = store.merge((conflict,), directly_verified_ids={"peer"})
    assert verified.changed_device_ids == ("peer",)
    assert store.records()["peer"] == conflict


def test_local_record_revision_only_increments_when_content_changes(tmp_path) -> None:
    store = PoolRosterStore(tmp_path / "roster.json", local_device_id="local")
    first = store.update_local(
        display_name="本机",
        state=PoolMemberState.JOINED,
        ip_address="192.168.1.10",
        port=18487,
    )
    same = store.update_local(
        display_name="本机",
        state=PoolMemberState.JOINED,
        ip_address="192.168.1.10",
        port=18487,
    )
    left = store.update_local(
        display_name="本机",
        state=PoolMemberState.LEFT,
        ip_address="192.168.1.10",
        port=18487,
    )

    assert (first.revision, same.revision, left.revision) == (1, 1, 2)
    assert store.records()["local"] == left


def test_update_local_removes_foreign_records_at_the_same_endpoint(tmp_path) -> None:
    path = tmp_path / "roster.json"
    store = PoolRosterStore(path, local_device_id="local")
    store.merge(
        (
            _record("ghost-a", ip_address="192.168.1.10", port=18487),
            _record("ghost-b", ip_address="192.168.1.10", port=18487),
            _record("other-ip", ip_address="192.168.1.11", port=18487),
            _record("other-port", ip_address="192.168.1.10", port=18488),
        )
    )

    store.update_local(
        display_name="本机",
        state=PoolMemberState.JOINED,
        ip_address="192.168.1.10",
        port=18487,
    )

    expected_ids = {"local", "other-ip", "other-port"}
    assert set(store.records()) == expected_ids
    assert set(PoolRosterStore(path, local_device_id="local").records()) == expected_ids


def test_unchanged_local_record_still_cleans_a_later_endpoint_conflict(tmp_path) -> None:
    store = PoolRosterStore(tmp_path / "roster.json", local_device_id="local")
    local = store.update_local(
        display_name="本机",
        state=PoolMemberState.JOINED,
        ip_address="192.168.1.10",
        port=18487,
    )
    store.merge((_record("ghost", ip_address="192.168.1.10", port=18487),))

    same = store.update_local(
        display_name="本机",
        state=PoolMemberState.JOINED,
        ip_address="192.168.1.10",
        port=18487,
    )

    assert same.revision == local.revision
    assert set(store.records()) == {"local"}


def test_roster_round_trips_records_revision_map_and_digest(tmp_path) -> None:
    path = tmp_path / "lan-alert-pool-roster.json"
    store = PoolRosterStore(path, local_device_id="local")
    store.merge((_record("peer-a", revision=2), _record("peer-b", revision=4)))

    loaded = PoolRosterStore(path, local_device_id="local")

    assert loaded.revisions() == {"peer-a": 2, "peer-b": 4}
    assert loaded.digest() == store.digest()
    assert len(loaded.digest()) == 64


def test_roster_backs_up_corrupt_json_and_starts_empty(tmp_path) -> None:
    path = tmp_path / "lan-alert-pool-roster.json"
    path.write_text("not-json", encoding="utf-8")

    store = PoolRosterStore(path, local_device_id="local")

    assert store.records() == {}
    assert len(tuple(tmp_path.glob("lan-alert-pool-roster.json.corrupt-*.bak"))) == 1


def test_roster_rejects_more_than_256_records_and_invalid_record_values(tmp_path) -> None:
    store = PoolRosterStore(tmp_path / "roster.json", local_device_id="local")
    records = tuple(
        _record(f"peer-{index}", ip_address=f"10.0.{index // 250}.{index % 250 + 1}")
        for index in range(257)
    )

    with pytest.raises(ValueError, match="256"):
        store.merge(records)
    with pytest.raises(ValueError, match="revision"):
        _record(revision=True)
    with pytest.raises(ValueError, match="IPv4"):
        _record(ip_address="not-an-ip")


def test_roster_rejects_duplicate_device_ids_in_file(tmp_path) -> None:
    path = tmp_path / "roster.json"
    raw = {
        "schema_version": 1,
        "local_device_id": "local",
        "local_revision": 0,
        "records": [
            {
                "device_id": "peer",
                "display_name": "小林",
                "state": "joined",
                "revision": 1,
                "ip_address": "192.168.1.20",
                "port": 18487,
                "protocol_version": 1,
            },
            {
                "device_id": "peer",
                "display_name": "小林",
                "state": "joined",
                "revision": 2,
                "ip_address": "192.168.1.20",
                "port": 18487,
                "protocol_version": 1,
            },
        ],
    }
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    store = PoolRosterStore(path, local_device_id="local")

    assert store.records() == {}
    assert len(tuple(tmp_path.glob("roster.json.corrupt-*.bak"))) == 1
