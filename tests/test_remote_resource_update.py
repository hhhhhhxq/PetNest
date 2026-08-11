from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path

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


def _clock(start: datetime):
    value = start

    def now() -> datetime:
        return value

    def advance(**kwargs: int) -> None:
        nonlocal value
        value += timedelta(**kwargs)

    return now, advance


def test_check_is_throttled_for_24_hours_but_force_bypasses(tmp_path: Path) -> None:
    now, advance = _clock(datetime(2026, 8, 11, 9, tzinfo=UTC))
    cache = _FakeCache(_manifest(b"new"))
    coordinator = RemoteResourceUpdateCoordinator(cache, tmp_path / "state.json", now=now)

    first = coordinator.check()
    advance(hours=1)
    skipped = coordinator.check()
    forced = coordinator.check(force=True)

    assert first.checked is True
    assert first.update_available is True
    assert skipped.skipped is True
    assert forced.checked is True
    assert cache.fetch_calls == 2


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
