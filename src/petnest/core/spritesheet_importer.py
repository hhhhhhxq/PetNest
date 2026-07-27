"""将 Codex 标准透明精灵图转换为 PetNest PNG 序列帧宠物包。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
import tempfile

from PIL import Image, UnidentifiedImageError

from .package_validator import PackageValidationError, PackageValidator


@dataclass(frozen=True, slots=True)
class SpriteSheetLayout:
    """均匀网格精灵图的尺寸约束。"""

    columns: int
    rows: int
    cell_width: int
    cell_height: int

    @property
    def image_size(self) -> tuple[int, int]:
        return (self.columns * self.cell_width, self.rows * self.cell_height)


CODEX_STANDARD_LAYOUT = SpriteSheetLayout(columns=8, rows=9, cell_width=192, cell_height=208)
_PET_ID_PATTERN = re.compile(r"[a-z][a-z0-9_-]*\Z")


@dataclass(frozen=True, slots=True)
class SpriteSheetInspection:
    """已通过格式校验的本地精灵图信息。"""

    source: Path
    size: tuple[int, int]
    layout: SpriteSheetLayout
    nonempty_columns_by_row: tuple[tuple[int, ...], ...]


@dataclass(frozen=True, slots=True)
class SpriteSheetImportResult:
    """一次成功导入的宠物包位置。"""

    package_id: str
    package_root: Path
    inspection: SpriteSheetInspection


@dataclass(frozen=True, slots=True)
class _RowMapping:
    action: str
    loop: bool
    fps: int
    priority: int
    interruptible: bool
    next_animation: str | None = None
    frame_durations_ms: tuple[int, ...] = ()


_ROW_MAPPINGS: tuple[_RowMapping, ...] = (
    _RowMapping("idle", True, 8, 10, True, frame_durations_ms=(280, 110, 110, 140, 140, 320)),
    _RowMapping("drag", True, 10, 80, False, frame_durations_ms=(120, 120, 120, 120, 120, 120, 120, 220)),
    _RowMapping("codex_running_left", True, 10, 20, True, frame_durations_ms=(120, 120, 120, 120, 120, 120, 120, 220)),
    _RowMapping("click", False, 10, 50, False, "context", (140, 140, 140, 280)),
    _RowMapping("drop", False, 10, 70, False, "context", (140, 140, 140, 140, 280)),
    _RowMapping("error", False, 10, 100, False, "context", (140, 140, 140, 140, 140, 140, 140, 240)),
    _RowMapping("waiting", True, 8, 60, True, frame_durations_ms=(150, 150, 150, 150, 150, 260)),
    _RowMapping("working", True, 10, 60, True, frame_durations_ms=(120, 120, 120, 120, 120, 220)),
    _RowMapping("hover", True, 8, 30, True, frame_durations_ms=(150, 150, 150, 150, 150, 280)),
)


class SpriteSheetImportError(ValueError):
    """导入源文件或目标目录不符合安全规则时抛出。"""


class SpriteSheetImporter:
    """以确定性网格裁切将本地 Codex `8 × 9` 图集导入 PetNest。"""

    layout = CODEX_STANDARD_LAYOUT

    def inspect(self, source: Path) -> SpriteSheetInspection:
        """验证输入是原始 RGBA PNG 和受支持的固定网格尺寸。"""
        path = source.expanduser().resolve()
        if not path.is_file():
            raise SpriteSheetImportError(f"找不到精灵图文件：{source}")
        try:
            with Image.open(path) as image:
                if image.format != "PNG":
                    raise SpriteSheetImportError("仅支持 PNG 精灵图")
                if image.size != self.layout.image_size:
                    expected = " × ".join(str(item) for item in self.layout.image_size)
                    actual = " × ".join(str(item) for item in image.size)
                    raise SpriteSheetImportError(f"精灵图尺寸必须为 {expected}，当前为 {actual}")
                if "A" not in image.getbands():
                    raise SpriteSheetImportError("精灵图必须包含透明 alpha 通道")
                rgba = image.convert("RGBA")
                nonempty = tuple(
                    tuple(column for column in range(self.layout.columns) if self._cell_has_pixels(rgba, row, column))
                    for row in range(self.layout.rows)
                )
        except (OSError, UnidentifiedImageError) as error:
            raise SpriteSheetImportError(f"无法读取 PNG 精灵图：{error}") from error
        return SpriteSheetInspection(source=path, size=self.layout.image_size, layout=self.layout, nonempty_columns_by_row=nonempty)

    def import_file(
        self, source: Path, pets_root: Path, pet_id: str, *, name: str | None = None,
        selected_columns_by_action: dict[str, tuple[int, ...]] | None = None,
    ) -> SpriteSheetImportResult:
        """按像素检测或手动格位选择生成新包；同名目录绝不覆盖。"""
        inspection = self.inspect(source)
        identifier = self._validate_pet_id(pet_id)
        root = pets_root.expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        destination = root / identifier
        if destination.exists():
            raise SpriteSheetImportError(f"宠物 ID “{identifier}” 已存在，不会覆盖已有资源")

        temporary = Path(tempfile.mkdtemp(prefix=f".{identifier}-", dir=root))
        try:
            self._write_package(inspection, temporary, identifier, name or identifier, selected_columns_by_action)
            validation = PackageValidator().validate(temporary)
            if not validation.is_valid:
                raise SpriteSheetImportError("生成的宠物包未通过校验：" + "；".join(validation.errors))
            temporary.replace(destination)
        except (OSError, PackageValidationError, SpriteSheetImportError) as error:
            if temporary.exists():
                shutil.rmtree(temporary)
            if isinstance(error, SpriteSheetImportError):
                raise
            raise SpriteSheetImportError(f"导入精灵图失败：{error}") from error
        return SpriteSheetImportResult(identifier, destination, inspection)

    @staticmethod
    def _validate_pet_id(pet_id: str) -> str:
        identifier = pet_id.strip().lower()
        if not _PET_ID_PATTERN.fullmatch(identifier):
            raise SpriteSheetImportError("宠物 ID 必须以小写字母开头，只能包含小写字母、数字、- 或 _")
        return identifier

    def _write_package(
        self, inspection: SpriteSheetInspection, destination: Path, identifier: str, name: str,
        selected_columns_by_action: dict[str, tuple[int, ...]] | None,
    ) -> None:
        animations_root = destination / "animations"
        animations_root.mkdir(parents=True)
        selected_by_action = self._selected_columns(inspection, selected_columns_by_action)
        if not selected_by_action.get("idle"):
            raise SpriteSheetImportError("idle 动作至少要选择一张帧")
        with Image.open(inspection.source) as raw_image:
            image = raw_image.convert("RGBA")
            for row, mapping in enumerate(_ROW_MAPPINGS):
                columns = selected_by_action[mapping.action]
                if not columns:
                    continue
                action_root = animations_root / mapping.action
                action_root.mkdir()
                for index, column in enumerate(columns, start=1):
                    left = column * self.layout.cell_width
                    top = row * self.layout.cell_height
                    frame = image.crop((left, top, left + self.layout.cell_width, top + self.layout.cell_height))
                    frame.save(action_root / f"{index:03d}.png")
        with Image.open(animations_root / "idle" / "001.png") as preview:
            preview.save(destination / "preview.png")
        (destination / "pet.json").write_text(
            json.dumps(self._config(identifier, name, selected_by_action), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _config(identifier: str, name: str, selected_by_action: dict[str, tuple[int, ...]]) -> dict[str, object]:
        animations: dict[str, dict[str, object]] = {}
        for mapping in _ROW_MAPPINGS:
            columns = selected_by_action[mapping.action]
            if not columns:
                continue
            definition: dict[str, object] = {
                "path": f"animations/{mapping.action}", "fps": mapping.fps, "loop": mapping.loop,
                "priority": mapping.priority, "interruptible": mapping.interruptible,
                "frame_durations_ms": [_duration_for_column(mapping, column) for column in columns],
            }
            if mapping.next_animation is not None:
                definition["next"] = mapping.next_animation
            animations[mapping.action] = definition
        return {
            "schema_version": 1, "id": identifier, "name": name, "version": "1.0.0",
            "description": "由 Codex 8×9 精灵图导入",
            "canvas": {"width": CODEX_STANDARD_LAYOUT.cell_width, "height": CODEX_STANDARD_LAYOUT.cell_height},
            "display": {"default_scale": 0.8, "min_scale": 0.25, "max_scale": 2.0, "alpha_hit_test_threshold": 10},
            "animations": animations,
            "bindings": {
                "mouse.enter": "hover", "mouse.click": "click", "mouse.drag_start": "drag", "mouse.drag_end": "drop",
                "agent.working": "working", "agent.waiting": "waiting", "agent.success": "success", "agent.error": "error",
            },
            "fallbacks": {"success": ["idle"], "sleep": ["idle"], "wake": ["idle"]},
            "import_metadata": {"source_format": "codex_8x9", "selected_columns_by_action": selected_by_action},
        }

    def _selected_columns(
        self, inspection: SpriteSheetInspection, selected_columns_by_action: dict[str, tuple[int, ...]] | None,
    ) -> dict[str, tuple[int, ...]]:
        selected: dict[str, tuple[int, ...]] = {}
        for row, mapping in enumerate(_ROW_MAPPINGS):
            columns = inspection.nonempty_columns_by_row[row] if selected_columns_by_action is None else selected_columns_by_action.get(mapping.action, ())
            if any(isinstance(column, bool) or not isinstance(column, int) or not 0 <= column < self.layout.columns for column in columns):
                raise SpriteSheetImportError(f"动作 {mapping.action} 的格位必须在 0 到 {self.layout.columns - 1} 之间")
            selected[mapping.action] = tuple(sorted(set(columns)))
        return selected

    def _cell_has_pixels(self, image: Image.Image, row: int, column: int) -> bool:
        left = column * self.layout.cell_width
        top = row * self.layout.cell_height
        return image.crop((left, top, left + self.layout.cell_width, top + self.layout.cell_height)).getchannel("A").getbbox() is not None


def _duration_for_column(mapping: _RowMapping, column: int) -> int:
    """标准表以外的格位仍可导入，使用其动作 FPS 产生合理默认值。"""
    if column < len(mapping.frame_durations_ms):
        return mapping.frame_durations_ms[column]
    return round(1000 / mapping.fps)
