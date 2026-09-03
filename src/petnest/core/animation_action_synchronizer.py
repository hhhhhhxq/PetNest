"""将未声明的动画帧目录安全地同步到宠物包配置。"""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Mapping

from .package_validator import (
    SUPPORTED_ANIMATION_FRAME_SUFFIXES,
    PackageValidator,
    animation_frame_paths,
)


class AnimationActionSyncError(ValueError):
    """同步动画动作时无法保证配置完整性。"""


@dataclass(frozen=True, slots=True)
class SyncedAction:
    """一个新写入配置的动画动作及其直接动画帧数。"""

    name: str
    frame_count: int


@dataclass(frozen=True, slots=True)
class SyncedTimeline:
    """一个因磁盘动画帧增删而自动调整过的逐帧时长。"""

    name: str
    frame_count: int


@dataclass(frozen=True, slots=True)
class AnimationActionSyncResult:
    """同步操作新增的动作及自动对齐的时间线。"""

    added: tuple[SyncedAction, ...]
    reconciled: tuple[SyncedTimeline, ...] = ()

    @property
    def changed(self) -> bool:
        """本次同步是否会写入 ``pet.json``。"""
        return bool(self.added or self.reconciled)


class AnimationActionSynchronizer:
    """发现动画目录，并且只在候选配置通过完整包校验后才写入。"""

    def snapshot_config_bytes(self, package_root: Path) -> bytes:
        """安全读取包内常规 ``pet.json`` 的原始字节，供调用方回滚。"""
        try:
            root = package_root.expanduser().resolve()
            config_path = root / "pet.json"
            self._ensure_regular_config(config_path)
            return config_path.read_bytes()
        except AnimationActionSyncError:
            raise
        except Exception as error:
            raise AnimationActionSyncError(f"读取动画配置失败：{error}") from error

    def restore_config_bytes(self, package_root: Path, contents: bytes) -> None:
        """通过同卷原子替换恢复先前保存的 ``pet.json`` 原始字节。"""
        try:
            root = package_root.expanduser().resolve()
            config_path = root / "pet.json"
            self._ensure_regular_config(config_path)
            self._replace_bytes_atomically(config_path, contents)
        except AnimationActionSyncError:
            raise
        except Exception as error:
            raise AnimationActionSyncError(f"恢复动画配置失败：{error}") from error

    def sync(self, package_root: Path) -> AnimationActionSyncResult:
        """将直接包含动画帧且未声明的 ``animations`` 子目录写入 ``pet.json``。"""
        try:
            root = package_root.expanduser().resolve()
            config_path = root / "pet.json"
            self._ensure_regular_config(config_path)
            config = self._read_config(config_path)
            animations = config.get("animations")
            if not isinstance(animations, dict):
                raise AnimationActionSyncError("pet.json 的 animations 必须是对象")

            additions = self._discover_additions(root, animations)
            candidate = dict(config)
            candidate_animations = dict(animations)
            candidate["animations"] = candidate_animations
            for action in additions:
                candidate_animations[action.name] = self._definition_for(action.name)

            reconciled = self._reconcile_frame_durations(root, candidate_animations)
            if not additions and not reconciled:
                return AnimationActionSyncResult(added=())

            self._validate_candidate(root, candidate)
            self._replace_config_atomically(config_path, candidate)
            return AnimationActionSyncResult(added=additions, reconciled=reconciled)
        except AnimationActionSyncError:
            raise
        except Exception as error:
            raise AnimationActionSyncError(f"同步动画动作失败：{error}") from error

    def update_frame_durations(self, package_root: Path, timelines: Mapping[str, tuple[int, ...]]) -> None:
        """将编辑后的逐帧时长原子写入宠物包，而非保存为本机覆盖。"""
        if not timelines:
            return
        try:
            root = package_root.expanduser().resolve()
            config_path = root / "pet.json"
            self._ensure_regular_config(config_path)
            config = self._read_config(config_path)
            animations = config.get("animations")
            if not isinstance(animations, dict):
                raise AnimationActionSyncError("pet.json 的 animations 必须是对象")

            candidate = dict(config)
            candidate_animations = dict(animations)
            candidate["animations"] = candidate_animations
            for action, durations in timelines.items():
                definition = animations.get(action)
                if not isinstance(definition, dict):
                    raise AnimationActionSyncError(f"动画 {action} 不存在，无法保存时长")
                if not durations or any(isinstance(duration, bool) or not isinstance(duration, int) or duration <= 0 for duration in durations):
                    raise AnimationActionSyncError(f"动画 {action} 的帧时长必须全部为正整数")
                candidate_definition = dict(definition)
                candidate_definition["frame_durations_ms"] = list(durations)
                candidate_animations[action] = candidate_definition

            self._validate_candidate(root, candidate)
            self._replace_config_atomically(config_path, candidate)
        except AnimationActionSyncError:
            raise
        except Exception as error:
            raise AnimationActionSyncError(f"保存动画时长失败：{error}") from error

    @staticmethod
    def _read_config(config_path: Path) -> dict[str, Any]:
        parsed = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(parsed, dict):
            raise AnimationActionSyncError("pet.json 顶层必须是对象")
        return parsed

    @staticmethod
    def _ensure_regular_config(config_path: Path) -> None:
        if config_path.is_symlink() or not stat.S_ISREG(config_path.lstat().st_mode):
            raise AnimationActionSyncError("pet.json 必须是包目录中的常规文件，不能是符号链接")

    @staticmethod
    def _discover_additions(root: Path, animations: dict[str, Any]) -> tuple[SyncedAction, ...]:
        animation_root = root / "animations"
        if not animation_root.is_dir():
            return ()

        actions: list[SyncedAction] = []
        directories = sorted(
            (path for path in animation_root.iterdir() if path.is_dir()),
            key=lambda path: (path.name.casefold(), path.name),
        )
        for directory in directories:
            if directory.name in animations:
                continue
            frame_entries = tuple(
                path
                for path in directory.iterdir()
                if path.suffix.casefold() in SUPPORTED_ANIMATION_FRAME_SUFFIXES and not path.is_dir()
            )
            for path in frame_entries:
                if not AnimationActionSynchronizer._is_safe_animation_frame(path, root):
                    raise AnimationActionSyncError(
                        f"动画目录 {directory.name} 的 PNG/WebP 帧 {path.name} 必须是包内的常规文件，不能是符号链接"
                    )
            frames = animation_frame_paths(directory)
            if frames:
                actions.append(SyncedAction(directory.name, len(frames)))
        return tuple(actions)

    @staticmethod
    def _is_safe_animation_frame(path: Path, root: Path) -> bool:
        return (
            not path.is_symlink()
            and stat.S_ISREG(path.lstat().st_mode)
            and path.resolve().is_relative_to(root)
        )

    @staticmethod
    def _definition_for(name: str) -> dict[str, object]:
        definition: dict[str, object] = {
            "path": f"animations/{name}",
            "fps": 10,
            "loop": name != "wake",
            "priority": 20,
        }
        if name == "wake":
            definition["next"] = "context"
        return definition

    @staticmethod
    def _reconcile_frame_durations(root: Path, animations: dict[str, Any]) -> tuple[SyncedTimeline, ...]:
        """按磁盘上的直接动画帧数补齐或截断已有逐帧时长。"""
        reconciled: list[SyncedTimeline] = []
        for name, definition in animations.items():
            if not isinstance(name, str) or not isinstance(definition, dict):
                continue
            durations = definition.get("frame_durations_ms")
            if not isinstance(durations, list) or any(
                isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in durations
            ):
                continue
            frame_count = AnimationActionSynchronizer._direct_animation_frame_count(root, definition)
            if frame_count is None or frame_count == 0 or len(durations) == frame_count:
                continue
            if len(durations) > frame_count:
                synced_durations = durations[:frame_count]
            else:
                fallback_duration = durations[-1] if durations else AnimationActionSynchronizer._fps_duration(definition)
                synced_durations = durations + [fallback_duration] * (frame_count - len(durations))
            candidate_definition = dict(definition)
            candidate_definition["frame_durations_ms"] = synced_durations
            animations[name] = candidate_definition
            reconciled.append(SyncedTimeline(name, frame_count))
        return tuple(reconciled)

    @staticmethod
    def _direct_animation_frame_count(root: Path, definition: dict[str, Any]) -> int | None:
        configured_path = definition.get("path")
        if not isinstance(configured_path, str) or not configured_path.strip():
            return None
        path = Path(configured_path)
        if path.is_absolute() or PureWindowsPath(configured_path).is_absolute():
            return None
        animation_path = (root / path).resolve()
        if not animation_path.is_relative_to(root) or not animation_path.is_dir():
            return None
        return len(animation_frame_paths(animation_path))

    @staticmethod
    def _fps_duration(definition: dict[str, Any]) -> int:
        fps = definition.get("fps")
        if isinstance(fps, bool) or not isinstance(fps, (int, float)) or fps <= 0:
            return 100
        return max(1, round(1000 / fps))

    @staticmethod
    def _validate_candidate(root: Path, config: dict[str, Any]) -> None:
        with tempfile.TemporaryDirectory(prefix=f".{root.name}-sync-", dir=root.parent) as temporary_directory:
            candidate_root = Path(temporary_directory) / root.name
            shutil.copytree(root, candidate_root, symlinks=True, ignore=shutil.ignore_patterns("pet.json"))
            AnimationActionSynchronizer._write_config(candidate_root / "pet.json", config)
            validation = PackageValidator().validate(candidate_root)
            if not validation.is_valid:
                raise AnimationActionSyncError("候选动画配置未通过校验：" + "；".join(validation.errors))

    @staticmethod
    def _replace_config_atomically(config_path: Path, config: dict[str, Any]) -> None:
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{config_path.name}.", suffix=".tmp", dir=config_path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as temporary_file:
                json.dump(config, temporary_file, ensure_ascii=False, indent=2)
                temporary_file.write("\n")
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, config_path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    @staticmethod
    def _replace_bytes_atomically(config_path: Path, contents: bytes) -> None:
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{config_path.name}.", suffix=".tmp", dir=config_path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(file_descriptor, "wb") as temporary_file:
                temporary_file.write(contents)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, config_path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    @staticmethod
    def _write_config(path: Path, config: dict[str, Any]) -> None:
        with path.open("w", encoding="utf-8", newline="\n") as config_file:
            json.dump(config, config_file, ensure_ascii=False, indent=2)
            config_file.write("\n")
