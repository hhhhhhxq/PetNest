"""Lottie 动效导入与 PNG 缓存回归测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from petnest.core.lottie_effects import (
    EffectCatalog,
    EffectImportError,
    LottieEffectImporter,
)


def _lottie_file(root: Path, *, frame_count: int = 4) -> Path:
    source = root / "爱心动效.json"
    source.write_text(
        json.dumps(
            {
                "v": "5.7.0",
                "fr": 10,
                "ip": 0,
                "op": frame_count,
                "w": 32,
                "h": 32,
                "nm": "test-heart",
                "ddd": 0,
                "assets": [],
                "layers": [],
                "markers": [],
            }
        ),
        encoding="utf-8",
    )
    return source


def test_inspect_uses_lottie_timeline_metadata(tmp_path: Path) -> None:
    info = LottieEffectImporter().inspect(_lottie_file(tmp_path))

    assert (info.width, info.height) == (32, 32)
    assert info.fps == pytest.approx(10)
    assert info.frame_count == 4
    assert info.duration_ms == 400


def test_import_preserves_source_and_writes_png_cache(tmp_path: Path) -> None:
    source = _lottie_file(tmp_path)
    result = LottieEffectImporter().import_file(source, tmp_path / "effects", "heart")

    effect_root = tmp_path / "effects" / "heart"
    assert result.package_root == effect_root
    assert (effect_root / "source.json").read_bytes() == source.read_bytes()
    assert len(tuple((effect_root / "frames").glob("*.png"))) == 4
    assert EffectCatalog().load(effect_root) == result.manifest


def test_import_and_catalog_preserve_effect_layer(tmp_path: Path) -> None:
    source = _lottie_file(tmp_path)
    result = LottieEffectImporter().import_file(source, tmp_path / "effects", "heart", layer="under")

    assert result.manifest.layer == "under"
    assert json.loads((result.package_root / "effect.json").read_text(encoding="utf-8"))["layer"] == "under"


def test_import_does_not_overwrite_existing_effect_by_default(tmp_path: Path) -> None:
    source = _lottie_file(tmp_path)
    importer = LottieEffectImporter()
    importer.import_file(source, tmp_path / "effects", "heart")

    with pytest.raises(EffectImportError, match="已存在"):
        importer.import_file(source, tmp_path / "effects", "heart")


def test_catalog_rejects_manifest_with_frame_count_mismatch(tmp_path: Path) -> None:
    source = _lottie_file(tmp_path)
    result = LottieEffectImporter().import_file(source, tmp_path / "effects", "heart")
    manifest_path = result.package_root / "effect.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["frame_count"] = 99
    manifest_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(EffectImportError, match="帧数"):
        EffectCatalog().load(result.package_root)
