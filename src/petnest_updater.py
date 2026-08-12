"""PetNest 跨平台更新器入口；由 PyInstaller 单独打包，不依赖 Qt。"""

from __future__ import annotations

import sys

from petnest.core.app_update import AppUpdateError


def main(argv: list[str] | None = None) -> int:
    try:
        values = list(sys.argv[1:] if argv is None else argv)
        if sys.platform == "win32":
            from petnest.core.windows_updater import parse_updater_args, run_installer

            return run_installer(parse_updater_args(values))
        if sys.platform == "darwin":
            from petnest.core.macos_updater import parse_macos_updater_args, run_macos_update

            return run_macos_update(parse_macos_updater_args(values))
        print("PetNestUpdater 仅支持 Windows 和 macOS。", file=sys.stderr)
        return 1
    except (AppUpdateError, OSError) as error:
        print(f"PetNest 更新失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
