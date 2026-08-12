class_name PetNestEffectPlayer
extends RefCounted

const MAX_TEXTURE_DIMENSION := 480
const MAX_CACHED_TEXTURES := 12

var package: Dictionary = {}
var playing := false
var loop_enabled := false
var elapsed := 0.0
var frame_index := -1
var current_texture: Texture2D
var texture_cache: Dictionary = {}
var cache_order: Array[int] = []


func play(effect_package: Dictionary, loop_override = null) -> Dictionary:
	stop()
	if not bool(effect_package.get("ok", false)):
		return {"ok": false, "error": "动效包不可播放"}
	package = effect_package
	loop_enabled = bool(package.get("loop", true)) if loop_override == null else bool(loop_override)
	playing = true
	return advance(0.0)


func stop() -> void:
	package = {}
	playing = false
	loop_enabled = false
	elapsed = 0.0
	frame_index = -1
	current_texture = null
	texture_cache.clear()
	cache_order.clear()


func advance(delta: float) -> Dictionary:
	if not playing or package.is_empty():
		return {"frame_changed": false, "completed": false, "texture": current_texture}
	elapsed += maxf(delta, 0.0)
	var count := int(package.get("frame_count", 0))
	var fps := float(package.get("fps", 0.0))
	if count <= 0 or fps <= 0.0:
		stop()
		return {"frame_changed": false, "completed": true, "texture": null}
	var next_index := int(floor(elapsed * fps))
	if next_index >= count:
		if loop_enabled:
			next_index %= count
			elapsed = float(next_index) / fps
		else:
			stop()
			return {"frame_changed": true, "completed": true, "texture": null}
	if next_index == frame_index:
		return {"frame_changed": false, "completed": false, "texture": current_texture}
	frame_index = next_index
	current_texture = _texture_for(frame_index)
	if current_texture == null:
		stop()
		return {"frame_changed": true, "completed": true, "texture": null}
	return {"frame_changed": true, "completed": false, "texture": current_texture}


func _texture_for(index: int) -> Texture2D:
	if texture_cache.has(index):
		return texture_cache[index]
	var frames: Array = package.get("frames", [])
	if index < 0 or index >= frames.size():
		return null
	var image := Image.new()
	if image.load(str(frames[index])) != OK:
		return null
	var largest := maxi(image.get_width(), image.get_height())
	if largest > MAX_TEXTURE_DIMENSION:
		var ratio := float(MAX_TEXTURE_DIMENSION) / float(largest)
		image.resize(maxi(1, roundi(image.get_width() * ratio)), maxi(1, roundi(image.get_height() * ratio)), Image.INTERPOLATE_LANCZOS)
	var texture := ImageTexture.create_from_image(image)
	texture_cache[index] = texture
	cache_order.append(index)
	while cache_order.size() > MAX_CACHED_TEXTURES:
		texture_cache.erase(cache_order.pop_front())
	return texture
