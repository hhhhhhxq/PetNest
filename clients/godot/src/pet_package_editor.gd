class_name PetNestPackageEditor
extends RefCounted


func update_frame_durations(package_root: String, updates: Dictionary) -> Dictionary:
	var config_path := package_root.path_join("pet.json")
	if not FileAccess.file_exists(config_path):
		return _failure("找不到 pet.json")
	var parsed = JSON.parse_string(FileAccess.get_file_as_string(config_path))
	if typeof(parsed) != TYPE_DICTIONARY:
		return _failure("pet.json 不是 JSON 对象")
	var config: Dictionary = parsed
	var animations_raw = config.get("animations", {})
	if typeof(animations_raw) != TYPE_DICTIONARY:
		return _failure("animations 不是对象")
	var animations: Dictionary = animations_raw
	for action_value in updates:
		var action := str(action_value)
		if not animations.has(action) or typeof(animations[action]) != TYPE_DICTIONARY:
			return _failure("动作不存在：" + action)
		var durations_raw = updates[action_value]
		if typeof(durations_raw) != TYPE_ARRAY or durations_raw.is_empty():
			return _failure("动作时长必须是非空数组：" + action)
		var definition: Dictionary = animations[action]
		var relative_path := str(definition.get("path", ""))
		var frame_count := _png_count(package_root.path_join(relative_path).simplify_path())
		if frame_count <= 0 or durations_raw.size() != frame_count:
			return _failure("动作 %s 的时长数量必须与 %d 张帧一致" % [action, frame_count])
		var durations: Array[int] = []
		for value in durations_raw:
			var duration := int(value)
			if duration < 1 or duration > 60000:
				return _failure("每帧时长必须介于 1 到 60000 毫秒")
			durations.append(duration)
		definition["frame_durations_ms"] = durations
		definition.erase("speed_multiplier")
	var normalized = _normalize_integral_numbers(config)
	var result := _atomic_write(config_path, JSON.stringify(normalized, "  ") + "\n")
	if result != OK:
		return _failure("写入 pet.json 失败：" + error_string(result))
	return {"ok": true}


func _png_count(root: String) -> int:
	var directory := DirAccess.open(root)
	if directory == null:
		return 0
	var count := 0
	for file in directory.get_files():
		if file.get_extension().to_lower() == "png":
			count += 1
	return count


func _normalize_integral_numbers(value):
	if typeof(value) == TYPE_FLOAT and is_equal_approx(float(value), roundf(float(value))):
		return int(value)
	if typeof(value) == TYPE_ARRAY:
		var normalized_array: Array = []
		for item in value:
			normalized_array.append(_normalize_integral_numbers(item))
		return normalized_array
	if typeof(value) == TYPE_DICTIONARY:
		var normalized_dictionary: Dictionary = {}
		for key in value:
			normalized_dictionary[key] = _normalize_integral_numbers(value[key])
		return normalized_dictionary
	return value


func _atomic_write(path: String, contents: String) -> Error:
	var temporary := path + ".godot.tmp"
	var backup := path + ".godot.bak"
	var file := FileAccess.open(temporary, FileAccess.WRITE)
	if file == null:
		return FileAccess.get_open_error()
	file.store_string(contents)
	file.flush()
	file.close()
	if FileAccess.file_exists(backup):
		DirAccess.remove_absolute(backup)
	var error := OK
	if FileAccess.file_exists(path):
		error = DirAccess.rename_absolute(path, backup)
		if error != OK:
			DirAccess.remove_absolute(temporary)
			return error
	error = DirAccess.rename_absolute(temporary, path)
	if error != OK:
		if FileAccess.file_exists(backup):
			DirAccess.rename_absolute(backup, path)
		return error
	if FileAccess.file_exists(backup):
		DirAccess.remove_absolute(backup)
	return OK


func _failure(message: String) -> Dictionary:
	return {"ok": false, "error": message}
