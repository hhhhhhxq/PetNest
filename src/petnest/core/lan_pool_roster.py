"""Atomic persistence and deterministic merge rules for the LAN alert-pool roster."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Iterable

from petnest.models.lan_pool import PoolMemberRecord, PoolMemberState, PoolMergeResult


MAX_POOL_RECORDS = 256


class PoolRosterStore:
    SCHEMA_VERSION = 1

    def __init__(self, path: Path, *, local_device_id: str) -> None:
        if not isinstance(local_device_id, str) or not local_device_id.strip() or len(local_device_id) > 64:
            raise ValueError("local_device_id must be a non-empty string of at most 64 characters")
        self.path = path
        self.local_device_id = local_device_id.strip()
        self._records: dict[str, PoolMemberRecord] = {}
        self._local_revision = 0
        self._write_blocked = False
        self._load()

    @property
    def is_write_blocked(self) -> bool:
        return self._write_blocked

    def records(self) -> dict[str, PoolMemberRecord]:
        return dict(self._records)

    def revisions(self) -> dict[str, int]:
        return {device_id: record.revision for device_id, record in sorted(self._records.items())}

    def joined_device_ids(self) -> tuple[str, ...]:
        return tuple(
            device_id
            for device_id, record in sorted(self._records.items())
            if record.state is PoolMemberState.JOINED
        )

    def digest(self) -> str:
        canonical = [asdict(self._records[device_id]) for device_id in sorted(self._records)]
        payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode("utf-8")).hexdigest()

    def merge(
        self,
        records: Iterable[PoolMemberRecord],
        *,
        directly_verified_ids: set[str] | frozenset[str] = frozenset(),
    ) -> PoolMergeResult:
        incoming = tuple(records)
        if any(not isinstance(record, PoolMemberRecord) for record in incoming):
            raise TypeError("records must contain PoolMemberRecord values")
        incoming_ids = [record.device_id for record in incoming]
        if len(set(incoming_ids)) != len(incoming_ids):
            raise ValueError("duplicate device_id in merge records")
        local_record = self._records.get(self.local_device_id)
        local_endpoint_conflict_ids = {
            record.device_id
            for record in incoming
            if local_record is not None
            and record.device_id != self.local_device_id
            and record.ip_address == local_record.ip_address
            and record.port == local_record.port
        }
        accepted_incoming_ids = set(incoming_ids).difference(local_endpoint_conflict_ids)
        if len(set(self._records).union(accepted_incoming_ids)) > MAX_POOL_RECORDS:
            raise ValueError("pool roster cannot contain more than 256 records")

        changed: list[str] = []
        local_newer: list[str] = []
        conflicts: list[str] = []
        for remote in incoming:
            if remote.device_id in local_endpoint_conflict_ids:
                conflicts.append(remote.device_id)
                continue
            local = self._records.get(remote.device_id)
            if remote.device_id == self.local_device_id and local != remote:
                conflicts.append(remote.device_id)
                continue
            if local is None:
                self._records[remote.device_id] = remote
                changed.append(remote.device_id)
                continue
            if remote.revision > local.revision:
                self._records[remote.device_id] = remote
                changed.append(remote.device_id)
            elif remote.revision < local.revision:
                local_newer.append(remote.device_id)
            elif remote != local:
                if remote.device_id in directly_verified_ids:
                    self._records[remote.device_id] = remote
                    changed.append(remote.device_id)
                else:
                    conflicts.append(remote.device_id)
        if changed:
            self._save()
        return PoolMergeResult(tuple(changed), tuple(local_newer), tuple(conflicts))

    def update_local(
        self,
        *,
        display_name: str,
        state: PoolMemberState,
        ip_address: str,
        port: int,
    ) -> PoolMemberRecord:
        existing = self._records.get(self.local_device_id)
        normalized_state = state if isinstance(state, PoolMemberState) else PoolMemberState(state)
        unchanged = (
            existing is not None
            and existing.display_name == display_name.strip()
            and existing.state is normalized_state
            and existing.ip_address == ip_address
            and existing.port == port
        )
        if unchanged:
            record = existing
        else:
            revision = max(self._local_revision, existing.revision if existing is not None else 0) + 1
            record = PoolMemberRecord(
                self.local_device_id,
                display_name,
                normalized_state,
                revision,
                ip_address,
                port,
                1,
            )
        conflicting_ids = tuple(
            device_id
            for device_id, candidate in self._records.items()
            if device_id != self.local_device_id
            and candidate.ip_address == ip_address
            and candidate.port == port
        )
        if unchanged and not conflicting_ids:
            return record
        for device_id in conflicting_ids:
            del self._records[device_id]
        if unchanged:
            self._save()
            return record
        self._records[self.local_device_id] = record
        self._local_revision = record.revision
        self._save()
        return record

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            local_revision, records = self._parse_document(raw)
        except FileNotFoundError:
            return
        except OSError:
            raise
        except (TypeError, ValueError, json.JSONDecodeError):
            if not self._quarantine_corrupt_file():
                self._write_blocked = True
            return
        self._local_revision = local_revision
        self._records = records

    def _parse_document(self, raw: object) -> tuple[int, dict[str, PoolMemberRecord]]:
        if not isinstance(raw, dict) or set(raw) != {
            "schema_version", "local_device_id", "local_revision", "records"
        }:
            raise ValueError("invalid roster document")
        if raw["schema_version"] != self.SCHEMA_VERSION or isinstance(raw["schema_version"], bool):
            raise ValueError("unsupported roster schema")
        if raw["local_device_id"] != self.local_device_id:
            raise ValueError("roster belongs to another local device")
        local_revision = raw["local_revision"]
        if isinstance(local_revision, bool) or not isinstance(local_revision, int) or local_revision < 0:
            raise ValueError("invalid local_revision")
        raw_records = raw["records"]
        if not isinstance(raw_records, list) or len(raw_records) > MAX_POOL_RECORDS:
            raise ValueError("invalid records list")
        records: dict[str, PoolMemberRecord] = {}
        required = {"device_id", "display_name", "state", "revision", "ip_address", "port", "protocol_version"}
        for raw_record in raw_records:
            if not isinstance(raw_record, dict) or set(raw_record) != required:
                raise ValueError("invalid member record")
            record = PoolMemberRecord(**raw_record)
            if record.device_id in records:
                raise ValueError("duplicate device_id")
            records[record.device_id] = record
        if self.local_device_id in records and local_revision < records[self.local_device_id].revision:
            raise ValueError("local_revision is older than the local record")
        return local_revision, records

    def _save(self) -> None:
        if self._write_blocked:
            raise OSError("roster writes are blocked until corrupt data is isolated")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f"{self.path.name}.tmp")
        document = {
            "schema_version": self.SCHEMA_VERSION,
            "local_device_id": self.local_device_id,
            "local_revision": self._local_revision,
            "records": [asdict(self._records[device_id]) for device_id in sorted(self._records)],
        }
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)

    def _quarantine_corrupt_file(self) -> bool:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup = self.path.with_name(f"{self.path.name}.corrupt-{stamp}.bak")
        try:
            os.replace(self.path, backup)
        except OSError:
            return False
        return True
