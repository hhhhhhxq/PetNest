"""PyInstaller 顶层入口，保留 ``petnest`` 包的相对导入上下文。"""

from petnest.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main())
