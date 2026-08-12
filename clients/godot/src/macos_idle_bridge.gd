class_name PetNestMacOSIdleBridge
extends RefCounted

const EVENT_PORT := 18490

var event_socket := PacketPeerUDP.new()
var process_id := -1
var running := false
var ready := false


func start() -> Error:
	if OS.get_name() != "macOS":
		return ERR_UNAVAILABLE
	if running:
		return OK
	var helper := _helper_path()
	if not FileAccess.file_exists(helper):
		return ERR_FILE_NOT_FOUND
	var error := event_socket.bind(EVENT_PORT, "127.0.0.1")
	if error != OK:
		return error
	process_id = OS.create_process(
		helper,
		PackedStringArray([
			"--event-port", str(EVENT_PORT),
			"--host-process-id", str(OS.get_process_id()),
		]),
		false
	)
	if process_id <= 0:
		event_socket.close()
		return ERR_CANT_FORK
	running = true
	ready = false
	return OK


func stop() -> void:
	if not running:
		return
	if process_id > 0:
		OS.kill(process_id)
	event_socket.close()
	process_id = -1
	running = false
	ready = false


func poll() -> Array[Dictionary]:
	var events: Array[Dictionary] = []
	while event_socket.get_available_packet_count() > 0:
		var parts := event_socket.get_packet().get_string_from_utf8().strip_edges().split("\t")
		if parts.is_empty():
			continue
		if parts[0] == "READY":
			ready = true
		elif parts[0] == "IDLE" and parts.size() >= 2:
			events.append({
				"kind": "idle",
				"idle_seconds": maxf(0.0, float(int(parts[1])) / 1000.0),
			})
	return events


func _helper_path() -> String:
	var configured := OS.get_environment("PETNEST_MACOS_IDLE_HELPER").strip_edges()
	if not configured.is_empty():
		return configured.simplify_path()
	return OS.get_executable_path().get_base_dir().path_join("..").path_join("Helpers").path_join("macos-idle-bridge").simplify_path()
