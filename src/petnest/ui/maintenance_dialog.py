"""由 Godot 高级版调用的独立程序与远程资源维护窗口。"""

from __future__ import annotations

import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
from threading import Thread

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton, QVBoxLayout

from petnest import __version__
from petnest.app import APP_UPDATE_MANIFEST_URL, REMOTE_RESOURCE_BASE_URL, bundled_resource_seed_root
from petnest.core.app_update import AppUpdateClient, AppUpdateError, AppUpdateInfo, build_updater_command
from petnest.core.remote_resource_cache import RemoteResourceCache
from petnest.core.remote_resource_update import RemoteResourceUpdateCoordinator
from petnest.core.settings_manager import SettingsManager


class MaintenanceDialog(QDialog):
    """不启动第二只桌宠，只运行普通版已验证过的更新核心。"""

    def __init__(self, mode: str, *, parent_pid: int = 0, restart_path: Path | None = None) -> None:
        super().__init__()
        if mode not in {"app-update", "resource-update"}:
            raise ValueError("维护模式无效")
        self.mode = mode
        self.parent_pid = parent_pid
        self.restart_path = restart_path
        self._events: Queue[tuple[str, object]] = Queue()
        self._worker: Thread | None = None
        self.setWindowTitle("PetNest 程序更新" if mode == "app-update" else "PetNest 远程资源更新")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        self.status = QLabel("准备检查更新…", self)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.close_button = QPushButton("关闭", self)
        self.close_button.clicked.connect(self.reject)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(100)
        self.poll_timer.timeout.connect(self._drain_events)
        self.poll_timer.start()
        QTimer.singleShot(0, self._start_check)

    def _start_check(self) -> None:
        self.close_button.setEnabled(False)
        self.status.setText("正在检查程序更新…" if self.mode == "app-update" else "正在检查远程资源更新…")
        target = self._check_app_update if self.mode == "app-update" else self._check_resources
        self._worker = Thread(target=target, name=f"PetNest {self.mode}", daemon=True)
        self._worker.start()

    def _check_app_update(self) -> None:
        try:
            info = AppUpdateClient(
                manifest_url=APP_UPDATE_MANIFEST_URL,
                current_version=__version__,
                platform_name=sys.platform,
            ).check()
            self._events.put(("app-check", info))
        except (AppUpdateError, OSError) as error:
            self._events.put(("error", str(error)))

    def _check_resources(self) -> None:
        try:
            manager = SettingsManager()
            cache = RemoteResourceCache(
                manager.path.parent / "remote-resources",
                REMOTE_RESOURCE_BASE_URL,
                seed_root=bundled_resource_seed_root(),
            )
            coordinator = RemoteResourceUpdateCoordinator(cache, cache.root / "state.json")
            result = coordinator.check(force=True)
            self._events.put(("resource-check", (coordinator, result)))
        except Exception as error:  # noqa: BLE001 - maintenance must show a recoverable error.
            self._events.put(("error", str(error) or error.__class__.__name__))

    def _start_app_download(self, info: AppUpdateInfo) -> None:
        self.status.setText(f"正在下载 PetNest {info.version}…")
        self.progress.setValue(0)

        def worker() -> None:
            destination = SettingsManager.default_path().parent / "updates" / f"PetNest-Setup-{info.version}.exe"
            try:
                client = AppUpdateClient(
                    manifest_url=APP_UPDATE_MANIFEST_URL,
                    current_version=__version__,
                    platform_name=sys.platform,
                )
                client.download(info, destination, progress=lambda value: self._events.put(("progress", value)))
                self._events.put(("app-downloaded", destination))
            except (AppUpdateError, OSError) as error:
                self._events.put(("error", str(error)))

        self._worker = Thread(target=worker, name="PetNest app download", daemon=True)
        self._worker.start()

    def _start_resource_apply(self, coordinator: RemoteResourceUpdateCoordinator) -> None:
        self.status.setText("正在下载并校验远程资源…")
        self.progress.setValue(0)

        def worker() -> None:
            result = coordinator.apply(progress=lambda value: self._events.put(("progress", value)))
            self._events.put(("resource-applied", result))

        self._worker = Thread(target=worker, name="PetNest resource download", daemon=True)
        self._worker.start()

    def _drain_events(self) -> None:
        while True:
            try:
                kind, payload = self._events.get_nowait()
            except Empty:
                return
            if kind == "progress":
                self.progress.setValue(max(0, min(100, int(payload))))
            elif kind == "error":
                self._finish_error(str(payload))
            elif kind == "app-check":
                self._handle_app_check(payload if isinstance(payload, AppUpdateInfo) else None)
            elif kind == "resource-check":
                coordinator, result = payload  # type: ignore[misc]
                self._handle_resource_check(coordinator, result)
            elif kind == "app-downloaded":
                self._launch_updater(Path(payload))
            elif kind == "resource-applied":
                self._handle_resource_applied(payload)

    def _handle_app_check(self, info: AppUpdateInfo | None) -> None:
        if info is None:
            self.status.setText("当前已经是最新版本。")
            self.progress.setValue(100)
            self.close_button.setEnabled(True)
            return
        notes = info.release_notes.strip() or "未提供更新说明。"
        answer = QMessageBox.question(
            self,
            "发现程序更新",
            f"发现 PetNest {info.version}。\n\n{notes}\n\n是否下载并安装？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer is QMessageBox.StandardButton.Yes:
            self._start_app_download(info)
        else:
            self.status.setText("已取消程序更新。")
            self.close_button.setEnabled(True)

    def _handle_resource_check(self, coordinator: RemoteResourceUpdateCoordinator, result: object) -> None:
        error = getattr(result, "error", None)
        if error:
            self._finish_error(str(error))
            return
        if not getattr(result, "update_available", False):
            self.status.setText("远程资源已经是最新版本。")
            self.progress.setValue(100)
            self.close_button.setEnabled(True)
            return
        version = getattr(result, "catalog_version", "新版本")
        answer = QMessageBox.question(
            self,
            "发现资源更新",
            f"发现远程资源目录 {version}，是否下载并应用？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer is QMessageBox.StandardButton.Yes:
            self._start_resource_apply(coordinator)
        else:
            self.status.setText("已取消远程资源更新。")
            self.close_button.setEnabled(True)

    def _handle_resource_applied(self, result: object) -> None:
        error = getattr(result, "error", None)
        if error:
            self._finish_error(str(error))
            return
        if getattr(result, "applied", False):
            self.status.setText("远程资源已更新。重新打开高级版设置后即可使用新资源。")
            self.progress.setValue(100)
        else:
            self.status.setText("没有需要应用的远程资源。")
        self.close_button.setEnabled(True)

    def _launch_updater(self, installer: Path) -> None:
        try:
            updater = Path(sys.executable).with_name("PetNestUpdater.exe")
            wait_pid = self.parent_pid if self.parent_pid > 0 else os.getpid()
            command = build_updater_command(
                updater,
                installer.resolve(),
                wait_pid,
                restart_path=self.restart_path.resolve() if self.restart_path is not None else None,
            )
            subprocess.Popen(command, cwd=str(updater.parent), close_fds=True)
        except (AppUpdateError, OSError) as error:
            self._finish_error(str(error))
            return
        QMessageBox.information(
            self,
            "更新已准备好",
            "更新包已经下载并校验。此维护窗口会关闭；请从托盘退出 PetNest 高级版，安装程序随后会自动运行。",
        )
        self.accept()

    def _finish_error(self, message: str) -> None:
        self.status.setText("更新失败：" + (message or "未知错误"))
        self.close_button.setEnabled(True)


def run_maintenance(mode: str, *, parent_pid: int = 0, restart_path: Path | None = None) -> int:
    dialog = MaintenanceDialog(mode, parent_pid=parent_pid, restart_path=restart_path)
    dialog.show()
    return dialog.exec()
