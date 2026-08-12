class_name PetNestPackageLoader
extends RefCounted


func discover(pets_root: String) -> Array[Dictionary]:
	var packages: Array[Dictionary] = []
	var directory := DirAccess.open(pets_root)
	if directory == null:
		return packages
	var names: Array[String] = []
	for directory_name in directory.get_directories():
		names.append(directory_name)
	names.sort_custom(func(left: String, right: String) -> bool: return left.naturalnocasecmp_to(right) < 0)
	for name in names:
		var result := load_package(pets_root.path_join(name))
		if bool(result.get("ok", false)):
			packages.append(result["package"])
		else:
			push_warning("忽略无效宠物包 %s：%s" % [name, str(result.get("error", "未知错误"))])
	return packages


func load_package(root: String) -> Dictionary:
	var normalized_root := root.simplify_path()
	var config_path := normalized_root.path_join("pet.json")
	if not FileAccess.file_exists(config_path):
		return _failure("缺少 pet.json")
	var parsed = JSON.parse_string(FileAccess.get_file_as_string(config_path))
	if typeof(parsed) != TYPE_DICTIONARY:
		return _failure("pet.json 必须是 JSON 对象")
	var config: Dictionary = parsed
	if int(config.get("schema_version", 0)) != 1:
		return _failure("schema_version 必须为 1")
	var identifier := str(config.get("id", "")).strip_edges()
	if identifier.is_empty():
		return _failure("缺少宠物 id")
	var canvas_raw = config.get("canvas", {})
	if typeof(canvas_raw) != TYPE_DICTIONARY:
		return _failure("canvas 必须是对象")
	var canvas: Dictionary = canvas_raw
	var canvas_width := int(canvas.get("width", 0))
	var canvas_height := int(canvas.get("height", 0))
	if canvas_width <= 0 or canvas_height <= 0:
		return _failure("canvas 尺寸无效")
	var animations_raw = config.get("animations", {})
	if typeof(animations_raw) != TYPE_DICTIONARY:
		return _failure("animations 必须是对象")
	var animations: Dictionary = {}
	for action_value in animations_raw:
		var action := str(action_value)
		var definition_raw = animations_raw[action_value]
		if typeof(definition_raw) != TYPE_DICTIONARY:
			continue
		var definition: Dictionary = definition_raw
		var relative_path := str(definition.get("path", ""))
		if relative_path.is_empty() or relative_path.is_absolute_path() or relative_path.replace("\\", "/").split("/").has(".."):
			continue
		var animation_root := normalized_root.path_join(relative_path).simplify_path()
		if not _is_within_root(animation_root, normalized_root):
			continue
		var frames := _png_frames(animation_root)
		if frames.is_empty():
			continue
		var frame_durations = definition.get("frame_durations_ms", [])
		if typeof(frame_durations) != TYPE_ARRAY or (not frame_durations.is_empty() and frame_durations.size() != frames.size()):
			frame_durations = []
		animations[action] = {
			"name": action,
			"path": animation_root,
			"frames": frames,
			"fps": maxf(float(definition.get("fps", 8.0)), 0.1),
			"loop": bool(definition.get("loop", true)),
			"next": str(definition.get("next", "")),
			"priority": int(definition.get("priority", 0)),
			"interruptible": bool(definition.get("interruptible", true)),
			"restart_on_reenter": bool(definition.get("restart_on_reenter", false)),
			"frame_durations_ms": frame_durations,
			"speed_multiplier": maxf(float(definition.get("speed_multiplier", 1.0)), 0.01),
		}
	if not animations.has("idle"):
		return _failure("缺少可用的 idle 动画")
	var display_raw = config.get("display", {})
	var display: Dictionary = display_raw if typeof(display_raw) == TYPE_DICTIONARY else {}
	var bindings_raw = config.get("bindings", {})
	var bindings: Dictionary = bindings_raw.duplicate(true) if typeof(bindings_raw) == TYPE_DICTIONARY else {}
	var fallbacks_raw = config.get("fallbacks", {})
	var fallbacks: Dictionary = fallbacks_raw.duplicate(true) if typeof(fallbacks_raw) == TYPE_DICTIONARY else {}
	return {
		"ok": true,
		"package": {
			"root": normalized_root,
			"id": identifier,
			"name": str(config.get("name", identifier)),
			"version": str(config.get("version", "0.0.0")),
			"canvas": Vector2i(canvas_width, canvas_height),
			"display": {
				"default_scale": float(display.get("default_scale", 1.0)),
				"min_scale": float(display.get("min_scale", 0.25)),
				"max_scale": float(display.get("max_scale", 2.0)),
				"alpha_hit_test_threshold": int(display.get("alpha_hit_test_threshold", 10)),
			},
			"animations": animations,
			"bindings": bindings,
			"fallbacks": fallbacks,
			"preview": normalized_root.path_join("preview.png"),
		},
	}


func _png_frames(animation_root: String) -> Array[String]:
	var frames: Array[String] = []
	var directory := DirAccess.open(animation_root)
	if directory == null:
		return frames
	for file in directory.get_files():
		if file.get_extension().to_lower() == "png":
			frames.append(animation_root.path_join(file))
	frames.sort_custom(func(left: String, right: String) -> bool: return left.get_file().naturalnocasecmp_to(right.get_file()) < 0)
	return frames


func _is_within_root(candidate: String, root: String) -> bool:
	var normalized_candidate := candidate.replace("\\", "/").to_lower()
	var normalized_root := root.replace("\\", "/").trim_suffix("/").to_lower()
	return normalized_candidate == normalized_root or normalized_candidate.begins_with(normalized_root + "/")


func _failure(message: String) -> Dictionary:
	return {"ok": false, "error": message}
