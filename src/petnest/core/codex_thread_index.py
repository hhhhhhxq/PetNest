"""Read recent Codex rollout locations from Desktop's local state databases."""

from __future__ import annotations

import os
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
import posixpath
import re
import sqlite3
from typing import Literal
import ntpath


_STATE_DATABASE_NAME = re.compile(r"state_(\d+)\.sqlite\Z", re.IGNORECASE)
_UUID_IDENTIFIER = re.compile(
    r"(?<![0-9a-f])([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})(?![0-9a-f])",
    re.IGNORECASE,
)
_MAX_LIMIT = 4096
_SQLITE_TIMEOUT_SECONDS = 0.05
_IndexStatus = Literal["ready", "unavailable", "incompatible"]


class CodexThreadIndex:
    """A bounded, read-only index of safely accessible Codex rollout logs."""

    def __init__(self, codex_home: Path) -> None:
        self._home = _normalize_path(codex_home)
        self._sessions = self._home / "sessions"
        self._last_status: _IndexStatus = "unavailable"

    @property
    def last_status(self) -> _IndexStatus:
        return self._last_status

    def recent_rollout_paths(self, *, limit: int = 64) -> tuple[Path, ...]:
        """Return the most recently updated safe rollout logs, without reading their bodies."""
        bounded_limit = _clamp_limit(limit)
        if not _path_chain_is_safe(self._home.parent, self._home):
            self._last_status = "unavailable"
            return ()
        if not _path_chain_is_safe(self._home, self._sessions) or not self._sessions.is_dir():
            self._last_status = "unavailable"
            return ()
        saw_incompatible = False
        for database in self._candidate_databases():
            status, paths = self._read_database(database, bounded_limit)
            if status == "unavailable":
                self._last_status = "unavailable"
                return ()
            if status == "ready":
                self._last_status = "ready"
                return paths
            saw_incompatible = True
        self._last_status = "incompatible" if saw_incompatible else "unavailable"
        return ()

    def resolve_thread_id(self, candidate_id: str) -> str | None:
        """Resolve a callback/session identifier to Desktop's canonical thread ID.

        Resumed Desktop rollouts can include a second UUID in the rollout filename.
        Some callback producers report that rollout identifier instead of the stable
        thread ID stored in the ``threads`` table.  Resolve both forms without
        opening or parsing conversation bodies.
        """
        if not isinstance(candidate_id, str) or not (0 < len(candidate_id) <= 200):
            return None
        if not _path_chain_is_safe(self._home.parent, self._home):
            self._last_status = "unavailable"
            return None
        if not _path_chain_is_safe(self._home, self._sessions) or not self._sessions.is_dir():
            self._last_status = "unavailable"
            return None
        saw_incompatible = False
        for database in self._candidate_databases():
            status, thread_id = self._resolve_database_thread_id(database, candidate_id)
            if status == "unavailable":
                self._last_status = "unavailable"
                return None
            if status == "ready":
                self._last_status = "ready"
                return thread_id
            saw_incompatible = True
        self._last_status = "incompatible" if saw_incompatible else "unavailable"
        return None

    def _candidate_databases(self) -> tuple[Path, ...]:
        try:
            candidates = []
            for path in self._home.glob("state_*.sqlite"):
                if not _STATE_DATABASE_NAME.fullmatch(path.name):
                    continue
                if not _path_chain_is_safe(self._home, path):
                    continue
                if path.is_file():
                    candidates.append(path)
        except OSError:
            return ()
        candidates.sort(key=_database_sort_key, reverse=True)
        return tuple(candidates)

    def _read_database(
        self, database: Path, limit: int
    ) -> tuple[Literal["incompatible", "ready", "unavailable"], tuple[Path, ...]]:
        if not _sqlite_read_only_preflight(self._home, database):
            return "unavailable", ()
        try:
            connection = sqlite3.connect(
                f"{database.as_uri()}?mode=ro",
                uri=True,
                timeout=_SQLITE_TIMEOUT_SECONDS,
            )
            try:
                connection.execute("PRAGMA query_only=ON")
                columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(threads)")
                }
                timestamp_column = (
                    "updated_at_ms"
                    if "updated_at_ms" in columns
                    else "updated_at"
                    if "updated_at" in columns
                    else None
                )
                if timestamp_column is None or not {"id", "rollout_path"}.issubset(columns):
                    return "incompatible", ()
                rows = connection.execute(
                    "SELECT id, rollout_path, "
                    f'"{timestamp_column}" '
                    "FROM threads "
                    f'ORDER BY "{timestamp_column}" DESC, id DESC LIMIT ?',
                    (_query_limit(limit),),
                )
                paths: list[Path] = []
                seen: set[Path] = set()
                for _, rollout_path, _ in rows:
                    path = self._safe_rollout_path(rollout_path)
                    if path is None or path in seen:
                        continue
                    seen.add(path)
                    paths.append(path)
                    if len(paths) == limit:
                        break
                return "ready", tuple(paths)
            finally:
                connection.close()
        except (OSError, sqlite3.Error, ValueError):
            return "unavailable", ()

    def _resolve_database_thread_id(
        self, database: Path, candidate_id: str
    ) -> tuple[Literal["incompatible", "ready", "unavailable"], str | None]:
        if not _sqlite_read_only_preflight(self._home, database):
            return "unavailable", None
        try:
            connection = sqlite3.connect(
                f"{database.as_uri()}?mode=ro",
                uri=True,
                timeout=_SQLITE_TIMEOUT_SECONDS,
            )
            try:
                connection.execute("PRAGMA query_only=ON")
                columns = {
                    str(row[1])
                    for row in connection.execute("PRAGMA table_info(threads)")
                }
                timestamp_column = (
                    "updated_at_ms"
                    if "updated_at_ms" in columns
                    else "updated_at"
                    if "updated_at" in columns
                    else None
                )
                if timestamp_column is None or not {"id", "rollout_path"}.issubset(columns):
                    return "incompatible", None
                exact = connection.execute(
                    "SELECT id FROM threads WHERE id = ? LIMIT 1",
                    (candidate_id,),
                ).fetchone()
                if exact is not None and isinstance(exact[0], str) and exact[0]:
                    return "ready", exact[0]
                if _UUID_IDENTIFIER.fullmatch(candidate_id) is None:
                    return "ready", None
                rows = connection.execute(
                    "SELECT id, rollout_path FROM threads "
                    f'ORDER BY "{timestamp_column}" DESC, id DESC LIMIT ?',
                    (_MAX_LIMIT,),
                )
                expected = candidate_id.casefold()
                for thread_id, rollout_path in rows:
                    if not isinstance(thread_id, str) or not thread_id:
                        continue
                    path = self._safe_rollout_path(rollout_path)
                    if path is None:
                        continue
                    identifiers = {
                        match.group(1).casefold()
                        for match in _UUID_IDENTIFIER.finditer(path.stem)
                    }
                    if expected in identifiers:
                        return "ready", thread_id
                return "ready", None
            finally:
                connection.close()
        except (OSError, sqlite3.Error, ValueError):
            return "unavailable", None

    def _safe_rollout_path(self, value: object) -> Path | None:
        if not isinstance(value, str) or not value:
            return None
        unprefixed = _strip_windows_extended_path_prefix(value)
        if not Path(unprefixed).is_absolute():
            return None
        path = _normalize_path(unprefixed)
        if path.suffix.casefold() != ".jsonl":
            return None
        try:
            path.relative_to(self._sessions)
        except ValueError:
            return None
        if not _path_chain_is_safe(self._home, path):
            return None
        try:
            return path if path.is_file() else None
        except OSError:
            return None


def _normalize_path(path: Path | str) -> Path:
    """Normalize lexical Windows and POSIX paths without resolving links."""
    normalized = _normalize_lexical_path(str(path))
    if os.name == "nt":
        return Path(ntpath.abspath(str(normalized)))
    return Path(posixpath.abspath(str(normalized)))


def _normalize_lexical_path(value: str) -> PurePath:
    """Normalize a path lexically while retaining its Windows or POSIX flavor."""
    unprefixed = _strip_windows_extended_path_prefix(value)
    if _looks_like_windows_path(unprefixed):
        return PureWindowsPath(ntpath.normpath(unprefixed))
    return PurePosixPath(posixpath.normpath(unprefixed))


def _strip_windows_extended_path_prefix(value: str) -> str:
    if value[:8].casefold() == "\\\\?\\unc\\":
        return "\\\\" + value[8:]
    if value.startswith("\\\\?\\"):
        return value[4:]
    return value


def _looks_like_windows_path(value: str) -> bool:
    return value.startswith("\\\\") or (len(value) >= 2 and value[1] == ":")


def _clamp_limit(value: int) -> int:
    try:
        return max(1, min(_MAX_LIMIT, int(value)))
    except (TypeError, ValueError, OverflowError):
        return 1


def _query_limit(limit: int) -> int:
    return min(_MAX_LIMIT, max(limit, limit * 4))


def _database_sort_key(path: Path) -> tuple[int, int, str]:
    match = _STATE_DATABASE_NAME.fullmatch(path.name)
    try:
        modified_ns = path.stat().st_mtime_ns
    except OSError:
        modified_ns = 0
    return (int(match.group(1)) if match is not None else -1, modified_ns, path.name.casefold())


def _path_chain_is_safe(root: Path, path: Path) -> bool:
    try:
        relative = path.absolute().relative_to(root.absolute())
    except ValueError:
        return False
    current = root.absolute()
    if _is_link_like(current):
        return False
    for part in relative.parts:
        current /= part
        if _is_link_like(current):
            return False
    return True


def _is_link_like(path: Path) -> bool:
    try:
        return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())
    except OSError:
        return True


def _sqlite_read_only_preflight(root: Path, database: Path) -> bool:
    """Prevent a read-only SQLite connection from creating missing WAL sidecars."""
    wal = Path(f"{database}-wal")
    shared_memory = Path(f"{database}-shm")
    rollback_journal = Path(f"{database}-journal")
    try:
        if rollback_journal.exists() or _is_link_like(rollback_journal):
            return False
        with database.open("rb") as stream:
            header = stream.read(100)
    except OSError:
        return False
    wal_mode = (len(header) >= 20 and (header[18] == 2 or header[19] == 2)) or wal.exists()
    if not wal_mode:
        return True
    for path in (wal, shared_memory):
        try:
            if not path.exists() or not path.is_file():
                return False
        except OSError:
            return False
        if not _path_chain_is_safe(root, path):
            return False
    return True


__all__ = ["CodexThreadIndex"]
