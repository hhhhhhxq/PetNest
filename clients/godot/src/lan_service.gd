class_name PetNestLanService
extends RefCounted

signal peer_changed(peer: Dictionary)
signal peer_removed(device_id: String)
signal interaction_received(interaction: Dictionary)
signal status_changed(message: String)

const Protocol = preload("res://src/lan_protocol.gd")
const ANNOUNCE_SECONDS := 8.0
const PEER_EXPIRY_SECONDS := 24.0

var socket := PacketPeerUDP.new()
var running := false
var port := Protocol.PORT
var device_id := ""
var display_name := ""
var pet_name := "Pet"
var peers: Dictionary = {}
var peer_seen_at: Dictionary = {}
var interaction_times: Dictionary = {}
var announce_elapsed := 0.0
var expiry_elapsed := 0.0


func configure(local_device_id: String, local_display_name: String, local_pet_name: String) -> void:
	device_id = local_device_id.strip_edges()
	display_name = local_display_name.strip_edges()
	pet_name = local_pet_name.strip_edges()
	if running:
		discover()


func start(requested_port := Protocol.PORT) -> Error:
	if running:
		return OK
	port = requested_port
	var error := socket.bind(port, "0.0.0.0")
	if error != OK:
		status_changed.emit("无法监听 UDP %d：%s" % [port, error_string(error)])
		return error
	socket.set_broadcast_enabled(true)
	running = true
	announce_elapsed = ANNOUNCE_SECONDS
	discover()
	return OK


func stop() -> void:
	if running:
		socket.close()
	running = false
	peers.clear()
	peer_seen_at.clear()
	interaction_times.clear()


func poll(delta: float) -> void:
	if not running:
		return
	announce_elapsed += delta
	expiry_elapsed += delta
	if announce_elapsed >= ANNOUNCE_SECONDS:
		announce_elapsed = 0.0
		discover()
	while socket.get_available_packet_count() > 0:
		var packet := socket.get_packet()
		var source_ip := socket.get_packet_ip()
		var source_port := socket.get_packet_port()
		_handle_packet(packet, source_ip, source_port)
	if expiry_elapsed >= 4.0:
		expiry_elapsed = 0.0
		_expire_peers()


func discover() -> bool:
	if not running:
		return false
	return _send(Protocol.hello(device_id, display_name, pet_name, port), "255.255.255.255", port)


func probe(ip_address: String, remote_port := Protocol.PORT) -> bool:
	if not running or not ip_address.is_valid_ip_address() or remote_port < 1 or remote_port > 65535:
		status_changed.emit("请输入有效的 IPv4 地址和端口")
		return false
	return _send(Protocol.hello(device_id, display_name, pet_name, port), ip_address, remote_port)


func send_interaction(target_device_id: String, interaction_type: String, text := "", effect_id := "") -> bool:
	if not running or not peers.has(target_device_id):
		status_changed.emit("目标设备已离线，请刷新附近设备")
		return false
	var peer: Dictionary = peers[target_device_id]
	var packet := Protocol.interaction(target_device_id, interaction_type, device_id, display_name, text, effect_id)
	var encoded := Protocol.encode(packet)
	if not bool(Protocol.decode_interaction(encoded, target_device_id).get("ok", false)):
		status_changed.emit("互动内容无效")
		return false
	return _send(packet, str(peer.get("ip_address", "")), int(peer.get("port", 0)))


func peer_list() -> Array[Dictionary]:
	var result: Array[Dictionary] = []
	for peer in peers.values():
		result.append(peer)
	result.sort_custom(func(left: Dictionary, right: Dictionary) -> bool: return str(left.get("display_name", "")).naturalnocasecmp_to(str(right.get("display_name", ""))) < 0)
	return result


func _handle_packet(data: PackedByteArray, source_ip: String, _source_port: int) -> void:
	var presence := Protocol.decode_presence(data)
	if bool(presence.get("ok", false)):
		var remote_device_id := str(presence.get("device_id", ""))
		if remote_device_id == device_id:
			return
		var peer := {
			"device_id": remote_device_id,
			"display_name": str(presence.get("display_name", "")),
			"pet_name": str(presence.get("pet_name", "")),
			"ip_address": source_ip,
			"port": int(presence.get("port", Protocol.PORT)),
			"capabilities": presence.get("capabilities", []),
		}
		var changed: bool = not peers.has(remote_device_id) or peers[remote_device_id] != peer
		peers[remote_device_id] = peer
		peer_seen_at[remote_device_id] = Time.get_ticks_msec()
		if changed:
			peer_changed.emit(peer)
		if str(presence.get("kind", "")) == "hello":
			_send(Protocol.hello(device_id, display_name, pet_name, port, "hello_ack"), source_ip, int(presence.get("port", Protocol.PORT)))
		return
	var interaction := Protocol.decode_interaction(data, device_id)
	if bool(interaction.get("ok", false)) and _allow_interaction(str(interaction.get("sender_device_id", ""))):
		interaction_received.emit(interaction)


func _allow_interaction(sender_device_id: String) -> bool:
	var now := Time.get_ticks_msec()
	var recent: Array = interaction_times.get(sender_device_id, [])
	var retained: Array[int] = []
	for timestamp in recent:
		if now - int(timestamp) < 60000:
			retained.append(int(timestamp))
	if retained.size() >= 30:
		interaction_times[sender_device_id] = retained
		return false
	retained.append(now)
	interaction_times[sender_device_id] = retained
	return true


func _expire_peers() -> void:
	var now := Time.get_ticks_msec()
	for remote_device_id in peer_seen_at.keys():
		if now - int(peer_seen_at[remote_device_id]) < int(PEER_EXPIRY_SECONDS * 1000.0):
			continue
		peer_seen_at.erase(remote_device_id)
		peers.erase(remote_device_id)
		peer_removed.emit(str(remote_device_id))


func _send(packet: Dictionary, address: String, destination_port: int) -> bool:
	var data := Protocol.encode(packet)
	if data.is_empty() or destination_port < 1 or destination_port > 65535:
		return false
	var error := socket.set_dest_address(address, destination_port)
	if error == OK:
		error = socket.put_packet(data)
	if error != OK:
		status_changed.emit("局域网消息发送失败：%s" % error_string(error))
		return false
	return true
