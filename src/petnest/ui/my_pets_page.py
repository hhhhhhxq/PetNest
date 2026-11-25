"""One library for frame pets and interactive companions."""

from __future__ import annotations

import sys
from time import monotonic

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from petnest.core.keyboard_cat import (
    CAT_RENDERER,
    COATS,
    KEYBOARDS,
    CatState,
    cat_preferences,
)
from petnest.platforms.physical_keys import MAC_KEYS
from petnest.core.cat_appearance import switch_appearance
from petnest.ui.exchange_page import ExchangePage
from petnest.ui.keyboard_cat_renderer import render_cat
from petnest.ui.pet_appearance_controls import (
    LIBRARY_STYLE,
    AppearanceChoices,
    PetPreview,
    PetToggle,
)


class MyPetsPage(ExchangePage):
    edit_actions = Signal()

    def __init__(
        self,
        packages,
        current_id,
        *,
        preferences=None,
        save_preferences=None,
        use_pet=None,
        input_status=None,
        request_permission=None,
        retry_input=None,
        locate_input_app=None,
        parent=None,
    ):
        super().__init__(parent)
        self._preferences = preferences or (lambda identifier: {})
        self._save_preferences = save_preferences or (lambda identifier, value: None)
        self._use_pet = use_pet or (lambda identifier: False)
        self._input_status = input_status or (lambda: "已关闭")
        self._request_permission = request_permission or (lambda: None)
        self._retry_input = retry_input or (lambda: None)
        self._locate_input_app = locate_input_app or (lambda: None)
        self._loading = False
        self._preview_state = CatState()
        QApplication.instance().installEventFilter(self)
        self.setStyleSheet(LIBRARY_STYLE)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        self.pet_list = QListWidget(self)
        self.pet_list.setObjectName("petLibraryList")
        self.pet_list.setFixedWidth(180)
        root.addWidget(self.pet_list)
        self.detail_scroll = QScrollArea(self)
        self.detail_scroll.setObjectName("petDetailScroll")
        self.detail_scroll.setWidgetResizable(True)
        self.detail_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        root.addWidget(self.detail_scroll, 1)
        self.detail = QWidget(self)
        self.detail.setObjectName("petDetailBody")
        layout = QVBoxLayout(self.detail)
        layout.setContentsMargins(0, 0, 8, 4)
        layout.setSpacing(12)
        self.detail_scroll.setWidget(self.detail)
        heading = QHBoxLayout()
        self.title = QLabel(self)
        self.title.setObjectName("petDetailTitle")
        heading.addWidget(self.title)
        heading.addStretch()
        self.active_badge = QLabel(self)
        self.active_badge.setObjectName("petStatusBadge")
        heading.addWidget(self.active_badge)
        layout.addLayout(heading)

        hero = QHBoxLayout()
        hero.setSpacing(12)
        self.preview_card, stage = self._card("petPreviewCard")
        self.preview = PetPreview(self)
        self.preview.setFixedHeight(260)
        stage.addWidget(self.preview)
        self.preview_hint = self._hint("动动鼠标，摸摸它的头，也可以试着打字")
        self.preview_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        stage.addWidget(self.preview_hint)
        stage.addStretch()
        scale_row = QHBoxLayout()
        scale_row.addWidget(self._label("桌面大小"))
        scale_row.addStretch()
        self.scale = QDoubleSpinBox(self)
        self.scale.setSingleStep(0.1)
        self.scale.setDecimals(1)
        self.scale.setSuffix(" 倍")
        self.scale.setFixedWidth(90)
        scale_row.addWidget(self.scale)
        stage.addLayout(scale_row)
        hero.addWidget(self.preview_card, 4)
        self.outfit, choices = self._card()
        choices.addWidget(self._label("猫咪花纹"))
        self.coat = AppearanceChoices(COATS, icon_size=QSize(60, 60), columns=3, parent=self)
        choices.addWidget(self.coat)
        choices.addWidget(self._label("小键盘配色"))
        self.keyboard = AppearanceChoices(
            KEYBOARDS, icon_size=QSize(90, 34), parent=self
        )
        choices.addWidget(self.keyboard)
        self.customize_button = QPushButton("自定义配色与白斑…", self)
        self.customize_button.clicked.connect(self._customize)
        choices.addWidget(self.customize_button)
        self.appearance_summary = self._hint("花纹与颜色可以自由搭配")
        choices.addWidget(self.appearance_summary)
        choices.addStretch()
        hero.addWidget(self.outfit, 5)
        layout.addLayout(hero)
        self.edit_button = QPushButton("管理这只宠物的动作", self)
        self.edit_button.clicked.connect(self.edit_actions.emit)
        layout.addWidget(self.edit_button)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        self.interaction_card, interactions = self._card()
        interactions.addWidget(self._label("一起互动"))
        self.look = PetToggle("看向鼠标", self)
        self.petting = PetToggle("摸头时回应我", self)
        self.follow = PetToggle("整只宠物跟着鼠标走", self)
        self.follow.setToolTip(
            "开启后宠物会移动位置；只想让它转头时，打开「看向鼠标」即可。"
        )
        for check in (self.look, self.petting, self.follow):
            interactions.addWidget(check)
        interactions.addWidget(self._hint("这些互动不需要键盘授权"))
        interactions.addStretch()
        bottom.addWidget(self.interaction_card, 4)
        self.input_card, typing = self._card()
        self.keys = PetToggle("打字时陪我敲键盘", self)
        typing.addWidget(self.keys)
        self.permission_status = QLabel(self)
        self.permission_status.setObjectName("petInputStatus")
        self.permission_status.setWordWrap(True)
        typing.addWidget(self.permission_status)
        self.input_explanation = self._hint("")
        typing.addWidget(self.input_explanation)
        permission_row = QHBoxLayout()
        permission_row.setSpacing(6)
        self.permission_button = QPushButton("去系统设置授权", self)
        self.retry_button = QPushButton("我已授权，重新检查", self)
        self.permission_button.clicked.connect(self._permission)
        self.retry_button.clicked.connect(self._retry)
        permission_row.addWidget(self.permission_button)
        permission_row.addWidget(self.retry_button)
        permission_row.addStretch()
        typing.addLayout(permission_row)
        self.locate_button = QPushButton("列表里找不到 PetNest？", self)
        self.locate_button.setToolTip("在 Finder 中选中当前应用，可拖入输入监控列表。")
        self.locate_button.clicked.connect(self._locate_input_app)
        typing.addWidget(self.locate_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.privacy = self._hint("只响应按键动作，不记录或上传输入内容")
        typing.addWidget(self.privacy)
        typing.addStretch()
        bottom.addWidget(self.input_card, 5)
        layout.addLayout(bottom)
        layout.addStretch()
        self._thumbnail_key = None
        for combo in (self.coat, self.keyboard):
            combo.currentIndexChanged.connect(self._changed)
        for check in (self.look, self.petting, self.follow, self.keys):
            check.toggled.connect(self._changed)
        self.scale.valueChanged.connect(self._changed)
        self.pet_list.currentRowChanged.connect(self._selected)
        self.preview_timer = QTimer(self)
        self.preview_timer.setInterval(50)
        self.preview_timer.timeout.connect(self._draw_preview)
        self.permission_timer = QTimer(self)
        self.permission_timer.setInterval(2000)
        self.permission_timer.timeout.connect(self._sync_status)
        self.refresh_packages(packages, current_id)

    def _label(self, text):
        label = QLabel(text, self)
        label.setObjectName("petSectionTitle")
        return label

    def _hint(self, text):
        label = QLabel(text, self)
        label.setObjectName("petHint")
        label.setWordWrap(True)
        return label

    def _card(self, name="petLibraryCard"):
        card = QFrame(self)
        card.setObjectName(name)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        return card, layout

    def _update_thumbnails(self):
        coat, keyboard = self.coat.currentData(), self.keyboard.currentData()
        if (coat, keyboard) == self._thumbnail_key:
            return
        self._thumbnail_key = (coat, keyboard)
        self.coat.set_images(
            {
                key: render_cat(
                    CatState(), {"coat": key, "keyboard": keyboard}, dt=0
                ).copy(130, 70, 110, 170)
                for key in COATS
            }
        )
        self.keyboard.set_images(
            {
                key: render_cat(CatState(), {"coat": coat, "keyboard": key}, dt=0).copy(
                    100, 236, 190, 62
                )
                for key in KEYBOARDS
            }
        )

    def selected_package(self):
        i = self.pet_list.currentRow()
        return self._packages[i] if 0 <= i < len(self._packages) else None

    def refresh_packages(self, packages, current_id):
        selected = self.selected_package() if hasattr(self, "_packages") else None
        wanted = selected.identifier if selected else current_id
        self._packages = tuple(packages)
        self._current_id = current_id
        self.pet_list.blockSignals(True)
        self.pet_list.clear()
        for p in packages:
            badge = "可换装 · 键鼠互动" if p.renderer == CAT_RENDERER else "动作陪伴"
            self.pet_list.addItem(
                f"{p.name}{' · 正在陪伴' if p.identifier == current_id else ''}\n{badge}"
            )
        index = next((i for i, p in enumerate(packages) if p.identifier == wanted), 0)
        self.pet_list.setCurrentRow(index)
        self.pet_list.blockSignals(False)
        self._selected()

    def _selected(self, *_):
        p = self.selected_package()
        if p is None:
            self.set_footer(
                status="暂无宠物", primary_text="让它陪我", primary_enabled=False
            )
            return
        self._loading = True
        raw = self._preferences(p.identifier)
        options = cat_preferences(raw)
        self.title.setText(p.name)
        self.active_badge.setText(
            "正在陪伴" if p.identifier == self._current_id else "预览中"
        )
        self.preview_hint.setText(
            "动动鼠标，摸摸它的头，也可以试着打字"
            if p.renderer == CAT_RENDERER
            else "你的桌面小伙伴"
        )
        self.outfit.setVisible(p.renderer == CAT_RENDERER)
        self.edit_button.setVisible(p.renderer != CAT_RENDERER)
        for check in (self.look, self.petting):
            check.setVisible(p.renderer == CAT_RENDERER)
        self.coat.setCurrentIndex(self.coat.findData(options["coat"]))
        self.keyboard.setCurrentIndex(self.keyboard.findData(options["keyboard"]))
        self.look.setChecked(options["look"])
        self.petting.setChecked(options["petting"])
        self.follow.setChecked(bool(raw.get("follow", False)))
        self.keys.setChecked(bool(raw.get("keys", False)))
        self.scale.setRange(p.display.min_scale, p.display.max_scale)
        self.scale.setValue(raw.get("scale", p.display.default_scale))
        self.keys.setText(
            "打字时陪我敲键盘" if p.renderer == CAT_RENDERER else "打字时播放工作动作"
        )
        self._loading = False
        self._preview_state = CatState()
        if p.renderer == CAT_RENDERER:
            self._update_thumbnails()
            self._appearance_summary(options)
        self._draw_preview()
        self._sync_status()
        active = p.identifier == self._current_id
        self.set_footer(
            status="当前正在使用 · 设置自动保存"
            if active
            else "查看中；点击后替换桌面上的宠物",
            primary_text="正在陪伴" if active else "让它陪我",
            primary_enabled=not active,
        )

    def _changed(self, *_):
        if self._loading:
            return
        p = self.selected_package()
        if p is None:
            return
        value = dict(self._preferences(p.identifier))
        value = switch_appearance(value, coat=self.coat.currentData(), keyboard=self.keyboard.currentData())
        value.update(
            coat=self.coat.currentData(),
            keyboard=self.keyboard.currentData(),
            look=self.look.isChecked(),
            petting=self.petting.isChecked(),
            follow=self.follow.isChecked(),
            keys=self.keys.isChecked(),
            scale=self.scale.value(),
        )
        self._save_preferences(p.identifier, value)
        if p.renderer == CAT_RENDERER:
            self._update_thumbnails()
            self._appearance_summary(cat_preferences(value))
        self._draw_preview()
        self._sync_status()

    def _appearance_summary(self, options):
        marks = options["white_markings"]
        details = []
        if options["colors"]:
            details.append("自定义颜色")
        if marks["face"] != "none":
            details.append("白脸")
        if marks["chest"]:
            details.append("白胸")
        if marks["paws"]:
            details.append("白袜")
        self.appearance_summary.setText(" · ".join(details) or "花纹与颜色可以自由搭配")

    def _customize(self):
        from petnest.ui.cat_appearance_dialog import CatAppearanceDialog
        p = self.selected_package()
        if p is None or p.renderer != CAT_RENDERER:
            return
        dialog = CatAppearanceDialog(self._preferences(p.identifier), self)
        self._appearance_dialog = dialog
        if dialog.exec() == dialog.DialogCode.Accepted:
            # Keep current scale, input and movement settings; this dialog owns appearance only.
            value = dict(self._preferences(p.identifier))
            result = dialog.result_preferences()
            for key in ("coat", "keyboard", "colors", "white_markings", "saved_palettes", "appearance_memory"):
                value[key] = result[key]
            self._save_preferences(p.identifier, value)
            self._selected()
        self._appearance_dialog = None
        dialog.deleteLater()

    def _sync_status(self):
        p = self.selected_package()
        active = p is not None and p.identifier == self._current_id
        enabled = self.keys.isChecked() and active
        raw = self._input_status() if enabled else ""
        connected = enabled and raw == "监听正常"
        needs_permission = (
            enabled
            and sys.platform == "darwin"
            and ("权限" in raw or "允许" in raw or "授权" in raw)
        )
        self.input_explanation.setToolTip(raw)
        if not active:
            title, explanation = (
                "使用这只宠物后生效",
                "可以先挑选外观，再点击下方「让它陪我」。",
            )
        elif not self.keys.isChecked():
            title, explanation = (
                "键盘陪伴已关闭",
                "开启上方开关，让它在你打字时一起动起来。",
            )
        elif connected:
            title, explanation = "● 已连接", "在其他应用中打字，它也会同步回应。"
        elif needs_permission:
            title, explanation = (
                "还差一步：允许键盘互动",
                "在系统「输入监控」中开启 PetNest。已开启却无效？移除旧项，再重新添加当前应用。",
            )
        else:
            title, explanation = (
                "键盘互动暂不可用",
                "可以重新检查连接；移动鼠标和摸头仍然可用。",
            )
        self.permission_status.setText(title)
        self.permission_status.setStyleSheet(
            "color: #4e8063;" if connected else "color: #8a6c50;"
        )
        self.input_explanation.setText(explanation)
        self.permission_button.setVisible(needs_permission)
        self.retry_button.setVisible(enabled and not connected)
        self.locate_button.setVisible(needs_permission)

    def _permission(self):
        self._request_permission()
        self._sync_status()

    def _retry(self):
        self._retry_input()
        self._sync_status()

    def _draw_preview(self):
        p = self.selected_package()
        if p is None:
            return
        if p.renderer == CAT_RENDERER:
            cursor = self.preview.logical_cursor()
            if cursor != getattr(self, "_preview_cursor", None):
                self._preview_state.last_activity = monotonic()
            self._preview_cursor = cursor
            image = render_cat(
                self._preview_state,
                self._preferences(p.identifier),
                cursor=cursor,
                dt=0.05,
            )
            pixmap = QPixmap.fromImage(image)
        else:
            frames = p.animations["idle"].frames
            pixmap = QPixmap(str(frames[0])) if frames else QPixmap()
        self.preview.set_frame(pixmap, cat=p.renderer == CAT_RENDERER)

    def cat_key_event(self, key, down):
        dialog = getattr(self, "_appearance_dialog", None)
        if dialog is not None and dialog.isVisible():
            dialog.state.key_event(key, down)
        p = self.selected_package()
        if self.isVisible() and p is not None and p.renderer == CAT_RENDERER:
            self._preview_state.key_event(key, down)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.ApplicationDeactivate:
            self._preview_state.reset()
            dialog = getattr(self, "_appearance_dialog", None)
            if dialog is not None:
                dialog.state.reset()
        # A local preview works before global input permission is granted.
        if (
            sys.platform == "darwin"
            and self.isVisible()
            and isinstance(watched, QWidget)
            and (watched is self or self.isAncestorOf(watched))
            and self._input_status() != "监听正常"
            and event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease)
        ):
            key = MAC_KEYS.get(event.nativeVirtualKey())
            if key is not None:
                self.cat_key_event(key, event.type() == QEvent.Type.KeyPress)
        return super().eventFilter(watched, event)

    def trigger_primary(self):
        p = self.selected_package()
        if p is not None and self._use_pet(p.identifier):
            self.refresh_packages(self._packages, p.identifier)
        else:
            self.set_footer(
                status="暂时无法切换，请结束当前提醒后重试", primary_text="重试"
            )

    def activate(self):
        self.preview_timer.start()
        self.permission_timer.start()
        self._sync_status()

    def deactivate(self):
        self.preview_timer.stop()
        self.permission_timer.stop()
        self._preview_state.reset()

    def hideEvent(self, event):
        self.preview_timer.stop()
        self.permission_timer.stop()
        self._preview_state.reset()
        super().hideEvent(event)

    def showEvent(self, event):
        self.preview_timer.start()
        self.permission_timer.start()
        super().showEvent(event)
