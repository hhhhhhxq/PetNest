"""Throttled resource checks, persistent update state, and manual apply."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
from typing import Any, Callable, Protocol
import uuid

from petnest.core.remote_resource_cache import ResourceSyncResult
from petnest.core.remote_resource_manifest import ResourceManifest


class _ResourceCache(Protocol):
    def fetch_manifest(self) -> ResourceManifest: ...

    def load_current_manifest(self) -> ResourceManifest | None: ...

    def sync(
        self,
        *,
        progress: Callable[[int], object] | None = None,
        on_resource_applied: Callable[[str], object] | None = None,
    ) -> ResourceManifest: ...

    def sync_partial(
        self,
        *,
        progress: Callable[[int], object] | None = None,
        on_resource_applied: Callable[[str], object] | None = None,
    ) -> ResourceSyncResult: ...


@dataclass(frozen=True, slots=True)
class RemoteResourceUpdateState:
    last_check_at: str | None = None
    remote_catalog_version: str | None = None
    applied_catalog_version: str | None = None
    update_available: bool = False
    last_error: str | None = None

    @classmethod
    def from_dict(cls, raw: object) -> "RemoteResourceUpdateState":
        if not isinstance(raw, dict):
            return cls()
        return cls(
            last_check_at=raw.get("last_check_at") if isinstance(raw.get("last_check_at"), str) else None,
            remote_catalog_version=(
                raw.get("remote_catalog_version")
                if isinstance(raw.get("remote_catalog_version"), str)
                else None
            ),
            applied_catalog_version=(
                raw.get("applied_catalog_version")
                if isinstance(raw.get("applied_catalog_version"), str)
                else None
            ),
            update_available=raw.get("update_available") is True,
            last_error=raw.get("last_error") if isinstance(raw.get("last_error"), str) else None,
        )


@dataclass(frozen=True, slots=True)
class RemoteResourceCheckResult:
    checked: bool
    skipped: bool
    update_available: bool
    catalog_version: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RemoteResourceApplyResult:
    applied: bool
    catalog_version: str | None = None
    error: str | None = None
    partial: bool = False
    updated_resource_ids: tuple[str, ...] = ()
    failed_resource_ids: tuple[str, ...] = ()
    resource_view_changed: bool = False


class RemoteResourceUpdateCoordinator:
    """Coordinate checks without mixing update metadata into user settings."""

    def __init__(
        self,
        cache: _ResourceCache,
        state_path: Path,
        *,
        now: Callable[[], datetime] | None = None,
        interval: timedelta = timedelta(hours=24),
    ) -> None:
        self.cache = cache
        self.state_path = Path(state_path)
        self.now = now or (lambda: datetime.now(UTC))
        self.interval = interval
        self.state = self._load_state()

    @property
    def update_available(self) -> bool:
        return self.state.update_available

    def should_check(self, *, force: bool = False) -> bool:
        if force or self.state.last_check_at is None:
            return True
        try:
            previous = datetime.fromisoformat(self.state.last_check_at).astimezone(UTC)
        except (TypeError, ValueError):
            return True
        return self.now().astimezone(UTC) - previous >= self.interval

    def check(self, *, force: bool = False) -> RemoteResourceCheckResult:
        if not self.should_check(force=force):
            return RemoteResourceCheckResult(False, True, self.update_available, self.state.remote_catalog_version)
        try:
            remote = self.cache.fetch_manifest()
            current = self.cache.load_current_manifest()
        except Exception as error:  # noqa: BLE001 - a failed check must not stop PetNest.
            message = str(error) or error.__class__.__name__
            self.state = self._replace(last_error=message)
            self._save_state()
            return RemoteResourceCheckResult(False, False, self.update_available, error=message)

        self.state = self._replace(
            last_check_at=self.now().astimezone(UTC).isoformat(),
            remote_catalog_version=remote.catalog_version,
            update_available=current is None or _manifest_signature(current) != _manifest_signature(remote),
            last_error=None,
        )
        self._save_state()
        return RemoteResourceCheckResult(True, False, self.update_available, remote.catalog_version)

    def apply(
        self,
        *,
        progress: Callable[[int], object] | None = None,
        on_resource_applied: Callable[[str], object] | None = None,
    ) -> RemoteResourceApplyResult:
        if not self.update_available:
            return RemoteResourceApplyResult(False, self.state.remote_catalog_version)
        try:
            sync_partial = getattr(self.cache, "sync_partial", None)
            if callable(sync_partial):
                kwargs: dict[str, object] = {}
                if progress is not None:
                    kwargs["progress"] = progress
                if on_resource_applied is not None:
                    kwargs["on_resource_applied"] = on_resource_applied
                result = sync_partial(**kwargs)
                return self._apply_partial_result(result)
            kwargs = {}
            if progress is not None:
                kwargs["progress"] = progress
            if on_resource_applied is not None:
                kwargs["on_resource_applied"] = on_resource_applied
            manifest = self.cache.sync(**kwargs)
        except Exception as error:  # noqa: BLE001 - retain the badge for a retry.
            message = str(error) or error.__class__.__name__
            self.state = self._replace(last_error=message, update_available=True)
            self._save_state()
            return RemoteResourceApplyResult(False, error=message)

        self.state = self._replace(
            remote_catalog_version=manifest.catalog_version,
            applied_catalog_version=manifest.catalog_version,
            update_available=False,
            last_error=None,
        )
        self._save_state()
        return RemoteResourceApplyResult(True, manifest.catalog_version)

    def _apply_partial_result(self, result: ResourceSyncResult) -> RemoteResourceApplyResult:
        current = self.cache.load_current_manifest()
        remaining = current is None or _manifest_signature(current) != _manifest_signature(result.manifest)
        error = "；".join(f"{failure.identifier}: {failure.error}" for failure in result.failures) or None
        if remaining and error is None:
            error = "仍有资源未应用"
        self.state = self._replace(
            remote_catalog_version=result.manifest.catalog_version,
            applied_catalog_version=(
                result.manifest.catalog_version if not remaining else self.state.applied_catalog_version
            ),
            update_available=remaining,
            last_error=error,
        )
        self._save_state()
        return RemoteResourceApplyResult(
            applied=not remaining,
            catalog_version=result.manifest.catalog_version,
            error=error,
            partial=bool(
                result.failures
                and (result.applied_resource_ids or result.removed_resource_ids or result.view_changed)
            ),
            updated_resource_ids=result.applied_resource_ids + result.removed_resource_ids,
            failed_resource_ids=tuple(failure.identifier for failure in result.failures),
            resource_view_changed=result.view_changed,
        )

    def _replace(self, **changes: Any) -> RemoteResourceUpdateState:
        values = asdict(self.state)
        values.update(changes)
        return RemoteResourceUpdateState(**values)

    def _load_state(self) -> RemoteResourceUpdateState:
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return RemoteResourceUpdateState()
        return RemoteResourceUpdateState.from_dict(raw)

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_name(f".{self.state_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(asdict(self.state), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with temporary.open("r+", encoding="utf-8") as stream:
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.state_path)
        finally:
            temporary.unlink(missing_ok=True)


def _manifest_signature(manifest: ResourceManifest) -> tuple[object, ...]:
    resources = tuple(
        (
            resource.identifier,
            resource.type,
            resource.version,
            tuple((file.path, file.size, file.sha256) for file in resource.files),
            json.dumps(dict(resource.metadata), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )
        for resource in manifest.resources
    )
    return manifest.catalog_version, resources
