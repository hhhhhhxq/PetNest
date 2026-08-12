extends Node2D

const SettingsStore = preload("res://src/settings_store.gd")
const PackageLoader = preload("res://src/pet_package_loader.gd")
const StateMachine = preload("res://src/pet_state_machine.gd")
const AnimationController = preload("res://src/pet_animation_controller.gd")
const IdleMonitor = preload("res://src/system_idle_monitor.gd")
const ExternalEventServer = preload("res://src/external_event_server.gd")
const SettingsDialog = preload("res://src/settings_dialog.gd")
const AnimationEditorDialog = preload("res://src/animation_editor_dialog.gd")
const PackageEditor = preload("res://src/pet_package_editor.gd")
const SpritesheetImportDialog = preload("res://src/spritesheet_import_dialog.gd")
const EffectPackageLoader = preload("res://src/effect_package_loader.gd")
const EffectPlayer = preload("res://src/effect_player.gd")
const LanService = preload("res://src/lan_service.gd")
const LanInteractionDialog = preload("res://src/lan_interaction_dialog.gd")
const WindowsNativePresenter = preload("res://src/windows_native_presenter.gd")
const MacOSIdleBridge = preload("res://src/macos_idle_bridge.gd")
const MotionAnimationResolver = preload("res://src/motion_animation_resolver.gd")
const CursorStyleCatalog = preload("res://src/cursor_style_catalog.gd")

const STRIP_HEIGHT := 340
const GROUND_MARGIN := 8.0
const WALK_SPEED := 115.0
const JUMP_SECONDS := 0.62
const JUMP_HEIGHT := 92.0
const CLICK_DISTANCE := 8.0
const CLICK_SECONDS := 0.35
const DOUBLE_CLICK_SECONDS := 0.34
const SINGLE_INSTANCE_PORT := 18485
const MOUSE_FOLLOW_GAP := 18.0
const MOUSE_FOLLOW_STOP_DISTANCE := 6.0

const MENU_PAUSE := 1
const MENU_AUTO_WALK := 2
const MENU_POWER_SAVER := 3
const MENU_MOUSE_FOLLOW := 4
const MENU_SYSTEM_IDLE := 5
const MENU_ALWAYS_ON_TOP := 6
const MENU_SCALE_UP := 10
const MENU_SCALE_DOWN := 11
const MENU_JUMP := 12
const MENU_WAVE := 13
const MENU_RELOAD := 20
const MENU_OPEN_PETS := 21
const MENU_STARTUP := 22
const MENU_SETTINGS := 23
const MENU_VISIBILITY := 24
const MENU_ANIMATION_EDITOR := 25
const MENU_IMPORT_SPRITESHEET := 26
const MENU_LAN_INTERACTIONS := 27
const MENU_APP_UPDATE := 28
const MENU_RESOURCE_UPDATE := 29
const MENU_QUIT := 99
const MENU_PET_BASE := 1000
const MENU_EFFECT_BASE := 2000

@onready var pet: Sprite2D = $Pet
@onready var effect_under: Sprite2D = $EffectUnder
@onready var effect_over: Sprite2D = $EffectOver
@onready var countdown: Label = $Countdown
@onready var interaction_bubble: Label = $InteractionBubble
@onready var menu: PopupMenu = $Menu
@onready var context_menu: PopupMenu = $ContextMenu
@onready var tray: StatusIndicator = $Tray

var settings_store = SettingsStore.new()
var package_loader = PackageLoader.new()
var state_machine = StateMachine.new()
var animation_controller = AnimationController.new()
var idle_monitor = IdleMonitor.new()
var external_server = ExternalEventServer.new()
var package_editor = PackageEditor.new()
var effect_package_loader = EffectPackageLoader.new()
var effect_player = EffectPlayer.new()
var lan_service = LanService.new()
var native_presenter = WindowsNativePresenter.new()
var macos_idle_bridge = MacOSIdleBridge.new()
var cursor_style_catalog = CursorStyleCatalog.new()
var instance_server := TCPServer.new()

var settings: Dictionary = {}
var packages: Array[Dictionary] = []
var current_package: Dictionary = {}
var effects: Array[Dictionary] = []
var cursor_styles: Array[Dictionary] = []
var pets_root := ""
var pet_scale := 1.0
var base_pet_position := Vector2.ZERO
var hovered := false
var dragging := false
var press_started_ms := 0
var press_position := Vector2.ZERO
var drag_offset_x := 0.0
var drag_offset_y := 0.0
var last_click_ms := -1000
var last_global_mouse := Vector2i(-100000, -100000)
var idle_seconds := 0.0
var native_system_idle_seconds := -1.0
var decision_seconds := 2.0
var walking := false
var walk_target := Vector2.ZERO
var roam_destination := Vector2.ZERO
var walk_direction := 1.0
var walk_axis := ""
var movement_action := ""
var mouse_follow_moving := false
var jumping := false
var jump_elapsed := 0.0
var countdown_accumulator := 0.0
var passthrough_accumulator := 0.0
var shutting_down := false
var bubble_seconds := 0.0
var native_presenter_enabled := false
var macos_idle_bridge_enabled := false
var pet_window_visible := true
var desktop_strip_position := Vector2i.ZERO
var desktop_strip_size := Vector2i(1280, STRIP_HEIGHT)
var settings_dialog: Window
var animation_editor_dialog: Window
var spritesheet_import_dialog: Window
var lan_interaction_dialog: Window


func _ready() -> void:
	# Windows is rendered by the native presenter and deliberately keeps an
	# opaque diagnostic host surface. macOS uses Godot's transparent window.
	RenderingServer.set_default_clear_color(
		Color(0.0, 0.0, 0.0, 0.0) if OS.get_name() == "macOS" else Color(1.0, 0.0, 1.0, 1.0)
	)
	if instance_server.listen(SINGLE_INSTANCE_PORT, "127.0.0.1") != OK:
		push_warning("PetNest Advanced 已在运行")
		get_tree().quit(2)
		return
	settings = settings_store.load_settings()
	_ensure_device_identity()
	_reload_cursor_styles()
	pets_root = settings_store.resolve_pets_root(settings)
	var pet_library_error := settings_store.ensure_pet_library(pets_root)
	if pet_library_error != OK and pet_library_error != ERR_FILE_NOT_FOUND:
		push_warning("无法初始化 PetNest 宠物库：%s" % error_string(pet_library_error))
	_configure_window()
	if OS.get_name() == "Windows":
		get_window().visible = false
	_configure_runtime()
	menu.id_pressed.connect(_on_menu_id_pressed)
	context_menu.id_pressed.connect(_on_menu_id_pressed)
	_configure_context_menu_theme()
	if tray.has_signal("pressed"):
		tray.connect("pressed", Callable(self, "_on_tray_pressed"))
	get_tree().auto_accept_quit = false
	if not _reload_packages():
		push_error("宠物库中没有可用的 PetNest 宠物包：" + pets_root)
		get_tree().quit(3)
		return
	_configure_native_presenter()
	_configure_macos_idle_bridge()
	if OS.get_name() == "macOS":
		_apply_cursor_style()
	_reload_effects()
	_configure_lan_interactions()
	_configure_external_events()
	_build_menu()
	_update_countdown()
	_update_mouse_passthrough()
	set_process(true)
	var capture_path := OS.get_environment("PETNEST_RENDER_CAPTURE").strip_edges()
	var preview_effect_id := OS.get_environment("PETNEST_PREVIEW_EFFECT").strip_edges()
	if not preview_effect_id.is_empty():
		_play_effect.call_deferred(preview_effect_id, false)
	if not capture_path.is_empty():
		_capture_render.call_deferred(capture_path)
	match OS.get_environment("PETNEST_OPEN_DIALOG").strip_edges().to_lower():
		"settings":
			_show_settings_dialog.call_deferred()
		"animations":
			_show_animation_editor.call_deferred()
		"import":
			_show_spritesheet_importer.call_deferred()
		"lan":
			_show_lan_interactions.call_deferred()


func _configure_context_menu_theme() -> void:
	context_menu.min_size = Vector2i(270, 0)
	context_menu.add_theme_font_size_override("font_size", 21)
	context_menu.add_theme_font_size_override("separator_font_size", 16)
	context_menu.add_theme_constant_override("v_separation", 10)
	context_menu.add_theme_constant_override("item_start_padding", 18)
	context_menu.add_theme_constant_override("item_end_padding", 22)
	context_menu.add_theme_constant_override("outline_size", 1)


func _configure_window() -> void:
	var window := get_window()
	var screen := DisplayServer.window_get_current_screen()
	var usable := DisplayServer.screen_get_usable_rect(screen)
	desktop_strip_position = usable.position
	desktop_strip_size = usable.size
	var use_transparent_desktop := OS.get_name() == "macOS"
	if use_transparent_desktop:
		window.size = usable.size
		window.position = usable.position
	else:
		window.size = Vector2i(usable.size.x, mini(STRIP_HEIGHT, usable.size.y))
		window.position = Vector2i(usable.position.x, usable.end.y - window.size.y)
	window.borderless = true
	window.transparent = use_transparent_desktop
	window.transparent_bg = use_transparent_desktop
	window.unresizable = true
	window.always_on_top = bool(settings.get("always_on_top", true))
	get_viewport().transparent_bg = use_transparent_desktop


func _configure_native_presenter() -> void:
	if OS.get_name() != "Windows":
		return
	if OS.get_environment("PETNEST_DISABLE_NATIVE_PRESENTER") == "1":
		get_window().visible = true
		return
	var error := native_presenter.start()
	if error != OK:
		push_warning("无法启动 Windows 原生透明显示器：%s" % error_string(error))
		get_window().visible = true
		return
	native_presenter_enabled = true
	_hide_godot_render_window()
	native_presenter.set_always_on_top(bool(settings.get("always_on_top", true)))
	_apply_cursor_style()


func _configure_macos_idle_bridge() -> void:
	if OS.get_name() != "macOS":
		return
	var error := macos_idle_bridge.start()
	if error != OK:
		push_warning("macOS 全局键盘/鼠标空闲检测不可用，将退回鼠标移动检测：%s" % error_string(error))
		return
	macos_idle_bridge_enabled = true


func _hide_godot_render_window() -> void:
	var window := get_window()
	var screen := DisplayServer.window_get_current_screen()
	var usable := DisplayServer.screen_get_usable_rect(screen)
	window.position = Vector2i(usable.end.x + window.size.x + 1024, usable.end.y + window.size.y + 1024)
	window.visible = false


func _configure_runtime() -> void:
	var power_saver := bool(settings.get("godot_power_saver", false))
	Engine.max_fps = 60 if power_saver else clampi(int(settings.get("godot_renderer_max_fps", 240)), 60, 360)
	idle_monitor.configure(
		float(settings.get("system_bored_seconds", 20)),
		float(settings.get("system_sleep_seconds", 35))
	)


func _configure_external_events() -> void:
	external_server.stop()
	if not bool(settings.get("external_event_server_enabled", false)):
		return
	var port := clampi(int(settings.get("external_event_port", 18486)), 1024, 65535)
	var error := external_server.start(port)
	if error != OK:
		push_warning("无法监听 PetNest 外部事件端口 %d（可能已被标准版占用）" % port)


func _ensure_device_identity() -> void:
	if str(settings.get("device_id", "")).strip_edges().is_empty():
		settings["device_id"] = Crypto.new().generate_random_bytes(16).hex_encode()
	_save_settings()


func _display_name() -> String:
	var nickname := str(settings.get("nickname", "")).strip_edges()
	if not nickname.is_empty():
		return nickname.left(40)
	var device_id := str(settings.get("device_id", "")).to_upper()
	return "用户-%s" % (device_id.right(4) if not device_id.is_empty() else "本机")


func _update_lan_identity() -> void:
	var pet_name := str(current_package.get("name", "Pet")) if not current_package.is_empty() else "Pet"
	lan_service.configure(str(settings.get("device_id", "")), _display_name(), pet_name)


func _configure_lan_interactions() -> void:
	if not lan_service.interaction_received.is_connected(_on_lan_interaction_received):
		lan_service.interaction_received.connect(_on_lan_interaction_received)
		lan_service.peer_changed.connect(_on_lan_peers_changed)
		lan_service.peer_removed.connect(_on_lan_peer_removed)
		lan_service.status_changed.connect(_on_lan_status_changed)
	_update_lan_identity()
	if bool(settings.get("lan_interaction_enabled", true)):
		var error := lan_service.start()
		if error != OK:
			push_warning("局域网互动未启动；桌宠其余功能不受影响")
	else:
		lan_service.stop()


func _reload_effects() -> void:
	var roots: Array[String] = effect_package_loader.default_roots(pets_root)
	effects = effect_package_loader.discover(roots)
	if is_instance_valid(lan_interaction_dialog):
		lan_interaction_dialog.set("effects", effects.duplicate(true))


func _effect_by_id(identifier: String) -> Dictionary:
	for effect in effects:
		if str(effect.get("id", "")) == identifier:
			return effect
	return {}


func _play_effect(identifier: String, loop_override = false) -> bool:
	var effect := _effect_by_id(identifier)
	if effect.is_empty():
		return false
	var result: Dictionary = effect_player.play(effect, loop_override)
	if not bool(result.get("ok", true)):
		return false
	_apply_effect_frame(result)
	return true


func _update_effect(delta: float) -> void:
	if not effect_player.playing:
		return
	var result: Dictionary = effect_player.advance(delta)
	if bool(result.get("frame_changed", false)):
		_apply_effect_frame(result)
	else:
		_position_effect_sprites()


func _apply_effect_frame(result: Dictionary) -> void:
	if bool(result.get("completed", false)) or result.get("texture", null) == null:
		effect_under.texture = null
		effect_over.texture = null
		return
	var target := effect_under if str(effect_player.package.get("layer", "over")) == "under" else effect_over
	var other := effect_over if target == effect_under else effect_under
	other.texture = null
	target.texture = result.get("texture")
	var texture_size := target.texture.get_size()
	var max_width := maxf(140.0, _half_pet_width() * 3.0)
	var max_height := minf(float(STRIP_HEIGHT - 12), maxf(180.0, _half_pet_height() * 2.8))
	var fit_scale := minf(1.0, minf(max_width / maxf(texture_size.x, 1.0), max_height / maxf(texture_size.y, 1.0)))
	target.scale = Vector2.ONE * fit_scale
	_position_effect_sprites()


func _position_effect_sprites() -> void:
	effect_under.position = pet.position
	effect_over.position = pet.position


func _show_interaction_bubble(message: String) -> void:
	interaction_bubble.text = message
	interaction_bubble.custom_minimum_size = Vector2(260, 44)
	interaction_bubble.size = Vector2(300, 64)
	var style := StyleBoxFlat.new()
	style.bg_color = Color(1.0, 0.96, 0.84, 0.95)
	style.border_color = Color(0.65, 0.46, 0.28, 0.92)
	style.set_border_width_all(1)
	style.set_corner_radius_all(12)
	style.content_margin_left = 10.0
	style.content_margin_right = 10.0
	interaction_bubble.add_theme_stylebox_override("normal", style)
	interaction_bubble.position = Vector2(
		clampf(pet.position.x - interaction_bubble.size.x * 0.5, 0.0, desktop_strip_size.x - interaction_bubble.size.x),
		maxf(4.0, pet.position.y - _half_pet_height() - interaction_bubble.size.y - 10.0)
	)
	interaction_bubble.visible = true
	bubble_seconds = 5.0


func _on_lan_interaction_received(interaction: Dictionary) -> void:
	var sender := str(interaction.get("sender_name", "附近设备"))
	match str(interaction.get("type", "")):
		"greeting":
			_show_interaction_bubble("%s 向你打招呼 👋" % sender)
			_dispatch_event("mouse.click", 50, true)
		"heart":
			_show_interaction_bubble("%s 送了你爱心 ❤️" % sender)
			_play_effect("stream-of-hearts", false)
		"text":
			_show_interaction_bubble("%s：%s" % [sender, str(interaction.get("text", ""))])
		"effect":
			var effect_id := str(interaction.get("effect_id", ""))
			var effect := _effect_by_id(effect_id)
			if effect.is_empty():
				_show_interaction_bubble("%s 发送了本地未安装的特效" % sender)
			else:
				_show_interaction_bubble("%s 发送了 %s" % [sender, effect.get("name", effect_id)])
				_play_effect(effect_id, false)


func _on_lan_peers_changed(_peer: Dictionary) -> void:
	_refresh_lan_dialog_peers()


func _on_lan_peer_removed(_device_id: String) -> void:
	_refresh_lan_dialog_peers()


func _on_lan_status_changed(message: String) -> void:
	if is_instance_valid(lan_interaction_dialog):
		lan_interaction_dialog.call("set_status", message)


func _refresh_lan_dialog_peers() -> void:
	if is_instance_valid(lan_interaction_dialog):
		lan_interaction_dialog.call("set_peers", lan_service.peer_list())


func _reload_packages(preferred_id := "") -> bool:
	packages = package_loader.discover(pets_root)
	if packages.is_empty():
		return false
	var wanted := preferred_id
	if wanted.is_empty():
		wanted = str(settings.get("current_pet_id", ""))
	var selected: Dictionary = packages[0]
	for candidate in packages:
		if str(candidate.get("id", "")) == wanted:
			selected = candidate
			break
	_load_package(selected)
	return true


func _load_package(package: Dictionary) -> void:
	current_package = package
	state_machine.configure(package)
	animation_controller.configure(package)
	settings["current_pet_id"] = str(package["id"])
	var display: Dictionary = package["display"]
	pet_scale = clampf(
		float(settings.get("scale", display.get("default_scale", 1.0))),
		float(display.get("min_scale", 0.25)),
		float(display.get("max_scale", 2.0))
	)
	settings["scale"] = pet_scale
	pet.scale = Vector2.ONE * pet_scale
	pet.flip_h = false
	var saved_x := float(settings.get("godot_pet_x", -1.0))
	if int(settings.get("godot_position_space_version", 0)) < 1:
		var legacy_width := get_viewport_rect().size.x
		if saved_x >= 0.0 and legacy_width > 0.0:
			saved_x *= float(desktop_strip_size.x) / legacy_width
		settings["godot_position_space_version"] = 1
	if saved_x < 0.0:
		saved_x = desktop_strip_size.x * 0.78
	var saved_y := float(settings.get("godot_pet_y", -1.0))
	if saved_y < 0.0:
		saved_y = desktop_strip_size.y - GROUND_MARGIN - _half_pet_height()
	base_pet_position.x = clampf(saved_x, _half_pet_width(), desktop_strip_size.x - _half_pet_width())
	base_pet_position.y = _clamp_pet_y(saved_y)
	pet.position = base_pet_position
	_apply_current_texture()
	_load_tray_icon()
	_update_lan_identity()
	_save_settings()
	if is_instance_valid(menu):
		_build_menu()


func _process(delta: float) -> void:
	if current_package.is_empty():
		return
	_poll_native_presenter()
	_poll_macos_idle_bridge()
	_poll_instance_server()
	_poll_external_events()
	_update_global_mouse(delta)
	_update_motion(delta)
	_update_animation(delta)
	_update_effect(delta)
	lan_service.poll(delta)
	_update_hover()
	countdown_accumulator += delta
	if countdown_accumulator >= 1.0:
		countdown_accumulator = 0.0
		_update_countdown()
	if bubble_seconds > 0.0:
		bubble_seconds = maxf(0.0, bubble_seconds - delta)
		if bubble_seconds <= 0.0:
			interaction_bubble.visible = false
	passthrough_accumulator += delta
	if passthrough_accumulator >= 0.05:
		passthrough_accumulator = 0.0
		_update_mouse_passthrough()
	_sync_native_presenter()


func _poll_native_presenter() -> void:
	if not native_presenter_enabled:
		return
	for native_event in native_presenter.poll():
		_handle_native_presenter_event(native_event)


func _poll_macos_idle_bridge() -> void:
	if not macos_idle_bridge_enabled:
		return
	for idle_event in macos_idle_bridge.poll():
		if str(idle_event.get("kind", "")) == "idle":
			native_system_idle_seconds = float(idle_event.get("idle_seconds", 0.0))


func _sync_native_presenter() -> void:
	if not native_presenter_enabled or not pet_window_visible:
		return
	var frame_path := animation_controller.current_frame_path()
	if not frame_path.is_empty():
		var scaled_size := Vector2(current_package.get("canvas", Vector2i.ONE)) * pet_scale
		var frame_size := Vector2i(maxi(1, roundi(scaled_size.x)), maxi(1, roundi(scaled_size.y)))
		var global_center := Vector2(desktop_strip_position) + pet.position
		var frame_position := Vector2i(
			roundi(global_center.x - float(frame_size.x) * 0.5),
			roundi(global_center.y - float(frame_size.y) * 0.5)
		)
		native_presenter.present(frame_path, Rect2i(frame_position, frame_size), pet.flip_h)
	_sync_native_countdown()


func _sync_native_countdown() -> void:
	var card_size := Vector2i(maxi(1, roundi(countdown.size.x)), maxi(1, roundi(countdown.size.y)))
	var card_position := Vector2i(
		roundi(desktop_strip_position.x + countdown.position.x),
		roundi(desktop_strip_position.y + countdown.position.y)
	)
	native_presenter.present_countdown(
		countdown.text,
		Rect2i(card_position, card_size),
		str(settings.get("countdown_theme", "cream")),
		countdown.visible
	)


func _handle_native_presenter_event(native_event: Dictionary) -> void:
	var kind := str(native_event.get("kind", ""))
	if kind == "error":
		push_warning("Windows 原生透明显示器错误：" + str(native_event.get("message", "未知错误")))
		return
	if kind == "closed":
		_shutdown()
		return
	if kind == "idle":
		native_system_idle_seconds = float(native_event.get("idle_seconds", 0.0))
		return
	if kind == "cursor_applied":
		settings["cursor_restore_pending"] = bool(native_event.get("applied", false))
		_save_settings()
		return
	if not bool(settings.get("mouse_interaction_enabled", true)):
		return
	if kind == "enter" or kind == "leave":
		var next_hovered := kind == "enter"
		if next_hovered != hovered:
			hovered = next_hovered
			_dispatch_event("mouse.enter" if hovered else "mouse.leave", 30, false)
		return
	if not kind in ["down", "up", "move", "double"]:
		return
	var global_position: Vector2 = native_event.get("global_position", Vector2.ZERO)
	var local_position := global_position - Vector2(desktop_strip_position)
	var button := int(native_event.get("button", 0))
	if kind == "move":
		if dragging:
			_mark_activity()
			var previous_x := base_pet_position.x
			base_pet_position.x = _clamp_pet_x(local_position.x - drag_offset_x)
			base_pet_position.y = _clamp_pet_y(local_position.y - drag_offset_y)
			var horizontal_delta := base_pet_position.x - previous_x
			if absf(horizontal_delta) > 0.1:
				_set_drag_animation(signf(horizontal_delta))
			pet.position = base_pet_position
		return
	if kind == "double":
		return
	if button == MOUSE_BUTTON_RIGHT and kind == "down":
		_mark_activity()
		return
	if button == MOUSE_BUTTON_RIGHT and kind == "up":
		_build_menu()
		context_menu.position = Vector2i(roundi(global_position.x), roundi(global_position.y))
		context_menu.popup()
		context_menu.grab_focus()
		if native_presenter_enabled:
			native_presenter.focus_host_popup()
		return
	if button != MOUSE_BUTTON_LEFT:
		return
	if kind == "down":
		_mark_activity()
		dragging = true
		walking = false
		walk_axis = ""
		movement_action = ""
		press_started_ms = Time.get_ticks_msec()
		press_position = local_position
		drag_offset_x = local_position.x - base_pet_position.x
		drag_offset_y = local_position.y - base_pet_position.y
		_dispatch_event("mouse.drag_start", 80, true)
	elif kind == "up":
		_finish_mouse_drag(local_position)


func _finish_mouse_drag(local_position: Vector2) -> void:
	var was_dragging := dragging
	dragging = false
	if not was_dragging:
		return
	settings["godot_pet_x"] = base_pet_position.x
	settings["godot_pet_y"] = base_pet_position.y
	_save_settings()
	var elapsed := float(Time.get_ticks_msec() - press_started_ms) / 1000.0
	var moved := press_position.distance_to(local_position)
	if elapsed <= CLICK_SECONDS and moved <= CLICK_DISTANCE:
		var now := Time.get_ticks_msec()
		if now - last_click_ms <= int(DOUBLE_CLICK_SECONDS * 1000.0):
			_start_jump()
			last_click_ms = -1000
		else:
			_dispatch_event("mouse.click", 50, true)
			last_click_ms = now
	else:
		_dispatch_event("mouse.drag_end", 70, true)


func _poll_instance_server() -> void:
	while instance_server.is_connection_available():
		var peer := instance_server.take_connection()
		if peer != null:
			peer.disconnect_from_host()


func _poll_external_events() -> void:
	for event in external_server.poll():
		var event_name := str(event.get("event", ""))
		if not event_name.is_empty():
			_dispatch_event(event_name, int(event.get("priority", 0)), false)


func _update_animation(delta: float) -> void:
	animation_controller.playing = not bool(settings.get("animation_paused", false))
	var result: Dictionary = animation_controller.advance(delta)
	if bool(result.get("frame_changed", false)):
		_apply_current_texture()
	if bool(result.get("completed", false)):
		if walking:
			_ensure_movement_animation(true)
			return
		var next_action := state_machine.complete()
		if not next_action.is_empty():
			animation_controller.play(next_action, true)
			_apply_current_texture()


func _apply_current_texture() -> void:
	pet.texture = animation_controller.current_texture()


func _update_global_mouse(delta: float) -> void:
	var global_mouse := DisplayServer.mouse_get_position()
	if global_mouse != last_global_mouse:
		last_global_mouse = global_mouse
		idle_seconds = 0.0
	else:
		idle_seconds += delta
	if bool(settings.get("system_idle_enabled", true)):
		var effective_idle_seconds := native_system_idle_seconds if native_system_idle_seconds >= 0.0 else idle_seconds
		var idle_event := idle_monitor.update(effective_idle_seconds)
		if not idle_event.is_empty():
			_dispatch_event(idle_event, 40, idle_event == "system.wake")


func _update_motion(delta: float) -> void:
	if dragging:
		return
	if bool(settings.get("mouse_follow_enabled", false)):
		if walking:
			walking = false
			mouse_follow_moving = true
		var local_mouse := Vector2(DisplayServer.mouse_get_position() - desktop_strip_position)
		var follow_target := MotionAnimationResolver.cursor_lower_right_target(
			local_mouse,
			Vector2(_half_pet_width(), _half_pet_height()),
			Vector2(desktop_strip_size),
			MOUSE_FOLLOW_GAP
		)
		var follow_delta := follow_target - base_pet_position
		var follow_speed := 6.0 * clampf(float(settings.get("mouse_follow_scale", 0.45)), 0.1, 2.0)
		if follow_delta.length() > MOUSE_FOLLOW_STOP_DISTANCE:
			mouse_follow_moving = true
			var follow_axis := "horizontal" if absf(follow_delta.x) >= absf(follow_delta.y) else "vertical"
			var follow_direction := signf(follow_delta.x if follow_axis == "horizontal" else follow_delta.y)
			_set_movement_animation(follow_axis, follow_direction, not animation_controller.playing)
			base_pet_position = base_pet_position.move_toward(follow_target, WALK_SPEED * follow_speed * delta)
		else:
			base_pet_position = follow_target
			if mouse_follow_moving:
				mouse_follow_moving = false
				walk_axis = ""
				movement_action = ""
				_play_context_action()
	else:
		if mouse_follow_moving:
			mouse_follow_moving = false
			walk_axis = ""
			movement_action = ""
			_play_context_action()
		decision_seconds -= delta
		if walking:
			_ensure_movement_animation()
			base_pet_position = base_pet_position.move_toward(walk_target, WALK_SPEED * delta)
			if base_pet_position.distance_to(walk_target) <= 0.5:
				base_pet_position = walk_target
				if base_pet_position.distance_to(roam_destination) > 0.5:
					_begin_next_roam_segment()
				else:
					walking = false
					walk_axis = ""
					movement_action = ""
					decision_seconds = randf_range(2.5, 6.5)
					_play_context_action()
		elif decision_seconds <= 0.0 and bool(settings.get("godot_auto_walk", true)):
			_start_random_walk()
	if jumping:
		jump_elapsed += delta
		if jump_elapsed >= JUMP_SECONDS:
			jumping = false
			jump_elapsed = 0.0
			pet.position = base_pet_position
		else:
			var progress := jump_elapsed / JUMP_SECONDS
			pet.position = base_pet_position - Vector2(0.0, sin(progress * PI) * JUMP_HEIGHT)
			pet.position.y = _clamp_pet_y(pet.position.y)
	else:
		pet.position = base_pet_position
	_update_countdown_position()


func _start_random_walk() -> void:
	var left := _half_pet_width()
	var right := desktop_strip_size.x - _half_pet_width()
	var top := _half_pet_height() + JUMP_HEIGHT
	var bottom := desktop_strip_size.y - _half_pet_height()
	if right <= left or bottom <= top:
		return
	roam_destination = Vector2(randf_range(left, right), randf_range(top, bottom))
	if roam_destination.distance_to(base_pet_position) < 160.0:
		roam_destination = Vector2(
			right if base_pet_position.x < desktop_strip_size.x * 0.5 else left,
			top if base_pet_position.y > desktop_strip_size.y * 0.5 else bottom
		)
	walking = true
	_begin_next_roam_segment()


func _begin_next_roam_segment() -> void:
	var remaining := roam_destination - base_pet_position
	if absf(remaining.x) > 0.5:
		walk_axis = "horizontal"
		walk_target = Vector2(roam_destination.x, base_pet_position.y)
		walk_direction = signf(remaining.x)
		_set_movement_animation(walk_axis, walk_direction, true)
	elif absf(remaining.y) > 0.5:
		walk_axis = "vertical"
		walk_target = Vector2(base_pet_position.x, roam_destination.y)
		walk_direction = signf(remaining.y)
		_set_movement_animation(walk_axis, walk_direction, true)
	else:
		walking = false
		walk_axis = ""
		movement_action = ""


func _set_movement_animation(axis: String, direction: float, restart := false) -> void:
	var animations: Dictionary = current_package.get("animations", {})
	var selection: Dictionary = MotionAnimationResolver.resolve(animations, axis, direction)
	var selected := str(selection.get("action", ""))
	if selected.is_empty():
		selected = "idle"
	movement_action = selected
	pet.flip_h = bool(selection.get("flip_h", false))
	var resolved := state_machine.force_action(selected)
	if not resolved.is_empty():
		animation_controller.play(resolved, restart)
		_apply_current_texture()


func _ensure_movement_animation(restart := false) -> void:
	if movement_action.is_empty():
		return
	if restart or animation_controller.action != movement_action or not animation_controller.playing:
		state_machine.force_action(movement_action)
		animation_controller.play(movement_action, true)
		_apply_current_texture()


func _set_drag_animation(direction: float) -> void:
	var animations: Dictionary = current_package.get("animations", {})
	var selection: Dictionary = MotionAnimationResolver.resolve_drag(animations, direction)
	var selected := str(selection.get("action", ""))
	if selected.is_empty():
		return
	pet.flip_h = bool(selection.get("flip_h", false))
	state_machine.force_action(selected)
	animation_controller.play(selected, not animation_controller.playing)
	_apply_current_texture()


func _start_jump() -> void:
	if jumping or dragging:
		return
	walking = false
	walk_axis = ""
	movement_action = ""
	jumping = true
	jump_elapsed = 0.0
	var action := state_machine.resolve("click")
	if not action.is_empty():
		state_machine.force_action(action)
		animation_controller.play(action, true)


func _play_context_action() -> void:
	var action := state_machine.force_action("hover" if hovered else "idle")
	if not action.is_empty():
		animation_controller.play(action, true)


func _dispatch_event(event_name: String, priority := 0, forced := false) -> void:
	var action := state_machine.handle(event_name, priority, forced)
	if not action.is_empty():
		animation_controller.play(action, true)
		_apply_current_texture()


func _input(event: InputEvent) -> void:
	if native_presenter_enabled:
		return
	if not bool(settings.get("mouse_interaction_enabled", true)):
		return
	if event is InputEventMouseButton:
		_handle_mouse_button(event)
	elif event is InputEventMouseMotion and dragging:
		_mark_activity()
		var previous_x := base_pet_position.x
		base_pet_position.x = _clamp_pet_x(event.position.x - drag_offset_x)
		base_pet_position.y = _clamp_pet_y(event.position.y - drag_offset_y)
		var horizontal_delta := base_pet_position.x - previous_x
		if absf(horizontal_delta) > 0.1:
			_set_drag_animation(signf(horizontal_delta))
		pet.position = base_pet_position
		get_viewport().set_input_as_handled()


func _handle_mouse_button(event: InputEventMouseButton) -> void:
	if not _point_hits_pet(event.position) and not dragging:
		return
	if event.button_index == MOUSE_BUTTON_RIGHT and not event.pressed:
		_mark_activity()
		_build_menu()
		context_menu.position = DisplayServer.mouse_get_position()
		context_menu.popup()
		context_menu.grab_focus()
		get_viewport().set_input_as_handled()
		return
	if event.button_index != MOUSE_BUTTON_LEFT:
		return
	if event.pressed:
		_mark_activity()
		dragging = true
		walking = false
		walk_axis = ""
		movement_action = ""
		press_started_ms = Time.get_ticks_msec()
		press_position = event.position
		drag_offset_x = event.position.x - base_pet_position.x
		drag_offset_y = event.position.y - base_pet_position.y
		_dispatch_event("mouse.drag_start", 80, true)
	else:
		_finish_mouse_drag(event.position)
		get_viewport().set_input_as_handled()


func _update_hover() -> void:
	var local_mouse := Vector2(DisplayServer.mouse_get_position() - desktop_strip_position)
	var is_over := _point_hits_pet(local_mouse)
	if is_over == hovered:
		return
	hovered = is_over
	_dispatch_event("mouse.enter" if hovered else "mouse.leave", 30, false)


func _mark_activity() -> void:
	idle_seconds = 0.0
	var wake_event := idle_monitor.update(0.0)
	if not wake_event.is_empty():
		_dispatch_event(wake_event, 40, true)


func _pet_rect() -> Rect2:
	var size := Vector2(current_package.get("canvas", Vector2i(1, 1))) * pet_scale
	return Rect2(pet.position - size * 0.5, size)


func _pet_polygon() -> PackedVector2Array:
	var display: Dictionary = current_package.get("display", {})
	var source := animation_controller.current_hit_polygon(int(display.get("alpha_hit_test_threshold", 10)))
	if source.size() < 3:
		var rect := _pet_rect()
		return PackedVector2Array([rect.position, Vector2(rect.end.x, rect.position.y), rect.end, Vector2(rect.position.x, rect.end.y)])
	var canvas := Vector2(current_package.get("canvas", Vector2i.ONE))
	var transformed := PackedVector2Array()
	for source_point in source:
		var local_point := (source_point - canvas * 0.5) * pet_scale
		if pet.flip_h:
			local_point.x = -local_point.x
		transformed.append(pet.position + local_point)
	return transformed


func _point_hits_pet(point: Vector2) -> bool:
	var polygon := _pet_polygon()
	return polygon.size() >= 3 and Geometry2D.is_point_in_polygon(point, polygon)


func _update_mouse_passthrough() -> void:
	if native_presenter_enabled:
		return
	if current_package.is_empty():
		return
	if not bool(settings.get("mouse_interaction_enabled", true)):
		DisplayServer.window_set_mouse_passthrough(PackedVector2Array([
			Vector2(-20.0, -20.0), Vector2(-10.0, -20.0), Vector2(-15.0, -10.0),
		]))
		return
	DisplayServer.window_set_mouse_passthrough(_pet_polygon())


func _half_pet_width() -> float:
	return float(current_package.get("canvas", Vector2i(1, 1)).x) * pet_scale * 0.5


func _half_pet_height() -> float:
	return float(current_package.get("canvas", Vector2i(1, 1)).y) * pet_scale * 0.5


func _clamp_pet_x(value: float) -> float:
	return clampf(value, _half_pet_width(), desktop_strip_size.x - _half_pet_width())


func _clamp_pet_y(value: float) -> float:
	return clampf(value, _half_pet_height(), desktop_strip_size.y - _half_pet_height())


func _build_menu() -> void:
	_populate_menu(menu)
	_populate_menu(context_menu)


func _populate_menu(target: PopupMenu) -> void:
	target.clear()
	target.add_item("跳跃", MENU_JUMP)
	target.add_item("互动", MENU_WAVE)
	target.add_separator()
	target.add_check_item("暂停动画", MENU_PAUSE)
	target.add_check_item("自动行走", MENU_AUTO_WALK)
	target.add_check_item("省电模式（60 FPS）", MENU_POWER_SAVER)
	target.add_check_item("跟随鼠标", MENU_MOUSE_FOLLOW)
	target.add_check_item("空闲动作", MENU_SYSTEM_IDLE)
	target.add_check_item("始终置顶", MENU_ALWAYS_ON_TOP)
	_set_menu_checked(target, MENU_PAUSE, bool(settings.get("animation_paused", false)))
	_set_menu_checked(target, MENU_AUTO_WALK, bool(settings.get("godot_auto_walk", true)))
	_set_menu_checked(target, MENU_POWER_SAVER, bool(settings.get("godot_power_saver", false)))
	_set_menu_checked(target, MENU_MOUSE_FOLLOW, bool(settings.get("mouse_follow_enabled", false)))
	_set_menu_checked(target, MENU_SYSTEM_IDLE, bool(settings.get("system_idle_enabled", true)))
	_set_menu_checked(target, MENU_ALWAYS_ON_TOP, bool(settings.get("always_on_top", true)))
	target.add_separator()
	target.add_item("放大", MENU_SCALE_UP)
	target.add_item("缩小", MENU_SCALE_DOWN)
	target.add_separator("切换宠物")
	for index in range(packages.size()):
		var package: Dictionary = packages[index]
		target.add_radio_check_item(str(package.get("name", package.get("id", "Pet"))), MENU_PET_BASE + index)
		_set_menu_checked(target, MENU_PET_BASE + index, str(package.get("id", "")) == str(current_package.get("id", "")))
	if not effects.is_empty():
		target.add_separator("预览本地特效")
		for index in range(effects.size()):
			target.add_item(str(effects[index].get("name", effects[index].get("id", "Effect"))), MENU_EFFECT_BASE + index)
	target.add_separator()
	target.add_item("局域网互动…", MENU_LAN_INTERACTIONS)
	target.add_item("高级设置…", MENU_SETTINGS)
	target.add_item("编辑动画时长…", MENU_ANIMATION_EDITOR)
	target.add_item("导入精灵图…", MENU_IMPORT_SPRITESHEET)
	target.add_item("隐藏桌宠" if pet_window_visible else "显示桌宠", MENU_VISIBILITY)
	target.add_item("重新加载宠物库", MENU_RELOAD)
	target.add_item("打开宠物库", MENU_OPEN_PETS)
	target.add_separator("更新")
	target.add_item("检查程序更新…", MENU_APP_UPDATE)
	target.add_item("检查远程资源更新…", MENU_RESOURCE_UPDATE)
	if OS.get_name() in ["Windows", "macOS"]:
		target.add_check_item("开机启动高级版", MENU_STARTUP)
		_set_menu_checked(target, MENU_STARTUP, bool(settings.get("run_at_startup", false)) and str(settings.get("preferred_client", "")) == "godot")
	target.add_separator()
	target.add_item("退出 PetNest Advanced", MENU_QUIT)


func _set_menu_checked(target: PopupMenu, identifier: int, checked: bool) -> void:
	var index := target.get_item_index(identifier)
	if index >= 0:
		target.set_item_checked(index, checked)


func _on_menu_id_pressed(identifier: int) -> void:
	# Close first: rebuilding a visible PopupMenu from id_pressed can leave its
	# native Windows popup stuck because the selection signal fires before hide.
	menu.hide()
	context_menu.hide()
	if identifier >= MENU_PET_BASE and identifier < MENU_PET_BASE + packages.size():
		_load_package(packages[identifier - MENU_PET_BASE])
		_build_menu.call_deferred()
		return
	if identifier >= MENU_EFFECT_BASE and identifier < MENU_EFFECT_BASE + effects.size():
		_play_effect(str(effects[identifier - MENU_EFFECT_BASE].get("id", "")), false)
		_build_menu.call_deferred()
		return
	match identifier:
		MENU_PAUSE:
			settings["animation_paused"] = not bool(settings.get("animation_paused", false))
		MENU_AUTO_WALK:
			settings["godot_auto_walk"] = not bool(settings.get("godot_auto_walk", true))
			walking = false
			walk_axis = ""
			movement_action = ""
		MENU_POWER_SAVER:
			settings["godot_power_saver"] = not bool(settings.get("godot_power_saver", false))
			_configure_runtime()
		MENU_MOUSE_FOLLOW:
			settings["mouse_follow_enabled"] = not bool(settings.get("mouse_follow_enabled", false))
			walking = false
			walk_axis = ""
			movement_action = ""
			mouse_follow_moving = false
			if not bool(settings["mouse_follow_enabled"]):
				_play_context_action()
		MENU_SYSTEM_IDLE:
			settings["system_idle_enabled"] = not bool(settings.get("system_idle_enabled", true))
			_mark_activity()
		MENU_ALWAYS_ON_TOP:
			settings["always_on_top"] = not bool(settings.get("always_on_top", true))
			get_window().always_on_top = bool(settings["always_on_top"])
			if native_presenter_enabled:
				native_presenter.set_always_on_top(bool(settings["always_on_top"]))
		MENU_SCALE_UP:
			_set_pet_scale(pet_scale + 0.1)
		MENU_SCALE_DOWN:
			_set_pet_scale(pet_scale - 0.1)
		MENU_JUMP:
			_start_jump()
		MENU_WAVE:
			_dispatch_event("mouse.click", 50, true)
		MENU_RELOAD:
			_reload_packages(str(current_package.get("id", "")))
			_reload_effects()
		MENU_SETTINGS:
			_show_settings_dialog()
		MENU_LAN_INTERACTIONS:
			_show_lan_interactions()
		MENU_VISIBILITY:
			_toggle_visibility()
		MENU_ANIMATION_EDITOR:
			_show_animation_editor()
		MENU_IMPORT_SPRITESHEET:
			_show_spritesheet_importer()
		MENU_OPEN_PETS:
			OS.shell_open(pets_root)
		MENU_APP_UPDATE:
			_launch_maintenance("app-update")
		MENU_RESOURCE_UPDATE:
			_launch_maintenance("resource-update")
		MENU_STARTUP:
			_set_platform_startup(not (bool(settings.get("run_at_startup", false)) and str(settings.get("preferred_client", "")) == "godot"))
		MENU_QUIT:
			_shutdown()
			return
	_save_settings()
	_build_menu.call_deferred()


func _show_settings_dialog() -> void:
	if is_instance_valid(settings_dialog):
		settings_dialog.show()
		settings_dialog.grab_focus()
		return
	settings_dialog = SettingsDialog.new()
	settings_dialog.configure(settings, cursor_styles)
	settings_dialog.settings_applied.connect(_apply_dialog_settings)
	add_child(settings_dialog)
	settings_dialog.popup_centered()


func _show_animation_editor() -> void:
	if is_instance_valid(animation_editor_dialog):
		animation_editor_dialog.show()
		animation_editor_dialog.grab_focus()
		return
	animation_editor_dialog = AnimationEditorDialog.new()
	animation_editor_dialog.configure(current_package)
	animation_editor_dialog.durations_saved.connect(_save_animation_durations)
	add_child(animation_editor_dialog)
	animation_editor_dialog.popup_centered()


func _show_lan_interactions() -> void:
	if is_instance_valid(lan_interaction_dialog):
		lan_interaction_dialog.show()
		lan_interaction_dialog.grab_focus()
		_refresh_lan_dialog_peers()
		return
	lan_service.discover()
	lan_interaction_dialog = LanInteractionDialog.new()
	lan_interaction_dialog.configure(lan_service.peer_list(), effects)
	lan_interaction_dialog.interaction_requested.connect(_send_lan_interaction)
	lan_interaction_dialog.effect_preview_requested.connect(_preview_lan_effect)
	lan_interaction_dialog.discover_requested.connect(lan_service.discover)
	lan_interaction_dialog.probe_requested.connect(_on_lan_probe_requested)
	add_child(lan_interaction_dialog)
	lan_interaction_dialog.popup_centered()


func _send_lan_interaction(target_device_id: String, interaction_type: String, text: String, effect_id: String) -> void:
	var sent := lan_service.send_interaction(target_device_id, interaction_type, text, effect_id)
	if is_instance_valid(lan_interaction_dialog):
		lan_interaction_dialog.call("set_status", "已发送" if sent else "发送失败，请稍后重试")


func _preview_lan_effect(effect_id: String) -> void:
	var played := _play_effect(effect_id, false)
	if is_instance_valid(lan_interaction_dialog):
		lan_interaction_dialog.call("set_status", "正在本机预览特效" if played else "本地特效不可用")


func _on_lan_probe_requested(ip_address: String, remote_port: int) -> void:
	var sent := lan_service.probe(ip_address, remote_port)
	if sent and is_instance_valid(lan_interaction_dialog):
		lan_interaction_dialog.call("set_status", "已发送验证请求，正在等待对方响应…")


func _save_animation_durations(updates: Dictionary) -> void:
	var result := package_editor.update_frame_durations(str(current_package.get("root", "")), updates)
	if not bool(result.get("ok", false)):
		push_error("无法保存动画时长：" + str(result.get("error", "未知错误")))
		return
	_reload_packages(str(current_package.get("id", "")))


func _show_spritesheet_importer() -> void:
	if is_instance_valid(spritesheet_import_dialog):
		spritesheet_import_dialog.show()
		spritesheet_import_dialog.grab_focus()
		return
	spritesheet_import_dialog = SpritesheetImportDialog.new()
	spritesheet_import_dialog.configure(pets_root)
	spritesheet_import_dialog.package_imported.connect(_on_package_imported)
	add_child(spritesheet_import_dialog)
	spritesheet_import_dialog.popup_centered()


func _on_package_imported(package_id: String) -> void:
	_reload_packages(package_id)


func _apply_dialog_settings(updated: Dictionary) -> void:
	settings = updated
	_configure_runtime()
	get_window().always_on_top = bool(settings.get("always_on_top", true))
	if native_presenter_enabled:
		native_presenter.set_always_on_top(bool(settings.get("always_on_top", true)))
	_set_pet_scale(float(settings.get("scale", pet_scale)))
	idle_monitor.configure(
		float(settings.get("system_bored_seconds", 20)),
		float(settings.get("system_sleep_seconds", 35))
	)
	_mark_activity()
	_configure_external_events()
	_configure_lan_interactions()
	_reload_cursor_styles()
	_apply_cursor_style()
	_apply_countdown_theme()
	_update_countdown()
	_update_mouse_passthrough()
	_save_settings()
	_build_menu()


func _reload_cursor_styles() -> void:
	cursor_styles = cursor_style_catalog.discover(cursor_style_catalog.default_roots())


func _apply_cursor_style() -> void:
	var selected := cursor_style_catalog.find(cursor_styles, str(settings.get("cursor_style_id", "")))
	var enabled := bool(settings.get("cursor_style_enabled", false)) and not selected.is_empty()
	if native_presenter_enabled:
		native_presenter.set_cursor_style(enabled, str(selected.get("root", "")) if enabled else "")
		return
	if OS.get_name() != "macOS":
		return
	var restore_pending := bool(settings.get("cursor_restore_pending", false))
	if not enabled and not restore_pending:
		return
	var executable := _maintenance_executable()
	if executable.is_empty():
		push_warning("macOS 系统光标需要同一安装包中的 PetNest 标准维护组件")
		return
	var arguments := PackedStringArray(["--cursor-action", "apply" if enabled else "restore"])
	if enabled:
		arguments.append("--cursor-style-root")
		arguments.append(str(selected.get("root", "")))
	var output: Array = []
	var result := OS.execute(executable, arguments, output, true, true)
	if result == 0:
		settings["cursor_restore_pending"] = enabled
		_save_settings()
	else:
		push_warning("无法%s macOS 系统光标：%s" % ["应用" if enabled else "恢复", " ".join(output)])


func _restore_macos_cursor_style() -> void:
	if OS.get_name() != "macOS" or not bool(settings.get("cursor_restore_pending", false)):
		return
	var executable := _maintenance_executable()
	if executable.is_empty():
		return
	var output: Array = []
	if OS.execute(executable, PackedStringArray(["--cursor-action", "restore"]), output, true, true) == 0:
		settings["cursor_restore_pending"] = false
	else:
		push_warning("退出时无法恢复 macOS 系统光标：%s" % " ".join(output))


func _toggle_visibility() -> void:
	pet_window_visible = not pet_window_visible
	if native_presenter_enabled:
		native_presenter.set_visible(pet_window_visible)
	else:
		get_window().visible = pet_window_visible
	if pet_window_visible and not native_presenter_enabled:
		_configure_window()
		_update_mouse_passthrough()
	_build_menu()


func _on_tray_pressed(mouse_button: int, _mouse_position: Vector2i) -> void:
	if mouse_button == MOUSE_BUTTON_LEFT:
		_toggle_visibility()


func _set_pet_scale(value: float) -> void:
	var display: Dictionary = current_package["display"]
	pet_scale = clampf(value, float(display.get("min_scale", 0.25)), float(display.get("max_scale", 2.0)))
	settings["scale"] = pet_scale
	pet.scale = Vector2.ONE * pet_scale
	base_pet_position.x = _clamp_pet_x(base_pet_position.x)
	base_pet_position.y = _clamp_pet_y(base_pet_position.y)
	pet.position = base_pet_position
	_update_mouse_passthrough()


func _set_platform_startup(enabled: bool) -> void:
	if OS.get_name() == "macOS":
		_set_macos_startup(enabled)
		return
	if OS.get_name() != "Windows":
		return
	var executable := OS.get_executable_path()
	var value := "\"%s\"" % executable
	var arguments := PackedStringArray(["ADD", "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run", "/v", "PetNest", "/t", "REG_SZ", "/d", value, "/f"])
	if not enabled:
		arguments = PackedStringArray(["DELETE", "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run", "/v", "PetNest", "/f"])
	var output: Array = []
	var result := OS.execute("reg.exe", arguments, output, true, true)
	if result == 0:
		settings["run_at_startup"] = enabled
		settings["preferred_client"] = "godot" if enabled else settings.get("preferred_client", "pyside6")
	else:
		push_warning("无法更新 Windows 开机启动项：" + " ".join(output))


func _set_macos_startup(enabled: bool) -> void:
	var home := OS.get_environment("HOME").strip_edges()
	if home.is_empty():
		push_warning("无法更新 macOS 登录启动项：HOME 不可用")
		return
	var agents_root := home.path_join("Library").path_join("LaunchAgents")
	var plist_path := agents_root.path_join("com.petnest.advanced.plist")
	var error := OK
	if enabled:
		error = DirAccess.make_dir_recursive_absolute(agents_root)
		if error == OK:
			var file := FileAccess.open(plist_path, FileAccess.WRITE)
			if file == null:
				error = FileAccess.get_open_error()
			else:
				var executable := _xml_escape(OS.get_executable_path())
				file.store_string("""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.petnest.advanced</string>
  <key>ProgramArguments</key><array><string>%s</string></array>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
""" % executable)
				file.close()
	else:
		if FileAccess.file_exists(plist_path):
			error = DirAccess.remove_absolute(plist_path)
	if error == OK:
		settings["run_at_startup"] = enabled
		settings["preferred_client"] = "godot" if enabled else settings.get("preferred_client", "pyside6")
	else:
		push_warning("无法更新 macOS 登录启动项：%s" % error_string(error))


func _xml_escape(value: String) -> String:
	return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;").replace("'", "&apos;")


func _maintenance_executable() -> String:
	var configured := OS.get_environment("PETNEST_MAINTENANCE_EXE").strip_edges()
	if not configured.is_empty() and FileAccess.file_exists(configured):
		return configured
	var executable_dir := OS.get_executable_path().get_base_dir()
	var candidates := PackedStringArray()
	if OS.get_name() == "macOS":
		candidates.append(executable_dir.path_join("../../..").path_join("PetNest.app").path_join("Contents").path_join("MacOS").path_join("PetNest").simplify_path())
		candidates.append(ProjectSettings.globalize_path("res://../../dist/PetNest.app/Contents/MacOS/PetNest").simplify_path())
	else:
		candidates.append(executable_dir.path_join("..").path_join("PetNest.exe").simplify_path())
		candidates.append(executable_dir.path_join("..").path_join("PetNest").path_join("PetNest.exe").simplify_path())
		candidates.append(ProjectSettings.globalize_path("res://../../dist/PetNest/PetNest.exe").simplify_path())
	for candidate in candidates:
		if FileAccess.file_exists(candidate):
			return candidate
	return ""


func _launch_maintenance(mode: String) -> void:
	if OS.get_name() == "macOS" and mode == "app-update":
		OS.shell_open("https://github.com/qinxiaohui-qq/PetNest/releases/latest")
		_show_interaction_bubble("已打开 PetNest 最新版本页面")
		return
	var executable := _maintenance_executable()
	if executable.is_empty():
		_show_interaction_bubble("未找到标准版维护组件，请重新运行完整安装包")
		push_warning("无法打开 PetNest 更新入口：未找到 PetNest.exe")
		return
	var arguments := PackedStringArray([
		"--maintenance",
		mode,
		"--parent-pid",
		str(OS.get_process_id()),
	])
	if mode == "app-update":
		arguments.append("--restart-path")
		arguments.append(OS.get_executable_path())
	var process_id := OS.create_process(executable, arguments)
	if process_id <= 0:
		_show_interaction_bubble("无法打开更新窗口")
		push_warning("无法启动 PetNest 维护组件：%s" % executable)


func _load_tray_icon() -> void:
	var preview := str(current_package.get("preview", ""))
	if not FileAccess.file_exists(preview):
		return
	var image := Image.new()
	if image.load(preview) != OK:
		return
	image.resize(64, 64, Image.INTERPOLATE_LANCZOS)
	tray.icon = ImageTexture.create_from_image(image)
	tray.tooltip = "PetNest Advanced · " + str(current_package.get("name", "Pet"))


func _update_countdown() -> void:
	if not bool(settings.get("work_countdown_enabled", true)):
		countdown.visible = false
		return
	var now := Time.get_datetime_dict_from_system()
	var python_weekday := (int(now.get("weekday", 0)) + 6) % 7
	var daily_raw = settings.get("daily_work_end_times", {})
	var end_text := str(settings.get("work_end_time", "18:00"))
	if typeof(daily_raw) == TYPE_DICTIONARY and daily_raw.has(str(python_weekday)):
		var configured = daily_raw[str(python_weekday)]
		if configured == null or str(configured).is_empty():
			countdown.visible = false
			return
		end_text = str(configured)
	var parts := end_text.split(":")
	if parts.size() != 2 or not parts[0].is_valid_int() or not parts[1].is_valid_int():
		countdown.visible = false
		return
	var current_seconds := int(now.get("hour", 0)) * 3600 + int(now.get("minute", 0)) * 60 + int(now.get("second", 0))
	var end_seconds := int(parts[0]) * 3600 + int(parts[1]) * 60
	var remaining := maxi(end_seconds - current_seconds, 0)
	if remaining == 0:
		countdown.text = "今日已下班"
	else:
		countdown.text = "下班 %02d:%02d:%02d" % [remaining / 3600, (remaining % 3600) / 60, remaining % 60]
	countdown.visible = true
	_apply_countdown_theme()
	_update_countdown_position()


func _update_countdown_position() -> void:
	if not countdown.visible:
		return
	var size := countdown.get_combined_minimum_size()
	var configured_width := float(settings.get("countdown_width", 132))
	var configured_height := float(settings.get("countdown_height", 37))
	var gap := float(settings.get("countdown_gap", 0))
	countdown.size = Vector2(maxf(size.x, configured_width), maxf(size.y, configured_height))
	var placement := str(settings.get("countdown_placement", "above"))
	var card_y := pet.position.y - _half_pet_height() - countdown.size.y - gap - 5.0
	if placement == "below":
		card_y = pet.position.y + _half_pet_height() + gap + 5.0
	countdown.position = Vector2(
		clampf(pet.position.x - countdown.size.x * 0.5, 0.0, desktop_strip_size.x - countdown.size.x),
		clampf(card_y, 0.0, maxf(0.0, desktop_strip_size.y - countdown.size.y))
	)


func _apply_countdown_theme() -> void:
	var theme_name := str(settings.get("countdown_theme", "cream"))
	var style := StyleBoxFlat.new()
	style.corner_radius_top_left = 10
	style.corner_radius_top_right = 10
	style.corner_radius_bottom_left = 10
	style.corner_radius_bottom_right = 10
	style.content_margin_left = 8.0
	style.content_margin_right = 8.0
	match theme_name:
		"night":
			style.bg_color = Color(0.08, 0.10, 0.15, 0.86)
			style.border_color = Color(0.45, 0.62, 0.92, 0.9)
			countdown.add_theme_color_override("font_color", Color(0.94, 0.96, 1.0))
		"yarn":
			style.bg_color = Color(0.92, 0.74, 0.70, 0.88)
			style.border_color = Color(0.55, 0.30, 0.32, 0.9)
			countdown.add_theme_color_override("font_color", Color(0.25, 0.12, 0.13))
		_:
			style.bg_color = Color(0.98, 0.91, 0.72, 0.90)
			style.border_color = Color(0.64, 0.46, 0.26, 0.9)
			countdown.add_theme_color_override("font_color", Color(0.20, 0.15, 0.10))
	style.set_border_width_all(1)
	countdown.add_theme_stylebox_override("normal", style)


func _save_settings() -> void:
	var error := settings_store.save_settings(settings)
	if error != OK:
		push_warning("无法保存 PetNest 设置：%s" % error_string(error))


func _capture_render(path: String) -> void:
	await get_tree().create_timer(0.5).timeout
	await RenderingServer.frame_post_draw
	var image := get_viewport().get_texture().get_image()
	var error := image.save_png(path)
	if error != OK:
		push_error("无法保存 Godot 渲染校验图：%s" % error_string(error))
	_shutdown()


func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_CLOSE_REQUEST:
		_shutdown()


func _shutdown() -> void:
	if shutting_down:
		return
	shutting_down = true
	settings["godot_pet_x"] = base_pet_position.x
	settings["godot_pet_y"] = base_pet_position.y
	_restore_macos_cursor_style()
	_save_settings()
	external_server.stop()
	lan_service.stop()
	effect_player.stop()
	if native_presenter_enabled:
		native_presenter.stop()
	if macos_idle_bridge_enabled:
		macos_idle_bridge.stop()
	instance_server.stop()
	get_tree().quit()
