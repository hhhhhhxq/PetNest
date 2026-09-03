"""Persistent local adoption receipts for the PetNest pet store."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import json
import os
from pathlib import Path
import re
import tempfile
from uuid import uuid4

from .pet_store_catalog import PetStoreFile, PetStoreItem


_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class PetStoreStatus(StrEnum):
    NOT_ADOPTED = "not_adopted"
    LOCAL_EXISTING = "local_existing"
    ADOPTED = "adopted"
    UPDATE_AVAILABLE = "update_available"


@dataclass(frozen=True, slots=True)
class PetStoreReceipt:
    pet_id: str
    package_sha256: str
    installed_at: datetime
    catalog_updated_at: datetime


class PetStoreStateStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path).expanduser().resolve()

    def load(self) -> dict[str, PetStoreReceipt]:
        if not self.path.is_file():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return self._parse(raw)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError):
            self._quarantine_invalid()
            return {}

    def receipt(self, pet_id: str) -> PetStoreReceipt | None:
        return self.load().get(pet_id)

    def record_install(
        self,
        item: PetStoreItem,
        *,
        package: PetStoreFile | None = None,
        installed_at: datetime | None = None,
    ) -> None:
        installed = installed_at or datetime.now(UTC)
        if installed.tzinfo is None or installed.utcoffset() is None:
            raise ValueError("installed_at 必须包含 UTC 偏移")
        receipts = self.load()
        installed_package = package or item.package
        if installed_package not in item.package_files:
            raise ValueError("安装收据的 package 必须属于当前商店宠物")
        receipts[item.identifier] = PetStoreReceipt(
            item.identifier,
            installed_package.sha256,
            installed.astimezone(UTC),
            item.updated_at.astimezone(UTC),
        )
        self._save(receipts)

    def forget(self, pet_id: str) -> None:
        receipts = self.load()
        if receipts.pop(pet_id, None) is not None:
            self._save(receipts)

    def status_for(self, item: PetStoreItem, pets_root: Path) -> PetStoreStatus:
        pet_root = Path(pets_root).expanduser() / item.identifier
        exists = pet_root.is_dir() and not pet_root.is_symlink()
        receipt = self.receipt(item.identifier)
        if not exists:
            if receipt is not None:
                self.forget(item.identifier)
            return PetStoreStatus.NOT_ADOPTED
        if receipt is None:
            return PetStoreStatus.LOCAL_EXISTING
        if any(receipt.package_sha256 == package.sha256 for package in item.package_files):
            return PetStoreStatus.ADOPTED
        return PetStoreStatus.UPDATE_AVAILABLE

    def _parse(self, raw: object) -> dict[str, PetStoreReceipt]:
        if not isinstance(raw, dict) or raw.get("schema_version") != 1:
            raise ValueError("state schema 无效")
        values = raw.get("receipts")
        if not isinstance(values, dict):
            raise ValueError("receipts 无效")
        receipts: dict[str, PetStoreReceipt] = {}
        for pet_id, value in values.items():
            if not isinstance(pet_id, str) or _ID_RE.fullmatch(pet_id) is None:
                raise ValueError("receipt ID 无效")
            if not isinstance(value, dict):
                raise ValueError("receipt 必须是对象")
            digest = value.get("package_sha256")
            if not isinstance(digest, str) or _SHA_RE.fullmatch(digest) is None:
                raise ValueError("receipt SHA-256 无效")
            receipts[pet_id] = PetStoreReceipt(
                pet_id,
                digest,
                _parse_time(value.get("installed_at")),
                _parse_time(value.get("catalog_updated_at")),
            )
        return receipts

    def _save(self, receipts: dict[str, PetStoreReceipt]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "receipts": {
                pet_id: {
                    "package_sha256": receipt.package_sha256,
                    "installed_at": _time_text(receipt.installed_at),
                    "catalog_updated_at": _time_text(receipt.catalog_updated_at),
                }
                for pet_id, receipt in sorted(receipts.items())
            },
        }
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}-", suffix=".tmp", dir=self.path.parent
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _quarantine_invalid(self) -> None:
        if not self.path.exists():
            return
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        destination = self.path.with_name(
            f"state.invalid-{timestamp}-{uuid4().hex[:8]}.json"
        )
        try:
            os.replace(self.path, destination)
        except OSError:
            try:
                self.path.unlink()
            except OSError:
                pass


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("receipt 时间无效")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("receipt 时间缺少偏移")
    return parsed.astimezone(UTC)


def _time_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = [
    "PetStoreReceipt",
    "PetStoreStateStore",
    "PetStoreStatus",
]
