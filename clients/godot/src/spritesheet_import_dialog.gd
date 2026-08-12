class_name PetNestSpritesheetImportDialog
extends Window

signal package_imported(package_id: String)

const Importer = preload("res://src/spritesheet_importer.gd")

var pets_root := ""
var importer = Importer.new()
var source_input: LineEdit
var pet_id_input: LineEdit
var name_input: LineEdit
var status_label: Label
var file_dialog: FileDialog
var mode_input: OptionButton
var selection_scroll: ScrollContainer
var selection_grid: GridContainer
var selection_buttons: Dictionary = {}
var current_inspection: Dictionary = {}


func configure(root: String) -> void:
	pets_root = root


func _ready() -> void:
	title = "导入精灵图 — PetNest Advanced"
	size = Vector2i(860, 760)
	min_size = Vector2i(700, 600)
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
	margin.add_theme_constant_override("margin_left", 18)
	margin.add_theme_constant_override("margin_top", 16)
	margin.add_theme_constant_override("margin_right", 18)
	margin.add_theme_constant_override("margin_bottom", 16)
	margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(margin)
	var root := VBoxContainer.new()
	root.add_theme_constant_override("separation", 10)
	margin.add_child(root)
	var heading := Label.new()
	heading.text = "从透明 PNG 网格创建宠物包"
	heading.add_theme_font_size_override("font_size", 21)
	root.add_child(heading)
	var hint := Label.new()
	hint.text = "支持标准 1536×1872（8×9）及可选扩展 1536×2288（8×11）；可自动跳过透明格位或手动选帧，素材不会默认安装。"
	hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	root.add_child(hint)

	var source_row := HBoxContainer.new()
	source_input = LineEdit.new()
	source_input.placeholder_text = "选择 PNG 精灵图"
	source_input.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	source_input.text_changed.connect(_inspect_source)
	source_row.add_child(source_input)
	var browse := Button.new()
	browse.text = "选择文件…"
	browse.pressed.connect(_choose_source)
	source_row.add_child(browse)
	root.add_child(source_row)
	pet_id_input = _add_line(root, "宠物 ID", "例如 my_cat")
	name_input = _add_line(root, "显示名称", "可选，默认使用宠物 ID")
	var mode_row := HBoxContainer.new()
	var mode_label := Label.new()
	mode_label.text = "导入方式"
	mode_label.custom_minimum_size.x = 110
	mode_row.add_child(mode_label)
	mode_input = OptionButton.new()
	mode_input.add_item("自动跳过透明格位")
	mode_input.add_item("手动选择所需帧")
	mode_input.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	mode_input.item_selected.connect(_mode_changed)
	mode_row.add_child(mode_input)
	root.add_child(mode_row)

	selection_scroll = ScrollContainer.new()
	selection_scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_AUTO
	selection_scroll.vertical_scroll_mode = ScrollContainer.SCROLL_MODE_AUTO
	selection_scroll.custom_minimum_size.y = 330
	selection_scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	selection_scroll.visible = false
	root.add_child(selection_scroll)

	status_label = Label.new()
	status_label.text = "选择文件后会检查尺寸、透明通道和每个格位。"
	status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	root.add_child(status_label)
	var buttons := HBoxContainer.new()
	buttons.alignment = BoxContainer.ALIGNMENT_END
	var cancel := Button.new()
	cancel.text = "取消"
	cancel.pressed.connect(queue_free)
	buttons.add_child(cancel)
	var import_button := Button.new()
	import_button.text = "导入并切换"
	import_button.pressed.connect(_import)
	buttons.add_child(import_button)
	root.add_child(buttons)

	file_dialog = FileDialog.new()
	file_dialog.transparent = false
	file_dialog.transparent_bg = false
	file_dialog.access = FileDialog.ACCESS_FILESYSTEM
	file_dialog.file_mode = FileDialog.FILE_MODE_OPEN_FILE
	file_dialog.filters = PackedStringArray(["*.png ; PNG 图像"])
	file_dialog.file_selected.connect(_file_selected)
	add_child(file_dialog)


func _add_line(parent: VBoxContainer, label_text: String, placeholder: String) -> LineEdit:
	var row := HBoxContainer.new()
	var label := Label.new()
	label.text = label_text
	label.custom_minimum_size.x = 110
	row.add_child(label)
	var input := LineEdit.new()
	input.placeholder_text = placeholder
	input.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	row.add_child(input)
	parent.add_child(row)
	return input


func _choose_source() -> void:
	file_dialog.popup_centered_ratio(0.75)


func _file_selected(path: String) -> void:
	source_input.text = path
	if pet_id_input.text.strip_edges().is_empty():
		pet_id_input.text = _suggest_identifier(path.get_file().get_basename())


func _inspect_source(path: String) -> void:
	if path.strip_edges().is_empty() or not FileAccess.file_exists(path.strip_edges()):
		current_inspection = {}
		selection_scroll.visible = false
		return
	var result := importer.inspect(path.strip_edges())
	if bool(result.get("ok", false)):
		current_inspection = result
		_build_selection_grid(path.strip_edges(), result)
		_mode_changed(mode_input.selected)
		status_label.modulate = Color(0.40, 0.82, 0.48)
		status_label.text = "检测通过：8×%d，共 %d 个有内容格位。" % [int(result["rows"]), int(result["frame_count"])]
	else:
		current_inspection = {}
		selection_scroll.visible = false
		status_label.modulate = Color(0.95, 0.35, 0.32)
		status_label.text = "无法导入：" + str(result.get("error", "未知错误"))


func _mode_changed(index: int) -> void:
	selection_scroll.visible = index == 1 and not current_inspection.is_empty()
	if selection_scroll.visible:
		_refresh_manual_status()


func _build_selection_grid(path: String, inspection: Dictionary) -> void:
	if is_instance_valid(selection_grid):
		selection_scroll.remove_child(selection_grid)
		selection_grid.queue_free()
	selection_buttons.clear()
	selection_grid = GridContainer.new()
	selection_grid.columns = 9
	selection_grid.add_theme_constant_override("h_separation", 6)
	selection_grid.add_theme_constant_override("v_separation", 6)
	selection_scroll.add_child(selection_grid)
	var image := Image.new()
	if image.load(path) != OK:
		return
	image.convert(Image.FORMAT_RGBA8)
	var selected: Dictionary = inspection.get("selected_columns_by_action", {})
	for row in range(int(inspection.get("rows", 0))):
		var action := str(Importer.ROW_MAPPINGS[row]["action"])
		var action_label := Label.new()
		action_label.text = action
		action_label.custom_minimum_size.x = 116
		selection_grid.add_child(action_label)
		var row_buttons: Array[BaseButton] = []
		for column in range(Importer.COLUMNS):
			var cell := VBoxContainer.new()
			cell.custom_minimum_size = Vector2(72, 94)
			var preview := image.get_region(Rect2i(column * Importer.CELL_SIZE.x, row * Importer.CELL_SIZE.y, Importer.CELL_SIZE.x, Importer.CELL_SIZE.y))
			preview.resize(64, 69, Image.INTERPOLATE_LANCZOS)
			var button := TextureButton.new()
			button.texture_normal = ImageTexture.create_from_image(preview)
			button.ignore_texture_size = true
			button.stretch_mode = TextureButton.STRETCH_KEEP_ASPECT_CENTERED
			button.toggle_mode = true
			button.button_pressed = (selected.get(action, []) as Array).has(column)
			button.custom_minimum_size = Vector2(68, 72)
			button.tooltip_text = "%s · 第 %d 格" % [action, column + 1]
			button.toggled.connect(func(_pressed: bool) -> void: _refresh_manual_status())
			cell.add_child(button)
			var column_label := Label.new()
			column_label.text = str(column + 1)
			column_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
			cell.add_child(column_label)
			selection_grid.add_child(cell)
			row_buttons.append(button)
		selection_buttons[action] = row_buttons


func _manual_selection() -> Dictionary:
	var selected: Dictionary = {}
	for action in selection_buttons:
		var columns: Array[int] = []
		var buttons: Array = selection_buttons[action]
		for column in range(buttons.size()):
			if (buttons[column] as BaseButton).button_pressed:
				columns.append(column)
		selected[action] = columns
	return selected


func _refresh_manual_status() -> void:
	if mode_input.selected != 1 or current_inspection.is_empty():
		return
	var count := 0
	for columns in _manual_selection().values():
		count += (columns as Array).size()
	status_label.modulate = Color(0.40, 0.82, 0.48)
	status_label.text = "手动模式：已选择 %d 帧；idle 至少保留一帧。" % count


func _import() -> void:
	var selected := _manual_selection() if mode_input.selected == 1 else {}
	var result := importer.import_file(source_input.text.strip_edges(), pets_root, pet_id_input.text, name_input.text, selected)
	if not bool(result.get("ok", false)):
		status_label.modulate = Color(0.95, 0.35, 0.32)
		status_label.text = "导入失败：" + str(result.get("error", "未知错误"))
		return
	status_label.modulate = Color(0.40, 0.82, 0.48)
	status_label.text = "导入完成：" + str(result.get("package_root", ""))
	package_imported.emit(str(result["package_id"]))
	queue_free()


func _suggest_identifier(source_name: String) -> String:
	var regex := RegEx.new()
	regex.compile("[^a-z0-9_-]+")
	var candidate := regex.sub(source_name.to_lower(), "_", true)
	while candidate.begins_with("_") or candidate.begins_with("-"):
		candidate = candidate.substr(1)
	while candidate.ends_with("_") or candidate.ends_with("-"):
		candidate = candidate.left(-1)
	if candidate.is_empty() or not candidate.left(1) in "abcdefghijklmnopqrstuvwxyz":
		candidate = "pet_" + candidate
	return candidate
