"""在宠物目录同一文件系统内准备、验证并原子切换候选包。"""

from __future__ import annotations

from collections.abc import Callable
import os
from pathlib import Path
import shutil
import tempfile
from uuid import uuid4

from .package_validator import PackageValidator


class PackageTransactionError(ValueError):
    """候选包未通过验证或原子切换失败。"""


class PackageTransaction:
    """目录级事务；提交前的任何失败都不会触碰正式目录。"""

    def __init__(self, target: Path, validator: Callable[[Path], object] | None = None) -> None:
        raw_target = Path(target).expanduser()
        if raw_target.is_symlink():
            raise PackageTransactionError("事务目标不能是符号链接")
        self.target = raw_target.resolve()
        self._validator = validator or PackageValidator().validate
        self._candidate: Path | None = None
        self._backup: Path | None = None
        self._committed = False

    @property
    def candidate(self) -> Path:
        if self._candidate is None:
            raise PackageTransactionError("事务尚未准备")
        return self._candidate

    def __enter__(self) -> "PackageTransaction":
        self.prepare()
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        if exc_type is not None:
            self.rollback()
        elif self._committed:
            self._cleanup_backup()
        else:
            self.rollback()
        return False

    def prepare(self) -> Path:
        if self._candidate is not None:
            return self._candidate
        if self.target.is_symlink():
            raise PackageTransactionError("事务目标不能是符号链接")
        parent = self.target.parent
        parent.mkdir(parents=True, exist_ok=True)
        candidate = Path(tempfile.mkdtemp(prefix=f".{self.target.name}.candidate-", dir=parent))
        try:
            if self.target.exists():
                if not self.target.is_dir():
                    raise PackageTransactionError(f"目标包不是目录：{self.target}")
                _reject_symlinks(self.target)
                shutil.copytree(self.target, candidate, dirs_exist_ok=True, symlinks=False)
            self._candidate = candidate
            return candidate
        except Exception:
            shutil.rmtree(candidate, ignore_errors=True)
            raise

    def commit(self) -> None:
        candidate = self.candidate
        self._validate(candidate)
        backup: Path | None = None
        original_moved = False
        try:
            if self.target.exists():
                backup = self.target.parent / f".{self.target.name}.rollback-{uuid4().hex}"
                self.target.rename(backup)
                original_moved = True
                self._backup = backup
            candidate.rename(self.target)
            self._candidate = None
            self._committed = True
        except Exception as error:
            if not original_moved:
                self._backup = None
                raise PackageTransactionError(f"原子切换失败，原目录未改动：{error}") from error
            try:
                if self.target.exists() and self.target.is_dir():
                    shutil.rmtree(self.target)
                if backup is None or not backup.exists():
                    raise FileNotFoundError(f"回滚目录不存在：{backup}")
                backup.rename(self.target)
            except Exception as restore_error:
                self._backup = backup
                raise PackageTransactionError(
                    f"原子切换失败，且无法恢复原目录；回滚目录保留在 {backup}：{restore_error}"
                ) from error
            self._backup = None
            raise PackageTransactionError(f"原子切换失败，已恢复原目录：{error}") from error

    def rollback(self) -> None:
        if self._committed:
            if self.target.exists():
                shutil.rmtree(self.target, ignore_errors=True)
            if self._backup is not None and self._backup.exists():
                self._backup.rename(self.target)
            self._backup = None
            self._committed = False
            return
        if self._candidate is not None and self._candidate.exists():
            shutil.rmtree(self._candidate, ignore_errors=True)
        self._candidate = None

    def _validate(self, candidate: Path) -> None:
        try:
            result = self._validator(candidate)
        except PackageTransactionError:
            raise
        except Exception as error:
            raise PackageTransactionError(f"候选包校验失败：{error}") from error
        if result is False:
            raise PackageTransactionError("候选包校验失败")
        if result is None:
            return
        if hasattr(result, "is_valid") and not bool(result.is_valid):
            errors = getattr(result, "errors", ())
            detail = "；".join(str(item) for item in errors) or "未知错误"
            raise PackageTransactionError(f"候选包校验失败：{detail}")

    def _cleanup_backup(self) -> None:
        if self._backup is not None and self._backup.exists():
            shutil.rmtree(self._backup, ignore_errors=True)
        self._backup = None


def _reject_symlinks(root: Path) -> None:
    for current, directories, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in (*directories, *filenames):
            candidate = current_path / name
            if candidate.is_symlink():
                raise PackageTransactionError(f"目标包不能包含符号链接：{candidate}")


__all__ = ["PackageTransaction", "PackageTransactionError"]
