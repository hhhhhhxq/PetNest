"""源码版的当前用户 LaunchAgent；不结束或自动重启正在运行的桌宠。"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
from collections.abc import Callable

from .base import StartupRegistrationResult

LOGGER = logging.getLogger(__name__)
SOURCE_STARTUP_LABEL = "com.petnest.source"


class MacOSSourceLoginItem:
    """登记下次登录启动；退出应用后不保活，关闭开关也不杀当前进程。"""

    def __init__(
        self,
        *,
        project_root: Path | None = None,
        python_executable: Path | None = None,
        home: Path | None = None,
        uid: int | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.project_root = (project_root or Path(__file__).resolve().parents[3]).absolute()
        # 不 resolve：解析虚拟环境中的符号链接会丢失 venv 的依赖环境。
        self.python_executable = (python_executable or Path(sys.executable)).absolute()
        self.home = home or Path.home()
        self.uid = getattr(os, "getuid", lambda: 0)() if uid is None else uid
        self._runner = runner

    @property
    def plist_path(self) -> Path:
        return self.home / "Library" / "LaunchAgents" / f"{SOURCE_STARTUP_LABEL}.plist"

    @property
    def supported(self) -> bool:
        return (
            (self.project_root / "pyproject.toml").is_file()
            and (self.project_root / "src" / "petnest" / "__main__.py").is_file()
            and self.python_executable.is_file()
            and os.access(self.python_executable, os.X_OK)
        )

    def _definition(self) -> dict[str, object]:
        logs = self.home / "Library" / "Logs" / "PetNest" / "logs"
        return {
            "Label": SOURCE_STARTUP_LABEL,
            "ProgramArguments": [str(self.python_executable), "-m", "petnest"],
            "WorkingDirectory": str(self.project_root),
            "EnvironmentVariables": {"PYTHONPATH": str(self.project_root / "src")},
            "RunAtLoad": True,
            "LimitLoadToSessionType": "Aqua",
            "StandardOutPath": str(logs / "source-startup.stdout.log"),
            "StandardErrorPath": str(logs / "source-startup.stderr.log"),
        }

    def _write(self, contents: bytes) -> None:
        self.plist_path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.plist_path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(contents)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.plist_path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def configure(self, enabled: bool) -> StartupRegistrationResult:
        if enabled and not self.supported:
            return StartupRegistrationResult(False, message="源码目录或 Python 环境不可用，无法登记自动启动。")
        previous: bytes | None = None
        file_changed = False
        try:
            previous = self.plist_path.read_bytes() if self.plist_path.exists() else None
            if enabled:
                (self.home / "Library" / "Logs" / "PetNest" / "logs").mkdir(parents=True, exist_ok=True)
                self._write(plistlib.dumps(self._definition()))
            else:
                self.plist_path.unlink(missing_ok=True)
            file_changed = True
            # enable/disable 不终止当前进程。不要在设置保存/启动修复时 bootout，
            # 否则由 launchd 拉起的应用会在持久化设置前被系统结束。
            result = self._runner(
                ["/bin/launchctl", "enable" if enabled else "disable", f"gui/{self.uid}/{SOURCE_STARTUP_LABEL}"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "launchctl 未能修改自动启动状态。")
            return StartupRegistrationResult(True)
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            # 超时/执行失败同样恢复原登记，避免设置显示关闭但文件已经启用。
            if file_changed:
                try:
                    if previous is None:
                        self.plist_path.unlink(missing_ok=True)
                    else:
                        self._write(previous)
                except OSError:
                    LOGGER.exception("无法恢复源码自动启动登记")
            LOGGER.warning("无法修改源码自动启动项", exc_info=True)
            return StartupRegistrationResult(False, message=str(error))


__all__ = ["MacOSSourceLoginItem", "SOURCE_STARTUP_LABEL"]
