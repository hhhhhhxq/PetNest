class_name PetNestSettingsDialog
extends Window

signal settings_applied(updated: Dictionary)

const WEEKDAY_NAMES := ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

var initial_settings: Dictionary = {}
var cursor_styles: Array[Dictionary] = []
var inputs: Dictionary = {}
var daily_enabled: Dictionary = {}
var daily_time: Dictionary = {}
var error_label: Label


func configure(current: Dictionary, available_cursor_styles: Array[Dictionary] = []) -> void:
	initial_settings = current.duplicate(true)
	cursor_styles = available_cursor_styles.duplicate(true)


func _ready() -> void:
	title = "PetNest Advanced 设置"
	size = Vector2i(620, 760)
	min_size = Vector2i(520, 620)
	initial_position = Window.WINDOW_INITIAL_POSITION_CENTER_MAIN_WINDOW_SCREEN
	transient = false
	exclusive = false
	transparent = false
	transparent_bg = false
	close_requested.connect(queue_free)
	_build_ui()


func _build_ui() -> void:
	var background := ColorRect.new()
	background.color = Color(0.105, 0.115, 0.14, 1.0)
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(background)
	var margin := MarginContainer.new()
	margin.add_theme_constant_override("margin_left", 16)
	margin.add_theme_constant_override("margin_top", 14)
	margin.add_theme_constant_override("margin_right", 16)
	margin.add_theme_constant_override("margin_bottom", 14)
	margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(margin)

	var root := VBoxContainer.new()
	root.add_theme_constant_override("separation", 8)
	margin.add_child(root)
	var heading := Label.new()
	heading.text = "标准功能与 Godot 高级功能"
	heading.add_theme_font_size_override("font_size", 22)
	root.add_child(heading)
	var hint := Label.new()
	hint.text = "保存后立即生效，并与 PySide6 标准版共享 settings.json。"
	hint.modulate = Color(0.65, 0.67, 0.72)
	root.add_child(hint)

	var scroll := ScrollContainer.new()
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	root.add_child(scroll)
	var form := VBoxContainer.new()
	form.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	form.add_theme_constant_override("separation", 6)
	scroll.add_child(form)

	_add_section(form, "显示与交互")
	inputs["scale"] = _add_spin(form, "宠物缩放", 0.25, 2.0, 0.05, float(initial_settings.get("scale", 1.0)), " 倍")
	inputs["always_on_top"] = _add_check(form, "始终置顶", bool(initial_settings.get("always_on_top", true)))
	inputs["mouse_interaction_enabled"] = _add_check(form, "启用鼠标交互", bool(initial_settings.get("mouse_interaction_enabled", true)))
	inputs["mouse_follow_enabled"] = _add_check(form, "跟随鼠标", bool(initial_settings.get("mouse_follow_enabled", false)))
	inputs["mouse_follow_scale"] = _add_spin(form, "鼠标跟随速度", 0.10, 2.0, 0.05, float(initial_settings.get("mouse_follow_scale", 0.45)), " 倍")

	_add_section(form, "系统鼠标样式")
	inputs["cursor_style_enabled"] = _add_check(form, "使用自定义系统光标", bool(initial_settings.get("cursor_style_enabled", false)))
	var cursor_style := OptionButton.new()
	if cursor_styles.is_empty():
		cursor_style.add_item("没有可用鼠标主题")
		cursor_style.set_item_metadata(0, "")
		cursor_style.disabled = true
		(inputs["cursor_style_enabled"] as CheckBox).disabled = true
	else:
		for style in cursor_styles:
			cursor_style.add_item(str(style.get("name", style.get("id", "鼠标主题"))))
			cursor_style.set_item_metadata(cursor_style.item_count - 1, str(style.get("id", "")))
	var selected_cursor := str(initial_settings.get("cursor_style_id", ""))
	for index in range(cursor_style.item_count):
		if str(cursor_style.get_item_metadata(index)) == selected_cursor:
			cursor_style.select(index)
	inputs["cursor_style_id"] = cursor_style
	_add_row(form, "鼠标主题", cursor_style)

	_add_section(form, "Godot 高级能力")
	inputs["godot_auto_walk"] = _add_check(form, "自动行走", bool(initial_settings.get("godot_auto_walk", true)))
	inputs["godot_power_saver"] = _add_check(form, "省电模式（限制 60 FPS）", bool(initial_settings.get("godot_power_saver", false)))
	inputs["godot_renderer_max_fps"] = _add_spin(form, "高性能最大帧率", 60, 360, 1, float(initial_settings.get("godot_renderer_max_fps", 240)), " FPS")

	_add_section(form, "系统空闲动作")
	inputs["system_idle_enabled"] = _add_check(form, "启用 bored / sleep / wake", bool(initial_settings.get("system_idle_enabled", true)))
	inputs["system_bored_seconds"] = _add_spin(form, "无操作后无聊", 1, 86400, 1, float(initial_settings.get("system_bored_seconds", 20)), " 秒")
	inputs["system_sleep_seconds"] = _add_spin(form, "无操作后睡觉", 2, 86400, 1, float(initial_settings.get("system_sleep_seconds", 35)), " 秒")

	_add_section(form, "本机事件接口")
	inputs["external_event_server_enabled"] = _add_check(form, "启用 127.0.0.1 JSON 事件", bool(initial_settings.get("external_event_server_enabled", false)))
	inputs["external_event_port"] = _add_spin(form, "监听端口", 1024, 65535, 1, float(initial_settings.get("external_event_port", 18486)), "")

	_add_section(form, "局域网互动")
	inputs["lan_interaction_enabled"] = _add_check(form, "允许附近设备发现并互动", bool(initial_settings.get("lan_interaction_enabled", true)))
	inputs["nickname"] = _add_line(form, "我的昵称", str(initial_settings.get("nickname", "")), "留空则显示短设备码")
	(inputs["nickname"] as LineEdit).max_length = 24

	_add_section(form, "上下班倒计时")
	inputs["work_countdown_enabled"] = _add_check(form, "显示倒计时", bool(initial_settings.get("work_countdown_enabled", true)))
	inputs["work_start_time"] = _add_line(form, "上班时间", str(initial_settings.get("work_start_time", "09:00")), "HH:mm")
	inputs["countdown_gap"] = _add_spin(form, "与宠物间距", 0, 80, 1, float(initial_settings.get("countdown_gap", 0)), " 像素")
	inputs["countdown_width"] = _add_spin(form, "卡片最小宽度", 110, 420, 1, float(initial_settings.get("countdown_width", 132)), " 像素")
	inputs["countdown_height"] = _add_spin(form, "卡片高度", 26, 100, 1, float(initial_settings.get("countdown_height", 37)), " 像素")
	var placement := OptionButton.new()
	placement.add_item("宠物上方")
	placement.set_item_metadata(0, "above")
	placement.add_item("宠物下方")
	placement.set_item_metadata(1, "below")
	var selected_placement := str(initial_settings.get("countdown_placement", "above"))
	for index in range(placement.item_count):
		if str(placement.get_item_metadata(index)) == selected_placement:
			placement.select(index)
	inputs["countdown_placement"] = placement
	_add_row(form, "卡片位置", placement)
	var theme := OptionButton.new()
	theme.add_item("A · 奶油爪爪")
	theme.set_item_metadata(0, "cream")
	theme.add_item("B · 黑猫夜灯")
	theme.set_item_metadata(1, "night")
	theme.add_item("C · 毛线便签")
	theme.set_item_metadata(2, "yarn")
	var selected_theme := str(initial_settings.get("countdown_theme", "cream"))
	for index in range(theme.item_count):
		if str(theme.get_item_metadata(index)) == selected_theme:
			theme.select(index)
	inputs["countdown_theme"] = theme
	_add_row(form, "倒计时主题", theme)

	var schedule_raw = initial_settings.get("daily_work_end_times", {})
	var schedule: Dictionary = schedule_raw if typeof(schedule_raw) == TYPE_DICTIONARY else {}
	for index in range(WEEKDAY_NAMES.size()):
		var key := str(index)
		var configured = schedule.get(key, "18:00" if index < 5 else null)
		var row_control := HBoxContainer.new()
		var enabled := CheckBox.new()
		enabled.text = "上班"
		enabled.button_pressed = configured != null
		row_control.add_child(enabled)
		var time_input := LineEdit.new()
		time_input.text = str(configured) if configured != null else str(initial_settings.get("work_end_time", "18:00"))
		time_input.placeholder_text = "HH:mm"
		time_input.custom_minimum_size.x = 110
		time_input.editable = enabled.button_pressed
		enabled.toggled.connect(func(value: bool) -> void: time_input.editable = value)
		row_control.add_child(time_input)
		daily_enabled[key] = enabled
		daily_time[key] = time_input
		_add_row(form, WEEKDAY_NAMES[index] + "下班", row_control)

	error_label = Label.new()
	error_label.modulate = Color(0.95, 0.35, 0.32)
	error_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	root.add_child(error_label)
	var buttons := HBoxContainer.new()
	buttons.alignment = BoxContainer.ALIGNMENT_END
	var cancel := Button.new()
	cancel.text = "取消"
	cancel.pressed.connect(queue_free)
	buttons.add_child(cancel)
	var save := Button.new()
	save.text = "保存并应用"
	save.pressed.connect(_save)
	buttons.add_child(save)
	root.add_child(buttons)


func _add_section(parent: VBoxContainer, text: String) -> void:
	var separator := HSeparator.new()
	parent.add_child(separator)
	var label := Label.new()
	label.text = text
	label.add_theme_font_size_override("font_size", 17)
	parent.add_child(label)


func _add_row(parent: VBoxContainer, label_text: String, control: Control) -> void:
	var row := HBoxContainer.new()
	row.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var label := Label.new()
	label.text = label_text
	label.custom_minimum_size.x = 210
	row.add_child(label)
	control.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(control)
	parent.add_child(row)


func _add_check(parent: VBoxContainer, label_text: String, value: bool) -> CheckBox:
	var input := CheckBox.new()
	input.button_pressed = value
	_add_row(parent, label_text, input)
	return input


func _add_spin(parent: VBoxContainer, label_text: String, minimum: float, maximum: float, step: float, value: float, suffix: String) -> SpinBox:
	var input := SpinBox.new()
	input.min_value = minimum
	input.max_value = maximum
	input.step = step
	input.value = clampf(value, minimum, maximum)
	input.suffix = suffix
	input.allow_greater = false
	input.allow_lesser = false
	_add_row(parent, label_text, input)
	return input


func _add_line(parent: VBoxContainer, label_text: String, value: String, placeholder: String) -> LineEdit:
	var input := LineEdit.new()
	input.text = value
	input.placeholder_text = placeholder
	_add_row(parent, label_text, input)
	return input


func _save() -> void:
	var updated := initial_settings.duplicate(true)
	updated["scale"] = float((inputs["scale"] as SpinBox).value)
	for key in ["always_on_top", "mouse_interaction_enabled", "mouse_follow_enabled", "cursor_style_enabled", "godot_auto_walk", "godot_power_saver", "system_idle_enabled", "external_event_server_enabled", "lan_interaction_enabled", "work_countdown_enabled"]:
		updated[key] = bool((inputs[key] as CheckBox).button_pressed)
	var cursor_style := inputs["cursor_style_id"] as OptionButton
	updated["cursor_style_id"] = str(cursor_style.get_item_metadata(cursor_style.selected))
	if str(updated["cursor_style_id"]).is_empty():
		updated["cursor_style_enabled"] = false
	updated["nickname"] = (inputs["nickname"] as LineEdit).text.strip_edges()
	updated["mouse_follow_scale"] = float((inputs["mouse_follow_scale"] as SpinBox).value)
	for key in ["godot_renderer_max_fps", "system_bored_seconds", "system_sleep_seconds", "external_event_port", "countdown_gap", "countdown_width", "countdown_height"]:
		updated[key] = int((inputs[key] as SpinBox).value)
	updated["system_sleep_seconds"] = maxi(int(updated["system_sleep_seconds"]), int(updated["system_bored_seconds"]) + 1)
	var start_time := (inputs["work_start_time"] as LineEdit).text.strip_edges()
	if not _valid_time(start_time):
		error_label.text = "上班时间必须使用 HH:mm 格式。"
		return
	updated["work_start_time"] = start_time
	var schedule: Dictionary = {}
	for key in daily_time:
		if not (daily_enabled[key] as CheckBox).button_pressed:
			schedule[key] = null
			continue
		var time_text := (daily_time[key] as LineEdit).text.strip_edges()
		if not _valid_time(time_text):
			error_label.text = "%s下班时间必须使用 HH:mm 格式。" % WEEKDAY_NAMES[int(key)]
			return
		schedule[key] = time_text
	updated["daily_work_end_times"] = schedule
	updated["work_end_time"] = _first_work_end(schedule, str(initial_settings.get("work_end_time", "18:00")))
	var theme := inputs["countdown_theme"] as OptionButton
	updated["countdown_theme"] = str(theme.get_item_metadata(theme.selected))
	var placement := inputs["countdown_placement"] as OptionButton
	updated["countdown_placement"] = str(placement.get_item_metadata(placement.selected))
	error_label.text = ""
	settings_applied.emit(updated)
	queue_free()


func _valid_time(value: String) -> bool:
	var parts := value.split(":")
	return parts.size() == 2 and parts[0].is_valid_int() and parts[1].is_valid_int() and int(parts[0]) in range(24) and int(parts[1]) in range(60)


func _first_work_end(schedule: Dictionary, fallback: String) -> String:
	for index in range(7):
		var value = schedule.get(str(index), null)
		if value != null:
			return str(value)
	return fallback
