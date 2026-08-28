from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import sqlite3
import subprocess
import sys
import time

import pytest

import petnest.core.codex_thread_index as thread_index_module
from petnest.core.codex_thread_index import (
    CodexThreadIndex,
    _normalize_lexical_path,
    _normalize_path,
    _sqlite_read_only_preflight,
    _strip_windows_extended_path_prefix,
)


def _create_database(
    home: Path,
    version: int,
    *,
    updated_column: str = "updated_at_ms",
    rows: list[tuple[str, str, object]] | None = None,
) -> Path:
    database = home / f"state_{version}.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute(
            f"CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, {updated_column})"
        )
        connection.executemany(
            f"INSERT INTO threads (id, rollout_path, {updated_column}) VALUES (?, ?, ?)",
            rows or [],
        )
    return database


def _session_file(home: Path, name: str = "thread.jsonl") -> Path:
    path = home / "sessions" / "2025" / "01" / "01" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"type":"session_meta"}\n', encoding="utf-8")
    return path


def _sqlite_source_snapshot(database: Path) -> tuple[tuple[str, ...], dict[str, tuple[int, int, bytes]]]:
    entries = tuple(sorted(path.name for path in database.parent.iterdir()))
    files: dict[str, tuple[int, int, bytes]] = {}
    for path in (database, Path(f"{database}-wal"), Path(f"{database}-shm")):
        if path.exists():
            stat = path.stat()
            files[path.name] = (stat.st_size, stat.st_mtime_ns, path.read_bytes())
    return entries, files


def _sqlite_header(*, wal: bool) -> bytes:
    header = bytearray(100)
    header[:16] = b"SQLite format 3\x00"
    header[18] = 2 if wal else 1
    header[19] = 2 if wal else 1
    return bytes(header)


def test_uses_latest_compatible_database_for_an_old_rollout_path(tmp_path: Path) -> None:
    old_rollout = _session_file(tmp_path, "from-old-day.jsonl")
    newer_rollout = _session_file(tmp_path, "from-new-day.jsonl")
    _create_database(tmp_path, 1, rows=[("old", str(old_rollout), 10)])
    _create_database(tmp_path, 2, rows=[("new", str(newer_rollout), 20)])

    index = CodexThreadIndex(tmp_path)

    assert index.recent_rollout_paths() == (newer_rollout,)
    assert index.last_status == "ready"


def test_resolves_rollout_suffix_identifier_to_canonical_thread_id(tmp_path: Path) -> None:
    thread_id = "01a04792-35f6-7833-b686-032b645972e3"
    rollout_id = "01a04799-9b90-71d2-816e-659670a7ccd3"
    rollout = _session_file(
        tmp_path,
        f"rollout-2026-08-28T17-00-44-{thread_id}_{rollout_id}.jsonl",
    )
    _create_database(tmp_path, 1, rows=[(thread_id, str(rollout), 10)])

    index = CodexThreadIndex(tmp_path)

    assert index.resolve_thread_id(rollout_id) == thread_id
    assert index.last_status == "ready"


def test_resolve_thread_id_accepts_an_exact_canonical_id(tmp_path: Path) -> None:
    thread_id = "01a04792-35f6-7833-b686-032b645972e3"
    rollout = _session_file(tmp_path, f"rollout-{thread_id}.jsonl")
    _create_database(tmp_path, 1, rows=[(thread_id, str(rollout), 10)])

    assert CodexThreadIndex(tmp_path).resolve_thread_id(thread_id) == thread_id


def test_resolve_thread_id_does_not_guess_from_partial_or_unknown_values(tmp_path: Path) -> None:
    thread_id = "01a04792-35f6-7833-b686-032b645972e3"
    rollout = _session_file(tmp_path, f"rollout-{thread_id}.jsonl")
    _create_database(tmp_path, 1, rows=[(thread_id, str(rollout), 10)])

    index = CodexThreadIndex(tmp_path)

    assert index.resolve_thread_id("01a04792") is None
    assert index.resolve_thread_id("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa") is None


def test_skips_newer_database_with_incompatible_schema(tmp_path: Path) -> None:
    rollout = _session_file(tmp_path)
    _create_database(tmp_path, 1, rows=[("usable", str(rollout), 10)])
    with sqlite3.connect(tmp_path / "state_2.sqlite") as connection:
        connection.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT)")

    assert CodexThreadIndex(tmp_path).recent_rollout_paths() == (rollout,)


def test_rejects_external_non_jsonl_and_directory_rollout_paths(tmp_path: Path) -> None:
    accepted = _session_file(tmp_path, "accepted.jsonl")
    external = tmp_path.parent / "outside.jsonl"
    external.write_text("outside", encoding="utf-8")
    non_jsonl = _session_file(tmp_path, "not-a-log.txt")
    directory = tmp_path / "sessions" / "2025" / "01" / "directory.jsonl"
    directory.mkdir()
    missing = tmp_path / "sessions" / "2025" / "01" / "01" / "missing.jsonl"
    _create_database(
        tmp_path,
        1,
        rows=[
            ("external", str(external), 40),
            ("non-jsonl", str(non_jsonl), 30),
            ("directory", str(directory), 20),
            ("relative", "sessions/2025/01/01/accepted.jsonl", 15),
            ("missing", str(missing), 12),
            ("accepted", str(accepted), 10),
        ],
    )

    assert CodexThreadIndex(tmp_path).recent_rollout_paths(limit=4) == (accepted,)


def test_rejects_symlinked_rollout_path(tmp_path: Path) -> None:
    external = tmp_path.parent / "outside.jsonl"
    external.write_text("outside", encoding="utf-8")
    linked = tmp_path / "sessions" / "2025" / "01" / "01" / "linked.jsonl"
    linked.parent.mkdir(parents=True)
    try:
        os.symlink(external, linked)
    except OSError:
        pytest.skip("Creating symlinks is unavailable on this Windows test host")
    _create_database(tmp_path, 1, rows=[("link", str(linked), 10)])

    assert CodexThreadIndex(tmp_path).recent_rollout_paths() == ()


@pytest.mark.skipif(os.name != "nt", reason="Junctions are a Windows-specific path type")
def test_rejects_rollout_path_below_a_junction(tmp_path: Path) -> None:
    external_root = tmp_path.parent / "external-session-directory"
    external_root.mkdir()
    external_log = external_root / "linked.jsonl"
    external_log.write_text("outside", encoding="utf-8")
    junction = tmp_path / "sessions" / "2025" / "01" / "01" / "junction"
    junction.parent.mkdir(parents=True)
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(external_root)],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("Creating junctions is unavailable on this Windows test host")
    try:
        _create_database(tmp_path, 1, rows=[("junction", str(junction / "linked.jsonl"), 10)])

        assert CodexThreadIndex(tmp_path).recent_rollout_paths() == ()
    finally:
        junction.rmdir()


@pytest.mark.parametrize(
    "database_setup",
    [
        "missing-table",
        "missing-rollout-path",
        "corrupt",
    ],
)
def test_returns_empty_for_missing_or_unreadable_database(
    tmp_path: Path, database_setup: str
) -> None:
    database = tmp_path / "state_1.sqlite"
    if database_setup == "missing-table":
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE other (id TEXT)")
    elif database_setup == "missing-rollout-path":
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, updated_at_ms INTEGER)")
    else:
        database.write_bytes(b"not a sqlite database")

    index = CodexThreadIndex(tmp_path)

    assert index.recent_rollout_paths() == ()
    assert index.last_status in {"incompatible", "unavailable"}


def test_default_limit_uses_a_bounded_overscan_for_duplicate_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    duplicate = _session_file(tmp_path, "duplicate-overscan.jsonl")
    unique = _session_file(tmp_path, "unique-overscan.jsonl")
    _create_database(
        tmp_path,
        1,
        rows=[
            *( (f"duplicate-{number}", str(duplicate), 1000 - number) for number in range(70) ),
            ("unique", str(unique), 900),
        ],
    )
    query_limits: list[int] = []
    original_connect = sqlite3.connect

    class _ConnectionProxy:
        def __init__(self, connection: sqlite3.Connection) -> None:
            self._connection = connection

        def execute(self, statement: str, parameters: tuple[object, ...] = ()) -> object:
            if "ORDER BY" in statement:
                query_limits.append(int(parameters[0]))
            return self._connection.execute(statement, parameters)

        def close(self) -> None:
            self._connection.close()

    monkeypatch.setattr(
        thread_index_module.sqlite3,
        "connect",
        lambda *args, **kwargs: _ConnectionProxy(original_connect(*args, **kwargs)),
    )

    assert CodexThreadIndex(tmp_path).recent_rollout_paths() == (duplicate, unique)
    assert query_limits == [256]


def test_returns_empty_when_database_is_exclusively_locked_by_another_process(tmp_path: Path) -> None:
    rollout = _session_file(tmp_path)
    database = _create_database(tmp_path, 1, rows=[("thread", str(rollout), 10)])
    older_rollout = _session_file(tmp_path, "older.jsonl")
    _create_database(tmp_path, 0, rows=[("older", str(older_rollout), 1)])
    ready = tmp_path / "writer-ready"
    process = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import sqlite3, sys, time; "
                "connection = sqlite3.connect(sys.argv[1]); "
                "connection.execute('PRAGMA locking_mode=EXCLUSIVE'); "
                "connection.execute('BEGIN EXCLUSIVE'); "
                "open(sys.argv[2], 'w').close(); "
                "time.sleep(10)"
            ),
            str(database),
            str(ready),
        ]
    )
    try:
        for _ in range(100):
            if ready.exists():
                break
            time.sleep(0.02)
        assert ready.exists()

        assert CodexThreadIndex(tmp_path).recent_rollout_paths() == ()
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_applies_limit_clamps_and_descending_update_order(tmp_path: Path) -> None:
    oldest = _session_file(tmp_path, "oldest.jsonl")
    newest = _session_file(tmp_path, "newest.jsonl")
    middle = _session_file(tmp_path, "middle.jsonl")
    _create_database(
        tmp_path,
        1,
        rows=[
            ("oldest", str(oldest), 1),
            ("newest", str(newest), 3),
            ("middle", str(middle), 2),
        ],
    )

    index = CodexThreadIndex(tmp_path)
    assert index.recent_rollout_paths(limit=2) == (newest, middle)
    assert index.recent_rollout_paths(limit=0) == (newest,)
    assert index.recent_rollout_paths(limit=999_999) == (newest, middle, oldest)


def test_deduplicates_rollout_paths_without_losing_older_unique_paths(tmp_path: Path) -> None:
    duplicate = _session_file(tmp_path, "duplicate.jsonl")
    unique = _session_file(tmp_path, "unique.jsonl")
    _create_database(
        tmp_path,
        1,
        rows=[
            ("duplicate-new", str(duplicate), 30),
            ("duplicate-old", str(duplicate), 20),
            ("unique", str(unique), 10),
        ],
    )

    assert CodexThreadIndex(tmp_path).recent_rollout_paths(limit=2) == (duplicate, unique)


def test_reads_uncheckpointed_wal_without_changing_source_database_or_wal(tmp_path: Path) -> None:
    rollout = _session_file(tmp_path)
    database = tmp_path / "state_1.sqlite"
    writer = sqlite3.connect(database)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute(
            "CREATE TABLE threads (id TEXT PRIMARY KEY, rollout_path TEXT, updated_at_ms INTEGER)"
        )
        writer.execute("INSERT INTO threads VALUES (?, ?, ?)", ("live", str(rollout), 10))
        writer.commit()
        assert Path(f"{database}-wal").is_file()
        before = _sqlite_source_snapshot(database)

        assert CodexThreadIndex(tmp_path).recent_rollout_paths() == (rollout,)

        after = _sqlite_source_snapshot(database)
        assert after[0] == before[0]
        for name in (database.name, f"{database.name}-wal"):
            assert after[1][name] == before[1][name]
    finally:
        writer.close()


def test_wal_preflight_requires_safe_wal_and_shm_sidecars(tmp_path: Path) -> None:
    database = tmp_path / "state_1.sqlite"
    database.write_bytes(_sqlite_header(wal=True))

    assert not _sqlite_read_only_preflight(tmp_path, database)

    Path(f"{database}-wal").write_bytes(b"wal")
    assert not _sqlite_read_only_preflight(tmp_path, database)

    Path(f"{database}-shm").write_bytes(b"shm")
    assert _sqlite_read_only_preflight(tmp_path, database)


@pytest.mark.parametrize("sidecars", [(), ("wal",)])
def test_wal_mode_with_missing_sidecars_returns_empty_without_creating_files(
    tmp_path: Path, sidecars: tuple[str, ...]
) -> None:
    _session_file(tmp_path)
    database = tmp_path / "state_1.sqlite"
    database.write_bytes(_sqlite_header(wal=True))
    for suffix in sidecars:
        Path(f"{database}-{suffix}").write_bytes(suffix.encode("ascii"))
    before = _sqlite_source_snapshot(database)

    assert CodexThreadIndex(tmp_path).recent_rollout_paths() == ()

    assert _sqlite_source_snapshot(database) == before


def test_rollback_mode_does_not_create_sidecars(tmp_path: Path) -> None:
    rollout = _session_file(tmp_path)
    database = _create_database(tmp_path, 1, rows=[("thread", str(rollout), 10)])
    before = _sqlite_source_snapshot(database)

    assert CodexThreadIndex(tmp_path).recent_rollout_paths() == (rollout,)

    assert _sqlite_source_snapshot(database) == before


def test_uses_updated_at_when_millisecond_timestamp_is_absent(tmp_path: Path) -> None:
    rollout = _session_file(tmp_path)
    _create_database(
        tmp_path,
        1,
        updated_column="updated_at",
        rows=[("thread", str(rollout), "2026-08-24T12:00:00Z")],
    )

    assert CodexThreadIndex(tmp_path).recent_rollout_paths() == (rollout,)


def test_opening_database_read_only_does_not_change_its_metadata(tmp_path: Path) -> None:
    rollout = _session_file(tmp_path)
    database = _create_database(tmp_path, 1, rows=[("thread", str(rollout), 10)])
    before = database.stat()

    assert CodexThreadIndex(tmp_path).recent_rollout_paths() == (rollout,)

    after = database.stat()
    assert (after.st_mtime_ns, after.st_size) == (before.st_mtime_ns, before.st_size)


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-length syntax is platform-specific")
def test_normalizes_windows_extended_length_paths_without_touching_filesystem() -> None:
    assert _normalize_path(r"\\?\C:\Codex\sessions\2025\01\01\thread.jsonl") == Path(
        r"C:\Codex\sessions\2025\01\01\thread.jsonl"
    )


def test_normalizes_posix_absolute_paths_lexically_without_touching_filesystem() -> None:
    assert _normalize_lexical_path("/codex/sessions/2025/01/01/thread.jsonl") == PurePosixPath(
        "/codex/sessions/2025/01/01/thread.jsonl"
    )


def test_extended_unc_prefix_marker_is_case_insensitive() -> None:
    assert _strip_windows_extended_path_prefix(
        r"\\?\unc\Server\Share\sessions\thread.jsonl"
    ) == r"\\Server\Share\sessions\thread.jsonl"
    assert _strip_windows_extended_path_prefix(
        r"\\?\UnC\Server\Share\sessions\thread.jsonl"
    ) == r"\\Server\Share\sessions\thread.jsonl"


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-length syntax is platform-specific")
def test_extended_length_rollout_path_is_checked_against_sessions_root(tmp_path: Path) -> None:
    rollout = _session_file(tmp_path)
    _create_database(tmp_path, 1, rows=[("thread", f"\\\\?\\{rollout}", 10)])

    assert CodexThreadIndex(tmp_path).recent_rollout_paths() == (rollout,)
