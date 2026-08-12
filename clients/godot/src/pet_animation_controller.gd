class_name PetNestAnimationController
extends RefCounted

var package: Dictionary
var action := "idle"
var frame_index := 0
var elapsed_ms := 0.0
var playing := true
var texture_cache: Dictionary = {}
var hit_polygon_cache: Dictionary = {}


func configure(new_package: Dictionary) -> void:
	package = new_package
	texture_cache.clear()
	hit_polygon_cache.clear()
	play("idle", true)


func play(new_action: String, restart := false) -> bool:
	var animations: Dictionary = package.get("animations", {})
	if not animations.has(new_action):
		return false
	var definition: Dictionary = animations[new_action]
	if action == new_action and not restart and not bool(definition.get("restart_on_reenter", false)):
		return false
	action = new_action
	frame_index = 0
	elapsed_ms = 0.0
	playing = true
	return true


func advance(delta: float) -> Dictionary:
	if not playing:
		return {"frame_changed": false, "completed": false}
	var definition: Dictionary = package["animations"][action]
	var frames: Array = definition["frames"]
	if frames.is_empty():
		return {"frame_changed": false, "completed": false}
	elapsed_ms += delta * 1000.0
	var changed := false
	while elapsed_ms >= _current_duration_ms(definition, frames.size()):
		elapsed_ms -= _current_duration_ms(definition, frames.size())
		frame_index += 1
		changed = true
		if frame_index >= frames.size():
			if bool(definition.get("loop", true)):
				frame_index = 0
			else:
				frame_index = frames.size() - 1
				playing = false
				return {"frame_changed": true, "completed": true}
	return {"frame_changed": changed, "completed": false}


func current_texture() -> Texture2D:
	var definition: Dictionary = package["animations"][action]
	var frames: Array = definition["frames"]
	if frames.is_empty():
		return null
	var path := str(frames[clampi(frame_index, 0, frames.size() - 1)])
	if texture_cache.has(path):
		return texture_cache[path]
	var image := Image.new()
	if image.load(path) != OK:
		push_warning("无法加载宠物帧：" + path)
		return null
	var texture := ImageTexture.create_from_image(image)
	texture_cache[path] = texture
	return texture


func current_frame_path() -> String:
	var definition: Dictionary = package["animations"][action]
	var frames: Array = definition["frames"]
	if frames.is_empty():
		return ""
	return str(frames[clampi(frame_index, 0, frames.size() - 1)])


func current_hit_polygon(alpha_threshold: int) -> PackedVector2Array:
	var definition: Dictionary = package["animations"][action]
	var frames: Array = definition["frames"]
	if frames.is_empty():
		return PackedVector2Array()
	var path := str(frames[clampi(frame_index, 0, frames.size() - 1)])
	var cache_key := "%s:%d" % [path, alpha_threshold]
	if hit_polygon_cache.has(cache_key):
		return hit_polygon_cache[cache_key]
	var image := Image.new()
	if image.load(path) != OK:
		return PackedVector2Array()
	var bitmap := BitMap.new()
	bitmap.create_from_image_alpha(image, clampf(float(alpha_threshold) / 255.0, 0.0, 1.0))
	var polygons := bitmap.opaque_to_polygons(Rect2i(Vector2i.ZERO, image.get_size()), 2.0)
	var selected := PackedVector2Array()
	var selected_area := 0.0
	for candidate in polygons:
		var area := absf(_polygon_area(candidate))
		if area > selected_area:
			selected_area = area
			selected = candidate
	if selected.is_empty():
		selected = PackedVector2Array([
			Vector2.ZERO,
			Vector2(image.get_width(), 0.0),
			Vector2(image.get_width(), image.get_height()),
			Vector2(0.0, image.get_height()),
		])
	hit_polygon_cache[cache_key] = selected
	return selected


func _polygon_area(points: PackedVector2Array) -> float:
	if points.size() < 3:
		return 0.0
	var area := 0.0
	for index in range(points.size()):
		var next_index := (index + 1) % points.size()
		area += points[index].x * points[next_index].y
		area -= points[next_index].x * points[index].y
	return area * 0.5


func _current_duration_ms(definition: Dictionary, frame_count: int) -> float:
	var durations = definition.get("frame_durations_ms", [])
	var base := 1000.0 / maxf(float(definition.get("fps", 8.0)), 0.1)
	if typeof(durations) == TYPE_ARRAY and durations.size() == frame_count:
		base = float(durations[clampi(frame_index, 0, durations.size() - 1)])
	return base / maxf(float(definition.get("speed_multiplier", 1.0)), 0.01)
