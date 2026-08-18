"""持久化已验证的局域网伙伴身份。"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path


@dataclass(frozen=True, slots=True)
class KnownLanPeer:
    """一个已验证的局域网伙伴端点。"""

    device_id: str
    display_name: str
    ip_address: str
    port: int

    def __post_init__(self) -> None:
        if not isinstance(self.device_id, str) or not self.device_id.strip() or len(self.device_id) > 64:
            raise ValueError("device_id must be a non-empty string of at most 64 characters")
        if not isinstance(self.display_name, str) or not self.display_name.strip() or len(self.display_name) > 40:
            raise ValueError("display_name must be a non-empty string of at most 40 characters")
        if not isinstance(self.ip_address, str):
            raise ValueError("ip_address must be an IPv4 address")
        try:
            ip = ipaddress.ip_address(self.ip_address)
        except (TypeError, ValueError) as error:
            raise ValueError("ip_address must be an IPv4 address") from error
        if ip.version != 4:
            raise ValueError("ip_address must be an IPv4 address")
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise ValueError("port must be an integer from 1 to 65535")


class KnownLanPeerRegistry:
    """在单一 JSON 文件中安全地读写已保存伙伴。"""

    SCHEMA_VERSION = 1

    def __init__(self, path: Path) -> None:
        self.path = path
        self._write_blocked = False

    @property
    def is_write_blocked(self) -> bool:
        """隔离损坏文件失败后，阻止当前实例覆盖原始内容。"""
        return self._write_blocked

    def load(self) -> tuple[KnownLanPeer, ...]:
        """读取登记表；无法信任的内容会被隔离。"""
        if self._write_blocked:
            return ()
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
            peers = self._parse_document(document)
        except FileNotFoundError:
            return ()
        except OSError:
            raise
        except (TypeError, ValueError, json.JSONDecodeError):
            if not self._quarantine_corrupt_file():
                self._write_blocked = True
            return ()
        return tuple(sorted(peers, key=lambda peer: peer.display_name.casefold()))

    def upsert(self, peer: KnownLanPeer) -> None:
        """按设备标识添加或更新伙伴。"""
        if not isinstance(peer, KnownLanPeer):
            raise TypeError("peer must be a KnownLanPeer")
        peers = {saved_peer.device_id: saved_peer for saved_peer in self.load()}
        peers[peer.device_id] = peer
        self._save(tuple(peers.values()))

    def forget(self, device_id: str) -> None:
        """删除指定伙伴；不存在时仍写出一致的登记表。"""
        peers = {peer.device_id: peer for peer in self.load()}
        peers.pop(device_id, None)
        self._save(tuple(peers.values()))

    def matches_expected_identity(self, ip_address: str, device_id: str) -> bool:
        """未登记 IP 可继续验证，已登记 IP 仅接受原设备。"""
        return all(peer.ip_address != ip_address or peer.device_id == device_id for peer in self.load())

    def _parse_document(self, document: object) -> tuple[KnownLanPeer, ...]:
        if not isinstance(document, dict) or set(document) != {"schema_version", "peers"}:
            raise ValueError("invalid registry document")
        schema_version = document["schema_version"]
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version != self.SCHEMA_VERSION
        ):
            raise ValueError("unsupported registry schema")
        raw_peers = document["peers"]
        if not isinstance(raw_peers, list):
            raise ValueError("peers must be a list")
        peers: list[KnownLanPeer] = []
        device_ids: set[str] = set()
        required_fields = {"device_id", "display_name", "ip_address", "port"}
        for raw_peer in raw_peers:
            if not isinstance(raw_peer, dict) or set(raw_peer) != required_fields:
                raise ValueError("invalid peer record")
            peer = KnownLanPeer(**raw_peer)
            if peer.device_id in device_ids:
                raise ValueError("duplicate device_id")
            device_ids.add(peer.device_id)
            peers.append(peer)
        return tuple(peers)

    def _save(self, peers: tuple[KnownLanPeer, ...]) -> None:
        if self._write_blocked:
            raise OSError("registry writes are blocked until corrupt data is isolated")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(f"{self.path.name}.tmp")
        document = {
            "schema_version": self.SCHEMA_VERSION,
            "peers": [asdict(peer) for peer in peers],
        }
        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        finally:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)

    def _quarantine_corrupt_file(self) -> bool:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup_path = self.path.with_name(f"{self.path.name}.corrupt-{timestamp}.bak")
        try:
            os.replace(self.path, backup_path)
        except OSError:
            return False
        return True
