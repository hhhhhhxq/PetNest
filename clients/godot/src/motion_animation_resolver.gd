class_name PetNestMotionAnimationResolver
extends RefCounted


static func cursor_lower_right_target(mouse_position: Vector2, pet_half_size: Vector2, desktop_size: Vector2, gap: float) -> Vector2:
	var desired := mouse_position + pet_half_size + Vector2.ONE * maxf(gap, 0.0)
	return Vector2(
		clampf(desired.x, pet_half_size.x, maxf(pet_half_size.x, desktop_size.x - pet_half_size.x)),
		clampf(desired.y, pet_half_size.y, maxf(pet_half_size.y, desktop_size.y - pet_half_size.y))
	)


static func resolve(animations: Dictionary, axis: String, direction: float) -> Dictionary:
	if axis == "vertical":
		var candidates := ["walk_up", "drag_up", "jump", "drop", "working"] if direction < 0.0 else ["walk_down", "drag_down", "drop", "jump", "working"]
		return {"action": _first_available(animations, candidates), "flip_h": false}

	var directional := ["walk_left", "drag_left", "codex_running_left"] if direction < 0.0 else ["walk_right", "drag_right"]
	var selected := _first_available(animations, directional)
	if not selected.is_empty():
		return {"action": selected, "flip_h": false}

	selected = _first_available(animations, ["walk", "drag"])
	if not selected.is_empty():
		return {"action": selected, "flip_h": direction < 0.0}

	var opposite := ["walk_right", "drag_right"] if direction < 0.0 else ["walk_left", "drag_left", "codex_running_left"]
	selected = _first_available(animations, opposite)
	return {"action": selected, "flip_h": not selected.is_empty()}


static func resolve_drag(animations: Dictionary, direction: float) -> Dictionary:
	var directional := ["drag_left"] if direction < 0.0 else ["drag_right"]
	var selected := _first_available(animations, directional)
	if not selected.is_empty():
		return {"action": selected, "flip_h": false}

	selected = _first_available(animations, ["drag"])
	if not selected.is_empty():
		return {"action": selected, "flip_h": direction < 0.0}

	var opposite := ["drag_right"] if direction < 0.0 else ["drag_left"]
	selected = _first_available(animations, opposite)
	return {"action": selected, "flip_h": not selected.is_empty()}


static func _first_available(animations: Dictionary, candidates: Array) -> String:
	for candidate in candidates:
		if animations.has(candidate):
			return str(candidate)
	return ""
