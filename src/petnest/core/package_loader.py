"""把已校验的宠物包配置转换为类型化模型。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from petnest.models import AnimationDefinition, Canvas, DisplaySettings, PetPackage

from .package_validator import PackageValidationError, PackageValidator


class PackageLoader:
    """仅加载通过 :class:`PackageValidator` 校验的本地目录。"""

    def __init__(self, validator: PackageValidator | None = None) -> None:
        self._validator = validator or PackageValidator()

    def load(self, package_root: Path) -> PetPackage:
        """校验并加载一个宠物包；无效输入不会产生半初始化对象。"""
        result = self._validator.validate(package_root)
        if not result.is_valid or result.config is None:
            raise PackageValidationError("；".join(result.errors))
        return self._build_package(result.root, result.config, result.frames)

    def discover(self, pets_root: Path) -> list[PetPackage]:
        """扫描一层子目录，并忽略损坏或不完整的宠物包。"""
        root = pets_root.expanduser()
        if not root.is_dir():
            return []
        packages: list[PetPackage] = []
        for candidate in sorted((item for item in root.iterdir() if item.is_dir()), key=lambda item: item.name.casefold()):
            try:
                packages.append(self.load(candidate))
            except PackageValidationError:
                continue
        return packages

    @staticmethod
    def _build_package(root: Path, config: dict[str, Any], frames: dict[str, tuple[Path, ...]]) -> PetPackage:
        canvas_config = _mapping(config["canvas"])
        animations: dict[str, AnimationDefinition] = {}
        for name, raw_definition in _mapping(config["animations"]).items():
            if name not in frames:
                continue
            definition = _mapping(raw_definition)
            animations[name] = AnimationDefinition(
                name=name,
                path=(root / str(definition["path"])).resolve(),
                fps=float(definition["fps"]),
                loop=bool(definition["loop"]),
                next_animation=_optional_string(definition.get("next")),
                priority=int(definition.get("priority", 0)),
                interruptible=bool(definition.get("interruptible", True)),
                restart_on_reenter=bool(definition.get("restart_on_reenter", False)),
                frames=frames[name],
            )
        display = _display_settings(config.get("display"))
        return PetPackage(
            root=root,
            identifier=str(config["id"]),
            name=str(config.get("name", config["id"])),
            version=str(config.get("version", "0.0.0")),
            canvas=Canvas(width=int(canvas_config["width"]), height=int(canvas_config["height"])),
            animations=animations,
            bindings={str(key): str(value) for key, value in _mapping(config.get("bindings", {})).items()},
            fallbacks={str(key): tuple(str(item) for item in value) for key, value in _mapping(config.get("fallbacks", {})).items()},
            display=display,
            author=_optional_string(config.get("author")),
            description=_optional_string(config.get("description")),
        )


def _mapping(value: object) -> Mapping[str, Any]:
    """调用方只传入 validator 已确认过的对象；此处保留窄类型转换。"""
    if not isinstance(value, Mapping):
        raise PackageValidationError("宠物包配置结构不合法")
    return value


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _display_settings(value: object) -> DisplaySettings:
    if not isinstance(value, Mapping):
        return DisplaySettings()
    return DisplaySettings(
        default_scale=float(value.get("default_scale", 1.0)),
        min_scale=float(value.get("min_scale", 0.25)),
        max_scale=float(value.get("max_scale", 2.0)),
        alpha_hit_test_threshold=int(value.get("alpha_hit_test_threshold", 10)),
    )
