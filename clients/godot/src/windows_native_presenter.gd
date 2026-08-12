class_name PetNestWindowsNativePresenter
extends RefCounted

const COMMAND_PORT := 18488
const EVENT_PORT := 18489

var command_socket := PacketPeerUDP.new()
var event_socket := PacketPeerUDP.new()
var process_id := -1
var running := false
var ready := false
var last_frame_command := ""
var last_countdown_command := ""
var desired_visible := true
var desired_always_on_top := true
var desired_cursor_enabled := false
var desired_cursor_root := ""


func start() -> Error:
	if OS.get_name() != "Windows":
		return ERR_UNAVAILABLE
	if running:
		return OK
	var script_path := _script_path()
	if not FileAccess.file_exists(script_path):
		return ERR_FILE_NOT_FOUND
	var error := event_socket.bind(EVENT_PORT, "127.0.0.1")
	if error != OK:
		return error
	error = command_socket.set_dest_address("127.0.0.1", COMMAND_PORT)
	if error != OK:
		event_socket.close()
		return error
	var powershell := OS.get_environment("SystemRoot").path_join("System32").path_join("WindowsPowerShell").path_join("v1.0").path_join("powershell.exe")
	if not FileAccess.file_exists(powershell):
		powershell = "powershell.exe"
	process_id = OS.create_process(
		powershell,
		PackedStringArray([
			"-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
			"-ExecutionPolicy", "Bypass", "-File", script_path,
			"-CommandPort", str(COMMAND_PORT), "-EventPort", str(EVENT_PORT),
			"-HostProcessId", str(OS.get_process_id()),
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
	_send("QUIT")
	event_socket.close()
	command_socket.close()
	process_id = -1
	running = false
	ready = false
	last_frame_command = ""
	last_countdown_command = ""


func poll() -> Array[Dictionary]:
	var events: Array[Dictionary] = []
	while event_socket.get_available_packet_count() > 0:
		var line := event_socket.get_packet().get_string_from_utf8().strip_edges()
		var parts := line.split("\t")
		if parts.is_empty():
			continue
		var kind := str(parts[0])
		if kind == "READY":
			ready = true
			last_frame_command = ""
			last_countdown_command = ""
			_send("VISIBLE\t%d" % (1 if desired_visible else 0))
			_send("TOPMOST\t%d" % (1 if desired_always_on_top else 0))
			_send_cursor_command()
			continue
		if kind in ["DOWN", "UP", "MOVE", "DOUBLE"] and parts.size() >= 4:
			events.append({
				"kind": kind.to_lower(),
				"button": int(parts[1]),
				"global_position": Vector2(float(parts[2]), float(parts[3])),
			})
		elif kind in ["ENTER", "LEAVE", "CLOSED"]:
			events.append({"kind": kind.to_lower()})
		elif kind == "IDLE" and parts.size() >= 2:
			events.append({
				"kind": "idle",
				"idle_seconds": maxf(0.0, float(int(parts[1])) / 1000.0),
			})
		elif kind == "CURSOR_APPLIED" and parts.size() >= 2:
			events.append({"kind": "cursor_applied", "applied": parts[1] == "1"})
		elif kind == "ERROR" and parts.size() >= 2:
			events.append({
				"kind": "error",
				"message": Marshalls.base64_to_utf8(str(parts[1])),
			})
	return events


func present(frame_path: String, global_rect: Rect2i, flip_h: bool) -> void:
	if not running or not ready or frame_path.is_empty():
		return
	var encoded_path := Marshalls.utf8_to_base64(frame_path)
	var command := "FRAME\t%s\t%d\t%d\t%d\t%d\t%d" % [
		encoded_path,
		global_rect.position.x,
		global_rect.position.y,
		global_rect.size.x,
		global_rect.size.y,
		1 if flip_h else 0,
	]
	if command == last_frame_command:
		return
	last_frame_command = command
	_send(command)


func present_countdown(text: String, global_rect: Rect2i, theme: String, visible: bool) -> void:
	if not running or not ready:
		return
	var command := "COUNTDOWN\t%s\t%d\t%d\t%d\t%d\t%s\t%d" % [
		Marshalls.utf8_to_base64(text),
		global_rect.position.x,
		global_rect.position.y,
		global_rect.size.x,
		global_rect.size.y,
		theme,
		1 if visible else 0,
	]
	if command == last_countdown_command:
		return
	last_countdown_command = command
	_send(command)


func set_visible(value: bool) -> void:
	desired_visible = value
	if ready:
		_send("VISIBLE\t%d" % (1 if value else 0))


func set_always_on_top(value: bool) -> void:
	desired_always_on_top = value
	if ready:
		_send("TOPMOST\t%d" % (1 if value else 0))


func set_cursor_style(enabled: bool, root: String = "") -> void:
	desired_cursor_enabled = enabled
	desired_cursor_root = root.simplify_path() if enabled else ""
	if ready:
		_send_cursor_command()


func focus_host_popup() -> void:
	if running and ready:
		_send("FOCUS_POPUP")


func _send_cursor_command() -> void:
	if desired_cursor_enabled and not desired_cursor_root.is_empty():
		_send("CURSOR\t1\t%s" % Marshalls.utf8_to_base64(desired_cursor_root))
	else:
		_send("CURSOR\t0")


func _send(message: String) -> void:
	if not running:
		return
	command_socket.put_packet(message.to_utf8_buffer())


func _script_path() -> String:
	if OS.has_feature("editor"):
		return ProjectSettings.globalize_path("res://windows-native-presenter.ps1")
	return OS.get_executable_path().get_base_dir().path_join("windows-native-presenter.ps1")
