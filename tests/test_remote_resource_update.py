from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path

from petnest.core.remote_resource_cache import ResourceSyncFailure, ResourceSyncResult
from petnest.core.remote_resource_manifest import ResourceManifest
from petnest.core.remote_resource_update import RemoteResourceUpdateCoordinator


def _manifest(content: bytes, *, catalog_version: str = "2026.8.11") -> ResourceManifest:
    path = "resources/cursors/demo/arrow.cur"
    raw = {
        "schema_version": 1,
        "catalog_version": catalog_version,
        "resources": [
            {
                "id": "demo",
                "type": "cursor_theme",
                "version": "1.0.0",
                "files": [{"path": path, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}],
                "metadata": {"name": "Demo"},
            }
        ],
    }
    return ResourceManifest.from_dict(raw)


@dataclass
class _FakeCache:
    remote: ResourceManifest
    current: ResourceManifest | None = None
    fetch_calls: int = 0
    sync_calls: int = 0
    fail_sync: bool = False

    def fetch_manifest(self) -> ResourceManifest:
        self.fetch_calls += 1
        return self.remote

    def load_current_manifest(self) -> ResourceManifest | None:
        return self.current

    def sync(self) -> ResourceManifest:
        self.sync_calls += 1
        if self.fail_sync:
            raise RuntimeError("offline")
        self.current = self.remote
        return self.remote


@dataclass
class _PartialFakeCache:
    remote: ResourceManifest
    current: ResourceManifest
    result: ResourceSyncResult

    def fetch_manifest(self) -> ResourceManifest:
        return self.remote

    def load_current_manifest(self) -> ResourceManifest:
        return self.current

    def sync_partial(self) -> ResourceSyncResult:
        return self.result


@dataclass
class _CallbackFakeCache:
    remote: ResourceManifest
    current: ResourceManifest
    result: ResourceSyncResult
    received_callback: object | None = None

    def fetch_manifest(self) -> ResourceManifest:
        return self.remote

    def load_current_manifest(self) -> ResourceManifest:
        return self.current

    def sync_partial(self, **kwargs: object) -> ResourceSyncResult:
        self.received_callback = kwargs.get("on_resource_started")
        return self.result


def _clock(start: datetime):
    value = start

    def now() -> datetime:
        return value

    def advance(**kwargs: int) -> None:
        nonlocal value
        value += timedelta(**kwargs)

    return now, advance


def test_check_is_throttled_for_60_seconds_but_force_bypasses(tmp_path: Path) -> None:
    now, advance = _clock(datetime(2026, 8, 11, 9, tzinfo=UTC))
    cache = _FakeCache(_manifest(b"new"))
    coordinator = RemoteResourceUpdateCoordinator(cache, tmp_path / "state.json", now=now)

    first = coordinator.check()
    advance(seconds=59)
    skipped = coordinator.check()
    advance(seconds=2)
    refreshed = coordinator.check()
    forced = coordinator.check(force=True)

    assert first.checked is True
    assert first.update_available is True
    assert skipped.skipped is True
    assert refreshed.checked is True
    assert forced.checked is True
    assert cache.fetch_calls == 3


def test_update_badge_state_survives_reload_and_clears_after_apply(tmp_path: Path) -> None:
    now, _advance = _clock(datetime(2026, 8, 11, 9, tzinfo=UTC))
    cache = _FakeCache(_manifest(b"new"))
    state_path = tmp_path / "state.json"
    coordinator = RemoteResourceUpdateCoordinator(cache, state_path, now=now)

    coordinator.check()
    reloaded = RemoteResourceUpdateCoordinator(cache, state_path, now=now)

    assert reloaded.update_available is True
    applied = reloaded.apply()

    assert applied.applied is True
    assert reloaded.update_available is False
    assert json.loads(state_path.read_text(encoding="utf-8"))["update_available"] is False


def test_same_catalog_version_with_changed_file_hash_is_an_update(tmp_path: Path) -> None:
    now, _advance = _clock(datetime(2026, 8, 11, 9, tzinfo=UTC))
    old = _manifest(b"old")
    cache = _FakeCache(_manifest(b"new"), current=old)
    coordinator = RemoteResourceUpdateCoordinator(cache, tmp_path / "state.json", now=now)

    result = coordinator.check()

    assert result.checked is True
    assert result.update_available is True


def test_failed_apply_keeps_update_badge(tmp_path: Path) -> None:
    now, _advance = _clock(datetime(2026, 8, 11, 9, tzinfo=UTC))
    cache = _FakeCache(_manifest(b"new"), fail_sync=True)
    coordinator = RemoteResourceUpdateCoordinator(cache, tmp_path / "state.json", now=now)
    coordinator.check()

    result = coordinator.apply()

    assert result.applied is False
    assert coordinator.update_available is True


def test_partial_apply_keeps_badge_and_reports_resource_level_result(tmp_path: Path) -> None:
    now, _advance = _clock(datetime(2026, 8, 11, 9, tzinfo=UTC))
    old = _manifest(b"old")
    remote = _manifest(b"new")
    cache = _PartialFakeCache(
        remote=remote,
        current=old,
        result=ResourceSyncResult(
            manifest=remote,
            applied_resource_ids=("demo",),
            failures=(ResourceSyncFailure("spark", "HTTP 502"),),
        ),
    )
    coordinator = RemoteResourceUpdateCoordinator(cache, tmp_path / "state.json", now=now)
    coordinator.check()

    result = coordinator.apply()

    assert result.applied is False
    assert result.partial is True
    assert result.updated_resource_ids == ("demo",)
    assert result.failed_resource_ids == ("spark",)
    assert result.resource_view_changed is False
    assert coordinator.update_available is True
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["last_error"] == "spark: HTTP 502"


def test_partial_apply_reports_a_changed_view_even_without_applied_resources(tmp_path: Path) -> None:
    now, _advance = _clock(datetime(2026, 8, 11, 9, tzinfo=UTC))
    old = _manifest(b"old")
    remote = _manifest(b"new")
    cache = _PartialFakeCache(
        remote=remote,
        current=old,
        result=ResourceSyncResult(
            manifest=remote,
            view_changed=True,
            failures=(ResourceSyncFailure("spark", "HTTP 502"),),
        ),
    )
    coordinator = RemoteResourceUpdateCoordinator(cache, tmp_path / "state.json", now=now)
    coordinator.check()

    result = coordinator.apply()

    assert result.applied is False
    assert result.partial is True
    assert result.updated_resource_ids == ()
    assert result.resource_view_changed is True
    assert coordinator.update_available is True


def test_apply_passes_resource_started_callback_to_cache(tmp_path: Path) -> None:
    old = _manifest(b"old")
    remote = _manifest(b"new")
    cache = _CallbackFakeCache(
        remote=remote,
        current=old,
        result=ResourceSyncResult(manifest=remote, applied_resource_ids=("demo",)),
    )
    coordinator = RemoteResourceUpdateCoordinator(cache, tmp_path / "state.json")
    coordinator.check()
    started: list[object | None] = []
    callback = started.append

    coordinator.apply(on_resource_started=callback)

    assert cache.received_callback is callback
