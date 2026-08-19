"""局域网互动的精致、克制的本地 UI。"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPoint, QTimer, QSize, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from petnest.core.device_identity import display_name_for, initials_for
from petnest.core.lan_chat import LanChatImageError, prepare_chat_image
from petnest.models.lan_interaction import (
    MAX_CHAT_TEXT_LENGTH,
    ChatDraft,
    ChatMessageKind,
    ChatScope,
    InteractionDraft,
    InteractionKind,
    LanChatMessage,
    LanPeer,
)
from petnest.models.lan_pool import PoolMemberView
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
        hint = QLabel(
            "端口固定为 18487。连接成功后可局域网聊天，"
            "也会互换双方当前 Codex 账号的脱敏用量快照；"
            "不传输登录凭据。",
            self,
        )
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
    """附近设备、远程伙伴、轻互动和局域网聊天的统一入口。"""

    _PREVIEW_SAMPLE_COUNT = 9
    _DEFAULT_STATUS = "选择一个互动方式后发送"
    _LAN_GROUP_DEVICE_ID = "*"
    _ALERT_GROUP_DEVICE_ID = "@lan-alert-group"

    def __init__(
        self,
        *,
        settings: Settings,
        peers: Sequence[LanPeer] = (),
        pool_members: Sequence[PoolMemberView] = (),
        remote_peers: Sequence[LanPeer] = (),
        effects: Sequence[object] = (),
        on_send: Callable[[InteractionDraft], bool | None] | None = None,
        on_chat_send: Callable[[ChatDraft], bool | None] | None = None,
        on_alert_membership_changed: Callable[[bool], bool | None] | None = None,
        on_update_peer_address: Callable[[str, str], bool | None] | None = None,
        on_forget_peer: Callable[[str], bool | None] | None = None,
        on_remote_send: Callable[[InteractionDraft], bool | None] | None = None,
        on_probe: Callable[[str], bool | None] | None = None,
        on_remote_pair: Callable[[str], bool | None] | None = None,
        on_preview: Callable[[object], bool | None] | None = None,
        on_preview_clear: Callable[[], None] | None = None,
        remote_send_async: bool = False,
        remote_pair_code: str = "",
        remote_status: str = "Firebase 尚未配置",
        chat_messages: Sequence[LanChatMessage] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("互动")
        self.setMinimumSize(760, 500)
        self.resize(860, 560)
        self._settings = settings
        self._peers = tuple(peers)
        self._pool_members = tuple(pool_members)
        self._remote_peers = tuple(remote_peers)
        self._effects = tuple(effects)
        self._on_send = on_send
        self._on_chat_send = on_chat_send
        self._on_alert_membership_changed = on_alert_membership_changed
        self._on_update_peer_address = on_update_peer_address
        self._on_forget_peer = on_forget_peer
        self._on_remote_send = on_remote_send
        self._on_probe = on_probe
        self._on_remote_pair = on_remote_pair
        self._on_preview = on_preview
        self._on_preview_clear = on_preview_clear
        self._remote_send_async = bool(remote_send_async)
        self._remote_pair_code = remote_pair_code
        self._remote_status = remote_status
        self._chat_messages = list(chat_messages)
        self._preview_active = False
        self._selected_peer: LanPeer | None = None
        self._selected_effect_id: str | None = None
        self._pending_send_draft: InteractionDraft | None = None
        self._success_feedback_timeout_ms = 2_500
        self._failure_feedback_timeout_ms = 4_000
        self._status_reset_timer = QTimer(self)
        self._status_reset_timer.setSingleShot(True)
        self._status_reset_timer.timeout.connect(self._restore_default_status)
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
            lan_group_chat_notifications_enabled=(
                self.group_chat_notifications_input.isChecked()
            ),
            lan_alert_group_joined=self._settings.lan_alert_group_joined,
            remote_interaction_enabled=self.remote_enabled_input.isChecked(),
        )

    def set_status_message(self, message: str) -> None:
        if self._pending_send_draft is not None:
            return
        self._show_feedback(str(message), timeout_ms=4_000)

    def remote_send_succeeded(self, draft: InteractionDraft) -> None:
        """远程服务确认写入 Firebase 后更新发送反馈。"""
        if self._pending_send_draft != draft:
            return
        self._pending_send_draft = None
        self._refresh_send_button()
        self._show_feedback("已发送 ✓", timeout_ms=self._success_feedback_timeout_ms)

    def remote_send_failed(self, draft: InteractionDraft, message: str) -> None:
        """远程服务报告写入失败后解除发送锁定。"""
        if self._pending_send_draft != draft:
            return
        self._pending_send_draft = None
        self._refresh_send_button()
        detail = str(message).strip()
        self._show_feedback(
            f"发送失败：{detail}" if detail else "发送失败，请稍后重试",
            timeout_ms=self._failure_feedback_timeout_ms,
        )

    def set_remote_status(self, message: str) -> None:
        self._remote_status = str(message)
        self.remote_status_label.setText(self._remote_status)

    def set_remote_pair_code(self, code: str) -> None:
        self._remote_pair_code = str(code)
        formatted = _display_pair_code(self._remote_pair_code) if self._remote_pair_code else "等待连接"
        self.pair_code_label.setText(f"我的码：{formatted}")

    def add_chat_message(self, message: LanChatMessage) -> None:
        """Append one in-session LAN chat message and refresh its conversation."""
        if any(item.message_id == message.message_id for item in self._chat_messages):
            return
        self._chat_messages.append(message)
        if len(self._chat_messages) > 200:
            del self._chat_messages[:-200]
        self._refresh_chat_messages()

    def set_peers(self, peers: Sequence[LanPeer]) -> None:
        """刷新设备列表，并尽量保留用户当前选择。"""
        selected_id = self._selected_peer.device_id if self._selected_peer is not None else None
        selected_mode = self.mode_tabs.currentIndex()
        self._peers = tuple(peers)
        self._populate_peers()
        if not self._peers:
            self._selected_peer = None
            self._peer_changed(None, None)
            return
        row = self._peer_row(selected_id)
        if row < 0:
            row = 2
        self.peer_list.setCurrentRow(row)
        self._peer_changed(self.peer_list.item(row), None)
        self.mode_tabs.setCurrentIndex(selected_mode)

    def set_pool_members(self, members: Sequence[PoolMemberView]) -> None:
        self._pool_members = tuple(members)
        selected_id = self._selected_peer.device_id if self._selected_peer is not None else None
        self._populate_peers()
        row = self._peer_row(selected_id)
        self.peer_list.setCurrentRow(row if row >= 0 else 0)
        self._refresh_alert_group_panel()
        self._refresh_send_button()

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
        self.manual_ip_button = QPushButton("连接电脑 IP", nearby_page)
        self.manual_ip_button.setObjectName("secondaryButton")
        self.manual_ip_button.setToolTip("连接后可聊天，并发起局域网 Codex 用量同步")
        self.manual_ip_button.clicked.connect(self._open_manual_peer_dialog)
        nearby_layout.addWidget(self.manual_ip_button)
        self.lan_enabled_input = QCheckBox("允许附近设备发现我", nearby_page)
        self.lan_enabled_input.setChecked(self._settings.lan_interaction_enabled)
        self.lan_enabled_input.setToolTip("只在局域网内广播昵称和宠物名称，不上传图片或动效文件")
        nearby_layout.addWidget(self.lan_enabled_input)
        self.group_chat_notifications_input = QCheckBox("群聊消息显示宠物气泡", nearby_page)
        self.group_chat_notifications_input.setChecked(
            self._settings.lan_group_chat_notifications_enabled
        )
        self.group_chat_notifications_input.setToolTip(
            "关闭后仍会接收群聊消息并显示在群聊记录中，只是不在桌宠旁弹出"
        )
        nearby_layout.addWidget(self.group_chat_notifications_input)
        self.peer_list = QListWidget(nearby_page)
        self.peer_list.setObjectName("peerList")
        self.peer_list.setSpacing(4)
        self.peer_list.setIconSize(QSize(30, 30))
        self.peer_list.currentItemChanged.connect(self._peer_changed)
        self.peer_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.peer_list.customContextMenuRequested.connect(self._show_peer_context_menu)
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
        self.remote_peer_list.setIconSize(QSize(30, 30))
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
        self.mode_tabs.addTab(self._build_chat_page(), "聊天")
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

    def _build_chat_page(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 12, 8, 8)
        layout.setSpacing(8)
        self.alert_group_panel = QFrame(page)
        self.alert_group_panel.setObjectName("alertGroupPanel")
        alert_layout = QVBoxLayout(self.alert_group_panel)
        alert_layout.setContentsMargins(10, 8, 10, 8)
        alert_header = QHBoxLayout()
        self.alert_group_label = QLabel(self.alert_group_panel)
        self.alert_group_label.setWordWrap(True)
        alert_header.addWidget(self.alert_group_label, 1)
        self.alert_join_button = QPushButton("加入预警组", self.alert_group_panel)
        self.alert_join_button.setObjectName("primaryButton")
        self.alert_join_button.clicked.connect(lambda: self._set_alert_group_joined(True))
        alert_header.addWidget(self.alert_join_button)
        self.alert_leave_button = QPushButton("退出", self.alert_group_panel)
        self.alert_leave_button.setObjectName("secondaryButton")
        self.alert_leave_button.clicked.connect(self._request_leave_alert_group)
        alert_header.addWidget(self.alert_leave_button)
        alert_layout.addLayout(alert_header)
        counts = QHBoxLayout()
        self.alert_joined_count_label = QLabel(self.alert_group_panel)
        self.alert_online_count_label = QLabel(self.alert_group_panel)
        self.alert_sendable_count_label = QLabel(self.alert_group_panel)
        for label in (
            self.alert_joined_count_label,
            self.alert_online_count_label,
            self.alert_sendable_count_label,
        ):
            label.setObjectName("mutedLabel")
            counts.addWidget(label)
        counts.addStretch(1)
        alert_layout.addLayout(counts)
        self.alert_member_list = QListWidget(self.alert_group_panel)
        self.alert_member_list.setMaximumHeight(126)
        alert_layout.addWidget(self.alert_member_list)
        self.alert_group_panel.hide()
        layout.addWidget(self.alert_group_panel)
        self.chat_list = QListWidget(page)
        self.chat_list.setObjectName("chatList")
        self.chat_list.setSpacing(5)
        self.chat_list.setIconSize(QSize(128, 96))
        layout.addWidget(self.chat_list, 1)

        emoji_row = QHBoxLayout()
        emoji_row.setSpacing(5)
        self.emoji_buttons: list[QPushButton] = []
        for emoji in ("😊", "😂", "🥰", "👍", "👋", "❤️"):
            button = QPushButton(emoji, page)
            button.setObjectName("emojiButton")
            button.setFixedSize(34, 30)
            button.clicked.connect(lambda _checked=False, value=emoji: self._send_chat_emoji(value))
            emoji_row.addWidget(button)
            self.emoji_buttons.append(button)
        emoji_row.addStretch(1)
        layout.addLayout(emoji_row)

        composer_row = QHBoxLayout()
        composer_row.setSpacing(8)
        self.chat_input = QTextEdit(page)
        self.chat_input.setPlaceholderText("输入局域网聊天消息…")
        self.chat_input.setMaximumHeight(76)
        self.chat_input.textChanged.connect(self._update_chat_count)
        composer_row.addWidget(self.chat_input, 1)
        self.chat_image_button = QPushButton("🖼  图片", page)
        self.chat_image_button.setObjectName("secondaryButton")
        self.chat_image_button.setToolTip("选择图片，压缩后通过局域网发送")
        self.chat_image_button.clicked.connect(self._choose_chat_image)
        composer_row.addWidget(self.chat_image_button)
        layout.addLayout(composer_row)
        self.chat_count_label = QLabel(
            f"0 / {MAX_CHAT_TEXT_LENGTH} · 记录仅在本次运行保留",
            page,
        )
        self.chat_count_label.setObjectName("mutedLabel")
        self.chat_count_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.chat_count_label)
        return page

    def _populate_peers(self) -> None:
        self.peer_list.clear()
        online = tuple(peer for peer in self._peers if peer.online)
        alert_members = tuple(member for member in self._pool_members if member.joined)
        if not self._pool_members:
            alert_members = tuple(
                peer for peer in online if peer.alert_group_supported and peer.alert_group_joined
            )
        alert_item = QListWidgetItem(
            self._peer_avatar("预警"),
            f"局域网预警组\n当前 {len(alert_members)} 人在线 · 自愿加入",
            self.peer_list,
        )
        alert_item.setData(Qt.ItemDataRole.UserRole, self._ALERT_GROUP_DEVICE_ID)
        alert_item.setToolTip("组内成员可聊天并发送危险预警")
        group_item = QListWidgetItem(
            self._peer_avatar("群聊"),
            f"局域网群聊\n当前 {len(online)} 台设备 · 文字/表情/图片",
            self.peer_list,
        )
        group_item.setData(Qt.ItemDataRole.UserRole, self._LAN_GROUP_DEVICE_ID)
        group_item.setToolTip("发送给当前已连接的所有局域网设备")
        for peer in self._peers:
            label = peer.display_name.strip() or f"用户-{peer.device_id[-4:].upper()}"
            item = QListWidgetItem(
                self._peer_avatar(label),
                label + "\n" + self._peer_status_text(peer),
                self.peer_list,
            )
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
            item = QListWidgetItem(self._peer_avatar(label), label + "\n" + peer.subtitle, self.remote_peer_list)
            item.setData(Qt.ItemDataRole.UserRole, peer.device_id)
            item.setToolTip("Firebase 远程伙伴")

    @staticmethod
    def _peer_status_text(peer: LanPeer) -> str:
        if peer.connection_state == "conflict":
            return "地址冲突"
        if peer.saved and not peer.online:
            return "已保存 · 离线"
        status = "已保存 · 在线" if peer.saved else ("附近 · 在线" if peer.online else "离线")
        if peer.online and not peer.alert_group_supported:
            status += " · 不支持预警组"
        elif peer.online and peer.alert_group_joined:
            status += " · 已加入预警组"
        return status

    def _alert_group_peers(self) -> tuple[LanPeer, ...]:
        return tuple(
            peer
            for peer in self._peers
            if peer.online and peer.alert_group_supported and peer.alert_group_joined
        )

    def _set_alert_group_joined(self, joined: bool) -> None:
        if self._settings.lan_alert_group_joined == joined:
            return
        if self._on_alert_membership_changed is not None:
            try:
                result = self._on_alert_membership_changed(joined)
            except Exception as error:  # noqa: BLE001 - UI surfaces callback errors.
                self._show_feedback(f"更新预警组状态失败：{error}", timeout_ms=self._failure_feedback_timeout_ms)
                return
            if result is False:
                self._show_feedback("更新预警组状态失败", timeout_ms=self._failure_feedback_timeout_ms)
                return
        self._settings = replace(self._settings, lan_alert_group_joined=joined)
        self._refresh_alert_group_panel()
        self._refresh_send_button()
        self._restore_default_status()

    def _request_leave_alert_group(self) -> None:
        answer = QMessageBox.question(
            self,
            "退出局域网预警组",
            "退出后将不再接收预警组聊天和危险预警，确定退出吗？",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._set_alert_group_joined(False)

    def _refresh_alert_group_panel(self) -> None:
        if not hasattr(self, "alert_group_panel"):
            return
        selected = self._selected_peer is not None and self._selected_peer.transport == "alert_group"
        self.alert_group_panel.setVisible(selected)
        if not selected:
            return
        joined = self._settings.lan_alert_group_joined
        views = tuple(member for member in self._pool_members if member.joined)
        if not self._pool_members:
            views = tuple(
                PoolMemberView(
                    peer.device_id,
                    peer.display_name,
                    True,
                    peer.online,
                    peer.online,
                    bool(peer.online and peer.ip_address and peer.port),
                )
                for peer in self._alert_group_peers()
            )
        joined_count = len(views)
        online_count = sum(member.online for member in views)
        sendable_count = sum(member.reachable and member.verified and member.online for member in views)
        self.alert_group_label.setText(
            "预警池成员名单"
            if joined
            else "加入后可参与预警组聊天，并接收危险预警"
        )
        self.alert_joined_count_label.setText(f"已加入 {joined_count} 人")
        self.alert_online_count_label.setText(f"在线 {online_count} 人")
        self.alert_sendable_count_label.setText(f"可发送 {sendable_count} 人")
        self.alert_member_list.clear()
        for member in views:
            if member.reachable and member.verified and member.online:
                status = "在线 · 可发送"
            elif member.online:
                status = "在线 · 正在验证"
            else:
                status = "离线"
            self.alert_member_list.addItem(f"{member.display_name}    {status}")
        self.alert_join_button.setVisible(not joined)
        self.alert_leave_button.setVisible(joined)

    def _selected_saved_peer(self) -> LanPeer | None:
        return self._selected_peer if self._selected_peer is not None and self._selected_peer.saved else None

    def _show_peer_context_menu(self, position: QPoint) -> None:
        peer = self._selected_saved_peer()
        if peer is None:
            return
        menu = QMenu(self.peer_list)
        update_action = menu.addAction("更新地址…")
        forget_action = menu.addAction("忘记此伙伴")
        selected = menu.exec(self.peer_list.viewport().mapToGlobal(position))
        if selected is update_action:
            self._update_selected_peer_address()
        elif selected is forget_action:
            self._forget_selected_peer()

    def _update_selected_peer_address(self) -> None:
        peer = self._selected_saved_peer()
        if peer is None or self._on_update_peer_address is None:
            return
        dialog = ManualPeerDialog(self)
        if peer.ip_address:
            dialog.ip_input.setText(peer.ip_address)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        result = self._on_update_peer_address(peer.device_id, dialog.ip_address())
        if result is False:
            self._show_feedback("更新地址失败", timeout_ms=self._failure_feedback_timeout_ms)
        else:
            self._show_feedback("正在验证新地址…", timeout_ms=self._success_feedback_timeout_ms)

    def _forget_selected_peer(self) -> None:
        peer = self._selected_saved_peer()
        if peer is None or self._on_forget_peer is None:
            return
        answer = QMessageBox.question(
            self,
            "忘记局域网伙伴",
            f"确定忘记“{peer.display_name}”吗？以后可重新输入 IP 添加。",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        result = self._on_forget_peer(peer.device_id)
        if result is False:
            self._show_feedback("忘记伙伴失败", timeout_ms=self._failure_feedback_timeout_ms)
            return
        self.remove_peer(peer.device_id)
        self._show_feedback("已忘记伙伴", timeout_ms=self._success_feedback_timeout_ms)

    @staticmethod
    def _peer_avatar(label: str) -> QIcon:
        """在名称左侧绘制头像缩写，右侧文字只保留完整名称。"""
        pixmap = QPixmap(30, 30)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#fff0e8"))
        painter.drawEllipse(1, 1, 28, 28)
        painter.setPen(QColor("#a85d3e"))
        font = QFont()
        font.setBold(True)
        font.setPointSize(9)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, initials_for(label))
        painter.end()
        return QIcon(pixmap)

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
            self.peer_list.setCurrentRow(2)
            self.mode_tabs.setCurrentIndex(0)
        else:
            self.peer_list.setCurrentRow(1)
            self.mode_tabs.setCurrentIndex(3)
        self._update_nickname_button()
        self._mode_changed(self.mode_tabs.currentIndex())

    def _peer_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if self.device_tabs.currentIndex() != 0:
            return
        self._restore_default_status()
        self._selected_peer = None
        if current is not None:
            peer_id = current.data(Qt.ItemDataRole.UserRole)
            if peer_id == self._ALERT_GROUP_DEVICE_ID:
                self._selected_peer = LanPeer(
                    device_id=self._ALERT_GROUP_DEVICE_ID,
                    display_name="局域网预警组",
                    online=True,
                    transport="alert_group",
                )
                self.mode_tabs.setCurrentIndex(3)
            elif peer_id == self._LAN_GROUP_DEVICE_ID:
                self._selected_peer = LanPeer(
                    device_id=self._LAN_GROUP_DEVICE_ID,
                    display_name="局域网群聊",
                    online=True,
                    transport="lan_group",
                )
                self.mode_tabs.setCurrentIndex(3)
            else:
                self._selected_peer = next(
                    (peer for peer in self._peers if peer.device_id == peer_id),
                    None,
                )
        label = self._selected_peer.display_name if self._selected_peer else "未选择设备"
        if self._selected_peer is not None and self._selected_peer.transport in {"lan_group", "alert_group"}:
            count = len(self._alert_group_peers()) if self._selected_peer.transport == "alert_group" else len(
                tuple(peer for peer in self._peers if peer.online)
            )
            unit = "人" if self._selected_peer.transport == "alert_group" else "台"
            self.recipient_label.setText(f"发送给：{label}（{count} {unit}在线）")
        else:
            self.recipient_label.setText(f"发送给：{label}" if self._selected_peer else label)
        self._refresh_chat_messages()
        self._refresh_alert_group_panel()
        self._refresh_send_button()

    def _remote_peer_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if self.device_tabs.currentIndex() != 1:
            return
        self._restore_default_status()
        self._selected_peer = None
        if current is not None:
            peer_id = current.data(Qt.ItemDataRole.UserRole)
            self._selected_peer = next((peer for peer in self._remote_peers if peer.device_id == peer_id), None)
        if self._selected_peer is not None and self.mode_tabs.currentIndex() == 3:
            self.mode_tabs.setCurrentIndex(0)
        label = self._selected_peer.display_name if self._selected_peer else "未选择伙伴"
        self.recipient_label.setText(f"发送给：{label}" if self._selected_peer else label)
        self._refresh_chat_messages()
        self._refresh_send_button()

    def _device_tab_changed(self, index: int) -> None:
        if index == 0:
            if self.peer_list.currentRow() < 0:
                self.peer_list.setCurrentRow(2 if self._peers else 1)
            self._peer_changed(self.peer_list.currentItem(), None)
        else:
            if self._remote_peers and self.remote_peer_list.currentRow() < 0:
                self.remote_peer_list.setCurrentRow(0)
            self._remote_peer_changed(self.remote_peer_list.currentItem(), None)

    def _quick_selection_changed(self) -> None:
        self._restore_default_status()
        self._refresh_send_button()

    def _mode_changed(self, _index: int) -> None:
        self._restore_default_status()
        self._refresh_chat_messages()
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
            preview_path = self._preview_frame_path(effect)
            pixmap = QPixmap(str(preview_path)) if preview_path is not None else QPixmap()
            self.effect_preview.setPixmap(pixmap.scaled(150, 150, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            self.effect_preview.setText("")
        else:
            self.effect_preview.setPixmap(QPixmap())
            self.effect_preview.setText("已选择")
        duration = int(getattr(effect, "duration_ms", 0)) if effect is not None else 0
        self.effect_meta.setText(f"{self._selected_effect_id} · {duration / 1000:.1f} 秒\n只发送编号，不传输资源文件")
        self.preview_button.setEnabled(effect is not None and self._on_preview is not None)
        self._refresh_send_button()

    @classmethod
    def _preview_frame_path(cls, effect: object) -> Path | None:
        """从少量均匀采样帧中选出可见内容最多的一帧作为缩略图。

        不扫描整组动效，避免大动效在互动页中造成新的卡顿；首帧为空时，
        也能选到已经进入画面的代表帧。
        """
        frames = tuple(Path(path) for path in getattr(effect, "frames", ()) if path)
        if not frames:
            return None
        if len(frames) <= cls._PREVIEW_SAMPLE_COUNT:
            sample_indices = range(len(frames))
        else:
            last = len(frames) - 1
            sample_indices = sorted(
                {round(index * last / (cls._PREVIEW_SAMPLE_COUNT - 1)) for index in range(cls._PREVIEW_SAMPLE_COUNT)}
            )
        best_path: Path | None = None
        best_score = -1
        for index in sample_indices:
            path = frames[index]
            image = QImage(str(path)).convertToFormat(QImage.Format.Format_RGBA8888)
            if image.isNull():
                continue
            try:
                data = bytes(image.constBits())
            except (TypeError, ValueError):
                continue
            score = sum(1 for alpha in data[3::4] if alpha > 8)
            if score > best_score:
                best_score = score
                best_path = path
        return best_path or frames[0]

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
        self._restore_default_status()
        self._refresh_send_button()

    def _update_chat_count(self) -> None:
        length = len(self.chat_input.toPlainText())
        self.chat_count_label.setText(
            f"{length} / {MAX_CHAT_TEXT_LENGTH} · 记录仅在本次运行保留"
        )
        self._restore_default_status()
        self._refresh_send_button()

    def _refresh_chat_messages(self) -> None:
        if not hasattr(self, "chat_list"):
            return
        self.chat_list.clear()
        peer = self._selected_peer
        if peer is None:
            empty = QListWidgetItem("选择一台附近设备开始聊天", self.chat_list)
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            empty.setForeground(QColor("#8f8b86"))
            return
        if peer.transport not in {"lan", "lan_group", "alert_group"}:
            empty = QListWidgetItem("图片聊天暂仅支持局域网附近设备", self.chat_list)
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            empty.setForeground(QColor("#8f8b86"))
            return
        if peer.transport == "lan_group":
            messages = [item for item in self._chat_messages if item.scope is ChatScope.LAN_ROOM]
        elif peer.transport == "alert_group":
            messages = [item for item in self._chat_messages if item.scope is ChatScope.ALERT_GROUP]
        else:
            messages = [
                item
                for item in self._chat_messages
                if item.scope is ChatScope.DIRECT
                and item.peer_device_id(self._settings.device_id) == peer.device_id
            ]
        if not messages:
            text = (
                "还没有群聊消息，发个表情和大家打招呼吧"
                if peer.transport in {"lan_group", "alert_group"}
                else "还没有消息，发个表情打招呼吧"
            )
            empty = QListWidgetItem(text, self.chat_list)
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            empty.setForeground(QColor("#8f8b86"))
            return
        for message in messages:
            local = message.sender_device_id == self._settings.device_id
            sender = "我" if local else (message.sender_name or peer.display_name)
            stamp = datetime.fromtimestamp(message.created_at).strftime("%H:%M")
            if message.kind is ChatMessageKind.IMAGE:
                item = QListWidgetItem(
                    f"{sender} · {stamp}\n🖼 {message.image_name or '图片'}",
                    self.chat_list,
                )
                pixmap = QPixmap()
                if message.image_data and pixmap.loadFromData(message.image_data):
                    item.setIcon(
                        QIcon(
                            pixmap.scaled(
                                128,
                                96,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation,
                            )
                        )
                    )
                    item.setSizeHint(QSize(0, 112))
            else:
                item = QListWidgetItem(
                    f"{sender} · {stamp}\n{message.text or ''}",
                    self.chat_list,
                )
            item.setData(Qt.ItemDataRole.UserRole, message.message_id)
            if local:
                item.setForeground(QColor("#a85d3e"))
        self.chat_list.scrollToBottom()

    def _refresh_send_button(self) -> None:
        if self._pending_send_draft is not None:
            self.send_button.setText("发送中…")
            self.send_button.setEnabled(False)
            return
        self.send_button.setEnabled(True)
        if (
            self._selected_peer is not None
            and self._selected_peer.transport in {"lan_group", "alert_group"}
            and self.mode_tabs.currentIndex() != 3
        ):
            self.send_button.setText("群聊仅支持聊天")
            self.send_button.setEnabled(False)
            return
        if self.mode_tabs.currentIndex() == 0:
            self.send_button.setText("发送招呼" if self.greeting_button.isChecked() else "发送爱心")
            return
        if self.mode_tabs.currentIndex() == 1:
            self.send_button.setText("发送文字")
            return
        if self.mode_tabs.currentIndex() == 2:
            self.send_button.setText("发送动效")
            return
        local_peer = self._selected_peer is not None and (
            (self._selected_peer.transport == "lan" and self._selected_peer.online)
            or (
                self._selected_peer.transport == "lan_group"
                and any(peer.online for peer in self._peers)
            )
            or (
                self._selected_peer.transport == "alert_group"
                and self._settings.lan_alert_group_joined
                and bool(self._alert_group_peers())
            )
        )
        self.send_button.setText("发送消息")
        self.send_button.setEnabled(local_peer and bool(self.chat_input.toPlainText().strip()))
        self.chat_input.setEnabled(local_peer)
        self.chat_image_button.setEnabled(local_peer)
        for button in self.emoji_buttons:
            button.setEnabled(local_peer)

    def interaction_draft(self) -> InteractionDraft | None:
        if self._selected_peer is None or self._selected_peer.transport == "lan_group":
            return None
        try:
            if self.mode_tabs.currentIndex() == 0:
                kind = InteractionKind.GREETING if self.greeting_button.isChecked() else InteractionKind.HEART
                return InteractionDraft.quick(self._selected_peer.device_id, kind)
            if self.mode_tabs.currentIndex() == 1:
                return InteractionDraft.text_message(self._selected_peer.device_id, self.text_input.toPlainText())
            if self.mode_tabs.currentIndex() == 2 and self._selected_effect_id:
                return InteractionDraft.effect(self._selected_peer.device_id, self._selected_effect_id)
        except ValueError as error:
            self.status_label.setText(str(error))
        return None

    def _send_current(self) -> None:
        if self._pending_send_draft is not None:
            return
        if self.mode_tabs.currentIndex() == 3:
            self._send_chat_text()
            return
        draft = self.interaction_draft()
        if draft is None:
            self._show_feedback("请先选择设备和有效内容", timeout_ms=4_000)
            return
        sender = self._on_remote_send if self._selected_peer.transport == "remote" else self._on_send
        if sender is None:
            self._show_feedback("发送接口尚未启用，当前仅完成本地预览", timeout_ms=4_000)
            return
        is_remote_async = self._selected_peer.transport == "remote" and self._remote_send_async
        if is_remote_async:
            self._pending_send_draft = draft
            self._refresh_send_button()
            self._show_feedback("正在发送…")
        try:
            sent = sender(draft)
        except Exception as error:  # noqa: BLE001 - UI 必须把网络层错误转为可见状态。
            if is_remote_async:
                self._pending_send_draft = None
                self._refresh_send_button()
            self._show_feedback(f"发送失败：{error}", timeout_ms=self._failure_feedback_timeout_ms)
            return
        if is_remote_async:
            if sent is False:
                self._pending_send_draft = None
                self._refresh_send_button()
                self._show_feedback("发送失败，请稍后重试", timeout_ms=self._failure_feedback_timeout_ms)
            return
        if sent is True:
            self._show_feedback("已发送 ✓", timeout_ms=self._success_feedback_timeout_ms)
        else:
            self._show_feedback("发送失败，请稍后重试", timeout_ms=self._failure_feedback_timeout_ms)

    def _send_chat_text(self) -> None:
        if self._selected_peer is None or self._selected_peer.transport not in {"lan", "lan_group", "alert_group"}:
            self._show_feedback("请先选择一台附近设备", timeout_ms=self._failure_feedback_timeout_ms)
            return
        try:
            if self._selected_peer.transport == "lan_group":
                draft = ChatDraft.group_text_message(self.chat_input.toPlainText())
            elif self._selected_peer.transport == "alert_group":
                draft = ChatDraft.alert_group_text_message(self.chat_input.toPlainText())
            else:
                draft = ChatDraft.text_message(
                    self._selected_peer.device_id,
                    self.chat_input.toPlainText(),
                )
        except ValueError as error:
            self._show_feedback(str(error), timeout_ms=self._failure_feedback_timeout_ms)
            return
        if self._send_chat_draft(draft):
            self.chat_input.clear()

    def _send_chat_emoji(self, emoji: str) -> None:
        if self._selected_peer is None or self._selected_peer.transport not in {"lan", "lan_group", "alert_group"}:
            self._show_feedback("请先选择一台附近设备", timeout_ms=self._failure_feedback_timeout_ms)
            return
        try:
            if self._selected_peer.transport == "lan_group":
                draft = ChatDraft.group_emoji(emoji)
            elif self._selected_peer.transport == "alert_group":
                draft = ChatDraft.alert_group_emoji(emoji)
            else:
                draft = ChatDraft.emoji(self._selected_peer.device_id, emoji)
        except ValueError as error:
            self._show_feedback(str(error), timeout_ms=self._failure_feedback_timeout_ms)
            return
        self._send_chat_draft(draft)

    def _choose_chat_image(self) -> None:
        if self._selected_peer is None or self._selected_peer.transport not in {"lan", "lan_group", "alert_group"}:
            self._show_feedback("请先选择一台附近设备", timeout_ms=self._failure_feedback_timeout_ms)
            return
        filename, _filter = QFileDialog.getOpenFileName(
            self,
            "选择要发送的图片",
            "",
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp *.gif)",
        )
        if not filename:
            return
        self._show_feedback("正在压缩图片…")
        try:
            data, safe_name = prepare_chat_image(Path(filename))
            if self._selected_peer.transport == "lan_group":
                draft = ChatDraft.group_image(data, safe_name)
            elif self._selected_peer.transport == "alert_group":
                draft = ChatDraft.alert_group_image(data, safe_name)
            else:
                draft = ChatDraft.image(self._selected_peer.device_id, data, safe_name)
        except (LanChatImageError, OSError, ValueError) as error:
            self._show_feedback(str(error), timeout_ms=self._failure_feedback_timeout_ms)
            return
        self._send_chat_draft(draft)

    def _send_chat_draft(self, draft: ChatDraft) -> bool:
        if self._on_chat_send is None:
            self._show_feedback("局域网聊天接口尚未启用", timeout_ms=self._failure_feedback_timeout_ms)
            return False
        try:
            sent = self._on_chat_send(draft)
        except Exception as error:  # noqa: BLE001 - UI must surface network errors.
            self._show_feedback(f"发送失败：{error}", timeout_ms=self._failure_feedback_timeout_ms)
            return False
        if sent is False:
            self._show_feedback("发送失败，请确认对方仍在线", timeout_ms=self._failure_feedback_timeout_ms)
            return False
        self._show_feedback("正在发送…", timeout_ms=self._success_feedback_timeout_ms)
        return True

    def _show_feedback(self, message: str, *, timeout_ms: int = 0) -> None:
        self._status_reset_timer.stop()
        self.status_label.setText(str(message))
        if timeout_ms > 0:
            self._status_reset_timer.start(timeout_ms)

    def _restore_default_status(self) -> None:
        self._status_reset_timer.stop()
        if self._pending_send_draft is None:
            if hasattr(self, "mode_tabs") and self.mode_tabs.currentIndex() == 3:
                if (
                    self._selected_peer is not None
                    and self._selected_peer.transport in {"lan_group", "alert_group"}
                ):
                    count = (
                        len(self._alert_group_peers())
                        if self._selected_peer.transport == "alert_group"
                        else len(tuple(peer for peer in self._peers if peer.online))
                    )
                    self.status_label.setText(f"群聊将发送给当前 {count} 人；记录仅在本次运行保留")
                else:
                    self.status_label.setText("聊天记录仅保留在本次 PetNest 运行中")
            else:
                self.status_label.setText(self._DEFAULT_STATUS)

    def _peer_row(self, device_id: str | None) -> int:
        for row in range(self.peer_list.count()):
            if self.peer_list.item(row).data(Qt.ItemDataRole.UserRole) == device_id:
                return row
        return -1

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
    QCheckBox { color: #4b4641; spacing: 7px; padding: 2px 0; background: transparent; }
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
