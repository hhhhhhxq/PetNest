"""从受限 ZIP 或文件夹安装当前宠物的下班全屏动画。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import stat
import tempfile
from typing import Any, Mapping
from uuid import uuid4
from zipfile import BadZipFile, ZipFile, ZipInfo

from PIL import Image, UnidentifiedImageError

from petnest.core.package_validator import PackageValidator, natural_sort_key

from .action_installer import ConflictDecision, ActionInstallError, install_actions
from .action_pack import ActionPack, ActionPackError
from .action_transfer import ActionTransferError, load_legacy_work_finish_pack
from .exchange_source import ExchangeSource, UnsafeExchangeSourceError


MAX_FILES = 256
MAX_UNPACKED_BYTES = 128 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100


class WorkFinishImportError(ValueError):
    """导入包不安全、无效或无法原子安装。"""


@dataclass(frozen=True, slots=True)
class WorkFinishBundleSummary:
    name: str
    canvas: tuple[int, int]
    walk_frames: int
    lie_down_frames: int


@dataclass(frozen=True, slots=True)
class WorkFinishImportResult(WorkFinishBundleSummary):
    pet_root: Path


@dataclass(frozen=True, slots=True)
class _Phase:
    path: Path
    fps: float
    frame_durations_ms: tuple[int, ...] | None
    frames: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class _Bundle:
    root: Path
    name: str
    canvas: tuple[int, int]
    walk: _Phase
    lie_down: _Phase

    def summary(self) -> WorkFinishBundleSummary:
        return WorkFinishBundleSummary(self.name, self.canvas, len(self.walk.frames), len(self.lie_down.frames))


class WorkFinishImporter:
    """检查和安装标准下班动画包，不依赖源文件继续存在。"""

    def inspect(self, source: Path) -> WorkFinishBundleSummary:
        try:
            with self.open_action_pack(source) as pack:
                return _summary_from_action_pack(pack)
        except WorkFinishImportError:
            raise
        except (ActionPackError, ActionTransferError, UnsafeExchangeSourceError) as error:
            raise WorkFinishImportError(str(error)) from error

    def install(self, source: Path, pet_root: Path) -> WorkFinishImportResult:
        pet = Path(pet_root).expanduser().resolve()
        if not (pet / "pet.json").is_file():
            raise WorkFinishImportError("目标宠物缺少 pet.json")
        try:
            with self.open_action_pack(source) as pack:
                summary = _summary_from_action_pack(pack)
                install_actions(
                    pet,
                    pack,
                    decisions={
                        "work_finish_walk": ConflictDecision.replace(),
                        "work_finish_lie_down": ConflictDecision.replace(),
                    },
                )
                return WorkFinishImportResult(
                    summary.name,
                    summary.canvas,
                    summary.walk_frames,
                    summary.lie_down_frames,
                    pet,
                )
        except WorkFinishImportError:
            raise
        except (ActionPackError, ActionTransferError, ActionInstallError, UnsafeExchangeSourceError) as error:
            raise WorkFinishImportError(str(error)) from error

    def open_action_pack(self, source: Path) -> ActionPack:
        """打开旧版来源并返回通用动作包；调用方负责关闭返回对象。"""

        try:
            materialized = ExchangeSource.open(Path(source))
            pack = load_legacy_work_finish_pack(materialized.root)
            pack._source = materialized
            return pack
        except Exception:
            if "materialized" in locals():
                materialized.__exit__(None, None, None)
            raise

    def _materialize(self, source: Path, destination: Path) -> Path:
        destination.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            self._copy_folder(source.resolve(), destination)
        elif source.is_file() and source.suffix.casefold() == ".zip":
            self._extract_zip(source, destination)
        else:
            raise WorkFinishImportError("请选择 ZIP 文件或动画文件夹")
        manifests = [path for path in destination.rglob("manifest.json") if path.is_file()]
        if len(manifests) != 1:
            raise WorkFinishImportError("动画包必须且只能包含一个 manifest.json")
        return manifests[0].parent.resolve()

    @staticmethod
    def _copy_folder(source: Path, destination: Path) -> None:
        count = 0
        total = 0
        for path in source.rglob("*"):
            if path.is_symlink():
                raise WorkFinishImportError("文件夹动画包不能包含符号链接")
            if path.is_dir():
                continue
            if not path.is_file():
                raise WorkFinishImportError("文件夹动画包只能包含常规文件")
            count += 1
            total += path.stat().st_size
            _check_limits(count, total)
            relative = path.relative_to(source)
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)

    @staticmethod
    def _extract_zip(source: Path, destination: Path) -> None:
        try:
            with ZipFile(source) as archive:
                files = [item for item in archive.infolist() if not item.is_dir()]
                total = sum(item.file_size for item in files)
                _check_limits(len(files), total)
                seen: set[str] = set()
                for item in files:
                    relative = _safe_zip_path(item)
                    folded = relative.as_posix().casefold()
                    if folded in seen:
                        raise WorkFinishImportError("ZIP 包含重复路径")
                    seen.add(folded)
                    if item.file_size and (item.compress_size == 0 or item.file_size / item.compress_size > MAX_COMPRESSION_RATIO):
                        raise WorkFinishImportError("ZIP 压缩比异常")
                    target = destination.joinpath(*relative.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(item) as source_stream, target.open("wb") as target_stream:
                        shutil.copyfileobj(source_stream, target_stream)
        except (BadZipFile, OSError) as error:
            raise WorkFinishImportError(f"ZIP 无法读取：{error}") from error

    def _parse_bundle(self, root: Path) -> _Bundle:
        try:
            raw = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise WorkFinishImportError(f"manifest.json 无法读取：{error}") from error
        if not isinstance(raw, Mapping):
            raise WorkFinishImportError("manifest.json 顶层必须是对象")
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise WorkFinishImportError("manifest.name 必须是非空字符串")
        canvas = _canvas(raw.get("canvas"))
        walk = self._phase(root, raw.get("walk"), canvas, "walk")
        lie_down = self._phase(root, raw.get("lie_down"), canvas, "lie_down")
        return _Bundle(root, name.strip(), canvas, walk, lie_down)

    @staticmethod
    def _phase(root: Path, value: object, canvas: tuple[int, int], label: str) -> _Phase:
        if not isinstance(value, Mapping):
            raise WorkFinishImportError(f"manifest.{label} 必须是对象")
        path = _safe_relative_directory(root, value.get("path"), label)
        fps = value.get("fps")
        if isinstance(fps, bool) or not isinstance(fps, (int, float)) or fps <= 0:
            raise WorkFinishImportError(f"manifest.{label}.fps 必须大于 0")
        frames = tuple(sorted((item for item in path.iterdir() if item.is_file() and item.suffix.casefold() == ".png"), key=natural_sort_key))
        if not frames:
            raise WorkFinishImportError(f"{label} 没有 PNG 帧")
        durations = value.get("frame_durations_ms")
        parsed_durations: tuple[int, ...] | None = None
        if durations is not None:
            if not isinstance(durations, list) or len(durations) != len(frames) or any(
                isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in durations
            ):
                raise WorkFinishImportError(f"{label} 的逐帧时长必须与 PNG 帧一一对应")
            parsed_durations = tuple(durations)
        for frame in frames:
            try:
                with Image.open(frame) as image:
                    image.load()
                    if "A" not in image.getbands() or image.size != canvas:
                        raise WorkFinishImportError(f"PNG 帧 {frame.name} 必须是 {canvas[0]}×{canvas[1]} RGBA")
            except (OSError, UnidentifiedImageError) as error:
                raise WorkFinishImportError(f"PNG 帧 {frame.name} 无法读取：{error}") from error
        return _Phase(path, float(fps), parsed_durations, frames)

    @staticmethod
    def _install_in_candidate(bundle: _Bundle, candidate: Path) -> None:
        animations_root = candidate / "animations"
        definitions: dict[str, dict[str, Any]] = {}
        for action, phase, loop in (
            ("work_finish_walk", bundle.walk, True),
            ("work_finish_lie_down", bundle.lie_down, False),
        ):
            target = animations_root / action
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(phase.path, target)
            definition: dict[str, Any] = {
                "path": f"animations/{action}",
                "scope": "fullscreen",
                "canvas": {"width": bundle.canvas[0], "height": bundle.canvas[1]},
                "fps": phase.fps,
                "loop": loop,
                "priority": 20,
            }
            if phase.frame_durations_ms is not None:
                definition["frame_durations_ms"] = list(phase.frame_durations_ms)
            definitions[action] = definition
        config_path = candidate / "pet.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["animations"] = {**config["animations"], **definitions}
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    @staticmethod
    def _apply_candidate(candidate: Path, pet: Path) -> None:
        actions = ("work_finish_walk", "work_finish_lie_down")
        token = uuid4().hex
        original_config = (pet / "pet.json").read_bytes()
        backups: dict[str, Path] = {}
        installed: list[Path] = []
        try:
            for action in actions:
                target = pet / "animations" / action
                backup = pet / "animations" / f".{action}.{token}.bak"
                if target.exists():
                    os.replace(target, backup)
                    backups[action] = backup
                shutil.copytree(candidate / "animations" / action, target)
                installed.append(target)
            _replace_bytes(pet / "pet.json", (candidate / "pet.json").read_bytes())
        except Exception as error:
            for target in installed:
                if target.exists() and target.is_relative_to(pet):
                    shutil.rmtree(target)
            for action, backup in backups.items():
                if backup.exists():
                    os.replace(backup, pet / "animations" / action)
            _replace_bytes(pet / "pet.json", original_config)
            raise WorkFinishImportError(f"安装失败，已恢复原动画：{error}") from error
        for backup in backups.values():
            if backup.exists():
                shutil.rmtree(backup)


def _summary_from_action_pack(pack: ActionPack) -> WorkFinishBundleSummary:
    walk = pack.actions.get("work_finish_walk")
    lie_down = pack.actions.get("work_finish_lie_down")
    if walk is None or lie_down is None:
        raise WorkFinishImportError("下班动画包必须包含进入和躺下动作")
    canvas = walk.definition.get("canvas")
    if not isinstance(canvas, Mapping):
        raise WorkFinishImportError("下班动画动作缺少 canvas")
    width, height = canvas.get("width"), canvas.get("height")
    if not isinstance(width, int) or not isinstance(height, int):
        raise WorkFinishImportError("下班动画 canvas 尺寸无效")
    return WorkFinishBundleSummary(
        pack.name,
        (width, height),
        len(walk.asset_paths),
        len(lie_down.asset_paths),
    )


def _safe_zip_path(item: ZipInfo) -> PurePosixPath:
    mode = item.external_attr >> 16
    if stat.S_IFMT(mode) == stat.S_IFLNK:
        raise WorkFinishImportError("ZIP 不能包含符号链接")
    windows = PureWindowsPath(item.filename)
    relative = PurePosixPath(item.filename.replace("\\", "/"))
    if windows.is_absolute() or windows.drive or relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise WorkFinishImportError("ZIP 路径不安全")
    return relative


def _check_limits(count: int, total: int) -> None:
    if count > MAX_FILES or total > MAX_UNPACKED_BYTES:
        raise WorkFinishImportError("动画包文件数量或解压体积超出限制")


def _canvas(value: object) -> tuple[int, int]:
    if not isinstance(value, Mapping):
        raise WorkFinishImportError("manifest.canvas 必须是对象")
    width, height = value.get("width"), value.get("height")
    if any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in (width, height)):
        raise WorkFinishImportError("manifest.canvas 尺寸必须是正整数")
    return int(width), int(height)


def _safe_relative_directory(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise WorkFinishImportError(f"manifest.{label}.path 必须是相对目录")
    if Path(value).is_absolute() or PureWindowsPath(value).is_absolute():
        raise WorkFinishImportError(f"manifest.{label}.path 必须位于动画包内")
    resolved = (root / value).resolve()
    if not resolved.is_relative_to(root) or not resolved.is_dir():
        raise WorkFinishImportError(f"manifest.{label}.path 不存在或逃逸动画包")
    return resolved


def _replace_bytes(path: Path, contents: bytes) -> None:
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


__all__ = [
    "WorkFinishBundleSummary",
    "WorkFinishImportError",
    "WorkFinishImporter",
    "WorkFinishImportResult",
]
