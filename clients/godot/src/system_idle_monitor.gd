class_name PetNestSystemIdleMonitor
extends RefCounted

enum IdleState { ACTIVE, BORED, SLEEPING }

var bored_seconds := 20.0
var sleep_seconds := 35.0
var state := IdleState.ACTIVE


func configure(new_bored_seconds: float, new_sleep_seconds: float) -> void:
	bored_seconds = maxf(new_bored_seconds, 1.0)
	sleep_seconds = maxf(new_sleep_seconds, bored_seconds + 1.0)
	state = IdleState.ACTIVE


func update(idle_seconds: float) -> String:
	var target := IdleState.ACTIVE
	if idle_seconds >= sleep_seconds:
		target = IdleState.SLEEPING
	elif idle_seconds >= bored_seconds:
		target = IdleState.BORED
	if target == state:
		return ""
	state = target
	if target == IdleState.BORED:
		return "system.bored"
	if target == IdleState.SLEEPING:
		return "system.sleep"
	return "system.wake"

