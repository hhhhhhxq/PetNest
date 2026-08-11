"""PetNest Windows 更新器入口；由 PyInstaller 单独打包，不依赖 Qt。"""

from __future__ import annotations

import sys

from petnest.core.app_update import AppUpdateError
from petnest.core.windows_updater import parse_updater_args, run_installer


def main(argv: list[str] | None = None) -> int:
    if sys.platform != "win32":
        print("PetNestUpdater 只能在 Windows 上运行。", file=sys.stderr)
        return 1
    try:
        arguments = parse_updater_args(list(sys.argv[1:] if argv is None else argv))
        return run_installer(arguments)
    except (AppUpdateError, OSError) as error:
        print(f"PetNest 更新失败：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
