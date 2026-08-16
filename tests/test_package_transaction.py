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
