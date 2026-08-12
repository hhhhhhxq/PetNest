extends SceneTree

const MotionAnimationResolver = preload("res://src/motion_animation_resolver.gd")

const SettingsStore = preload("res://src/settings_store.gd")
const PackageLoader = preload("res://src/pet_package_loader.gd")
const StateMachine = preload("res://src/pet_state_machine.gd")
const AnimationController = preload("res://src/pet_animation_controller.gd")
const IdleMonitor = preload("res://src/system_idle_monitor.gd")
const ExternalEventServer = preload("res://src/external_event_server.gd")
const SpritesheetImporter = preload("res://src/spritesheet_importer.gd")
const PackageEditor = preload("res://src/pet_package_editor.gd")
const EffectPackageLoader = preload("res://src/effect_package_loader.gd")
const EffectPlayer = preload("res://src/effect_player.gd")
const LanProtocol = preload("res://src/lan_protocol.gd")
const LanService = preload("res://src/lan_service.gd")

var failures: Array[String] = []


func _init() -> void:
	call_deferred("_run")


func _run() -> void:
	var pets_root := ProjectSettings.globalize_path("res://../../pets").simplify_path()
	var loader = PackageLoader.new()
	var packages: Array[Dictionary] = loader.discover(pets_root)
	_check(not packages.is_empty(), "应发现默认 sample_pet")

	var sample: Dictionary = {}
	for package in packages:
		if str(package.get("id", "")) == "sample_pet":
			sample = package
			break
	_check(not sample.is_empty(), "应加载默认 sample_pet")
	if not sample.is_empty():
		var state_package := sample.duplicate(true)
		var state_animations: Dictionary = (sample["animations"] as Dictionary).duplicate(true)
		for action in ["bored", "sleep", "wake"]:
			state_animations[action] = state_animations["idle"]
		state_package["animations"] = state_animations
		var bindings: Dictionary = (sample.get("bindings", {}) as Dictionary).duplicate(true)
		bindings["system.bored"] = "bored"
		bindings["system.sleep"] = "sleep"
		bindings["system.wake"] = "wake"
		state_package["bindings"] = bindings
		var state_machine = StateMachine.new()
		state_machine.configure(state_package)
		_check(state_machine.handle("system.bored", 40) == "bored", "状态机应进入 bored")
		_check(state_machine.handle("system.sleep", 40) == "sleep", "状态机应进入 sleep")
		_check(state_machine.handle("system.wake", 40, true) == "wake", "状态机应进入 wake")
		var controller = AnimationController.new()
		controller.configure(sample)
		_check(controller.current_texture() != null, "应能从外部宠物目录加载 PNG")
		_check(controller.current_hit_polygon(10).size() >= 3, "应能生成按透明度穿透的宠物轮廓")
		var directional_animations := {"codex_running_left": {}, "drag": {}, "drop": {}}
		var left_motion: Dictionary = MotionAnimationResolver.resolve(directional_animations, "horizontal", -1.0)
		var right_motion: Dictionary = MotionAnimationResolver.resolve(directional_animations, "horizontal", 1.0)
		var vertical_motion: Dictionary = MotionAnimationResolver.resolve(directional_animations, "vertical", -1.0)
		_check(left_motion.get("action", "") == "codex_running_left" and not bool(left_motion.get("flip_h", true)), "向左移动必须使用未镜像的左跑动画")
		_check(right_motion.get("action", "") == "drag" and not bool(right_motion.get("flip_h", true)), "向右移动必须使用未镜像的右跑动画")
		_check(vertical_motion.get("action", "") == "drop" and not bool(vertical_motion.get("flip_h", true)), "纵向移动应使用正面跳跃动画")
		var generic_left: Dictionary = MotionAnimationResolver.resolve({"drag": {}}, "horizontal", -1.0)
		_check(generic_left.get("action", "") == "drag" and bool(generic_left.get("flip_h", false)), "只有右跑素材时向左移动必须镜像")
		var drag_left: Dictionary = MotionAnimationResolver.resolve_drag(directional_animations, -1.0)
		var drag_right: Dictionary = MotionAnimationResolver.resolve_drag(directional_animations, 1.0)
		_check(drag_left.get("action", "") == "drag" and bool(drag_left.get("flip_h", false)), "向左拖拽必须镜像右向 drag 帧")
		_check(drag_right.get("action", "") == "drag" and not bool(drag_right.get("flip_h", true)), "向右拖拽必须保持原始 drag 帧")
		var follow_target := MotionAnimationResolver.cursor_lower_right_target(Vector2(100, 100), Vector2(50, 60), Vector2(1000, 800), 18.0)
		_check(follow_target == Vector2(168, 178), "鼠标跟随目标应位于光标右下方并留出间距")
		var clamped_follow_target := MotionAnimationResolver.cursor_lower_right_target(Vector2(990, 790), Vector2(50, 60), Vector2(1000, 800), 18.0)
		_check(clamped_follow_target == Vector2(950, 740), "鼠标右下方空间不足时跟随目标必须限制在桌面内")

	var idle_monitor = IdleMonitor.new()
	idle_monitor.configure(2.0, 4.0)
	_check(idle_monitor.update(2.1) == "system.bored", "空闲 2 秒应触发 bored")
	_check(idle_monitor.update(4.1) == "system.sleep", "空闲 4 秒应触发 sleep")
	_check(idle_monitor.update(0.0) == "system.wake", "恢复活动应触发 wake")

	var effects_root := ProjectSettings.globalize_path("res://../../effects").simplify_path()
	var effect_loader = EffectPackageLoader.new()
	var effects: Array[Dictionary] = effect_loader.discover([effects_root])
	_check(effects.size() >= 6, "应发现新版内置本地特效")
	var fire_effect: Dictionary = {}
	for effect in effects:
		if str(effect.get("id", "")) == "fire":
			fire_effect = effect
			break
	_check(not fire_effect.is_empty() and int(fire_effect.get("frame_count", 0)) == 30, "应校验并加载 fire 特效包")
	if not fire_effect.is_empty():
		var effect_player = EffectPlayer.new()
		var first_effect_frame: Dictionary = effect_player.play(fire_effect, false)
		_check(first_effect_frame.get("texture", null) != null, "Godot 应能从外部 PNG 帧创建特效纹理")
		var next_effect_frame: Dictionary = effect_player.advance(1.0 / float(fire_effect["fps"]))
		_check(bool(next_effect_frame.get("frame_changed", false)), "本地特效应按清单帧率前进")
		effect_player.stop()

	var interaction_packet := LanProtocol.interaction("peer-1", "text", "local-1", "小平安", "跨运行时你好")
	var decoded_interaction := LanProtocol.decode_interaction(LanProtocol.encode(interaction_packet), "peer-1")
	_check(bool(decoded_interaction.get("ok", false)) and decoded_interaction.get("text", "") == "跨运行时你好", "Godot 应兼容 PySide6 局域网互动协议")
	_check(not bool(LanProtocol.decode_interaction(LanProtocol.encode(interaction_packet), "other-peer").get("ok", false)), "局域网互动必须校验目标设备")

	var port_a := 30000 + int(OS.get_process_id() % 1000) * 2
	var port_b := port_a + 1
	var sender = LanService.new()
	var receiver = LanService.new()
	sender.configure("sender", "发送方", "示例宠物")
	receiver.configure("receiver", "接收方", "示例宠物")
	var received_interactions: Array[Dictionary] = []
	receiver.interaction_received.connect(func(interaction: Dictionary) -> void: received_interactions.append(interaction))
	_check(sender.start(port_a) == OK and receiver.start(port_b) == OK, "两个 Godot 局域网服务应能监听独立测试端口")
	_check(sender.probe("127.0.0.1", port_b), "应能定向发现跨网段设备")
	for attempt in range(150):
		sender.poll(0.01)
		receiver.poll(0.01)
		if not sender.peer_list().is_empty():
			break
		OS.delay_msec(2)
	_check(not sender.peer_list().is_empty() and sender.peer_list()[0].get("device_id", "") == "receiver", "定向 hello / hello_ack 应建立附近设备")
	if not sender.peer_list().is_empty():
		_check(sender.send_interaction("receiver", "text", "你好，高级版"), "高级版应能发送局域网文字互动")
		for attempt in range(100):
			receiver.poll(0.01)
			if not received_interactions.is_empty():
				break
			OS.delay_msec(2)
	_check(not received_interactions.is_empty() and received_interactions[0].get("text", "") == "你好，高级版", "高级版应能接收局域网互动")
	sender.stop()
	receiver.stop()

	var event_server = ExternalEventServer.new()
	_check(event_server.start(29486) == OK, "本机事件服务应能监听端口")
	var event_client := StreamPeerTCP.new()
	_check(event_client.connect_to_host("127.0.0.1", 29486) == OK, "测试客户端应能连接")
	var received_events: Array[Dictionary] = []
	for attempt in range(100):
		event_client.poll()
		event_server.poll()
		if event_client.get_status() == StreamPeerTCP.STATUS_CONNECTED:
			break
		OS.delay_msec(2)
	if event_client.get_status() == StreamPeerTCP.STATUS_CONNECTED:
		event_client.put_data('{"event":"agent.working","source":"godot-smoke"}\n'.to_utf8_buffer())
		for attempt in range(100):
			received_events = event_server.poll()
			if not received_events.is_empty():
				break
			OS.delay_msec(2)
	_check(not received_events.is_empty() and received_events[0].get("event", "") == "agent.working", "应接收一行一个 JSON 的外部事件")
	event_client.disconnect_from_host()
	event_server.stop()

	var temporary := ProjectSettings.globalize_path("user://smoke-settings.json")
	var store = SettingsStore.new(temporary)
	var smoke_settings: Dictionary = store.load_settings()
	smoke_settings["schema_version"] = 18.0
	smoke_settings["current_pet_id"] = "sample_pet"
	_check(store.save_settings(smoke_settings) == OK, "设置应能写入")
	var serialized := FileAccess.get_file_as_string(temporary)
	_check(serialized.contains("\"schema_version\": 18"), "设置版本必须保持 JSON 整数")
	_check(not serialized.contains("\"schema_version\": 18.0"), "设置版本不能写成浮点数")
	DirAccess.remove_absolute(temporary)

	var import_root := ProjectSettings.globalize_path("user://godot-smoke-pets")
	_remove_tree(import_root)
	var sheet_path := ProjectSettings.globalize_path("user://godot-smoke-sheet.png")
	print("Godot smoke: creating spritesheet fixture")
	var sheet := Image.create(1536, 1872, false, Image.FORMAT_RGBA8)
	sheet.fill(Color(0.0, 0.0, 0.0, 0.0))
	for row in range(9):
		sheet.fill_rect(Rect2i(24, row * 208 + 24, 80, 120), Color(0.8, 0.7, 0.5, 1.0))
	_check(sheet.save_png(sheet_path) == OK, "应能创建导入测试图")
	print("Godot smoke: inspecting spritesheet fixture")
	var importer = SpritesheetImporter.new()
	var inspection: Dictionary = importer.inspect(sheet_path)
	_check(bool(inspection.get("ok", false)) and int(inspection.get("rows", 0)) == 9, "应识别 8×9 精灵图")
	print("Godot smoke: importing spritesheet fixture")
	var imported: Dictionary = importer.import_file(sheet_path, import_root, "smoke_cat", "Smoke Cat")
	_check(bool(imported.get("ok", false)), "应能原生导入精灵图")
	var manual_imported: Dictionary = importer.import_file(
		sheet_path,
		import_root,
		"smoke_manual",
		"Smoke Manual",
		{"idle": [0], "click": [0]},
	)
	_check(bool(manual_imported.get("ok", false)) and int(manual_imported.get("frame_count", 0)) == 2, "手动选帧应只导入用户勾选的格位")
	print("Godot smoke: editing imported package")
	if bool(imported.get("ok", false)):
		var imported_package: Dictionary = loader.load_package(str(imported["package_root"]))
		_check(bool(imported_package.get("ok", false)), "Godot 导入的宠物包应通过加载校验")
		var package_editor = PackageEditor.new()
		var updated: Dictionary = package_editor.update_frame_durations(str(imported["package_root"]), {"idle": [175]})
		_check(bool(updated.get("ok", false)), "应能原子更新逐帧时长")
		var saved_config := FileAccess.get_file_as_string(str(imported["package_root"]).path_join("pet.json"))
		_check(saved_config.contains("175") and not saved_config.contains("175.0"), "动画时长应保持 JSON 整数")
	_remove_tree(import_root)
	DirAccess.remove_absolute(sheet_path)
	print("Godot smoke: spritesheet fixture complete")

	if failures.is_empty():
		print("PetNest Godot smoke tests passed")
		quit(0)
	else:
		for failure in failures:
			push_error(failure)
		quit(1)


func _check(condition: bool, message: String) -> void:
	if not condition:
		failures.append(message)


func _remove_tree(path: String) -> void:
	var directory := DirAccess.open(path)
	if directory == null:
		return
	for child_directory in directory.get_directories():
		_remove_tree(path.path_join(child_directory))
	for file in directory.get_files():
		DirAccess.remove_absolute(path.path_join(file))
	DirAccess.remove_absolute(path)
