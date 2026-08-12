class_name PetNestExternalEventServer
extends RefCounted

const MAX_MESSAGE_BYTES := 4096
const MAX_EVENTS_PER_SECOND := 30
const ALLOWED_FIELDS := {"event": true, "source": true, "payload": true, "priority": true}

var server := TCPServer.new()
var clients: Array[StreamPeerTCP] = []
var buffers: Dictionary = {}
var accepted_at_ms: Array[int] = []
var listening := false


func start(port: int) -> Error:
	stop()
	var error := server.listen(port, "127.0.0.1")
	listening = error == OK
	return error


func stop() -> void:
	for client in clients:
		client.disconnect_from_host()
	clients.clear()
	buffers.clear()
	accepted_at_ms.clear()
	server.stop()
	listening = false


func poll() -> Array[Dictionary]:
	var events: Array[Dictionary] = []
	if not listening:
		return events
	while server.is_connection_available():
		var peer := server.take_connection()
		if peer != null:
			clients.append(peer)
			buffers[peer.get_instance_id()] = ""
	for client in clients.duplicate():
		client.poll()
		var status: int = client.get_status()
		if status == StreamPeerTCP.STATUS_NONE or status == StreamPeerTCP.STATUS_ERROR:
			_remove_client(client)
			continue
		var available: int = client.get_available_bytes()
		if available <= 0:
			continue
		var identifier: int = client.get_instance_id()
		var buffer: String = str(buffers.get(identifier, "")) + client.get_utf8_string(available)
		if buffer.to_utf8_buffer().size() > MAX_MESSAGE_BYTES and not buffer.contains("\n"):
			_remove_client(client)
			continue
		while buffer.contains("\n"):
			var newline: int = buffer.find("\n")
			var line: String = buffer.substr(0, newline).strip_edges()
			buffer = buffer.substr(newline + 1)
			if line.is_empty():
				continue
			if line.to_utf8_buffer().size() > MAX_MESSAGE_BYTES:
				continue
			var parsed = JSON.parse_string(line)
			var validated := _validated_event(parsed)
			if not validated.is_empty() and _allow_event():
				events.append(validated)
		buffers[identifier] = buffer
	return events


func _remove_client(client: StreamPeerTCP) -> void:
	buffers.erase(client.get_instance_id())
	clients.erase(client)
	client.disconnect_from_host()


func _validated_event(parsed) -> Dictionary:
	if typeof(parsed) != TYPE_DICTIONARY:
		return {}
	for key in parsed:
		if not ALLOWED_FIELDS.has(str(key)):
			return {}
	var event_name = parsed.get("event", null)
	var source = parsed.get("source", "external")
	var payload = parsed.get("payload", {})
	var priority = parsed.get("priority", 0)
	if typeof(event_name) != TYPE_STRING or event_name.is_empty() or event_name.length() > 128:
		return {}
	if typeof(source) != TYPE_STRING or source.is_empty() or source.length() > 128:
		return {}
	if typeof(payload) != TYPE_DICTIONARY or typeof(priority) == TYPE_BOOL or typeof(priority) not in [TYPE_INT, TYPE_FLOAT]:
		return {}
	if typeof(priority) == TYPE_FLOAT and float(priority) != floorf(float(priority)):
		return {}
	return {
		"event": event_name,
		"source": source,
		"payload": payload,
		"priority": int(priority),
	}


func _allow_event() -> bool:
	var now := Time.get_ticks_msec()
	while not accepted_at_ms.is_empty() and now - accepted_at_ms[0] >= 1000:
		accepted_at_ms.pop_front()
	if accepted_at_ms.size() >= MAX_EVENTS_PER_SECOND:
		return false
	accepted_at_ms.append(now)
	return true
