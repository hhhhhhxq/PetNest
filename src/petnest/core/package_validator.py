"""对不受信任宠物包进行结构、路径和图片资源校验。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any

from PIL import Image, UnidentifiedImageError


_NUMBER_PARTS = re.compile(r"(\d+)")
_INTERACTION_ITEM_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_REQUIRED_ANIMATION = "idle"
_ENTRANCE_DIRECTIONS = {"left", "right", "none"}
SUPPORTED_ANIMATION_FRAME_SUFFIXES = frozenset({".png", ".webp"})
_MAX_INTERACTION_ITEMS = 8
_MAX_INTERACTION_ICON_SIZE = 512
_HOLD_PLAY_DIRECTIONS = {"center", "left", "right", "up_left", "up_right"}
MAX_TIMELINE_DURATION_MS = 2_147_483_647


class PackageValidationError(ValueError):
    """宠物包无法安全加载时抛出的异常。"""


@dataclass(slots=True)
class ValidationResult:
    """校验结果，同时保留 loader 构造模型所需的已解析数据。"""

    root: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    config: dict[str, Any] | None = None
    frames: dict[str, tuple[Path, ...]] = field(default_factory=dict)
    interaction_item_icons: dict[str, Path] = field(default_factory=dict)
    interaction_hold_play: dict[str, Mapping[str, Any]] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return not self.errors


def natural_sort_key(path: Path) -> tuple[object, ...]:
    """按文件名中的数字而非字典序排列动画帧。"""
    return tuple(
        int(part) if part.isdigit() else part.casefold()
        for part in _NUMBER_PARTS.split(path.name)
    )


def animation_frame_paths(animation_path: Path) -> tuple[Path, ...]:
    """Return naturally sorted PNG/WebP animation frames from a directory."""

    return tuple(
        sorted(
            (
                item
                for item in animation_path.iterdir()
                if item.is_file() and item.suffix.casefold() in SUPPORTED_ANIMATION_FRAME_SUFFIXES
            ),
            key=natural_sort_key,
        )
    )


class PackageValidator:
    """验证目录式 PetNest 宠物包，绝不跟随包外资源路径。"""

    def validate(self, package_root: Path) -> ValidationResult:
        """返回全部可报告的问题，而不是在第一个问题处中断。"""
        configured_root = package_root.expanduser()
        root = configured_root.resolve()
        result = ValidationResult(root=root)
        if configured_root.is_symlink():
            result.errors.append("宠物包根目录不能是符号链接")
            return result
        if not root.is_dir():
            result.errors.append(f"宠物包目录不存在：{package_root}")
            return result

        config_path = root / "pet.json"
        if not config_path.is_file():
            result.errors.append("缺少 pet.json")
            return result

        try:
            parsed = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            result.errors.append(f"pet.json JSON 无法解析：{error}")
            return result
        if not isinstance(parsed, dict):
            result.errors.append("pet.json 顶层必须是对象")
            return result
        result.config = parsed

        self._validate_metadata(parsed, result)
        self._validate_interaction_items(parsed.get("interaction_items"), root, result)
        canvas = self._validate_canvas(parsed, result)
        animations = parsed.get("animations")
        if not isinstance(animations, Mapping):
            result.errors.append("animations 必须是对象")
            return result
        if _REQUIRED_ANIMATION not in animations:
            result.errors.append("宠物包必须定义 idle 动画")

        for name, definition in animations.items():
            if not isinstance(name, str) or not name.strip():
                result.errors.append("动画名称必须是非空字符串")
                continue
            self._validate_animation(name, definition, root, canvas, result)

        self._validate_hold_play_items(
            parsed.get("interaction_items"),
            root,
            canvas,
            animations,
            result,
        )

        fallbacks = parsed.get("fallbacks")
        self._validate_fallbacks(fallbacks, result)
        self._validate_bindings(parsed.get("bindings"), animations, fallbacks, result)
        return result

    @staticmethod
    def _validate_metadata(config: Mapping[str, Any], result: ValidationResult) -> None:
        if config.get("schema_version") != 1:
            result.errors.append("schema_version 必须为当前支持的版本 1")
        if not isinstance(config.get("id"), str) or not config["id"].strip():
            result.errors.append("id 必须是非空字符串")

    @staticmethod
    def _validate_canvas(config: Mapping[str, Any], result: ValidationResult) -> tuple[int, int] | None:
        canvas = config.get("canvas")
        return PackageValidator._validate_canvas_mapping(canvas, result, "canvas")

    @staticmethod
    def _validate_canvas_mapping(
        canvas: object,
        result: ValidationResult,
        label: str,
    ) -> tuple[int, int] | None:
        if not isinstance(canvas, Mapping):
            result.errors.append(f"{label} 必须是对象")
            return None
        width, height = canvas.get("width"), canvas.get("height")
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in (width, height)):
            result.errors.append(f"{label}.width 和 {label}.height 必须是正整数")
            return None
        return width, height

    def _validate_animation(
        self,
        name: str,
        definition: object,
        root: Path,
        canvas: tuple[int, int] | None,
        result: ValidationResult,
    ) -> None:
        if not isinstance(definition, Mapping):
            result.errors.append(f"动画 {name} 的定义必须是对象")
            return
        self._validate_entrance_direction(name, definition, result)
        fps = definition.get("fps")
        if isinstance(fps, bool) or not isinstance(fps, (int, float)) or fps <= 0:
            result.errors.append(f"动画 {name} 的 FPS 必须大于 0")
        if not isinstance(definition.get("loop"), bool):
            result.errors.append(f"动画 {name} 的 loop 必须是布尔值")

        animation_canvas = self._animation_canvas(name, definition, canvas, result)

        animation_path = self._safe_path(root, definition.get("path"), name, result)
        if animation_path is None:
            return
        if not animation_path.is_dir():
            message = f"动画 {name} 的目录不存在：{definition.get('path')}"
            if name == _REQUIRED_ANIMATION:
                result.errors.append(message)
            else:
                result.warnings.append(message)
            return

        frames = animation_frame_paths(animation_path)
        if not frames:
            message = f"动画 {name} 没有 PNG 帧或 WebP 帧"
            if name == _REQUIRED_ANIMATION:
                result.errors.append(message)
            else:
                result.warnings.append(message)
            return
        frames_by_stem: dict[str, Path] = {}
        duplicate_stems_found = False
        for frame in frames:
            stem = frame.stem.casefold()
            existing = frames_by_stem.get(stem)
            if existing is not None:
                result.errors.append(
                    f"动画 {name} 同时包含同名帧：{existing.name}、{frame.name}"
                )
                duplicate_stems_found = True
            else:
                frames_by_stem[stem] = frame
        if duplicate_stems_found:
            return
        result.frames[name] = frames
        self._validate_timeline(name, definition, len(frames), result)
        for frame in frames:
            self._validate_frame(name, frame, animation_canvas, result)

    @staticmethod
    def _validate_entrance_direction(
        name: str,
        definition: Mapping[str, object],
        result: ValidationResult,
    ) -> None:
        if "entrance_direction" not in definition:
            return
        direction = definition["entrance_direction"]
        if definition.get("scope", "pet") != "fullscreen":
            result.errors.append(f"动画 {name}：只有全屏动画可以声明 entrance_direction")
        elif not isinstance(direction, str) or direction not in _ENTRANCE_DIRECTIONS:
            result.errors.append(f"动画 {name} 的 entrance_direction 必须是 left、right 或 none")

    @staticmethod
    def _animation_canvas(
        name: str,
        definition: Mapping[str, object],
        package_canvas: tuple[int, int] | None,
        result: ValidationResult,
    ) -> tuple[int, int] | None:
        scope = definition.get("scope", "pet")
        if scope not in {"pet", "fullscreen"}:
            result.errors.append(f"动画 {name} 的 scope 必须是 pet 或 fullscreen")
            return package_canvas
        if "canvas" not in definition:
            if scope == "fullscreen":
                return PackageValidator._validate_canvas_mapping(
                    None,
                    result,
                    f"动画 {name} 的 canvas",
                )
            return package_canvas
        return PackageValidator._validate_canvas_mapping(
            definition.get("canvas"),
            result,
            f"动画 {name} 的 canvas",
        )

    @staticmethod
    def _validate_timeline(name: str, definition: Mapping[str, object], frame_count: int, result: ValidationResult) -> None:
        durations = definition.get("frame_durations_ms")
        if durations is not None:
            if not isinstance(durations, list):
                result.errors.append(f"动画 {name} 的 frame_durations_ms 必须是数组")
            elif len(durations) != frame_count:
                result.errors.append(f"动画 {name} 的 frame_durations_ms 数量必须与动画帧数一致")
            elif any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in durations):
                result.errors.append(f"动画 {name} 的 frame_durations_ms 必须全部为正整数")
            elif any(value > MAX_TIMELINE_DURATION_MS for value in durations) or sum(
                durations
            ) > MAX_TIMELINE_DURATION_MS:
                result.errors.append(
                    f"动画 {name} 的逐帧时长总和超过安全上限 {MAX_TIMELINE_DURATION_MS} ms"
                )
        multiplier = definition.get("speed_multiplier", 1.0)
        if isinstance(multiplier, bool) or not isinstance(multiplier, (int, float)) or multiplier <= 0:
            result.errors.append(f"动画 {name} 的 speed_multiplier 必须大于 0")

    @staticmethod
    def _safe_path(root: Path, configured_path: object, name: str, result: ValidationResult) -> Path | None:
        if not isinstance(configured_path, str) or not configured_path.strip():
            result.errors.append(f"动画 {name} 的 path 必须是非空相对路径")
            return None
        candidate = Path(configured_path)
        if candidate.is_absolute() or PureWindowsPath(configured_path).is_absolute():
            result.errors.append(f"动画 {name} 的路径必须位于包目录内")
            return None
        resolved = (root / candidate).resolve()
        if not resolved.is_relative_to(root):
            result.errors.append(f"动画 {name} 的路径逃逸到包目录之外")
            return None
        return resolved

    @staticmethod
    def _validate_frame(
        animation_name: str,
        frame: Path,
        canvas: tuple[int, int] | None,
        result: ValidationResult,
    ) -> None:
        try:
            with Image.open(frame) as image:
                image.load()
                if "A" not in image.getbands():
                    result.errors.append(f"动画 {animation_name} 的帧 {frame.name} 缺少透明通道")
                if canvas is not None and image.size != canvas:
                    result.errors.append(
                        f"动画 {animation_name} 的帧 {frame.name} 画布尺寸为 {image.size}，应为 {canvas}"
                    )
        except (OSError, UnidentifiedImageError) as error:
            result.errors.append(f"动画 {animation_name} 的帧 {frame.name} 无法读取：{error}")

    @staticmethod
    def _validate_interaction_items(
        configured_items: object,
        root: Path,
        result: ValidationResult,
    ) -> None:
        if configured_items is None:
            return
        if not isinstance(configured_items, list):
            result.warnings.append("interaction_items 必须是数组，已忽略")
            return
        if len(configured_items) > _MAX_INTERACTION_ITEMS:
            result.warnings.append(
                f"interaction_items 最多读取 {_MAX_INTERACTION_ITEMS} 项，超出部分已忽略"
            )

        seen: set[str] = set()
        for index, item in enumerate(configured_items[:_MAX_INTERACTION_ITEMS], start=1):
            if not isinstance(item, Mapping):
                result.warnings.append(f"互动道具第 {index} 项必须是对象，已忽略")
                continue

            identifier = item.get("id")
            if not isinstance(identifier, str) or _INTERACTION_ITEM_ID.fullmatch(identifier) is None:
                result.warnings.append(
                    f"互动道具第 {index} 项的 id {identifier!r} 不合法，已忽略"
                )
                continue
            if identifier in seen:
                result.warnings.append(f"互动道具 {identifier} 的 id 重复，已忽略")
                continue
            seen.add(identifier)

            label = item.get("label")
            if not isinstance(label, str) or not 1 <= len(label.strip()) <= 40:
                result.warnings.append(
                    f"互动道具 {identifier} 的 label 去除首尾空白后长度必须为 1–40，已忽略"
                )
                continue

            icon = PackageValidator._validate_interaction_item_icon(
                identifier,
                item.get("icon"),
                root,
                result,
            )
            if icon is not None:
                result.interaction_item_icons[identifier] = icon

    @staticmethod
    def _validate_interaction_item_icon(
        identifier: str,
        configured_path: object,
        root: Path,
        result: ValidationResult,
    ) -> Path | None:
        if not isinstance(configured_path, str) or not configured_path.strip():
            result.warnings.append(
                f"互动道具 {identifier} 的 icon 必须是非空相对路径，已忽略"
            )
            return None

        try:
            candidate = Path(configured_path)
            if candidate.is_absolute() or PureWindowsPath(configured_path).is_absolute():
                result.warnings.append(
                    f"互动道具 {identifier} 的 icon 路径必须位于包目录内，已忽略"
                )
                return None
            resolved = (root / candidate).resolve()
            if not resolved.is_relative_to(root):
                result.warnings.append(
                    f"互动道具 {identifier} 的 icon 路径逃逸到包目录之外，已忽略"
                )
                return None
            if resolved.suffix.casefold() != ".png":
                result.warnings.append(f"互动道具 {identifier} 的 icon 必须是 PNG 文件，已忽略")
                return None
            if not resolved.is_file():
                result.warnings.append(f"互动道具 {identifier} 的 icon 文件不存在，已忽略")
                return None
        except (OSError, ValueError) as error:
            result.warnings.append(
                f"互动道具 {identifier} 的 icon 路径无法解析：{error}"
            )
            return None

        try:
            with Image.open(resolved) as image:
                if image.format != "PNG":
                    result.warnings.append(
                        f"互动道具 {identifier} 的 icon 内容必须是 PNG，已忽略"
                    )
                    return None
                if any(dimension > _MAX_INTERACTION_ICON_SIZE for dimension in image.size):
                    result.warnings.append(
                        f"互动道具 {identifier} 的 icon 宽高不能超过 {_MAX_INTERACTION_ICON_SIZE}，已忽略"
                    )
                    return None
                image.load()
                if "A" not in image.getbands():
                    result.warnings.append(
                        f"互动道具 {identifier} 的 icon 缺少透明通道，已忽略"
                    )
                    return None
        except (
            OSError,
            ValueError,
            UnidentifiedImageError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as error:
            result.warnings.append(f"互动道具 {identifier} 的 icon 无法读取：{error}")
            return None
        return resolved

    @staticmethod
    def _validate_hold_play_items(
        configured_items: object,
        root: Path,
        package_canvas: tuple[int, int] | None,
        animations: Mapping[str, object],
        result: ValidationResult,
    ) -> None:
        if not isinstance(configured_items, list):
            return
        for raw_item in configured_items[:_MAX_INTERACTION_ITEMS]:
            if not isinstance(raw_item, Mapping):
                continue
            identifier = raw_item.get("id")
            if not isinstance(identifier, str) or identifier not in result.interaction_item_icons:
                continue
            configured = raw_item.get("hold_play")
            if configured is None:
                continue
            reason = PackageValidator._hold_play_error(
                identifier,
                configured,
                root,
                package_canvas,
                animations,
                result,
            )
            if reason is not None:
                result.warnings.append(f"互动道具 {identifier} 的 hold_play {reason}，已忽略")
                continue
            result.interaction_hold_play[identifier] = configured

    @staticmethod
    def _hold_play_error(
        identifier: str,
        configured: object,
        root: Path,
        package_canvas: tuple[int, int] | None,
        animations: Mapping[str, object],
        result: ValidationResult,
    ) -> str | None:
        if not isinstance(configured, Mapping):
            return "必须是对象"
        cursor = PackageValidator._validate_interaction_item_icon(
            f"{identifier} 陪玩光标",
            configured.get("cursor"),
            root,
            result,
        )
        if cursor is None:
            return "cursor 无效"
        try:
            with Image.open(cursor) as cursor_image:
                cursor_size = cursor_image.size
        except OSError:
            return "cursor 无法读取"
        hotspot = PackageValidator._hold_play_pair(configured.get("cursor_hotspot"))
        if hotspot is None or not (0 <= hotspot[0] < cursor_size[0] and 0 <= hotspot[1] < cursor_size[1]):
            return "cursor_hotspot 必须落在光标图片范围内"

        ready_name = configured.get("ready_action")
        ready_canvas = PackageValidator._hold_play_action_canvas(
            ready_name,
            animations,
            package_canvas,
            result,
        )
        if ready_canvas is None:
            return f"ready_action {ready_name!r} 不可用"
        origin = PackageValidator._hold_play_pair(configured.get("attack_origin"))
        if origin is None or not PackageValidator._point_in_canvas(origin, ready_canvas):
            return "attack_origin 必须落在动作画布内"

        for key, minimum, maximum in (
            ("settle_ms", 50, 1000),
            ("cooldown_ms", 0, 5000),
            ("rearm_distance", 1, 512),
        ):
            value = configured.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                return f"{key} 必须是 {minimum}–{maximum} 的整数"

        targets = configured.get("targets")
        if not isinstance(targets, Mapping) or "center" not in targets:
            return "targets 必须是至少包含 center 的对象"
        if any(direction not in _HOLD_PLAY_DIRECTIONS for direction in targets):
            return "targets 包含不支持的方向"
        for direction, raw_target in targets.items():
            if not isinstance(raw_target, Mapping):
                return f"targets.{direction} 必须是对象"
            action_name = raw_target.get("action")
            action_canvas = PackageValidator._hold_play_action_canvas(
                action_name,
                animations,
                package_canvas,
                result,
            )
            if action_canvas is None:
                return f"targets.{direction}.action {action_name!r} 不可用"
            if action_canvas != ready_canvas:
                return f"targets.{direction} 与 ready_action 的画布不一致"
            contact_frame = raw_target.get("contact_frame")
            frame_count = len(result.frames.get(str(action_name), ()))
            if (
                isinstance(contact_frame, bool)
                or not isinstance(contact_frame, int)
                or not 1 <= contact_frame <= frame_count
            ):
                return f"targets.{direction}.contact_frame 必须落在动作帧范围内"
            point = PackageValidator._hold_play_pair(raw_target.get("contact_point"))
            if point is None or not PackageValidator._point_in_canvas(point, ready_canvas):
                return f"targets.{direction}.contact_point 必须落在动作画布内"
            correction = PackageValidator._hold_play_pair(raw_target.get("max_correction"))
            if correction is None or any(value < 0 or value > 64 for value in correction):
                return f"targets.{direction}.max_correction 每轴必须是 0–64"
        return None

    @staticmethod
    def _hold_play_action_canvas(
        action_name: object,
        animations: Mapping[str, object],
        package_canvas: tuple[int, int] | None,
        result: ValidationResult,
    ) -> tuple[int, int] | None:
        if not isinstance(action_name, str) or action_name not in result.frames:
            return None
        raw = animations.get(action_name)
        if not isinstance(raw, Mapping) or raw.get("scope", "pet") != "pet":
            return None
        canvas = raw.get("canvas")
        if canvas is None:
            return package_canvas
        if not isinstance(canvas, Mapping):
            return None
        width, height = canvas.get("width"), canvas.get("height")
        if isinstance(width, bool) or isinstance(height, bool):
            return None
        if not isinstance(width, int) or not isinstance(height, int):
            return None
        return width, height

    @staticmethod
    def _hold_play_pair(value: object) -> tuple[int, int] | None:
        if not isinstance(value, list) or len(value) != 2:
            return None
        x, y = value
        if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, int) or not isinstance(y, int):
            return None
        return x, y

    @staticmethod
    def _point_in_canvas(point: tuple[int, int], canvas: tuple[int, int]) -> bool:
        return 0 <= point[0] < canvas[0] and 0 <= point[1] < canvas[1]

    @staticmethod
    def _validate_bindings(
        bindings: object,
        animations: Mapping[object, object],
        fallbacks: object,
        result: ValidationResult,
    ) -> None:
        if bindings is None:
            return
        if not isinstance(bindings, Mapping):
            result.errors.append("bindings 必须是对象")
            return
        for event_name, animation_name in bindings.items():
            if not isinstance(event_name, str) or not isinstance(animation_name, str):
                result.errors.append("bindings 的事件和动作名称必须是字符串")
            elif animation_name not in animations and not _has_usable_fallback(animation_name, fallbacks):
                result.warnings.append(f"事件 {event_name} 指向缺失的可选动画 {animation_name}")

    @staticmethod
    def _validate_fallbacks(fallbacks: object, result: ValidationResult) -> None:
        if fallbacks is None:
            return
        if not isinstance(fallbacks, Mapping):
            result.errors.append("fallbacks 必须是对象")
            return
        graph: dict[str, tuple[str, ...]] = {}
        for source, targets in fallbacks.items():
            if not isinstance(source, str) or not isinstance(targets, list) or not all(isinstance(target, str) for target in targets):
                result.errors.append("fallbacks 必须是动作名到动作名数组的映射")
                continue
            graph[source] = tuple(targets)
        if _has_cycle(graph):
            result.errors.append("fallback 配置存在循环引用")


def _has_cycle(graph: Mapping[str, tuple[str, ...]]) -> bool:
    """用 DFS 检测 fallback 有向图中的环。"""
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        try:
            return any(visit(target) for target in graph.get(node, ()))
        finally:
            visiting.discard(node)
            visited.add(node)

    return any(visit(node) for node in graph)


def _has_usable_fallback(animation_name: str, fallbacks: object) -> bool:
    """缺失动作有已声明的候选 fallback 时不把它视为导入警告。"""
    if not isinstance(fallbacks, Mapping):
        return False
    candidates = fallbacks.get(animation_name)
    return isinstance(candidates, list) and bool(candidates) and all(isinstance(item, str) for item in candidates)
