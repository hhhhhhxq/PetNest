"""将本地 Lottie JSON 导入为可快速播放的透明 PNG 动效包。

Lottie 文件是源素材，运行时不直接解释 JSON。导入器使用 rlottie 一次性
渲染帧，并把源 JSON、帧目录和元数据放在同一个 effect 包中。这样播放端
只需要读取普通 PNG，局域网交互也只需传递 effect id。
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Iterator

from PIL import Image

LOGGER = logging.getLogger(__name__)

_EFFECT_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_EFFECT_LAYERS = frozenset({"under", "over"})
_SCHEMA_VERSION = 1


class EffectImportError(RuntimeError):
    """动效源文件或生成的动效包不可用。"""


@dataclass(frozen=True, slots=True)
class LottieEffectInfo:
    """从 Lottie 源文件读取的播放信息。"""

    source: Path
    width: int
    height: int
    fps: float
    frame_count: int
    source_frame_count: int
    duration_ms: int
    start_frame: int


@dataclass(frozen=True, slots=True)
class EffectManifest:
    """已导入动效包的可播放清单。"""

    root: Path
    identifier: str
    name: str
    width: int
    height: int
    fps: float
    frame_count: int
    duration_ms: int
    loop: bool
    source_path: Path
    frames: tuple[Path, ...]
    source_sha256: str
    renderer: str
    layer: str = "over"


@dataclass(frozen=True, slots=True)
class EffectImportResult:
    """一次成功导入的动效包。"""

    package_root: Path
    manifest: EffectManifest


class LottieEffectImporter:
    """把 Lottie JSON 原子地转换成 PNG 动效包。"""

    def __init__(
        self,
        *,
        max_source_bytes: int = 20 * 1024 * 1024,
        max_frames: int = 600,
        max_dimension: int = 4096,
    ) -> None:
        if max_source_bytes <= 0 or max_frames <= 0 or max_dimension <= 0:
            raise ValueError("动效导入限制必须大于 0")
        self.max_source_bytes = max_source_bytes
        self.max_frames = max_frames
        self.max_dimension = max_dimension

    def inspect(self, source: Path) -> LottieEffectInfo:
        """读取并校验 Lottie 时间线，不生成任何文件。"""
        source = _source_path(source)
        data = _read_source(source, self.max_source_bytes)
        raw = _parse_lottie_json(data)
        with _open_animation(data, source.parent) as animation:
            return self._inspect_animation(source, raw, animation)

    def import_file(
        self,
        source: Path,
        effects_root: Path,
        identifier: str,
        *,
        name: str | None = None,
        loop: bool = True,
        layer: str = "over",
        overwrite: bool = False,
    ) -> EffectImportResult:
        """渲染一个动效并写入 ``effects_root/<identifier>``。

        所有内容先写入同一文件系统上的隐藏临时目录；只有全部帧和清单
        校验完成后才切换到最终目录，因此中途关闭程序不会产生半包。
        """
        source = _source_path(source)
        _validate_effect_id(identifier)
        _validate_effect_layer(layer)
        data = _read_source(source, self.max_source_bytes)
        raw = _parse_lottie_json(data)
        effects_root = effects_root.expanduser().resolve()
        effects_root.mkdir(parents=True, exist_ok=True)
        target = effects_root / identifier
        if target.exists() and not overwrite:
            raise EffectImportError(f"动效 {identifier!r} 已存在；如需替换请显式启用覆盖")

        temp_root = Path(tempfile.mkdtemp(prefix=f".{identifier}.", dir=str(effects_root)))
        try:
            with _open_animation(data, source.parent) as animation:
                info = self._inspect_animation(source, raw, animation)
                frames_dir = temp_root / "frames"
                frames_dir.mkdir()
                for index in range(info.frame_count):
                    frame_number = info.start_frame + index
                    rendered = None
                    frame = None
                    try:
                        rendered = animation.render_pillow_frame(frame_num=frame_number)
                        frame = rendered.convert("RGBA")
                        if frame.size != (info.width, info.height):
                            resized = frame.resize((info.width, info.height), Image.Resampling.LANCZOS)
                            frame.close()
                            frame = resized
                        frame.save(frames_dir / f"{index + 1:04d}.png", format="PNG")
                    except Exception as error:  # noqa: BLE001 - 渲染器异常需转成可见导入错误。
                        raise EffectImportError(f"渲染第 {index + 1} 帧失败：{error}") from error
                    finally:
                        if rendered is not None:
                            rendered.close()
                        if frame is not None:
                            frame.close()

            (temp_root / "source.json").write_bytes(source.read_bytes())
            manifest_path = temp_root / "effect.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": _SCHEMA_VERSION,
                        "id": identifier,
                        "name": name.strip() if isinstance(name, str) and name.strip() else identifier,
                        "source": "source.json",
                        "frames": "frames",
                        "width": info.width,
                        "height": info.height,
                        "fps": info.fps,
                        "frame_count": info.frame_count,
                        "duration_ms": info.duration_ms,
                        "loop": bool(loop),
                        "layer": layer,
                        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "renderer": _renderer_name(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            _install_directory(temp_root, target, overwrite=overwrite)
            temp_root = Path()
            manifest = EffectCatalog().load(target)
            return EffectImportResult(package_root=target, manifest=manifest)
        except EffectImportError:
            raise
        except (OSError, ValueError, TypeError) as error:
            raise EffectImportError(f"无法保存动效 {identifier!r}：{error}") from error
        finally:
            if temp_root != Path() and temp_root.exists():
                shutil.rmtree(temp_root, ignore_errors=True)

    def _inspect_animation(self, source: Path, raw: Mapping[str, Any], animation: Any) -> LottieEffectInfo:
        width, height = animation.lottie_animation_get_size()
        fps = float(animation.lottie_animation_get_framerate())
        source_frame_count = int(animation.lottie_animation_get_totalframe())
        duration_seconds = float(animation.lottie_animation_get_duration())
        try:
            start = _positive_int(raw.get("ip"), allow_zero=True)
            end = _positive_int(raw.get("op"), allow_zero=True)
        except ValueError as error:
            raise EffectImportError(f"Lottie 时间线无效：{error}") from error
        frame_count = end - start
        if frame_count <= 0:
            frame_count = max(1, round(duration_seconds * fps))
        if width <= 0 or height <= 0 or width > self.max_dimension or height > self.max_dimension:
            raise EffectImportError(f"动效尺寸 {width}×{height} 超出限制（最大 {self.max_dimension}）")
        if fps <= 0 or duration_seconds <= 0:
            raise EffectImportError("Lottie 必须包含有效的帧率和时长")
        if frame_count > self.max_frames:
            raise EffectImportError(f"动效有 {frame_count} 帧，超过安全上限 {self.max_frames} 帧")
        return LottieEffectInfo(
            source=source,
            width=int(width),
            height=int(height),
            fps=fps,
            frame_count=int(frame_count),
            source_frame_count=max(0, source_frame_count),
            duration_ms=max(1, round(duration_seconds * 1000)),
            start_frame=start,
        )


class EffectCatalog:
    """发现和校验本地 PNG 动效包。"""

    def load(self, package_root: Path) -> EffectManifest:
        root = package_root.expanduser().resolve()
        manifest_path = root / "effect.json"
        if not root.is_dir() or not manifest_path.is_file():
            raise EffectImportError(f"动效包不完整：{root}")
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise EffectImportError(f"无法读取动效清单：{error}") from error
        if not isinstance(raw, Mapping) or raw.get("schema_version") != _SCHEMA_VERSION:
            raise EffectImportError("动效清单版本不受支持")
        identifier = raw.get("id")
        if not isinstance(identifier, str):
            raise EffectImportError("动效清单缺少 id")
        _validate_effect_id(identifier)
        source = _safe_child(root, raw.get("source"), "source.json")
        frames_dir = _safe_child(root, raw.get("frames"), "frames")
        if not source.is_file() or not frames_dir.is_dir():
            raise EffectImportError("动效源文件或帧目录不存在")
        frames = tuple(
            sorted(
                (path for path in frames_dir.iterdir() if path.is_file() and path.suffix.lower() == ".png"),
                key=_frame_sort_key,
            )
        )
        try:
            expected_count = _positive_int(raw.get("frame_count"), allow_zero=False)
            width = _positive_int(raw.get("width"), allow_zero=False)
            height = _positive_int(raw.get("height"), allow_zero=False)
            duration_ms = _positive_int(raw.get("duration_ms"), allow_zero=False)
        except ValueError as error:
            raise EffectImportError(f"动效清单数字字段无效：{error}") from error
        if len(frames) != expected_count:
            raise EffectImportError(f"动效帧数不一致：清单为 {expected_count}，实际为 {len(frames)}")
        fps = _positive_float(raw.get("fps"))
        for frame_path in frames:
            try:
                with Image.open(frame_path) as frame:
                    if frame.size != (width, height) or frame.mode != "RGBA":
                        raise EffectImportError(f"帧 {frame_path.name} 不是统一的 RGBA {width}×{height} PNG")
            except OSError as error:
                raise EffectImportError(f"无法读取帧 {frame_path.name}：{error}") from error
        source_hash = raw.get("source_sha256", "")
        renderer = raw.get("renderer", "")
        layer = raw.get("layer", "over")
        _validate_effect_layer(layer)
        return EffectManifest(
            root=root,
            identifier=identifier,
            name=str(raw.get("name") or identifier),
            width=width,
            height=height,
            fps=fps,
            frame_count=expected_count,
            duration_ms=duration_ms,
            loop=bool(raw.get("loop", True)),
            layer=layer,
            source_path=source,
            frames=frames,
            source_sha256=str(source_hash),
            renderer=str(renderer),
        )

    def discover(self, effects_root: Path) -> list[EffectManifest]:
        root = effects_root.expanduser()
        if not root.is_dir():
            return []
        effects: list[EffectManifest] = []
        for candidate in sorted(
            (item for item in root.iterdir() if item.is_dir()),
            key=lambda item: item.name.casefold(),
        ):
            try:
                effects.append(self.load(candidate))
            except EffectImportError:
                LOGGER.warning("忽略无效动效包：%s", candidate, exc_info=True)
        return effects


def _source_path(source: Path) -> Path:
    path = source.expanduser().resolve()
    if not path.is_file() or path.suffix.lower() != ".json":
        raise EffectImportError("请选择一个存在的 Lottie JSON 文件")
    return path


def _read_source(source: Path, max_bytes: int) -> str:
    try:
        if source.stat().st_size > max_bytes:
            raise EffectImportError(f"Lottie 文件过大，不能超过 {max_bytes // (1024 * 1024)} MB")
        return source.read_text(encoding="utf-8-sig")
    except EffectImportError:
        raise
    except (OSError, UnicodeError) as error:
        raise EffectImportError(f"无法读取 Lottie 文件：{error}") from error


def _parse_lottie_json(data: str) -> Mapping[str, Any]:
    try:
        raw = json.loads(data)
    except json.JSONDecodeError as error:
        raise EffectImportError(f"Lottie JSON 格式错误：{error}") from error
    if not isinstance(raw, Mapping):
        raise EffectImportError("Lottie 根节点必须是 JSON 对象")
    for key in ("fr", "ip", "op", "w", "h"):
        if key not in raw:
            raise EffectImportError(f"Lottie 缺少字段：{key}")
    return raw


@contextmanager
def _open_animation(data: str, resource_path: Path) -> Iterator[Any]:
    try:
        from rlottie_python import LottieAnimation
    except ImportError as error:
        raise EffectImportError("缺少 rlottie-python，请先安装项目依赖") from error
    try:
        animation = LottieAnimation.from_data(data=data, resource_path=str(resource_path))
    except Exception as error:  # noqa: BLE001 - 第三方渲染器错误要统一呈现。
        raise EffectImportError(f"Lottie 无法解析或渲染：{error}") from error
    try:
        yield animation
    finally:
        try:
            animation.lottie_animation_destroy()
        except Exception:  # noqa: BLE001 - 清理失败不能覆盖导入结果。
            LOGGER.debug("清理 Lottie 渲染器失败", exc_info=True)


def _renderer_name() -> str:
    try:
        import rlottie_python

        return f"rlottie-python/{rlottie_python.__version__}"
    except (ImportError, AttributeError):
        return "rlottie-python"


def _validate_effect_id(identifier: str) -> None:
    if not isinstance(identifier, str) or _EFFECT_ID_RE.fullmatch(identifier) is None:
        raise EffectImportError("动效 ID 必须以小写字母开头，只能包含小写字母、数字、-、_，长度不超过 64")


def _validate_effect_layer(layer: object) -> None:
    if layer not in _EFFECT_LAYERS:
        raise EffectImportError("动效 layer 只能是 under 或 over")


def _safe_child(root: Path, value: object, fallback: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        value = fallback
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise EffectImportError("动效清单路径不能离开动效目录") from error
    return candidate


def _positive_int(value: object, *, allow_zero: bool) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("必须是数字")
    parsed = int(round(value))
    if parsed < 0 or (parsed == 0 and not allow_zero):
        raise ValueError("必须是正数")
    return parsed


def _positive_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) <= 0:
        raise EffectImportError("fps 必须是正数")
    return float(value)


def _frame_sort_key(path: Path) -> tuple[int, str]:
    try:
        return int(path.stem), path.name.casefold()
    except ValueError:
        return (2**31 - 1, path.name.casefold())


def _install_directory(temp_root: Path, target: Path, *, overwrite: bool) -> None:
    if not target.exists():
        temp_root.rename(target)
        return
    if not overwrite:
        raise EffectImportError(f"动效 {target.name!r} 已存在")
    backup = target.with_name(f".{target.name}.backup")
    if backup.exists():
        _remove_path(backup)
    target.rename(backup)
    try:
        temp_root.rename(target)
    except Exception:
        backup.rename(target)
        raise
    _remove_path(backup)


def _remove_path(path: Path) -> None:
    """删除覆盖操作产生的单个备份路径。"""
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
