class_name PetNestLanInteractionDialog
extends Window

signal interaction_requested(target_device_id: String, interaction_type: String, text: String, effect_id: String)
signal effect_preview_requested(effect_id: String)
signal discover_requested()
signal probe_requested(ip_address: String, port: int)

var peers: Array[Dictionary] = []
var effects: Array[Dictionary] = []
var peer_option: OptionButton
var effect_option: OptionButton
var text_input: LineEdit
var ip_input: LineEdit
var port_input: SpinBox
var status_label: Label


func configure(peer_items: Array[Dictionary], effect_items: Array[Dictionary]) -> void:
	peers = peer_items.duplicate(true)
	effects = effect_items.duplicate(true)


func _ready() -> void:
	title = "PetNest 局域网互动"
	size = Vector2i(620, 520)
	min_size = Vector2i(540, 460)
	initial_position = Window.WINDOW_INITIAL_POSITION_CENTER_MAIN_WINDOW_SCREEN
	transient = false
	exclusive = false
	close_requested.connect(queue_free)
	var background := ColorRect.new()
	background.color = Color(0.105, 0.115, 0.14, 1.0)
	background.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(background)
	var margin := MarginContainer.new()
	margin.add_theme_constant_override("margin_left", 20)
	margin.add_theme_constant_override("margin_top", 18)
	margin.add_theme_constant_override("margin_right", 20)
	margin.add_theme_constant_override("margin_bottom", 18)
	margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(margin)
	var root := VBoxContainer.new()
	root.add_theme_constant_override("separation", 10)
	margin.add_child(root)
	var heading := Label.new()
	heading.text = "附近的 PetNest"
	heading.add_theme_font_size_override("font_size", 22)
	root.add_child(heading)
	var peer_row := HBoxContainer.new()
	peer_option = OptionButton.new()
	peer_option.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	peer_row.add_child(peer_option)
	var refresh := Button.new()
	refresh.text = "刷新"
	refresh.pressed.connect(func() -> void: discover_requested.emit())
	peer_row.add_child(refresh)
	root.add_child(peer_row)
	_set_peers(peers)

	var quick_label := Label.new()
	quick_label.text = "快捷互动"
	root.add_child(quick_label)
	var quick_row := HBoxContainer.new()
	for item in [["打招呼 👋", "greeting"], ["送爱心 ❤️", "heart"]]:
		var button := Button.new()
		button.text = item[0]
		button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		button.pressed.connect(_send.bind(str(item[1])))
		quick_row.add_child(button)
	root.add_child(quick_row)

	var text_label := Label.new()
	text_label.text = "文字（最多 120 字）"
	root.add_child(text_label)
	var text_row := HBoxContainer.new()
	text_input = LineEdit.new()
	text_input.max_length = 120
	text_input.placeholder_text = "给附近的朋友说点什么"
	text_input.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	text_row.add_child(text_input)
	var text_send := Button.new()
	text_send.text = "发送文字"
	text_send.pressed.connect(_send.bind("text"))
	text_row.add_child(text_send)
	root.add_child(text_row)

	var effect_label := Label.new()
	effect_label.text = "本地特效（只传特效 ID，不发送文件）"
	root.add_child(effect_label)
	var effect_row := HBoxContainer.new()
	effect_option = OptionButton.new()
	effect_option.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	for effect in effects:
		effect_option.add_item(str(effect.get("name", effect.get("id", "Effect"))))
		effect_option.set_item_metadata(effect_option.item_count - 1, str(effect.get("id", "")))
	effect_row.add_child(effect_option)
	var preview := Button.new()
	preview.text = "本机预览"
	preview.pressed.connect(_preview_effect)
	effect_row.add_child(preview)
	var effect_send := Button.new()
	effect_send.text = "发送特效"
	effect_send.pressed.connect(_send.bind("effect"))
	effect_row.add_child(effect_send)
	root.add_child(effect_row)

	var manual_label := Label.new()
	manual_label.text = "跨网段手动添加"
	root.add_child(manual_label)
	var manual_row := HBoxContainer.new()
	ip_input = LineEdit.new()
	ip_input.placeholder_text = "192.168.1.100"
	ip_input.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	manual_row.add_child(ip_input)
	port_input = SpinBox.new()
	port_input.min_value = 1
	port_input.max_value = 65535
	port_input.value = 18487
	port_input.custom_minimum_size.x = 110
	manual_row.add_child(port_input)
	var probe := Button.new()
	probe.text = "验证设备"
	probe.pressed.connect(func() -> void: probe_requested.emit(ip_input.text.strip_edges(), int(port_input.value)))
	manual_row.add_child(probe)
	root.add_child(manual_row)

	status_label = Label.new()
	status_label.text = "未发现设备时，请确认双方都启用了局域网互动和 UDP 18487。"
	status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	status_label.modulate = Color(0.67, 0.70, 0.78)
	root.add_child(status_label)


func set_peers(peer_items: Array[Dictionary]) -> void:
	peers = peer_items.duplicate(true)
	if is_instance_valid(peer_option):
		_set_peers(peers)


func set_status(message: String) -> void:
	if is_instance_valid(status_label):
		status_label.text = message


func _set_peers(peer_items: Array[Dictionary]) -> void:
	var selected_id := ""
	if peer_option.selected >= 0:
		selected_id = str(peer_option.get_item_metadata(peer_option.selected))
	peer_option.clear()
	for peer in peer_items:
		var label := "%s · %s · %s" % [peer.get("display_name", "附近用户"), peer.get("pet_name", "Pet"), peer.get("ip_address", "")]
		peer_option.add_item(label)
		peer_option.set_item_metadata(peer_option.item_count - 1, str(peer.get("device_id", "")))
		if str(peer.get("device_id", "")) == selected_id:
			peer_option.select(peer_option.item_count - 1)
	if peer_option.item_count == 0:
		peer_option.add_item("暂未发现附近设备")
		peer_option.set_item_disabled(0, true)


func _target_device_id() -> String:
	if peer_option.selected < 0 or peer_option.is_item_disabled(peer_option.selected):
		return ""
	return str(peer_option.get_item_metadata(peer_option.selected))


func _send(interaction_type: String) -> void:
	var target := _target_device_id()
	if target.is_empty():
		set_status("请先选择一个在线设备")
		return
	var text := text_input.text.strip_edges() if interaction_type == "text" else ""
	var effect_id := ""
	if interaction_type == "text" and text.is_empty():
		set_status("文字不能为空")
		return
	if interaction_type == "effect":
		if effect_option.item_count == 0 or effect_option.selected < 0:
			set_status("本地没有可发送的特效")
			return
		effect_id = str(effect_option.get_item_metadata(effect_option.selected))
	interaction_requested.emit(target, interaction_type, text, effect_id)


func _preview_effect() -> void:
	if effect_option.item_count == 0 or effect_option.selected < 0:
		set_status("本地没有可预览的特效")
		return
	effect_preview_requested.emit(str(effect_option.get_item_metadata(effect_option.selected)))
