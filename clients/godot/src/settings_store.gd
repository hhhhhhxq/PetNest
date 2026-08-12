class_name PetNestSettingsStore
extends RefCounted

const DEFAULTS := {
	"schema_version": 18,
	"current_pet_id": "",
	"scale": 1.0,
	"always_on_top": true,
	"animation_paused": false,
	"mouse_interaction_enabled": true,
	"external_event_server_enabled": false,
	"external_event_port": 18486,
	"lan_interaction_enabled": true,
	"system_idle_enabled": true,
	"system_bored_seconds": 20,
	"system_sleep_seconds": 35,
	"run_at_startup": false,
	"pets_root": "",
	"nickname": "",
	"device_id": "",
	"work_countdown_enabled": true,
	"work_start_time": "09:00",
	"work_end_time": "18:00",
	"countdown_placement": "above",
	"daily_work_end_times": {
		"0": "18:00", "1": "18:00", "2": "18:00", "3": "18:00", "4": "18:00", "5": null, "6": null,
	},
	"mouse_follow_enabled": false,
	"mouse_follow_scale": 0.45,
	"cursor_style_enabled": false,
	"cursor_style_id": "",
	"cursor_restore_pending": false,
	"godot_auto_walk": true,
	"godot_power_saver": false,
	"godot_pet_x": -1.0,
	"godot_pet_y": -1.0,
	"godot_position_space_version": 0,
	"godot_renderer_max_fps": 240,
	"preferred_client": "pyside6",
}

const INTEGER_KEYS := [
	"schema_version",
	"window_x",
	"window_y",
	"external_event_port",
	"system_idle_seconds",
	"system_bored_seconds",
	"system_sleep_seconds",
	"countdown_gap",
	"countdown_width",
	"countdown_height",
	"godot_renderer_max_fps",
	"godot_position_space_version",
]

var path: String


func _init(custom_path := "") -> void:
	path = custom_path if not custom_path.is_empty() else default_path()


static func default_path() -> String:
	if OS.get_name() == "Windows":
		var appdata := OS.get_environment("APPDATA")
		if not appdata.is_empty():
			return appdata.path_join("PetNest").path_join("settings.json")
	if OS.get_name() == "macOS":
		return _macos_application_support_root().path_join("settings.json")
	return ProjectSettings.globalize_path("user://settings.json")


static func _macos_application_support_root() -> String:
	var home := OS.get_environment("HOME").strip_edges()
	if not home.is_empty():
		return home.path_join("Library").path_join("Application Support").path_join("PetNest")
	return ProjectSettings.globalize_path("user://").get_base_dir()


func load_settings() -> Dictionary:
	var settings := DEFAULTS.duplicate(true)
	if not FileAccess.file_exists(path):
		return settings
	var parsed = JSON.parse_string(FileAccess.get_file_as_string(path))
	if typeof(parsed) != TYPE_DICTIONARY:
		push_warning("PetNest settings.json 不是 JSON 对象，Godot 客户端将使用默认设置")
		return settings
	for key in parsed:
		settings[key] = parsed[key]
	settings["schema_version"] = DEFAULTS["schema_version"]
	return settings


func save_settings(settings: Dictionary) -> Error:
	var error := DirAccess.make_dir_recursive_absolute(path.get_base_dir())
	if error != OK:
		return error
	var temporary := path + ".godot.tmp"
	var backup := path + ".godot.bak"
	var file := FileAccess.open(temporary, FileAccess.WRITE)
	if file == null:
		return FileAccess.get_open_error()
	file.store_string(JSON.stringify(_normalized_for_save(settings), "  ") + "\n")
	file.flush()
	file.close()
	if FileAccess.file_exists(backup):
		DirAccess.remove_absolute(backup)
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


func _normalized_for_save(settings: Dictionary) -> Dictionary:
	var normalized := settings.duplicate(true)
	for key in INTEGER_KEYS:
		if normalized.has(key) and normalized[key] != null:
			normalized[key] = int(normalized[key])
	return normalized


func resolve_pets_root(settings: Dictionary) -> String:
	var environment_root := OS.get_environment("PETNEST_PETS_ROOT").strip_edges()
	if not environment_root.is_empty():
		return environment_root.simplify_path()
	var configured_value = settings.get("pets_root", "")
	var configured := str(configured_value).strip_edges() if configured_value != null else ""
	if not configured.is_empty():
		return configured.simplify_path()
	if OS.has_feature("editor"):
		return ProjectSettings.globalize_path("res://../../pets").simplify_path()
	var executable_directory := OS.get_executable_path().get_base_dir()
	for portable_root in [
		executable_directory.path_join("pets").simplify_path(),
		executable_directory.path_join("..").path_join("pets").simplify_path(),
		executable_directory.path_join("..").path_join("..").path_join("pets").simplify_path(),
	]:
		if DirAccess.dir_exists_absolute(portable_root):
			return portable_root
	if OS.get_name() == "Windows":
		var local_appdata := OS.get_environment("LOCALAPPDATA")
		if not local_appdata.is_empty():
			return local_appdata.path_join("PetNest").path_join("pets")
	if OS.get_name() == "macOS":
		return _macos_application_support_root().path_join("pets")
	return ProjectSettings.globalize_path("user://pets")


func ensure_pet_library(root: String) -> Error:
	var error := DirAccess.make_dir_recursive_absolute(root)
	if error != OK:
		return error
	var installed_sample := root.path_join("sample_pet").path_join("pet.json")
	if FileAccess.file_exists(installed_sample):
		return OK
	var source := _bundled_sample_root()
	if source.is_empty():
		return ERR_FILE_NOT_FOUND
	return _copy_directory(source, root.path_join("sample_pet"))


func _bundled_sample_root() -> String:
	var candidates: Array[String] = []
	if OS.has_feature("editor"):
		candidates.append(ProjectSettings.globalize_path("res://../../pets/sample_pet").simplify_path())
	var executable_directory := OS.get_executable_path().get_base_dir()
	for candidate in [
		executable_directory.path_join("..").path_join("Resources").path_join("pets").path_join("sample_pet"),
		executable_directory.path_join("pets").path_join("sample_pet"),
	]:
		candidates.append(candidate.simplify_path())
	for candidate in candidates:
		if FileAccess.file_exists(candidate.path_join("pet.json")):
			return candidate
	return ""


func _copy_directory(source: String, destination: String) -> Error:
	var error := DirAccess.make_dir_recursive_absolute(destination)
	if error != OK:
		return error
	for file_name in DirAccess.get_files_at(source):
		error = DirAccess.copy_absolute(source.path_join(file_name), destination.path_join(file_name))
		if error != OK:
			return error
	for directory_name in DirAccess.get_directories_at(source):
		error = _copy_directory(source.path_join(directory_name), destination.path_join(directory_name))
		if error != OK:
			return error
	return OK
