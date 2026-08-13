"""从已构建的安装包生成 GitHub Release 更新元数据。

示例：
    python tools/create_app_update_manifest.py \
      --version 0.2.0 \
      --installer dist/installer/PetNest-Setup-0.2.0.exe \
      --url https://github.com/hhhhhhxq/PetNest/releases/download/v0.2.0/PetNest-Setup-0.2.0.exe
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:[-+][0-9A-Za-z.-]+)?$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成 PetNest app-update.json")
    parser.add_argument("--version", required=True)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument(
        "--platform",
        choices=("windows-x64", "macos-x64", "macos-arm64"),
        default="windows-x64",
    )
    parser.add_argument("--output", type=Path, default=Path("app-update.json"))
    parser.add_argument("--notes", default="")
    return parser


def create_manifest(
    *,
    version: str,
    installer: Path,
    url: str,
    platform: str = "windows-x64",
    notes: str = "",
) -> dict[str, object]:
    if VERSION_RE.fullmatch(version) is None:
        raise ValueError(f"版本号格式无效：{version}")
    installer = installer.expanduser().resolve()
    if not installer.is_file():
        raise FileNotFoundError(installer)
    digest = hashlib.sha256()
    size = 0
    with installer.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    if not url.startswith("https://github.com/"):
        raise ValueError("更新 URL 必须是 github.com 的 HTTPS Release 地址")
    if len(notes.encode("utf-8")) > 64 * 1024:
        raise ValueError("更新说明过长")
    return {
        "schema_version": 1,
        "version": version,
        "platform": platform,
        "asset": {"url": url, "size": size, "sha256": digest.hexdigest()},
        "release_notes": notes,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        document = create_manifest(
            version=args.version,
            installer=args.installer,
            url=args.url,
            platform=args.platform,
            notes=args.notes,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as error:
        print(f"生成 app-update.json 失败：{error}", file=sys.stderr)
        return 1
    print(f"已生成 {args.output}（SHA-256: {document['asset']['sha256']}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
