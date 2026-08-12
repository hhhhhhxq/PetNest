class_name PetNestAnimationEditorDialog
extends Window

signal durations_saved(updates: Dictionary)

var package: Dictionary = {}
var timelines: Dictionary = {}
var changed: Dictionary = {}
var action_picker: OptionButton
var total_input: SpinBox
var frame_list: VBoxContainer
var preview: TextureRect
var summary: Label
var error_label: Label
var frame_inputs: Array[SpinBox] = []
var current_action := ""
var loading := false
var preview_index := 0
var preview_timer: Timer
var texture_cache: Dictionary = {}


func configure(current_package: Dictionary) -> void:
	package = current_package
	var animations: Dictionary = package.get("animations", {})
	for action_value in animations:
		var action := str(action_value)
		var definition: Dictionary = animations[action_value]
		var frames: Array = definition.get("frames", [])
		var configured = definition.get("frame_durations_ms", [])
		var durations: Array[int] = []
		if typeof(configured) == TYPE_ARRAY and configured.size() == frames.size():
			for value in configured:
				durations.append(clampi(int(value), 1, 60000))
		else:
			var duration := maxi(1, roundi(1000.0 / maxf(float(definition.get("fps", 8.0)), 0.1)))
			for frame in frames:
				durations.append(duration)
		timelines[action] = durations


func _ready() -> void:
	title = "编辑动画时长 — " + str(package.get("name", "Pet"))
	size = Vector2i(820, 660)
	min_size = Vector2i(680, 520)
	initial_position = Window.WINDOW_INITIAL_POSITION_CENTER_MAIN_WINDOW_SCREEN
	transient = false
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
	root.add_theme_constant_override("separation", 9)
	margin.add_child(root)

	var hint := Label.new()
	hint.text = "逐帧时长会写入 pet.json，并随宠物文件夹一起分享。"
	root.add_child(hint)
	action_picker = OptionButton.new()
	var actions: Array[String] = []
	for action_value in timelines:
		actions.append(str(action_value))
	actions.sort()
	for action in actions:
		action_picker.add_item(action)
		action_picker.set_item_metadata(action_picker.item_count - 1, action)
	action_picker.item_selected.connect(_select_action)
	root.add_child(action_picker)

	var total_row := HBoxContainer.new()
	var total_label := Label.new()
	total_label.text = "目标总时长"
	total_label.custom_minimum_size.x = 140
	total_row.add_child(total_label)
	total_input = SpinBox.new()
	total_input.min_value = 1
	total_input.max_value = 600000
	total_input.step = 10
	total_input.suffix = " ms"
	total_input.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	total_row.add_child(total_input)
	var distribute := Button.new()
	distribute.text = "按比例分配到各帧"
	distribute.pressed.connect(_distribute_total)
	total_row.add_child(distribute)
	root.add_child(total_row)

	var body := HSplitContainer.new()
	body.size_flags_vertical = Control.SIZE_EXPAND_FILL
	root.add_child(body)
	var scroll := ScrollContainer.new()
	scroll.custom_minimum_size.x = 390
	frame_list = VBoxContainer.new()
	frame_list.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.add_child(frame_list)
	body.add_child(scroll)
	var preview_column := VBoxContainer.new()
	var preview_title := Label.new()
	preview_title.text = "实时预览"
	preview_column.add_child(preview_title)
	preview = TextureRect.new()
	preview.custom_minimum_size = Vector2(300, 300)
	preview.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	preview.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
	preview.size_flags_vertical = Control.SIZE_EXPAND_FILL
	preview_column.add_child(preview)
	summary = Label.new()
	summary.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	preview_column.add_child(summary)
	body.add_child(preview_column)

	error_label = Label.new()
	error_label.modulate = Color(0.95, 0.35, 0.32)
	root.add_child(error_label)
	var buttons := HBoxContainer.new()
	buttons.alignment = BoxContainer.ALIGNMENT_END
	var cancel := Button.new()
	cancel.text = "取消"
	cancel.pressed.connect(queue_free)
	buttons.add_child(cancel)
	var save := Button.new()
	save.text = "保存到宠物包"
	save.pressed.connect(_save)
	buttons.add_child(save)
	root.add_child(buttons)

	preview_timer = Timer.new()
	preview_timer.one_shot = true
	preview_timer.timeout.connect(_advance_preview)
	add_child(preview_timer)
	if action_picker.item_count > 0:
		_select_action(0)


func _select_action(index: int) -> void:
	_store_frame_inputs()
	current_action = str(action_picker.get_item_metadata(index))
	loading = true
	for child in frame_list.get_children():
		child.queue_free()
	frame_inputs.clear()
	var frames: Array = package["animations"][current_action]["frames"]
	var durations: Array = timelines[current_action]
	for frame_index in range(frames.size()):
		var row := HBoxContainer.new()
		var thumbnail := TextureRect.new()
		thumbnail.custom_minimum_size = Vector2(58, 58)
		thumbnail.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
		thumbnail.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
		thumbnail.texture = _texture(str(frames[frame_index]))
		row.add_child(thumbnail)
		var label := Label.new()
		label.text = "第 %d 帧" % (frame_index + 1)
		label.custom_minimum_size.x = 100
		row.add_child(label)
		var spin := SpinBox.new()
		spin.min_value = 1
		spin.max_value = 60000
		spin.step = 1
		spin.suffix = " ms"
		spin.value = int(durations[frame_index])
		spin.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		spin.value_changed.connect(_frame_duration_changed)
		row.add_child(spin)
		frame_inputs.append(spin)
		frame_list.add_child(row)
	total_input.value = _timeline_total(durations)
	loading = false
	preview_index = 0
	_render_preview()


func _frame_duration_changed(_value: float) -> void:
	if loading or current_action.is_empty():
		return
	_store_frame_inputs()
	changed[current_action] = true
	total_input.value = _timeline_total(timelines[current_action])
	_render_preview()


func _store_frame_inputs() -> void:
	if loading or current_action.is_empty() or frame_inputs.is_empty():
		return
	var durations: Array[int] = []
	for input in frame_inputs:
		durations.append(int(input.value))
	timelines[current_action] = durations


func _distribute_total() -> void:
	if current_action.is_empty():
		return
	_store_frame_inputs()
	var source: Array = timelines[current_action]
	var source_total := _timeline_total(source)
	var target_total := int(total_input.value)
	if source_total <= 0 or target_total < source.size():
		error_label.text = "总时长不能小于帧数。"
		return
	var scaled: Array[int] = []
	for duration in source:
		scaled.append(maxi(1, roundi(float(duration) * target_total / source_total)))
	var difference := target_total - _timeline_total(scaled)
	scaled[scaled.size() - 1] = maxi(1, int(scaled[-1]) + difference)
	timelines[current_action] = scaled
	changed[current_action] = true
	error_label.text = ""
	loading = true
	for index in range(frame_inputs.size()):
		frame_inputs[index].value = int(scaled[index])
	total_input.value = target_total
	loading = false
	preview_index = 0
	_render_preview()


func _render_preview() -> void:
	if current_action.is_empty():
		return
	var frames: Array = package["animations"][current_action]["frames"]
	var durations: Array = timelines[current_action]
	if frames.is_empty():
		preview.texture = null
		return
	preview_index = posmod(preview_index, frames.size())
	preview.texture = _texture(str(frames[preview_index]))
	summary.text = "%d 帧 · %d ms" % [frames.size(), _timeline_total(durations)]
	preview_timer.start(maxf(float(durations[preview_index]) / 1000.0, 0.001))


func _advance_preview() -> void:
	preview_index += 1
	_render_preview()


func _texture(path: String) -> Texture2D:
	if texture_cache.has(path):
		return texture_cache[path]
	var image := Image.new()
	if image.load(path) != OK:
		return null
	var result := ImageTexture.create_from_image(image)
	texture_cache[path] = result
	return result


func _timeline_total(durations: Array) -> int:
	var total := 0
	for duration in durations:
		total += int(duration)
	return total


func _save() -> void:
	_store_frame_inputs()
	if not current_action.is_empty():
		changed[current_action] = true
	var updates: Dictionary = {}
	for action in changed:
		updates[action] = timelines[action]
	if updates.is_empty():
		error_label.text = "没有需要保存的更改。"
		return
	durations_saved.emit(updates)
	queue_free()
