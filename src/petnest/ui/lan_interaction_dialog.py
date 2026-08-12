"""局域网互动的精致、克制的本地 UI。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from petnest.core.device_identity import display_name_for, initials_for
from petnest.models.lan_interaction import InteractionDraft, InteractionKind, LanPeer
from petnest.models.settings import Settings


class NicknameDialog(QDialog):
    """只负责编辑昵称，不把昵称设置混入普通宠物设置表单。"""

    def __init__(self, nickname: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置我的昵称")
        self.setMinimumWidth(340)
        layout = QVBoxLayout(self)
        title = QLabel("别人会看到这个名字", self)
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.nickname_input = QLineEdit(self)
        self.nickname_input.setText(nickname)
        self.nickname_input.setMaxLength(24)
        self.nickname_input.setPlaceholderText("留空则显示“用户-短设备码”")
        layout.addWidget(self.nickname_input)
        hint = QLabel("昵称只保存在本机设置中，不会上传到服务器。", self)
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setStyleSheet(_dialog_stylesheet())

    def nickname(self) -> str:
        return self.nickname_input.text().strip()


class ManualPeerDialog(QDialog):
    """收集一个临时 IPv4 地址，不保存到本机设置。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("手动添加设备")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        title = QLabel("输入对方电脑的 IPv4 地址", self)
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.ip_input = QLineEdit(self)
        self.ip_input.setPlaceholderText("例如 192.168.21.146")
        self.ip_input.setClearButtonEnabled(True)
        self.ip_input.returnPressed.connect(self.accept)
        layout.addWidget(self.ip_input)
        hint = QLabel("端口固定为 18487。只在双方网络允许互通时有效，不会保存这个地址。", self)
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("验证并添加")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setStyleSheet(_dialog_stylesheet())

    def ip_address(self) -> str:
        return self.ip_input.text().strip()


class RemotePairDialog(QDialog):
    """收集另一台 PetNest 展示的远程伙伴码。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("添加远程伙伴")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        title = QLabel("输入对方的 10 位伙伴码", self)
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        self.code_input = QLineEdit(self)
        self.code_input.setPlaceholderText("例如 7K3M-P9WX-2Q")
        self.code_input.setMaxLength(14)
        self.code_input.setClearButtonEnabled(True)
        self.code_input.returnPressed.connect(self.accept)
        layout.addWidget(self.code_input)
        hint = QLabel("伙伴码只用于建立双方关系；互动消息通过 Firebase 的 HTTPS 连接传输。", self)
        hint.setObjectName("mutedLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("验证并添加")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.setStyleSheet(_dialog_stylesheet())

    def pair_code(self) -> str:
        return "".join(char for char in self.code_input.text().upper() if char.isalnum())


class LanInteractionDialog(QDialog):
    """附近设备、远程伙伴和三种互斥互动方式的统一入口。"""

    def __init__(
        self,
        *,
        settings: Settings,
        peers: Sequence[LanPeer] = (),
        remote_peers: Sequence[LanPeer] = (),
        effects: Sequence[object] = (),
        on_send: Callable[[InteractionDraft], bool | None] | None = None,
        on_remote_send: Callable[[InteractionDraft], bool | None] | None = None,
        on_probe: Callable[[str], bool | None] | None = None,
        on_remote_pair: Callable[[str], bool | None] | None = None,
        on_preview: Callable[[object], bool | None] | None = None,
        on_preview_clear: Callable[[], None] | None = None,
        remote_pair_code: str = "",
        remote_status: str = "Firebase 尚未配置",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("互动")
        self.setMinimumSize(760, 500)
        self.resize(860, 560)
        self._settings = settings
        self._peers = tuple(peers)
        self._remote_peers = tuple(remote_peers)
        self._effects = tuple(effects)
        self._on_send = on_send
        self._on_remote_send = on_remote_send
        self._on_probe = on_probe
        self._on_remote_pair = on_remote_pair
        self._on_preview = on_preview
        self._on_preview_clear = on_preview_clear
        self._remote_pair_code = remote_pair_code
        self._remote_status = remote_status
        self._preview_active = False
        self._selected_peer: LanPeer | None = None
        self._selected_effect_id: str | None = None
        self._build_ui()
        self._populate_peers()
        self._populate_remote_peers()
        self._populate_effects()
        self._select_initial_values()
        self.setStyleSheet(_dialog_stylesheet())
        self.finished.connect(lambda _result: self._clear_local_preview())

    @property
    def settings(self) -> Settings:
        return replace(
            self._settings,
            lan_interaction_enabled=self.lan_enabled_input.isChecked(),
            remote_interaction_enabled=self.remote_enabled_input.isChecked(),
        )

    def set_status_message(self, message: str) -> None:
        self.status_label.setText(str(message))

    def set_remote_status(self, message: str) -> None:
        self._remote_status = str(message)
        self.remote_status_label.setText(self._remote_status)

    def set_remote_pair_code(self, code: str) -> None:
        self._remote_pair_code = str(code)
        formatted = _display_pair_code(self._remote_pair_code) if self._remote_pair_code else "等待连接"
        self.pair_code_label.setText(f"我的码：{formatted}")

    def set_peers(self, peers: Sequence[LanPeer]) -> None:
        """刷新设备列表，并尽量保留用户当前选择。"""
        selected_id = self._selected_peer.device_id if self._selected_peer is not None else None
        self._peers = tuple(peers)
        self._populate_peers()
        if not self._peers:
            self._selected_peer = None
            self._peer_changed(None, None)
            return
        row = next((index for index, peer in enumerate(self._peers) if peer.device_id == selected_id), 0)
        self.peer_list.setCurrentRow(row)

    def update_peer(self, peer: LanPeer) -> None:
        """接收发现服务的单个更新。"""
        merged = {item.device_id: item for item in self._peers}
        merged[peer.device_id] = peer
        self.set_peers(tuple(merged.values()))

    def manual_probe_succeeded(self, peer: LanPeer) -> None:
        """定向握手成功后加入列表并选中新设备。"""
        self.update_peer(peer)
        for row in range(self.peer_list.count()):
            item = self.peer_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == peer.device_id:
                self.peer_list.setCurrentRow(row)
                break
        label = peer.display_name.strip() or f"用户-{peer.device_id[-4:].upper()}"
        self.set_status_message(f"已添加：{label}（{peer.ip_address or '未知 IP'}）")

    def remove_peer(self, device_id: str) -> None:
        self.set_peers(tuple(peer for peer in self._peers if peer.device_id != device_id))

    def set_remote_peers(self, peers: Sequence[LanPeer]) -> None:
        selected_id = (
            self._selected_peer.device_id
            if self._selected_peer is not None and self._selected_peer.transport == "remote"
            else None
        )
        self._remote_peers = tuple(peers)
        self._populate_remote_peers()
        if self.device_tabs.currentIndex() != 1:
            return
        if not self._remote_peers:
            self._selected_peer = None
            self._remote_peer_changed(None, None)
            return
        row = next((index for index, peer in enumerate(self._remote_peers) if peer.device_id == selected_id), 0)
        self.remote_peer_list.setCurrentRow(row)

    def update_remote_peer(self, peer: LanPeer) -> None:
        merged = {item.device_id: item for item in self._remote_peers}
        merged[peer.device_id] = peer
        self.set_remote_peers(tuple(merged.values()))

    def remove_remote_peer(self, device_id: str) -> None:
        self.set_remote_peers(tuple(peer for peer in self._remote_peers if peer.device_id != device_id))

    def remote_pair_succeeded(self, peer: LanPeer) -> None:
        self.update_remote_peer(peer)
        self.device_tabs.setCurrentIndex(1)
        for row in range(self.remote_peer_list.count()):
            item = self.remote_peer_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == peer.device_id:
                self.remote_peer_list.setCurrentRow(row)
                break
        self.set_status_message(f"已添加远程伙伴：{peer.display_name}")

    def _open_manual_peer_dialog(self) -> None:
        dialog = ManualPeerDialog(self)
        if not dialog.exec():
            return
        if self._on_probe is None:
            self.set_status_message("手动验证接口尚未启用")
            return
        try:
            started = self._on_probe(dialog.ip_address())
        except Exception as error:  # noqa: BLE001 - 网络层错误必须显示在窗口中。
            self.set_status_message(f"验证失败：{error}")
            return
        if started is not False:
            self.set_status_message(f"正在验证 {dialog.ip_address()} …")

    def _open_remote_pair_dialog(self) -> None:
        dialog = RemotePairDialog(self)
        if not dialog.exec():
            return
        if self._on_remote_pair is None:
            self.set_status_message("Firebase 尚未配置，无法添加远程伙伴")
            return
        try:
            started = self._on_remote_pair(dialog.pair_code())
        except Exception as error:  # noqa: BLE001 - 网络层错误必须显示在窗口中。
            self.set_status_message(f"添加失败：{error}")
            return
        if started is not False:
            self.set_status_message("正在验证伙伴码…")

    def _copy_pair_code(self) -> None:
        if not self._remote_pair_code:
            self.set_status_message("远程伙伴尚未连接，暂时没有可复制的伙伴码")
            return
        QGuiApplication.clipboard().setText(self._remote_pair_code)
        self.set_status_message("伙伴码已复制")

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(18)

        left = QFrame(self)
        left.setObjectName("sidebar")
        left.setFixedWidth(238)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(16, 16, 16, 16)
        left_layout.setSpacing(10)
        left_title = QLabel("互动设备", left)
        left_title.setObjectName("titleLabel")
        left_layout.addWidget(left_title)
        left_hint = QLabel("选择附近设备或已经配对的远程伙伴", left)
        left_hint.setObjectName("mutedLabel")
        left_hint.setWordWrap(True)
        left_layout.addWidget(left_hint)
        self.device_tabs = QTabWidget(left)
        self.device_tabs.setObjectName("deviceTabs")

        nearby_page = QWidget(self.device_tabs)
        nearby_layout = QVBoxLayout(nearby_page)
        nearby_layout.setContentsMargins(4, 8, 4, 4)
        nearby_layout.setSpacing(8)
        self.manual_ip_button = QPushButton("手动添加 IP", nearby_page)
        self.manual_ip_button.setObjectName("secondaryButton")
        self.manual_ip_button.setToolTip("适用于自动广播发现不到的跨网段设备")
        self.manual_ip_button.clicked.connect(self._open_manual_peer_dialog)
        nearby_layout.addWidget(self.manual_ip_button)
        self.lan_enabled_input = QCheckBox("允许附近设备发现我", nearby_page)
        self.lan_enabled_input.setChecked(self._settings.lan_interaction_enabled)
        self.lan_enabled_input.setToolTip("只在局域网内广播昵称和宠物名称，不上传图片或动效文件")
        nearby_layout.addWidget(self.lan_enabled_input)
        self.peer_list = QListWidget(nearby_page)
        self.peer_list.setObjectName("peerList")
        self.peer_list.setSpacing(4)
        self.peer_list.currentItemChanged.connect(self._peer_changed)
        nearby_layout.addWidget(self.peer_list, 1)
        self.device_tabs.addTab(nearby_page, "附近设备")

        remote_page = QWidget(self.device_tabs)
        remote_layout = QVBoxLayout(remote_page)
        remote_layout.setContentsMargins(4, 8, 4, 4)
        remote_layout.setSpacing(8)
        self.remote_enabled_input = QCheckBox("启用远程伙伴", remote_page)
        self.remote_enabled_input.setChecked(self._settings.remote_interaction_enabled)
        remote_layout.addWidget(self.remote_enabled_input)
        pair_row = QHBoxLayout()
        formatted_code = _display_pair_code(self._remote_pair_code) if self._remote_pair_code else "等待连接"
        self.pair_code_label = QLabel(f"我的码：{formatted_code}", remote_page)
        self.pair_code_label.setObjectName("mutedLabel")
        self.copy_pair_code_button = QPushButton("复制", remote_page)
        self.copy_pair_code_button.setObjectName("linkButton")
        self.copy_pair_code_button.clicked.connect(self._copy_pair_code)
        pair_row.addWidget(self.pair_code_label, 1)
        pair_row.addWidget(self.copy_pair_code_button)
        remote_layout.addLayout(pair_row)
        self.add_remote_button = QPushButton("添加远程伙伴", remote_page)
        self.add_remote_button.setObjectName("secondaryButton")
        self.add_remote_button.clicked.connect(self._open_remote_pair_dialog)
        remote_layout.addWidget(self.add_remote_button)
        self.remote_status_label = QLabel(self._remote_status, remote_page)
        self.remote_status_label.setObjectName("mutedLabel")
        self.remote_status_label.setWordWrap(True)
        remote_layout.addWidget(self.remote_status_label)
        self.remote_peer_list = QListWidget(remote_page)
        self.remote_peer_list.setObjectName("remotePeerList")
        self.remote_peer_list.setSpacing(4)
        self.remote_peer_list.currentItemChanged.connect(self._remote_peer_changed)
        remote_layout.addWidget(self.remote_peer_list, 1)
        self.device_tabs.addTab(remote_page, "远程伙伴")
        left_layout.addWidget(self.device_tabs, 1)
        self.nickname_button = QPushButton(left)
        self.nickname_button.setObjectName("linkButton")
        self.nickname_button.clicked.connect(self._edit_nickname)
        left_layout.addWidget(self.nickname_button)
        root.addWidget(left)

        right = QFrame(self)
        right.setObjectName("contentPanel")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(20, 18, 20, 16)
        right_layout.setSpacing(12)
        heading_row = QHBoxLayout()
        heading = QLabel("发送互动", right)
        heading.setObjectName("titleLabel")
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        self.recipient_label = QLabel("未选择设备", right)
        self.recipient_label.setObjectName("mutedLabel")
        heading_row.addWidget(self.recipient_label)
        right_layout.addLayout(heading_row)

        self.mode_tabs = QTabWidget(right)
        self.mode_tabs.setObjectName("modeTabs")
        self.mode_tabs.addTab(self._build_quick_page(), "快捷互动")
        self.mode_tabs.addTab(self._build_text_page(), "文字")
        self.mode_tabs.addTab(self._build_effect_page(), "动效")
        self.mode_tabs.currentChanged.connect(self._mode_changed)
        right_layout.addWidget(self.mode_tabs, 1)

        bottom = QHBoxLayout()
        self.status_label = QLabel("选择一个互动方式后发送", right)
        self.status_label.setObjectName("mutedLabel")
        self.status_label.setWordWrap(True)
        bottom.addWidget(self.status_label, 1)
        self.send_button = QPushButton("发送招呼", right)
        self.send_button.setObjectName("primaryButton")
        self.send_button.setMinimumWidth(126)
        self.send_button.clicked.connect(self._send_current)
        bottom.addWidget(self.send_button)
        right_layout.addLayout(bottom)
        root.addWidget(right, 1)
        self.device_tabs.currentChanged.connect(self._device_tab_changed)

    def _build_quick_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 16, 8, 8)
        layout.setSpacing(12)
        hint = QLabel("一次只发送一种快捷互动", page)
        hint.setObjectName("mutedLabel")
        layout.addWidget(hint)
        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.greeting_button = self._quick_card("👋", "打招呼", "在对方宠物旁显示轻量提示")
        self.heart_button = self._quick_card("♥", "送爱心", "在对方宠物旁播放爱心动效")
        self.greeting_button.setChecked(True)
        cards.addWidget(self.greeting_button)
        cards.addWidget(self.heart_button)
        layout.addLayout(cards)
        layout.addStretch(1)
        return page

    def _quick_card(self, symbol: str, title: str, subtitle: str) -> QPushButton:
        button = QPushButton(f"{symbol}\n{title}\n{subtitle}", self)
        button.setCheckable(True)
        button.setAutoExclusive(True)
        button.setMinimumHeight(148)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        button.setObjectName("quickCard")
        button.clicked.connect(self._quick_selection_changed)
        return button

    def _build_text_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 16, 8, 8)
        layout.setSpacing(8)
        self.text_input = QTextEdit(page)
        self.text_input.setPlaceholderText("写一句轻松的问候…")
        self.text_input.setMaximumHeight(150)
        self.text_input.textChanged.connect(self._update_text_count)
        layout.addWidget(self.text_input)
        self.text_count_label = QLabel("0 / 120", page)
        self.text_count_label.setObjectName("mutedLabel")
        self.text_count_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.text_count_label)
        layout.addStretch(1)
        return page

    def _build_effect_page(self) -> QWidget:
        page = QWidget(self)
        layout = QHBoxLayout(page)
        layout.setContentsMargins(8, 16, 8, 8)
        layout.setSpacing(14)
        self.effect_list = QListWidget(page)
        self.effect_list.setObjectName("effectList")
        self.effect_list.currentItemChanged.connect(self._effect_changed)
        layout.addWidget(self.effect_list, 1)
        preview = QFrame(page)
        preview.setObjectName("previewCard")
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(12, 12, 12, 12)
        self.effect_preview = QLabel("选择一个动效", preview)
        self.effect_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.effect_preview.setMinimumSize(150, 150)
        self.effect_preview.setObjectName("effectPreview")
        preview_layout.addWidget(self.effect_preview, 1)
        self.effect_meta = QLabel("动效只发送编号，不传输资源文件", preview)
        self.effect_meta.setObjectName("mutedLabel")
        self.effect_meta.setWordWrap(True)
        preview_layout.addWidget(self.effect_meta)
        self.preview_button = QPushButton("在我的宠物上预览", preview)
        self.preview_button.setObjectName("previewButton")
        self.preview_button.setEnabled(False)
        self.preview_button.clicked.connect(self._preview_selected_effect)
        preview_layout.addWidget(self.preview_button)
        layout.addWidget(preview, 1)
        return page

    def _populate_peers(self) -> None:
        self.peer_list.clear()
        if not self._peers:
            item = QListWidgetItem("没有发现附近设备\n请确认对方已开启互动", self.peer_list)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setForeground(QColor("#8f8b86"))
            return
        for peer in self._peers:
            label = peer.display_name.strip() or f"用户-{peer.device_id[-4:].upper()}"
            item = QListWidgetItem(f"{initials_for(label)}  {label}\n{peer.subtitle}", self.peer_list)
            item.setData(Qt.ItemDataRole.UserRole, peer.device_id)
            item.setToolTip(peer.ip_address or "局域网设备")

    def _populate_remote_peers(self) -> None:
        self.remote_peer_list.clear()
        if not self._remote_peers:
            item = QListWidgetItem("还没有远程伙伴\n输入伙伴码即可添加", self.remote_peer_list)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setForeground(QColor("#8f8b86"))
            return
        for peer in self._remote_peers:
            label = peer.display_name.strip() or f"用户-{peer.device_id[-4:].upper()}"
            item = QListWidgetItem(f"{initials_for(label)}  {label}\n{peer.subtitle}", self.remote_peer_list)
            item.setData(Qt.ItemDataRole.UserRole, peer.device_id)
            item.setToolTip("Firebase 远程伙伴")

    def _populate_effects(self) -> None:
        self.effect_list.clear()
        if not self._effects:
            item = QListWidgetItem("暂无可用动效\n请先导入本地动效", self.effect_list)
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            item.setForeground(QColor("#8f8b86"))
            return
        for effect in self._effects:
            identifier = str(getattr(effect, "identifier", ""))
            name = str(getattr(effect, "name", identifier))
            duration = int(getattr(effect, "duration_ms", 0))
            item = QListWidgetItem(f"{name}\n{duration / 1000:.1f} 秒", self.effect_list)
            item.setData(Qt.ItemDataRole.UserRole, identifier)

    def _select_initial_values(self) -> None:
        if self._peers:
            self.peer_list.setCurrentRow(0)
        self._update_nickname_button()
        self._mode_changed(0)

    def _peer_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if self.device_tabs.currentIndex() != 0:
            return
        self._selected_peer = None
        if current is not None:
            peer_id = current.data(Qt.ItemDataRole.UserRole)
            self._selected_peer = next((peer for peer in self._peers if peer.device_id == peer_id), None)
        label = self._selected_peer.display_name if self._selected_peer else "未选择设备"
        self.recipient_label.setText(f"发送给：{label}" if self._selected_peer else label)
        self._refresh_send_button()

    def _remote_peer_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if self.device_tabs.currentIndex() != 1:
            return
        self._selected_peer = None
        if current is not None:
            peer_id = current.data(Qt.ItemDataRole.UserRole)
            self._selected_peer = next((peer for peer in self._remote_peers if peer.device_id == peer_id), None)
        label = self._selected_peer.display_name if self._selected_peer else "未选择伙伴"
        self.recipient_label.setText(f"发送给：{label}" if self._selected_peer else label)
        self._refresh_send_button()

    def _device_tab_changed(self, index: int) -> None:
        if index == 0:
            if self._peers and self.peer_list.currentRow() < 0:
                self.peer_list.setCurrentRow(0)
            self._peer_changed(self.peer_list.currentItem(), None)
        else:
            if self._remote_peers and self.remote_peer_list.currentRow() < 0:
                self.remote_peer_list.setCurrentRow(0)
            self._remote_peer_changed(self.remote_peer_list.currentItem(), None)

    def _quick_selection_changed(self) -> None:
        self._refresh_send_button()

    def _mode_changed(self, _index: int) -> None:
        self._refresh_send_button()

    def _effect_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        self._clear_local_preview()
        self._selected_effect_id = current.data(Qt.ItemDataRole.UserRole) if current else None
        if not self._selected_effect_id:
            self.effect_preview.setText("选择一个动效")
            self.effect_preview.setPixmap(QPixmap())
            self.effect_meta.setText("动效只发送编号，不传输资源文件")
            self.preview_button.setEnabled(False)
            self._refresh_send_button()
            return
        effect = self._selected_effect()
        frame_paths = tuple(getattr(effect, "frames", ())) if effect is not None else ()
        if frame_paths:
            pixmap = QPixmap(str(frame_paths[0]))
            self.effect_preview.setPixmap(pixmap.scaled(150, 150, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            self.effect_preview.setText("")
        else:
            self.effect_preview.setPixmap(QPixmap())
            self.effect_preview.setText("已选择")
        duration = int(getattr(effect, "duration_ms", 0)) if effect is not None else 0
        self.effect_meta.setText(f"{self._selected_effect_id} · {duration / 1000:.1f} 秒\n只发送编号，不传输资源文件")
        self.preview_button.setEnabled(effect is not None and self._on_preview is not None)
        self._refresh_send_button()

    def _selected_effect(self) -> object | None:
        if not self._selected_effect_id:
            return None
        return next(
            (item for item in self._effects if getattr(item, "identifier", None) == self._selected_effect_id),
            None,
        )

    def _preview_selected_effect(self) -> None:
        effect = self._selected_effect()
        if effect is None or self._on_preview is None:
            return
        self._clear_local_preview()
        try:
            played = self._on_preview(effect)
        except Exception as error:  # noqa: BLE001 - 预览失败不能关闭互动窗口。
            self.status_label.setText(f"预览失败：{error}")
            return
        if played is False:
            self.status_label.setText("动效帧不可用，无法预览")
            return
        self._preview_active = True
        self.status_label.setText("正在本机宠物上预览动效")

    def _clear_local_preview(self) -> None:
        if not self._preview_active:
            return
        self._preview_active = False
        if self._on_preview_clear is not None:
            try:
                self._on_preview_clear()
            except Exception:  # noqa: BLE001 - 清理失败不能阻止窗口关闭。
                self.status_label.setText("本机预览清理失败")

    def _update_text_count(self) -> None:
        self.text_count_label.setText(f"{len(self.text_input.toPlainText())} / 120")
        self._refresh_send_button()

    def _refresh_send_button(self) -> None:
        if self.mode_tabs.currentIndex() == 0:
            self.send_button.setText("发送招呼" if self.greeting_button.isChecked() else "发送爱心")
            return
        if self.mode_tabs.currentIndex() == 1:
            self.send_button.setText("发送文字")
            return
        self.send_button.setText("发送动效")

    def interaction_draft(self) -> InteractionDraft | None:
        if self._selected_peer is None:
            return None
        try:
            if self.mode_tabs.currentIndex() == 0:
                kind = InteractionKind.GREETING if self.greeting_button.isChecked() else InteractionKind.HEART
                return InteractionDraft.quick(self._selected_peer.device_id, kind)
            if self.mode_tabs.currentIndex() == 1:
                return InteractionDraft.text_message(self._selected_peer.device_id, self.text_input.toPlainText())
            if self._selected_effect_id:
                return InteractionDraft.effect(self._selected_peer.device_id, self._selected_effect_id)
        except ValueError as error:
            self.status_label.setText(str(error))
        return None

    def _send_current(self) -> None:
        draft = self.interaction_draft()
        if draft is None:
            self.status_label.setText("请先选择设备和有效内容")
            return
        sender = self._on_remote_send if self._selected_peer.transport == "remote" else self._on_send
        if sender is None:
            self.status_label.setText("发送接口尚未启用，当前仅完成本地预览")
            return
        try:
            sent = sender(draft)
        except Exception as error:  # noqa: BLE001 - UI 必须把网络层错误转为可见状态。
            self.status_label.setText(f"发送失败：{error}")
            return
        self.status_label.setText("已发送" if sent is not False else "发送失败，请稍后重试")

    def _edit_nickname(self) -> None:
        dialog = NicknameDialog(self._settings.nickname, self)
        if dialog.exec():
            self._settings = replace(self._settings, nickname=dialog.nickname())
            self._update_nickname_button()

    def _update_nickname_button(self) -> None:
        self.nickname_button.setText(f"设置我的昵称  ·  {display_name_for(self._settings)}")


def _display_pair_code(code: str) -> str:
    normalized = "".join(char for char in code.upper() if char.isalnum())
    return "-".join((normalized[:4], normalized[4:8], normalized[8:])) if len(normalized) == 10 else normalized


def _dialog_stylesheet() -> str:
    return """
    QDialog { background: #faf9f7; color: #272421; }
    QFrame#sidebar, QFrame#contentPanel { background: #ffffff; border: 1px solid #ebe6df; border-radius: 16px; }
    QLabel#titleLabel { font-size: 17px; font-weight: 650; color: #272421; }
    QLabel#sectionTitle { color: #272421; font-size: 15px; font-weight: 600; }
    QLabel#mutedLabel { color: #8f8b86; font-size: 12px; }
    QListWidget { background: transparent; border: none; outline: none; }
    QListWidget::item { padding: 10px 8px; border-radius: 10px; color: #4b4641; }
    QListWidget::item:selected { background: #fff0e8; color: #a85d3e; }
    QTabWidget::pane { border: 1px solid #ebe6df; border-radius: 12px; background: #fff; }
    QTabBar::tab { background: transparent; color: #8f8b86; padding: 8px 18px; border: none; }
    QTabBar::tab:selected { color: #a85d3e; background: #fff0e8; border-radius: 8px; }
    QPushButton#quickCard { background: #fcfbf9; border: 1px solid #ebe6df; border-radius: 14px; color: #4b4641; font-size: 13px; }
    QPushButton#quickCard:checked { background: #fff0e8; border: 1px solid #efbda2; color: #a85d3e; }
    QPushButton#primaryButton { background: #df8f68; color: white; border: none; border-radius: 10px; padding: 9px 18px; font-weight: 600; }
    QPushButton#primaryButton:disabled { background: #d8d1c9; }
    QPushButton#secondaryButton { background: #fcfbf9; color: #a85d3e; border: 1px solid #efbda2; border-radius: 9px; padding: 7px 10px; }
    QPushButton#secondaryButton:hover { background: #fff0e8; }
    QPushButton#previewButton { background: #fff0e8; color: #a85d3e; border: 1px solid #efbda2; border-radius: 9px; padding: 8px 12px; }
    QPushButton#previewButton:hover { background: #ffe6d8; }
    QPushButton#previewButton:disabled { background: #f2efeb; color: #aaa39b; border-color: #e6e0d8; }
    QPushButton#linkButton { text-align: left; color: #a85d3e; border: none; background: transparent; padding: 7px 2px; }
    QDialogButtonBox QPushButton { min-width: 86px; background: #fcfbf9; color: #4b4641; border: 1px solid #d9d2ca; border-radius: 9px; padding: 8px 14px; }
    QDialogButtonBox QPushButton:hover { background: #fff0e8; border-color: #efbda2; color: #a85d3e; }
    QDialogButtonBox QPushButton:default { background: #df8f68; color: #ffffff; border-color: #df8f68; font-weight: 600; }
    QDialogButtonBox QPushButton:default:hover { background: #d98259; border-color: #d98259; color: #ffffff; }
    QTextEdit, QLineEdit { background: #fcfbf9; color: #272421; placeholder-text-color: #aaa39b; border: 1px solid #ebe6df; border-radius: 10px; padding: 8px; }
    QFrame#previewCard { background: #fcfbf9; border: 1px solid #ebe6df; border-radius: 12px; }
    QLabel#effectPreview { color: #a7a19a; }
    """
