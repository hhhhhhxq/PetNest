"""读取宠物/动作交换来源，并在写入前完成安全解包。"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import stat
import tempfile
from zipfile import BadZipFile, ZipFile, ZipInfo


class UnsafeExchangeSourceError(ValueError):
    """来源不是可安全读取的文件夹或 ZIP。"""


@dataclass(frozen=True, slots=True)
class ExchangeLimits:
    """限制不受信任来源消耗的文件数、磁盘空间和压缩倍率。"""

    max_files: int = 2000
    max_uncompressed_bytes: int = 512 * 1024 * 1024
    max_compression_ratio: int = 100
    blocked_suffixes: tuple[str, ...] = (".exe", ".dll", ".bat", ".cmd", ".ps1", ".com", ".scr")


@dataclass(slots=True)
class ExchangeSource:
    """已物化的交换来源；ZIP 来源在退出上下文后自动删除临时目录。"""

    root: Path
    temporary_root: Path | None = None

    @property
    def temporary(self) -> bool:
        return self.temporary_root is not None

    @classmethod
    def open(cls, path: Path, limits: ExchangeLimits | None = None) -> "ExchangeSource":
        """打开目录或 ZIP，并返回可在上下文中使用的内容根目录。"""

        configured = Path(path).expanduser()
        limits = limits or ExchangeLimits()
        if configured.is_dir():
            root = configured.resolve()
            _validate_tree(root, limits)
            return cls(root)
        if not configured.is_file():
            raise UnsafeExchangeSourceError(f"交换来源不存在：{path}")

        temporary_root = Path(tempfile.mkdtemp(prefix="petnest-exchange-"))
        try:
            _extract_zip(configured, temporary_root, limits)
            root = _unwrap_outer_directory(temporary_root)
            _validate_tree(root, limits)
            return cls(root=root, temporary_root=temporary_root)
        except Exception:
            shutil.rmtree(temporary_root, ignore_errors=True)
            raise

    def __enter__(self) -> "ExchangeSource":
        return self

    def __exit__(self, *_: object) -> None:
        if self.temporary_root is not None and self.temporary_root.exists():
            shutil.rmtree(self.temporary_root, ignore_errors=True)


def _extract_zip(archive_path: Path, destination: Path, limits: ExchangeLimits) -> None:
    try:
        with ZipFile(archive_path) as archive:
            entries = tuple(archive.infolist())
            files = tuple(item for item in entries if not item.is_dir())
            _check_count_and_size(files, limits)
            seen: set[str] = set()
            for item in entries:
                relative = _safe_member_path(item, limits)
                folded = relative.as_posix().casefold()
                if folded in seen:
                    raise UnsafeExchangeSourceError("ZIP 包含重复路径")
                seen.add(folded)
                if item.is_dir():
                    (destination / Path(*relative.parts)).mkdir(parents=True, exist_ok=True)
                    continue
                target = destination.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    except BadZipFile as error:
        raise UnsafeExchangeSourceError(f"ZIP 无法读取：{error}") from error
    except OSError as error:
        raise UnsafeExchangeSourceError(f"ZIP 无法解压：{error}") from error


def _safe_member_path(item: ZipInfo, limits: ExchangeLimits) -> PurePosixPath:
    mode = item.external_attr >> 16
    if stat.S_IFMT(mode) == stat.S_IFLNK:
        raise UnsafeExchangeSourceError("ZIP 不能包含符号链接")
    raw_name = item.filename.replace("\\", "/")
    relative = PurePosixPath(raw_name)
    windows = PureWindowsPath(item.filename)
    if (
        not raw_name
        or windows.is_absolute()
        or bool(windows.drive)
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise UnsafeExchangeSourceError("ZIP 路径不安全")
    if relative.name.casefold().endswith(limits.blocked_suffixes):
        raise UnsafeExchangeSourceError("ZIP 不能包含可执行文件")
    return relative


def _check_count_and_size(files: tuple[ZipInfo, ...], limits: ExchangeLimits) -> None:
    if len(files) > limits.max_files:
        raise UnsafeExchangeSourceError("ZIP 文件数量超出限制")
    total = sum(max(0, int(item.file_size)) for item in files)
    if total > limits.max_uncompressed_bytes:
        raise UnsafeExchangeSourceError("ZIP 解压体积超出限制")
    for item in files:
        if item.file_size <= 0:
            continue
        if item.compress_size == 0 or item.file_size / item.compress_size > limits.max_compression_ratio:
            raise UnsafeExchangeSourceError("ZIP 压缩比异常")


def _unwrap_outer_directory(root: Path) -> Path:
    children = tuple(root.iterdir())
    if len(children) == 1 and children[0].is_dir() and not children[0].is_symlink():
        return children[0]
    return root


def _validate_tree(root: Path, limits: ExchangeLimits) -> None:
    if not root.is_dir():
        raise UnsafeExchangeSourceError("交换来源内容根目录不存在")
    count = 0
    total = 0
    for current, directories, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in directories:
            candidate = current_path / name
            if candidate.is_symlink():
                raise UnsafeExchangeSourceError("交换来源不能包含符号链接")
            if not candidate.resolve().is_relative_to(root.resolve()):
                raise UnsafeExchangeSourceError("交换来源路径逃逸内容根目录")
        for name in filenames:
            candidate = current_path / name
            if candidate.is_symlink() or not candidate.resolve().is_relative_to(root.resolve()):
                raise UnsafeExchangeSourceError("交换来源不能包含包外链接")
            if candidate.suffix.casefold() in limits.blocked_suffixes:
                raise UnsafeExchangeSourceError("交换来源不能包含可执行文件")
            count += 1
            try:
                total += candidate.stat().st_size
            except OSError as error:
                raise UnsafeExchangeSourceError(f"交换来源文件无法读取：{candidate}") from error
    if count > limits.max_files:
        raise UnsafeExchangeSourceError("交换来源文件数量超出限制")
    if total > limits.max_uncompressed_bytes:
        raise UnsafeExchangeSourceError("交换来源解压体积超出限制")


__all__ = ["ExchangeLimits", "ExchangeSource", "UnsafeExchangeSourceError"]
