"""Tests for safe folder and ZIP exchange sources."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from petnest.core.exchange_source import (
    ExchangeLimits,
    ExchangeSource,
    UnsafeExchangeSourceError,
)


def build_zip(tmp_path: Path, members: dict[str, bytes | str]) -> Path:
    archive = tmp_path / "source.zip"
    with ZipFile(archive, "w") as output:
        for name, contents in members.items():
            output.writestr(name, contents)
    return archive


def test_materialize_zip_unwraps_one_outer_directory(tmp_path: Path) -> None:
    archive = build_zip(tmp_path, {"shared/petnest-action-pack.json": "{}"})

    with ExchangeSource.open(archive) as source:
        assert source.root.name == "shared"
        assert (source.root / "petnest-action-pack.json").is_file()


def test_folder_source_keeps_folder_root(tmp_path: Path) -> None:
    source_root = tmp_path / "folder"
    source_root.mkdir()
    (source_root / "pet.json").write_text("{}", encoding="utf-8")

    with ExchangeSource.open(source_root) as source:
        assert source.root == source_root.resolve()
        assert source.temporary is False


@pytest.mark.parametrize("member", ["../escape.png", "/absolute.png", "C:\\escape.png"])
def test_rejects_unsafe_zip_member(tmp_path: Path, member: str) -> None:
    archive = build_zip(tmp_path, {member: b"x"})

    with pytest.raises(UnsafeExchangeSourceError):
        ExchangeSource.open(archive)


def test_rejects_symbolic_link_zip_member(tmp_path: Path) -> None:
    archive = tmp_path / "symlink.zip"
    info = __import__("zipfile").ZipInfo("link")
    info.external_attr = 0o120777 << 16
    with ZipFile(archive, "w") as output:
        output.writestr(info, "target")

    with pytest.raises(UnsafeExchangeSourceError):
        ExchangeSource.open(archive)


def test_rejects_executable_files(tmp_path: Path) -> None:
    archive = build_zip(tmp_path, {"shared/run.exe": b"x"})

    with pytest.raises(UnsafeExchangeSourceError):
        ExchangeSource.open(archive)


def test_rejects_file_and_size_limits(tmp_path: Path) -> None:
    archive = build_zip(tmp_path, {"a.png": b"1", "b.png": b"2"})

    with pytest.raises(UnsafeExchangeSourceError, match="文件数量"):
        ExchangeSource.open(archive, ExchangeLimits(max_files=1))

    with pytest.raises(UnsafeExchangeSourceError, match="解压体积"):
        ExchangeSource.open(archive, ExchangeLimits(max_uncompressed_bytes=1))


def test_source_cleanup_removes_temporary_directory(tmp_path: Path) -> None:
    archive = build_zip(tmp_path, {"petnest-action-pack.json": "{}"})

    with ExchangeSource.open(archive) as source:
        temporary_root = source.temporary_root
        assert temporary_root is not None and temporary_root.exists()

    assert temporary_root is not None and not temporary_root.exists()
