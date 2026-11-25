"""Draft-based appearance editor with the same animated renderer as the desktop pet."""

from copy import deepcopy

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPixmap, QRegularExpressionValidator
from PySide6.QtCore import QRegularExpression
from PySide6.QtWidgets import (
    QComboBox, QColorDialog, QDialog, QDialogButtonBox, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSlider,
    QTabWidget, QVBoxLayout, QWidget, QSizePolicy,
)

from petnest.core.cat_appearance import (
    COATS, FACE_MARKINGS, KEYBOARDS, PRESETS, apply_preset,
    resolved_colors, saved_palettes, remember_appearance, switch_appearance,
)
from petnest.core.keyboard_cat import CatState, cat_preferences
from petnest.ui.keyboard_cat_renderer import render_cat
from petnest.ui.pet_appearance_controls import AppearanceChoices, LIBRARY_STYLE, PetPreview
from petnest.ui.theme import dialog_stylesheet


class ColorField(QWidget):
    changed = Signal(str)

    def __init__(self, label, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel(label, self)
        row.addWidget(self.label, 1)
        self.swatch = QPushButton(self)
        self.swatch.setFixedSize(35, 32)
        self.swatch.setAccessibleName(f"选择{label}")
        self.swatch.clicked.connect(self._choose)
        row.addWidget(self.swatch)
        self.hex = QLineEdit(self)
        self.hex.setFixedWidth(100)
        self.hex.setAccessibleName(f"{label} HEX 色值")
        self.hex.setValidator(QRegularExpressionValidator(QRegularExpression("#[0-9a-fA-F]{6}"), self))
        self.hex.textEdited.connect(self._typed)
        self.hex.editingFinished.connect(lambda: self.set_color(self.color))
        row.addWidget(self.hex)
        self.color = "#000000"
        self.set_color(self.color)

    def set_color(self, color):
        self.color = color.upper()
        self.hex.setText(self.color)
        self.swatch.setStyleSheet(f"background: {self.color}; border: 1px solid #d8cbbf; border-radius: 8px;")

    def _typed(self, text):
        if self.hex.hasAcceptableInput():
            self.set_color(text)
            self.changed.emit(self.color)

    def _choose(self):
        # Native picker is modal; the draft changes only when a color is accepted.
        color = QColorDialog.getColor(QColor(self.color), self, self.label.text())
        if color.isValid():
            self.set_color(color.name())
            self.changed.emit(self.color)


class CatAppearanceDialog(QDialog):
    def __init__(self, preferences, parent=None):
        super().__init__(parent)
        self.setWindowTitle("自定义配色 · 可撤销换装")
        self.resize(940, 760)
        self.setMinimumSize(800, 620)
        self.setStyleSheet(dialog_stylesheet() + LIBRARY_STYLE + """
            QDialog { background: #fcf8f3; color: #51463e; }
            QWidget#catEditorBody, QWidget#catEditorTab { background: #fcf8f3; }
            QLineEdit, QComboBox { background: #fffdfa; border: 1px solid #e5d9ce; border-radius: 7px; padding: 6px; min-height: 20px; }
            QPushButton { padding: 7px 12px; border: 1px solid #e5d9ce; border-radius: 8px; background: #fffdfa; color: #51463e; }
            QPushButton:hover { background: #f7eee5; }
            QPushButton:default { background: #ad6949; color: white; }
            QTabWidget::pane { border: none; }
            QTabBar::tab { padding: 10px 22px; background: #f3e9df; border: none; color: #8b7b70; }
            QTabBar::tab:selected { background: #fffdfa; color: #a76747; }
            QSlider::groove:horizontal { height: 5px; background: #e5d9ce; border-radius: 2px; }
            QSlider::sub-page:horizontal { background: #cf946f; border-radius: 2px; }
            QSlider::handle:horizontal { width: 14px; margin: -5px 0; background: #fffdfa; border: 1px solid #b78565; border-radius: 7px; }
        """)
        self.original = deepcopy(preferences)
        self.draft = {**deepcopy(preferences), **cat_preferences(preferences)}
        self.saved = saved_palettes(preferences.get("saved_palettes"))
        self.state = CatState()
        self._syncing = False
        self._appearance_undo = []
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        title = QLabel("自定义配色", self)
        title.setObjectName("petDetailTitle")
        root.addWidget(title)
        root.addWidget(QLabel("切换花纹会记住各自配色；点击「保存并使用」后，下次打开也能找回", self))
        content = QHBoxLayout()
        content.setSpacing(20)
        root.addLayout(content, 1)
        stage = QFrame(self)
        stage.setObjectName("petPreviewCard")
        stage.setFixedWidth(300)
        left = QVBoxLayout(stage)
        self.preview_label = QLabel(self)
        self.preview_label.setObjectName("petSectionTitle")
        left.addWidget(self.preview_label)
        self.preview = PetPreview(stage)
        self.preview.setMinimumHeight(140)
        self.preview.setMaximumHeight(290)
        self.preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        left.addWidget(self.preview, 1)
        self.compare = QPushButton("按住对比原配色", self)
        self.compare.setCheckable(False)
        self.compare.pressed.connect(lambda: self._draw(True))
        self.compare.released.connect(self._draw)
        left.addWidget(self.compare)
        self.undo_button = QPushButton("撤销上次换装", self)
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self._undo_appearance)
        left.addWidget(self.undo_button)
        hint = QLabel("移动鼠标看看它转头\n保存后，桌面上的它也会换上新配色", self)
        hint.setObjectName("petHint")
        hint.setWordWrap(True)
        left.addWidget(hint)
        self.reset_button = QPushButton("恢复本次修改前的外观", self)
        self.reset_button.clicked.connect(self._reset)
        left.addWidget(self.reset_button)
        content.addWidget(stage)
        scroll = QScrollArea(self)
        scroll.setObjectName("petDetailScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content.addWidget(scroll, 1)
        controls = QWidget(self)
        controls.setObjectName("catEditorBody")
        right = QVBoxLayout(controls)
        right.setContentsMargins(0, 0, 10, 0)
        right.setSpacing(12)
        scroll.setWidget(controls)
        self.tabs = QTabWidget(self)
        right.addWidget(self.tabs)
        cat_tab, keyboard_tab = QWidget(self), QWidget(self)
        cat_tab.setObjectName("catEditorTab")
        keyboard_tab.setObjectName("catEditorTab")
        cat_layout, keyboard_layout = QVBoxLayout(cat_tab), QVBoxLayout(keyboard_tab)
        cat_layout.setContentsMargins(0, 12, 0, 0)
        keyboard_layout.setContentsMargins(0, 12, 0, 0)
        cat_layout.setSpacing(12)
        keyboard_layout.setSpacing(12)
        self.tabs.addTab(cat_tab, "猫咪")
        self.tabs.addTab(keyboard_tab, "小键盘")
        self.coat = AppearanceChoices(COATS, icon_size=QSize(70, 64), columns=3, parent=self)
        cat_layout.addWidget(self.coat)
        self.coat.currentIndexChanged.connect(self._coat_changed)
        self.fields = {}
        for key, label in (("fur", "底色"), ("point", "花纹色"), ("secondary", "花色二"), ("eyes", "眼睛")):
            field = ColorField(label, self)
            field.changed.connect(lambda color, k=key: self.set_color(k, color))
            self.fields[key] = field
            cat_layout.addWidget(field)
        white_title = QLabel("叠加白斑", self)
        white_title.setObjectName("petSectionTitle")
        cat_layout.addWidget(white_title)
        face_row = QHBoxLayout()
        face_row.addWidget(QLabel("脸部", self))
        self.face = QComboBox(self)
        for key, label in FACE_MARKINGS.items():
            self.face.addItem(label, key)
        face_row.addWidget(self.face, 1)
        cat_layout.addLayout(face_row)
        self.face.currentIndexChanged.connect(self._markings_changed)
        self.markings = {}
        for key, label in (("amount", "白脸宽度"), ("chest", "白胸面积"), ("paws", "白袜高度")):
            row = QHBoxLayout()
            row.addWidget(QLabel(label, self))
            slider = QSlider(Qt.Orientation.Horizontal, self)
            slider.setRange(0, 100)
            slider.setAccessibleName(label)
            slider.setToolTip("拖到最左侧关闭" if key != "amount" else "调整脸部白斑宽度")
            value = QLabel(self)
            value.setFixedWidth(40)
            row.addWidget(slider, 1)
            row.addWidget(value)
            self.markings[key] = (slider, value)
            slider.valueChanged.connect(self._markings_changed)
            cat_layout.addLayout(row)
        self.keyboard = AppearanceChoices(KEYBOARDS, icon_size=QSize(76, 30), parent=self)
        keyboard_layout.addWidget(self.keyboard)
        self.keyboard.currentIndexChanged.connect(self._keyboard_changed)
        for key, label in (("case", "键盘外壳"), ("keys", "普通键帽"), ("accent", "点缀键帽")):
            field = ColorField(label, self)
            field.changed.connect(lambda color, k=key: self.set_color(k, color))
            self.fields[key] = field
            keyboard_layout.addWidget(field)
        keyboard_layout.addWidget(QLabel("鼠标会自动搭配同一套颜色", self))
        keyboard_layout.addStretch()
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("搭配灵感", self))
        self.presets = QComboBox(self)
        self.presets.addItem("选一套配色…", None)
        for name in PRESETS:
            self.presets.addItem(name, name)
        self.presets.activated.connect(self._preset_selected)
        preset_row.addWidget(self.presets, 1)
        right.addLayout(preset_row)
        saved_row = QHBoxLayout()
        saved_row.addWidget(QLabel("我的配色", self))
        self.saved_combo = QComboBox(self)
        self.saved_combo.activated.connect(self._load_saved)
        saved_row.addWidget(self.saved_combo, 1)
        self.delete_button = QPushButton("删除", self)
        self.delete_button.clicked.connect(self._delete_saved)
        saved_row.addWidget(self.delete_button)
        self.palette_name = QLineEdit(self)
        self.palette_name.setMaxLength(32)
        self.palette_name.setPlaceholderText("配色名称")
        self.palette_name.setMaximumWidth(180)
        self.save_palette_button = QPushButton("收藏配色", self)
        self.save_palette_button.clicked.connect(self._save_palette)
        saved_row.addWidget(self.palette_name, 1)
        saved_row.addWidget(self.save_palette_button)
        root.insertLayout(2, saved_row)
        self.message = QLabel("收藏与外观将在点击「保存并使用」后一起保存", self)
        self.message.setObjectName("petHint")
        self.message.setWordWrap(True)
        right.addWidget(self.message)
        right.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save, self)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存并使用")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.coat.set_images({key: render_cat(CatState(), {"coat": key}, dt=0).copy(130, 70, 110, 170) for key in COATS})
        self.keyboard.set_images({key: render_cat(CatState(), {"keyboard": key}, dt=0).copy(100, 236, 190, 62) for key in KEYBOARDS})
        self._refresh_saved()
        self._sync()
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._draw)
        self.timer.start()

    def result_preferences(self):
        return {**remember_appearance(self.draft), "saved_palettes": deepcopy(self.saved)}

    def _checkpoint(self):
        self._appearance_undo.append((deepcopy(self.draft), self.palette_name.text()))
        self._appearance_undo = self._appearance_undo[-30:]
        self.undo_button.setEnabled(True)

    def _undo_appearance(self):
        if self._appearance_undo:
            self.draft, name = self._appearance_undo.pop()
            self.palette_name.setText(name)
            self.undo_button.setEnabled(bool(self._appearance_undo))
            self.presets.setCurrentIndex(0)
            self.message.setText("已恢复上次换装前的配色")
            self._sync()

    def _sync(self):
        self._syncing = True
        self.coat.setCurrentIndex(self.coat.findData(self.draft["coat"]))
        self.keyboard.setCurrentIndex(self.keyboard.findData(self.draft["keyboard"]))
        for key, color in resolved_colors(self.draft).items():
            self.fields[key].set_color(color)
        self.fields["point"].setVisible(self.draft["coat"] != "black")
        self.fields["point"].label.setText({"siamese": "重点色", "shaded": "渐层色", "tabby": "条纹色", "tortie": "花斑色", "calico": "花色一"}.get(self.draft["coat"], "花纹色"))
        self.fields["secondary"].setVisible(self.draft["coat"] == "calico")
        marks = self.draft["white_markings"]
        self.face.setCurrentIndex(self.face.findData(marks["face"]))
        for key, (slider, value) in self.markings.items():
            slider.setValue(round(marks[key] * 100))
            value.setText(f"{slider.value()}%" if slider.value() or key == "amount" else "无")
        self.markings["amount"][0].setEnabled(marks["face"] != "none")
        self.preview_label.setText(f"实时预览 · {COATS[self.draft['coat']]}")
        self._syncing = False
        self._draw()

    def set_color(self, key, color):
        self.draft["colors"][key] = color
        self._draw()

    def _coat_changed(self, *_):
        if self._syncing:
            return
        self._checkpoint()
        self.draft = switch_appearance(self.draft, coat=self.coat.currentData())
        self._sync()

    def _keyboard_changed(self, *_):
        if self._syncing:
            return
        self._checkpoint()
        self.draft = switch_appearance(self.draft, keyboard=self.keyboard.currentData())
        self._sync()

    def _markings_changed(self, *_):
        if self._syncing:
            return
        self.draft["white_markings"] = {"face": self.face.currentData(), **{k: s.value()/100 for k, (s, _) in self.markings.items()}}
        self._sync()

    def _preset_selected(self, index):
        name = self.presets.itemData(index)
        if name:
            self._checkpoint()
            self.draft = apply_preset(remember_appearance(self.draft), name)
            self.palette_name.setText(name)
            self._sync()

    def _refresh_saved(self):
        self.saved_combo.clear()
        self.saved_combo.addItem("选择已收藏的配色…", None)
        for index, entry in enumerate(self.saved):
            self.saved_combo.addItem(entry["name"], index)

    def _save_palette(self):
        name = self.palette_name.text().strip()
        if not name:
            self.message.setText("先给这套配色起个名字")
            self.palette_name.setFocus()
            return
        matching = next((i for i, entry in enumerate(self.saved) if entry["name"] == name), None)
        if matching is None and len(self.saved) >= 24:
            self.message.setText("最多收藏 24 套配色，可以先删除一套")
            return
        entry = {"name": name, **{k: deepcopy(self.draft[k]) for k in ("coat", "keyboard", "colors", "white_markings")}}
        if matching is None:
            self.saved.append(entry)
        else:
            self.saved[matching] = entry
        self._refresh_saved()
        self.saved_combo.setCurrentIndex(next(i + 1 for i, v in enumerate(self.saved) if v["name"] == name))
        self.message.setText(f"已加入「{name}」；点击「保存并使用」后保留")

    def _load_saved(self, index):
        selected = self.saved_combo.itemData(index)
        if selected is not None:
            self._checkpoint()
            entry = deepcopy(self.saved[selected])
            self.palette_name.setText(entry.pop("name"))
            self.draft = remember_appearance(self.draft)
            self.draft.update(entry)
            self._sync()

    def _delete_saved(self):
        selected = self.saved_combo.currentData()
        if selected is not None:
            self.saved.pop(selected)
            self._refresh_saved()

    def _reset(self):
        self._checkpoint()
        self.draft = {**deepcopy(self.original), **cat_preferences(self.original)}
        self._sync()

    def _draw(self, compare=False):
        options = self.original if compare or self.compare.isDown() else self.draft
        image = render_cat(self.state, options, cursor=self.preview.logical_cursor(), dt=0.05)
        self.preview.set_frame(QPixmap.fromImage(image), cat=True)

    def done(self, result):
        self.timer.stop()
        self.state.reset()
        super().done(result)
