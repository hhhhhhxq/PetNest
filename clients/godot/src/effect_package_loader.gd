class_name PetNestEffectPackageLoader
extends RefCounted

const EFFECT_ID_PATTERN := "^[a-z][a-z0-9_-]{0,63}$"


func discover(roots: Array[String]) -> Array[Dictionary]:
	var packages: Array[Dictionary] = []
	var seen := {}
	for root in roots:
		if not DirAccess.dir_exists_absolute(root):
			continue
		var directories := DirAccess.get_directories_at(root)
		directories.sort()
		for directory in directories:
			var package := load_package(root.path_join(directory))
			if not bool(package.get("ok", false)):
				continue
			var identifier := str(package.get("id", ""))
			if seen.has(identifier):
				continue
			seen[identifier] = true
			packages.append(package)
	return packages


func load_package(root: String) -> Dictionary:
	var normalized := root.simplify_path()
	var manifest_path := normalized.path_join("effect.json")
	if not FileAccess.file_exists(manifest_path):
		return _failure("动效包缺少 effect.json")
	var parsed = JSON.parse_string(FileAccess.get_file_as_string(manifest_path))
	if typeof(parsed) != TYPE_DICTIONARY:
		return _failure("effect.json 必须是 JSON 对象")
	var raw: Dictionary = parsed
	if int(raw.get("schema_version", 0)) != 1:
		return _failure("动效包版本不受支持")
	var identifier := str(raw.get("id", ""))
	var id_regex := RegEx.new()
	if id_regex.compile(EFFECT_ID_PATTERN) != OK or id_regex.search(identifier) == null:
		return _failure("动效 ID 无效")
	var frames_name := str(raw.get("frames", "frames"))
	if frames_name.is_empty() or frames_name.is_absolute_path() or frames_name.contains(".."):
		return _failure("动效帧目录无效")
	var frames_root := normalized.path_join(frames_name).simplify_path()
	if not DirAccess.dir_exists_absolute(frames_root):
		return _failure("动效帧目录不存在")
	var frame_names: Array[String] = []
	for file_name in DirAccess.get_files_at(frames_root):
		if file_name.get_extension().to_lower() == "png":
			frame_names.append(file_name)
	frame_names.sort_custom(func(left: String, right: String) -> bool: return left.naturalnocasecmp_to(right) < 0)
	var expected_count := int(raw.get("frame_count", 0))
	var width := int(raw.get("width", 0))
	var height := int(raw.get("height", 0))
	var fps := float(raw.get("fps", 0.0))
	if expected_count <= 0 or frame_names.size() != expected_count:
		return _failure("动效帧数与清单不一致")
	if width <= 0 or height <= 0 or width > 4096 or height > 4096 or fps <= 0.0 or fps > 240.0:
		return _failure("动效尺寸或帧率无效")
	var frames: Array[String] = []
	for file_name in frame_names:
		frames.append(frames_root.path_join(file_name))
	return {
		"ok": true,
		"root": normalized,
		"id": identifier,
		"name": str(raw.get("name", identifier)),
		"width": width,
		"height": height,
		"fps": fps,
		"frame_count": expected_count,
		"duration_ms": int(raw.get("duration_ms", roundi(float(expected_count) / fps * 1000.0))),
		"loop": bool(raw.get("loop", true)),
		"layer": "under" if str(raw.get("layer", "over")) == "under" else "over",
		"frames": frames,
	}


func default_roots(pets_root: String) -> Array[String]:
	var candidates: Array[String] = [pets_root.get_base_dir().path_join("effects").simplify_path()]
	if OS.has_feature("editor"):
		candidates.append(ProjectSettings.globalize_path("res://../../effects").simplify_path())
	var executable_directory := OS.get_executable_path().get_base_dir()
	for candidate in [
		executable_directory.path_join("effects"),
		executable_directory.path_join("..").path_join("Resources").path_join("effects"),
		executable_directory.path_join("..").path_join("effects"),
		executable_directory.path_join("..").path_join("..").path_join("effects"),
	]:
		candidates.append(candidate.simplify_path())
	var settings_root := _settings_root()
	if not settings_root.is_empty():
		var cache_root := settings_root.path_join("remote-resources")
		var pointer_path := cache_root.path_join("current.json")
		if FileAccess.file_exists(pointer_path):
			var pointer = JSON.parse_string(FileAccess.get_file_as_string(pointer_path))
			if typeof(pointer) == TYPE_DICTIONARY:
				var version_id := str(pointer.get("version_id", ""))
				var version_regex := RegEx.new()
				version_regex.compile("^[A-Za-z0-9._-]{1,128}$")
				if version_regex.search(version_id) != null:
					candidates.append(cache_root.path_join("versions").path_join(version_id).path_join("resources").path_join("effects").simplify_path())
	var roots: Array[String] = []
	for candidate in candidates:
		if not roots.has(candidate):
			roots.append(candidate)
	return roots


func _settings_root() -> String:
	if OS.get_name() == "Windows":
		var appdata := OS.get_environment("APPDATA")
		return appdata.path_join("PetNest") if not appdata.is_empty() else ""
	if OS.get_name() == "macOS":
		var home := OS.get_environment("HOME")
		return home.path_join("Library").path_join("Application Support").path_join("PetNest") if not home.is_empty() else ""
	return ProjectSettings.globalize_path("user://").get_base_dir()


func _failure(message: String) -> Dictionary:
	return {"ok": false, "error": message}
