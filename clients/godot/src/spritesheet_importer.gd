class_name PetNestSpritesheetImporter
extends RefCounted

const COLUMNS := 8
const CELL_SIZE := Vector2i(192, 208)
const SUPPORTED_ROWS := [9, 11]
const ROW_MAPPINGS := [
	{"action": "idle", "loop": true, "fps": 8, "priority": 10, "interruptible": true, "durations": [280, 110, 110, 140, 140, 320]},
	{"action": "drag", "loop": true, "fps": 10, "priority": 80, "interruptible": false, "durations": [120, 120, 120, 120, 120, 120, 120, 220]},
	{"action": "codex_running_left", "loop": true, "fps": 10, "priority": 20, "interruptible": true, "durations": [120, 120, 120, 120, 120, 120, 120, 220]},
	{"action": "click", "loop": false, "fps": 10, "priority": 50, "interruptible": false, "next": "context", "durations": [140, 140, 140, 280]},
	{"action": "drop", "loop": false, "fps": 10, "priority": 70, "interruptible": false, "next": "context", "durations": [140, 140, 140, 140, 280]},
	{"action": "error", "loop": false, "fps": 10, "priority": 100, "interruptible": false, "next": "context", "durations": [140, 140, 140, 140, 140, 140, 140, 240]},
	{"action": "waiting", "loop": true, "fps": 8, "priority": 60, "interruptible": true, "durations": [150, 150, 150, 150, 150, 260]},
	{"action": "working", "loop": true, "fps": 10, "priority": 60, "interruptible": true, "durations": [120, 120, 120, 120, 120, 220]},
	{"action": "hover", "loop": true, "fps": 8, "priority": 30, "interruptible": true, "durations": [150, 150, 150, 150, 150, 280]},
	{"action": "bored", "loop": false, "fps": 8, "priority": 25, "interruptible": true, "next": "context", "durations": [140, 140, 140, 140, 140, 140, 140, 280]},
	{"action": "wake", "loop": false, "fps": 8, "priority": 40, "interruptible": true, "next": "context", "durations": [140, 140, 140, 140, 140, 140, 140, 280]},
]


func inspect(source: String) -> Dictionary:
	var normalized := source.simplify_path()
	if source.get_extension().to_lower() != "png" or not FileAccess.file_exists(normalized):
		return _failure("请选择存在的 PNG 文件")
	var image := Image.new()
	var error := image.load(normalized)
	if error != OK:
		return _failure("无法读取 PNG：" + error_string(error))
	if image.get_width() != COLUMNS * CELL_SIZE.x:
		return _failure("图片宽度必须为 1536 像素（8 列）")
	if image.get_height() % CELL_SIZE.y != 0:
		return _failure("图片高度必须能按 208 像素整行切分")
	var rows := image.get_height() / CELL_SIZE.y
	if rows not in SUPPORTED_ROWS:
		return _failure("仅支持 8×9（1536×1872）或 8×11（1536×2288）精灵图")
	if image.detect_alpha() == Image.ALPHA_NONE:
		return _failure("精灵图必须包含透明像素")
	image.convert(Image.FORMAT_RGBA8)
	var selected: Dictionary = {}
	var total := 0
	for row in range(rows):
		var action := str(ROW_MAPPINGS[row]["action"])
		var columns: Array[int] = []
		for column in range(COLUMNS):
			if _cell_has_pixels(image, row, column):
				columns.append(column)
				total += 1
		selected[action] = columns
	return {
		"ok": true,
		"source": normalized,
		"rows": rows,
		"size": image.get_size(),
		"selected_columns_by_action": selected,
		"frame_count": total,
	}


func import_file(
	source: String,
	pets_root: String,
	pet_id: String,
	display_name: String,
	selected_columns_by_action: Dictionary = {},
) -> Dictionary:
	var inspection := inspect(source)
	if not bool(inspection.get("ok", false)):
		return inspection
	var identifier := pet_id.strip_edges().to_lower()
	var pattern := RegEx.new()
	pattern.compile("^[a-z][a-z0-9_-]*$")
	if pattern.search(identifier) == null:
		return _failure("宠物 ID 必须以小写字母开头，只能包含小写字母、数字、- 或 _")
	var root := pets_root.simplify_path()
	var error := DirAccess.make_dir_recursive_absolute(root)
	if error != OK:
		return _failure("无法创建宠物库：" + error_string(error))
	var destination := root.path_join(identifier)
	if DirAccess.dir_exists_absolute(destination) or FileAccess.file_exists(destination):
		return _failure("宠物 ID “%s” 已存在，不会覆盖已有资源" % identifier)
	var temporary := root.path_join(".%s-godot-%d" % [identifier, Time.get_ticks_msec()])
	error = DirAccess.make_dir_recursive_absolute(temporary.path_join("animations"))
	if error != OK:
		return _failure("无法创建临时导入目录：" + error_string(error))
	var image := Image.new()
	error = image.load(str(inspection["source"]))
	if error != OK:
		_remove_tree(temporary)
		return _failure("无法再次读取精灵图")
	image.convert(Image.FORMAT_RGBA8)
	var selected: Dictionary = inspection["selected_columns_by_action"]
	if not selected_columns_by_action.is_empty():
		selected = _normalized_selection(int(inspection["rows"]), selected_columns_by_action)
	if not selected.has("idle") or (selected["idle"] as Array).is_empty():
		_remove_tree(temporary)
		return _failure("idle 行至少需要一个有内容的格位")
	var rows := int(inspection["rows"])
	for row in range(rows):
		var mapping: Dictionary = ROW_MAPPINGS[row]
		var action := str(mapping["action"])
		var columns: Array = selected.get(action, [])
		if columns.is_empty():
			continue
		var action_root := temporary.path_join("animations").path_join(action)
		error = DirAccess.make_dir_recursive_absolute(action_root)
		if error != OK:
			_remove_tree(temporary)
			return _failure("无法创建动作目录：" + action)
		for frame_index in range(columns.size()):
			var column := int(columns[frame_index])
			var frame := image.get_region(Rect2i(column * CELL_SIZE.x, row * CELL_SIZE.y, CELL_SIZE.x, CELL_SIZE.y))
			error = frame.save_png(action_root.path_join("%03d.png" % (frame_index + 1)))
			if error != OK:
				_remove_tree(temporary)
				return _failure("无法保存动作帧：" + error_string(error))
	var preview_source := temporary.path_join("animations").path_join("idle").path_join("001.png")
	var preview := Image.new()
	error = preview.load(preview_source)
	if error == OK:
		error = preview.save_png(temporary.path_join("preview.png"))
	if error != OK:
		_remove_tree(temporary)
		return _failure("无法生成宠物预览图")
	var config := _config(identifier, display_name.strip_edges() if not display_name.strip_edges().is_empty() else identifier, rows, selected)
	var config_file := FileAccess.open(temporary.path_join("pet.json"), FileAccess.WRITE)
	if config_file == null:
		_remove_tree(temporary)
		return _failure("无法创建 pet.json")
	config_file.store_string(JSON.stringify(config, "  ") + "\n")
	config_file.flush()
	config_file.close()
	error = DirAccess.rename_absolute(temporary, destination)
	if error != OK:
		_remove_tree(temporary)
		return _failure("无法完成导入：" + error_string(error))
	var frame_count := 0
	for columns in selected.values():
		frame_count += (columns as Array).size()
	return {"ok": true, "package_id": identifier, "package_root": destination, "frame_count": frame_count}


func _normalized_selection(rows: int, requested: Dictionary) -> Dictionary:
	var selected: Dictionary = {}
	for row in range(rows):
		var action := str(ROW_MAPPINGS[row]["action"])
		var columns: Array[int] = []
		var raw_columns = requested.get(action, [])
		if typeof(raw_columns) == TYPE_ARRAY:
			for raw_column in raw_columns:
				var column := int(raw_column)
				if column >= 0 and column < COLUMNS and not columns.has(column):
					columns.append(column)
		columns.sort()
		selected[action] = columns
	return selected


func _config(identifier: String, display_name: String, rows: int, selected: Dictionary) -> Dictionary:
	var animations: Dictionary = {}
	for row in range(rows):
		var mapping: Dictionary = ROW_MAPPINGS[row]
		var action := str(mapping["action"])
		var columns: Array = selected.get(action, [])
		if columns.is_empty():
			continue
		var durations: Array[int] = []
		var source_durations: Array = mapping["durations"]
		for column_value in columns:
			var column := int(column_value)
			durations.append(int(source_durations[column]) if column < source_durations.size() else roundi(1000.0 / float(mapping["fps"])))
		var definition := {
			"path": "animations/" + action,
			"fps": int(mapping["fps"]),
			"loop": bool(mapping["loop"]),
			"priority": int(mapping["priority"]),
			"interruptible": bool(mapping["interruptible"]),
			"frame_durations_ms": durations,
		}
		if mapping.has("next"):
			definition["next"] = str(mapping["next"])
		animations[action] = definition
	return {
		"schema_version": 1,
		"id": identifier,
		"name": display_name,
		"version": "1.0.0",
		"description": "由 PetNest Advanced 8×%d 精灵图导入" % rows,
		"canvas": {"width": CELL_SIZE.x, "height": CELL_SIZE.y},
		"display": {"default_scale": 0.8, "min_scale": 0.25, "max_scale": 2.0, "alpha_hit_test_threshold": 10},
		"animations": animations,
		"bindings": {
			"mouse.enter": "hover", "mouse.click": "click", "mouse.drag_start": "drag", "mouse.drag_end": "drop",
			"agent.working": "working", "agent.waiting": "waiting", "agent.success": "success", "agent.error": "error",
			"system.bored": "bored", "system.sleep": "sleep", "system.wake": "wake",
		},
		"fallbacks": {"success": ["idle"], "bored": ["idle"], "sleep": ["idle"], "wake": ["idle"]},
		"import_metadata": {"source_format": "petnest_8x%d" % rows, "selected_columns_by_action": selected},
	}


func _cell_has_pixels(image: Image, row: int, column: int) -> bool:
	var region := image.get_region(Rect2i(column * CELL_SIZE.x, row * CELL_SIZE.y, CELL_SIZE.x, CELL_SIZE.y))
	var used := region.get_used_rect()
	return used.size.x > 0 and used.size.y > 0


func _remove_tree(path: String) -> void:
	var directory := DirAccess.open(path)
	if directory == null:
		return
	for child_directory in directory.get_directories():
		_remove_tree(path.path_join(child_directory))
	for file in directory.get_files():
		DirAccess.remove_absolute(path.path_join(file))
	DirAccess.remove_absolute(path)


func _failure(message: String) -> Dictionary:
	return {"ok": false, "error": message}
