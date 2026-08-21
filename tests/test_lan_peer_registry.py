"""持久化局域网伙伴登记表的测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import petnest.core.lan_peer_registry as lan_peer_registry
from petnest.core.lan_peer_registry import KnownLanPeer, KnownLanPeerRegistry


def peer(
    device_id: str = "remote-1",
    display_name: str = "小王",
    ip_address: str = "192.168.1.20",
    port: int = 19000,
) -> KnownLanPeer:
    return KnownLanPeer(device_id, display_name, ip_address, port)


def test_upsert_round_trips_atomically_and_sorts_by_display_name(tmp_path) -> None:
    path = tmp_path / "known-lan-peers.json"
    registry = KnownLanPeerRegistry(path)
    assert registry.path == path
    registry.upsert(peer("z", "张三", "192.168.1.30", 19001))
    registry.upsert(peer("a", "alice", "192.168.1.20", 19000))

    assert not (tmp_path / "known-lan-peers.json.tmp").exists()
    assert KnownLanPeerRegistry(path).load() == (
        peer("a", "alice", "192.168.1.20", 19000),
        peer("z", "张三", "192.168.1.30", 19001),
    )
    assert path.read_text(encoding="utf-8").endswith("\n")
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "peers": [
            {"device_id": "z", "display_name": "张三", "ip_address": "192.168.1.30", "port": 19001},
            {"device_id": "a", "display_name": "alice", "ip_address": "192.168.1.20", "port": 19000},
        ],
    }


def test_load_backs_up_corrupt_file_and_returns_empty(tmp_path) -> None:
    path = tmp_path / "known-lan-peers.json"
    path.write_text("{not json", encoding="utf-8")

    assert KnownLanPeerRegistry(path).load() == ()
    assert not path.exists()
    backups = list(tmp_path.glob("known-lan-peers.json.corrupt-*.bak"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{not json"


def test_mismatched_identity_cannot_claim_registered_ip(tmp_path) -> None:
    registry = KnownLanPeerRegistry(tmp_path / "known-lan-peers.json")
    registry.upsert(peer(device_id="trusted", ip_address="192.168.1.20", port=19000))

    assert not registry.matches_expected_identity("192.168.1.20", 19000, "attacker")
    assert registry.matches_expected_identity("192.168.1.20", 19000, "trusted")
    assert registry.matches_expected_identity("192.168.1.20", 19001, "other-device")
    assert registry.matches_expected_identity("192.168.1.21", 19000, "attacker")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"device_id": ""}, "device_id"),
        ({"device_id": "  "}, "device_id"),
        ({"display_name": "\t"}, "display_name"),
        ({"ip_address": "2001:db8::1"}, "IPv4"),
        ({"ip_address": 123}, "IPv4"),
        ({"port": True}, "port"),
    ],
)
def test_known_peer_rejects_invalid_values(kwargs, message) -> None:
    with pytest.raises(ValueError, match=message):
        peer(**kwargs)


def test_load_treats_duplicate_device_ids_as_corruption(tmp_path) -> None:
    path = tmp_path / "known-lan-peers.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "peers": [
                    {"device_id": "same", "display_name": "甲", "ip_address": "192.168.1.2", "port": 1},
                    {"device_id": "same", "display_name": "乙", "ip_address": "192.168.1.3", "port": 2},
                ],
            }
        ),
        encoding="utf-8",
    )

    assert KnownLanPeerRegistry(path).load() == ()
    assert list(tmp_path.glob("known-lan-peers.json.corrupt-*.bak"))


def test_load_rejects_non_integer_schema_version(tmp_path) -> None:
    path = tmp_path / "known-lan-peers.json"
    path.write_text(json.dumps({"schema_version": 1.0, "peers": []}), encoding="utf-8")

    assert KnownLanPeerRegistry(path).load() == ()
    assert list(tmp_path.glob("known-lan-peers.json.corrupt-*.bak"))


def test_read_permission_error_preserves_file_and_prevents_upsert_data_loss(tmp_path, monkeypatch) -> None:
    path = tmp_path / "known-lan-peers.json"
    original_contents = '{"schema_version": 1, "peers": []}'
    path.write_text(original_contents, encoding="utf-8")
    registry = KnownLanPeerRegistry(path)
    original_read_text = Path.read_text

    def deny_registry_read(target: Path, *args, **kwargs):
        if target == path:
            raise PermissionError("access denied")
        return original_read_text(target, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", deny_registry_read)

    with pytest.raises(PermissionError):
        registry.load()
    with pytest.raises(PermissionError):
        registry.upsert(peer())
    assert path.read_bytes().decode("utf-8") == original_contents


def test_failed_corruption_backup_blocks_mutators_without_overwriting_original(tmp_path, monkeypatch) -> None:
    path = tmp_path / "known-lan-peers.json"
    original_contents = "{corrupt"
    path.write_text(original_contents, encoding="utf-8")
    registry = KnownLanPeerRegistry(path)
    original_replace = lan_peer_registry.os.replace

    def deny_backup(source, destination):
        if source == path:
            raise PermissionError("backup denied")
        return original_replace(source, destination)

    monkeypatch.setattr(lan_peer_registry.os, "replace", deny_backup)

    assert registry.load() == ()
    assert registry.is_write_blocked
    with pytest.raises(OSError):
        registry.upsert(peer())
    with pytest.raises(OSError):
        registry.forget("remote-1")
    assert path.read_bytes().decode("utf-8") == original_contents


def test_new_registry_can_retry_corruption_isolation_after_prior_backup_failure(tmp_path, monkeypatch) -> None:
    path = tmp_path / "known-lan-peers.json"
    path.write_text("{corrupt", encoding="utf-8")
    original_replace = lan_peer_registry.os.replace

    monkeypatch.setattr(lan_peer_registry.os, "replace", lambda source, destination: (_ for _ in ()).throw(PermissionError()))
    assert KnownLanPeerRegistry(path).load() == ()
    monkeypatch.setattr(lan_peer_registry.os, "replace", original_replace)

    assert KnownLanPeerRegistry(path).load() == ()
    assert not path.exists()
    assert list(tmp_path.glob("known-lan-peers.json.corrupt-*.bak"))


def test_failed_save_replace_keeps_active_file_and_removes_temporary_file(tmp_path, monkeypatch) -> None:
    path = tmp_path / "known-lan-peers.json"
    registry = KnownLanPeerRegistry(path)
    registry.upsert(peer())
    original_contents = path.read_text(encoding="utf-8")
    original_replace = lan_peer_registry.os.replace

    def deny_save_replace(source, destination):
        if source.name.endswith(".tmp"):
            raise PermissionError("replace denied")
        return original_replace(source, destination)

    monkeypatch.setattr(lan_peer_registry.os, "replace", deny_save_replace)

    with pytest.raises(PermissionError):
        registry.upsert(peer(display_name="已更新"))
    assert path.read_text(encoding="utf-8") == original_contents
    assert not path.with_name(f"{path.name}.tmp").exists()


def test_upsert_replaces_existing_device_id_and_forget_removes_it(tmp_path) -> None:
    registry = KnownLanPeerRegistry(tmp_path / "known-lan-peers.json")
    registry.upsert(peer(device_id="same", display_name="旧名", ip_address="192.168.1.10", port=1000))
    registry.upsert(peer(device_id="same", display_name="新名", ip_address="192.168.1.11", port=2000))

    assert registry.load() == (peer("same", "新名", "192.168.1.11", 2000),)
    registry.forget("same")
    assert registry.load() == ()
