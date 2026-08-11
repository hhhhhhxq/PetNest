"""应用安装包更新的轻量状态对话框。"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from petnest.core.app_update import AppUpdateInfo


class AppUpdateDialog(QDialog):
    """只呈现状态；网络和安装动作由应用层后台调度。"""

    def __init__(
        self,
        current_version: str,
        *,
        on_check: Callable[[], object] | None = None,
        on_download: Callable[[AppUpdateInfo], object] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("PetNest 程序更新")
        self.setModal(False)
        self.setMinimumWidth(380)
        self._current_version = current_version
        self._on_download = on_download
        self._update: AppUpdateInfo | None = None
        layout = QVBoxLayout(self)
        self.version_label = QLabel(f"当前版本 {current_version}", self)
        self.version_label.setWordWrap(True)
        self.status_label = QLabel("点击“立即检查”获取最新安装包。", self)
        self.status_label.setWordWrap(True)
        self.notes_label = QLabel("", self)
        self.notes_label.setWordWrap(True)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        self.check_button = QPushButton("立即检查", self)
        self.download_button = QPushButton("下载并安装", self)
        self.download_button.setVisible(False)
        self.download_button.setEnabled(False)
        self.later_button = QPushButton("稍后", self)
        self.check_button.clicked.connect(on_check or (lambda: None))
        self.download_button.clicked.connect(self._download_clicked)
        self.later_button.clicked.connect(self.close)
        layout.addWidget(self.version_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.notes_label)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.check_button)
        layout.addWidget(self.download_button)
        buttons = QDialogButtonBox(self)
        buttons.addButton(self.later_button, QDialogButtonBox.ButtonRole.RejectRole)
        layout.addWidget(buttons)

    @property
    def update(self) -> AppUpdateInfo | None:
        return self._update

    def set_checking(self) -> None:
        self.check_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.status_label.setText("正在检查程序更新…")
        self.progress_bar.setVisible(False)

    def set_available(self, update: AppUpdateInfo) -> None:
        self._update = update
        self.version_label.setText(f"发现新版本 {update.version}")
        self.status_label.setText("可以下载新的安装包；当前版本会在安装失败时保留。")
        self.notes_label.setText(update.release_notes)
        self.check_button.setEnabled(True)
        self.download_button.setVisible(True)
        self.download_button.setEnabled(True)
        self.progress_bar.setVisible(False)

    def set_no_update(self) -> None:
        self._update = None
        self.version_label.setText(f"当前版本 {self._current_version}")
        self.status_label.setText("已经是最新版本。")
        self.notes_label.clear()
        self.check_button.setEnabled(True)
        self.download_button.setVisible(False)
        self.download_button.setEnabled(False)
        self.progress_bar.setVisible(False)

    def set_error(self, message: str) -> None:
        self.check_button.setEnabled(True)
        self.download_button.setEnabled(self._update is not None)
        self.status_label.setText(f"检查或下载失败：{message}")
        self.progress_bar.setVisible(False)

    def set_downloading(self, progress: int = 0) -> None:
        self.check_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.status_label.setText(f"正在下载安装包（{max(0, min(100, int(progress)))}%）…")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(max(0, min(100, int(progress))))

    def set_finished(self) -> None:
        self.check_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.status_label.setText("安装包已校验，程序即将退出并安装更新。")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(100)

    def _download_clicked(self) -> None:
        if self._update is not None and self._on_download is not None:
            self._on_download(self._update)
