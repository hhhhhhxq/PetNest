"""将 Lottie JSON 导入为 PetNest 可播放的 PNG 动效包。"""

from __future__ import annotations

import argparse
from pathlib import Path

from petnest.core.lottie_effects import EffectImportError, LottieEffectImporter


def main() -> int:
    parser = argparse.ArgumentParser(description="导入 Lottie JSON 并生成透明 PNG 动效缓存")
    parser.add_argument("source", type=Path, help="本地 Lottie JSON 文件")
    parser.add_argument("--effect-id", required=True, help="小写动效 ID，例如 heart-burst")
    parser.add_argument("--effects-root", type=Path, default=Path("effects"), help="动效库目录，默认是当前目录的 effects")
    parser.add_argument("--name", help="显示名称，默认使用 effect ID")
    parser.add_argument("--layer", choices=("under", "over"), default="over", help="显示层级，默认盖在宠物上层")
    parser.add_argument("--once", action="store_true", help="导入后默认只播放一次")
    parser.add_argument("--overwrite", action="store_true", help="覆盖同 ID 的已有动效包")
    args = parser.parse_args()
    try:
        result = LottieEffectImporter().import_file(
            args.source,
            args.effects_root,
            args.effect_id,
            name=args.name,
            loop=not args.once,
            layer=args.layer,
            overwrite=args.overwrite,
        )
    except EffectImportError as error:
        parser.error(str(error))
        return 2
    manifest = result.manifest
    print(
        f"导入完成：{manifest.name} ({manifest.identifier})；"
        f"{manifest.width}×{manifest.height}，{manifest.frame_count} 帧，"
        f"{manifest.duration_ms} ms；输出：{result.package_root}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
