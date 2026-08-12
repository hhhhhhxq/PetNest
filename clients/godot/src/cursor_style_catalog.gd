class_name PetNestCursorStyleCatalog
extends RefCounted

const STYLE_ID_PATTERN := "^[A-Za-z0-9_-]{1,64}$"
const OPTIONAL_ROLES := ["busy", "text", "move", "resize_horizontal", "resize_vertical", "resize_diag_1", "resize_diag_2"]


func discover(roots: Array[String]) -> Array[Dictionary]:
	var styles: Array[Dictionary] = []
	var seen := {}
	for root in roots:
		if not DirAccess.dir_exists_absolute(root):
			continue
		var directories := DirAccess.get_directories_at(root)
		directories.sort()
		for directory in directories:
			var style := load_style(root.path_join(directory))
			if not bool(style.get("ok", false)):
				continue
			var identifier := str(style.get("id", ""))
			if seen.has(identifier):
				continue
			seen[identifier] = true
			styles.append(style)
	return styles


func load_style(root: String) -> Dictionary:
	var normalized := root.simplify_path()
	var manifest_path := normalized.path_join("style.json")
	if not FileAccess.file_exists(manifest_path):
		return _failure("鼠标样式缺少 style.json")
	var parsed = JSON.parse_string(FileAccess.get_file_as_string(manifest_path))
	if typeof(parsed) != TYPE_DICTIONARY:
		return _failure("style.json 必须是 JSON 对象")
	var raw: Dictionary = parsed
	var identifier := str(raw.get("id", ""))
	var pattern := RegEx.new()
	pattern.compile(STYLE_ID_PATTERN)
	if identifier != normalized.get_file() or pattern.search(identifier) == null:
		return _failure("鼠标样式 ID 无效")
	var arrow_name := str(raw.get("arrow", ""))
	if arrow_name.get_file() != arrow_name or arrow_name.get_extension().to_lower() != "cur":
		return _failure("普通箭头文件无效")
	var arrow_path := normalized.path_join(arrow_name)
	if not FileAccess.file_exists(arrow_path):
		return _failure("普通箭头文件不存在")
	var roles := {"arrow": arrow_path}
	for role in OPTIONAL_ROLES:
		var role_path := normalized.path_join(role + ".cur")
		if FileAccess.file_exists(role_path):
			roles[role] = role_path
	return {
		"ok": true,
		"id": identifier,
		"name": str(raw.get("name", identifier)).strip_edges(),
		"root": normalized,
		"roles": roles,
	}


func default_roots() -> Array[String]:
	var candidates: Array[String] = []
	var settings_root := _settings_root()
	if not settings_root.is_empty():
		var cache_root := settings_root.path_join("remote-resources")
		var pointer_path := cache_root.path_join("current.json")
		if FileAccess.file_exists(pointer_path):
			var pointer = JSON.parse_string(FileAccess.get_file_as_string(pointer_path))
			if typeof(pointer) == TYPE_DICTIONARY:
				var version_id := str(pointer.get("version_id", ""))
				var version_pattern := RegEx.new()
				version_pattern.compile("^[A-Za-z0-9._-]{1,128}$")
				if version_pattern.search(version_id) != null:
					candidates.append(cache_root.path_join("versions").path_join(version_id).path_join("resources").path_join("cursors").simplify_path())
	if OS.has_feature("editor"):
		candidates.append(ProjectSettings.globalize_path("res://../../assets/cursors").simplify_path())
	var executable_directory := OS.get_executable_path().get_base_dir()
	for candidate in [
		executable_directory.path_join("cursors"),
		executable_directory.path_join("..").path_join("Resources").path_join("cursors"),
		executable_directory.path_join("..").path_join("_internal").path_join("assets").path_join("cursors"),
		executable_directory.path_join("_internal").path_join("assets").path_join("cursors"),
	]:
		candidates.append(candidate.simplify_path())
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


func find(styles: Array[Dictionary], identifier: String) -> Dictionary:
	for style in styles:
		if str(style.get("id", "")) == identifier:
			return style
	return {}


func _failure(message: String) -> Dictionary:
	return {"ok": false, "error": message}
