class_name PetNestLanProtocol
extends RefCounted

const VERSION := 1
const PORT := 18487
const MAX_PACKET_BYTES := 8 * 1024
const CAPABILITIES := ["greeting", "heart", "text", "effect"]


static func hello(device_id: String, display_name: String, pet_name: String, port: int, kind := "hello") -> Dictionary:
	return {
		"version": VERSION,
		"kind": kind,
		"device_id": device_id.strip_edges(),
		"display_name": display_name.strip_edges(),
		"pet_name": pet_name.strip_edges(),
		"port": port,
		"capabilities": CAPABILITIES.duplicate(),
	}


static func interaction(target_device_id: String, interaction_type: String, sender_device_id: String, sender_name: String, text := "", effect_id := "") -> Dictionary:
	var packet := {
		"version": VERSION,
		"kind": "interaction",
		"type": interaction_type,
		"target_device_id": target_device_id.strip_edges(),
		"sender_device_id": sender_device_id.strip_edges(),
		"sender_name": sender_name.strip_edges(),
	}
	if interaction_type == "text":
		packet["text"] = text.strip_edges()
	elif interaction_type == "effect":
		packet["effect_id"] = effect_id.strip_edges()
	return packet


static func encode(packet: Dictionary) -> PackedByteArray:
	var data := JSON.stringify(packet).to_utf8_buffer()
	return data if data.size() <= MAX_PACKET_BYTES else PackedByteArray()


static func decode_presence(data: PackedByteArray) -> Dictionary:
	var envelope := _decode_envelope(data, ["hello", "hello_ack"])
	if not bool(envelope.get("ok", false)):
		return envelope
	var packet: Dictionary = envelope["packet"]
	if not _valid_identity(packet.get("device_id")) or not _valid_text(packet.get("display_name"), 40) or not _valid_text(packet.get("pet_name"), 40):
		return _failure("设备身份无效")
	var port := int(packet.get("port", 0))
	var capabilities = packet.get("capabilities", null)
	if port < 1 or port > 65535 or typeof(capabilities) != TYPE_ARRAY:
		return _failure("设备端口或能力列表无效")
	for capability in capabilities:
		if not CAPABILITIES.has(str(capability)):
			return _failure("设备能力列表无效")
	packet["ok"] = true
	return packet


static func decode_interaction(data: PackedByteArray, local_device_id: String) -> Dictionary:
	var envelope := _decode_envelope(data, ["interaction"])
	if not bool(envelope.get("ok", false)):
		return envelope
	var packet: Dictionary = envelope["packet"]
	if not _valid_identity(packet.get("sender_device_id")) or not _valid_text(packet.get("sender_name"), 40):
		return _failure("发送方身份无效")
	if str(packet.get("sender_device_id", "")) == local_device_id:
		return _failure("忽略本机消息")
	var target := str(packet.get("target_device_id", ""))
	if target != local_device_id and target != "*":
		return _failure("互动目标不是本机")
	var interaction_type := str(packet.get("type", ""))
	if not CAPABILITIES.has(interaction_type):
		return _failure("互动类型无效")
	if interaction_type == "text" and not _valid_text(packet.get("text"), 120):
		return _failure("互动文字无效")
	if interaction_type == "effect" and not _valid_effect_id(packet.get("effect_id")):
		return _failure("互动特效 ID 无效")
	packet["ok"] = true
	return packet


static func _decode_envelope(data: PackedByteArray, kinds: Array[String]) -> Dictionary:
	if data.is_empty() or data.size() > MAX_PACKET_BYTES:
		return _failure("数据包大小无效")
	var json := JSON.new()
	if json.parse(data.get_string_from_utf8()) != OK or typeof(json.data) != TYPE_DICTIONARY:
		return _failure("JSON 数据包无效")
	var packet: Dictionary = json.data
	if int(packet.get("version", 0)) != VERSION or not kinds.has(str(packet.get("kind", ""))):
		return _failure("协议版本或消息类型无效")
	return {"ok": true, "packet": packet}


static func _valid_identity(value) -> bool:
	if typeof(value) != TYPE_STRING:
		return false
	var text := str(value).strip_edges()
	return not text.is_empty() and text.length() <= 64 and not text.contains("\\") and not text.contains("/") and not text.contains("\n") and not text.contains("\r")


static func _valid_text(value, maximum: int) -> bool:
	return typeof(value) == TYPE_STRING and not str(value).strip_edges().is_empty() and str(value).strip_edges().length() <= maximum


static func _valid_effect_id(value) -> bool:
	if typeof(value) != TYPE_STRING:
		return false
	var regex := RegEx.new()
	return regex.compile("^[a-z][a-z0-9_-]{0,63}$") == OK and regex.search(str(value)) != null


static func _failure(message: String) -> Dictionary:
	return {"ok": false, "error": message}
