class_name PetNestStateMachine
extends RefCounted

var package: Dictionary
var current_action := "idle"
var mouse_over := false


func configure(new_package: Dictionary) -> void:
	package = new_package
	current_action = "idle"
	mouse_over = false


func handle(event_name: String, event_priority := 0, forced := false) -> String:
	if event_name == "mouse.enter":
		mouse_over = true
	elif event_name == "mouse.leave":
		mouse_over = false
	var bindings: Dictionary = package.get("bindings", {})
	var requested := str(bindings.get(event_name, ""))
	if requested.is_empty():
		if event_name == "mouse.leave":
			requested = _context_action()
		else:
			return ""
	var target := resolve(requested)
	if target.is_empty() or target == current_action:
		return ""
	var animations: Dictionary = package["animations"]
	var current: Dictionary = animations[current_action]
	var target_definition: Dictionary = animations[target]
	if not forced and not bool(current.get("interruptible", true)):
		if maxi(event_priority, int(target_definition.get("priority", 0))) < int(current.get("priority", 0)):
			return ""
	current_action = target
	return target


func force_action(requested: String) -> String:
	var target := resolve(requested)
	if target.is_empty():
		return ""
	current_action = target
	return target


func complete() -> String:
	var animations: Dictionary = package["animations"]
	var definition: Dictionary = animations[current_action]
	if bool(definition.get("loop", true)):
		return ""
	var requested := str(definition.get("next", ""))
	var target := _context_action() if requested.is_empty() or requested == "context" else resolve(requested)
	if target.is_empty() or target == current_action:
		return ""
	current_action = target
	return target


func resolve(requested: String) -> String:
	return _resolve(requested, {})


func _resolve(requested: String, seen: Dictionary) -> String:
	if requested.is_empty() or seen.has(requested):
		return ""
	seen[requested] = true
	var animations: Dictionary = package.get("animations", {})
	if animations.has(requested):
		return requested
	var fallbacks: Dictionary = package.get("fallbacks", {})
	var candidates = fallbacks.get(requested, [])
	if typeof(candidates) == TYPE_ARRAY:
		for candidate in candidates:
			var resolved := _resolve(str(candidate), seen)
			if not resolved.is_empty():
				return resolved
	return "idle" if animations.has("idle") else ""


func _context_action() -> String:
	return resolve("hover" if mouse_over else "idle")

