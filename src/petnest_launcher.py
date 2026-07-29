"""PyInstaller 顶层入口，保留 ``petnest`` 包的相对导入上下文。"""

from petnest_startup import run_application


if __name__ == "__main__":
    raise SystemExit(run_application())
