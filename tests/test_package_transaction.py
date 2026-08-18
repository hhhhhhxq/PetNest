"""Tests for directory candidate transactions."""

from __future__ import annotations

from pathlib import Path

import pytest

from petnest.core.package_transaction import PackageTransaction, PackageTransactionError


def snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_validator_failure_does_not_change_target(tmp_path: Path) -> None:
    target = tmp_path / "pet"
    target.mkdir()
    (target / "pet.json").write_bytes(b"before")
    before = snapshot(target)

    def reject(_: Path) -> None:
        raise ValueError("invalid")

    with pytest.raises(PackageTransactionError, match="invalid"):
        with PackageTransaction(target, reject) as transaction:
            transaction.candidate.joinpath("pet.json").write_bytes(b"after")
            transaction.commit()

    assert snapshot(target) == before


def test_commit_replaces_target_and_cleans_candidate(tmp_path: Path) -> None:
    target = tmp_path / "pet"
    target.mkdir()
    (target / "pet.json").write_bytes(b"before")

    with PackageTransaction(target, lambda _: None) as transaction:
        transaction.candidate.joinpath("pet.json").write_bytes(b"after")
        transaction.commit()
        assert target.joinpath("pet.json").read_bytes() == b"after"

    assert not any(item.name.startswith(".pet.") for item in tmp_path.iterdir())


def test_exception_before_commit_restores_original(tmp_path: Path) -> None:
    target = tmp_path / "pet"
    target.mkdir()
    (target / "pet.json").write_bytes(b"before")

    with pytest.raises(RuntimeError):
        with PackageTransaction(target, lambda _: None) as transaction:
            transaction.candidate.joinpath("pet.json").write_bytes(b"after")
            raise RuntimeError("abort")

    assert target.joinpath("pet.json").read_bytes() == b"before"


def test_first_rename_failure_keeps_original_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "pet"
    target.mkdir()
    (target / "pet.json").write_bytes(b"before")
    original_rename = Path.rename

    def fail_original_move(path: Path, destination: Path) -> Path:
        if path == target:
            raise PermissionError("locked")
        return original_rename(path, destination)

    monkeypatch.setattr(Path, "rename", fail_original_move)

    with pytest.raises(PackageTransactionError, match="原子切换失败"):
        with PackageTransaction(target, lambda _: None) as transaction:
            transaction.candidate.joinpath("pet.json").write_bytes(b"after")
            transaction.commit()

    assert target.joinpath("pet.json").read_bytes() == b"before"
    assert not any(item.name.startswith(".pet.rollback-") for item in tmp_path.iterdir())


def test_candidate_rename_failure_restores_original_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "pet"
    target.mkdir()
    (target / "pet.json").write_bytes(b"before")
    original_rename = Path.rename

    def fail_candidate_move(path: Path, destination: Path) -> Path:
        if path.name.startswith(".pet.candidate-"):
            raise PermissionError("candidate locked")
        return original_rename(path, destination)

    monkeypatch.setattr(Path, "rename", fail_candidate_move)

    with pytest.raises(PackageTransactionError, match="已恢复原目录"):
        with PackageTransaction(target, lambda _: None) as transaction:
            transaction.candidate.joinpath("pet.json").write_bytes(b"after")
            transaction.commit()

    assert target.joinpath("pet.json").read_bytes() == b"before"
    assert not any(item.name.startswith(".pet.rollback-") for item in tmp_path.iterdir())


def test_restore_failure_reports_preserved_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "pet"
    target.mkdir()
    (target / "pet.json").write_bytes(b"before")
    original_rename = Path.rename

    def fail_candidate_and_restore(path: Path, destination: Path) -> Path:
        if path.name.startswith(".pet.candidate-"):
            raise PermissionError("candidate locked")
        if path.name.startswith(".pet.rollback-"):
            raise PermissionError("restore locked")
        return original_rename(path, destination)

    monkeypatch.setattr(Path, "rename", fail_candidate_and_restore)

    with pytest.raises(PackageTransactionError, match=r"回滚目录保留在.*\.pet\.rollback-"):
        with PackageTransaction(target, lambda _: None) as transaction:
            transaction.candidate.joinpath("pet.json").write_bytes(b"after")
            transaction.commit()

    backups = tuple(item for item in tmp_path.iterdir() if item.name.startswith(".pet.rollback-"))
    assert len(backups) == 1
    assert backups[0].joinpath("pet.json").read_bytes() == b"before"
    assert not target.exists()


def test_rejects_symlink_target_before_resolving(tmp_path: Path) -> None:
    actual = tmp_path / "actual"
    actual.mkdir()
    link = tmp_path / "pet"
    try:
        link.symlink_to(actual, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"当前平台不允许创建目录符号链接：{error}")

    with pytest.raises(PackageTransactionError, match="符号链接"):
        PackageTransaction(link)
