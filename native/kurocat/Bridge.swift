// PetNest adapter. Original upstream drawing; physics adds a scripted idle-age override.
import AppKit
import QuartzCore

// Isolate upstream preferences: PetNest owns persistence, never write KuroCat defaults.
final class UserDefaults {
    static let standard = UserDefaults()
    func set(_ value: Any, forKey: String) {}
    func object(forKey: String) -> Any? { nil }
    func string(forKey: String) -> String? { nil }
    func double(forKey: String) -> Double { 0 }
    func integer(forKey: String) -> Int { 0 }
}

// No second global input monitor: all input comes from PetNest's permission-aware relay.
final class InputEngine {
    static let shared = InputEngine()
    var activeKeys: Set<PhysicalKey> = []
    var pressedOrder: [PhysicalKey] = []
    var mouseVelocity = CGVector.zero
    var lastMouseLocation = CGPoint.zero
    var leftMouseDown = false
    var rightMouseDown = false
    var lastMouseMoveTime = 0.0
    var lastMouseClickTime = 0.0
    var lastKeyActivityTime = 0.0
    var currentKPM = 0.0
    func pollMouse(dt: CGFloat) {}
}

final class Companion {
    var appearance = PetAppearance()
    var physics = CatPhysics()
    var keys: [PhysicalKey] = []
    var events: [(Int32, Bool)] = []
    var previous: CGPoint?
    var lastMove = CACurrentMediaTime()
    var lastClick = CACurrentMediaTime()
    var lastKey = CACurrentMediaTime()
    var left = false
    var right = false
}

@_cdecl("petnest_cat_create")
public func createCat() -> UnsafeMutableRawPointer {
    Unmanaged.passRetained(Companion()).toOpaque()
}

@_cdecl("petnest_cat_destroy")
public func destroyCat(_ handle: UnsafeMutableRawPointer) {
    Unmanaged<Companion>.fromOpaque(handle).release()
}

@_cdecl("petnest_cat_key")
public func keyCat(_ handle: UnsafeMutableRawPointer, _ code: Int32, _ down: Int32) {
    let cat = Unmanaged<Companion>.fromOpaque(handle).takeUnretainedValue()
    // Bound transient input storage while a window is paused.
    if cat.events.count < 512 { cat.events.append((code, down != 0)) }
}

@_cdecl("petnest_cat_appearance")
public func appearanceCat(_ handle: UnsafeMutableRawPointer, _ json: UnsafePointer<CChar>) {
    let cat = Unmanaged<Companion>.fromOpaque(handle).takeUnretainedValue()
    cat.appearance = PetAppearance(String(cString: json).data(using: .utf8))
}

@_cdecl("petnest_cat_render")
public func renderCat(_ handle: UnsafeMutableRawPointer, _ pixels: UnsafeMutableRawPointer,
               _ x: Double, _ y: Double, _ delta: Double, _ coat: Int32,
               _ keyboard: Int32, _ look: Int32, _ petting: Int32,
               _ idle: Double) -> Int32 {
    return autoreleasepool {
    let cat = Unmanaged<Companion>.fromOpaque(handle).takeUnretainedValue()
    PetAppearance.current = cat.appearance
    let now = CACurrentMediaTime()
    let dt = max(0.001, min(0.04, delta))
    let settings = CatSettings.shared
    settings.coatTheme = coat == 1 ? .siamese : .classicBlack
    settings.eyeTheme = coat == 1 ? .siameseBlue : .neonChartreuse
    settings.keyboardTheme = keyboard == 1 ? .midnightHacker : keyboard == 2 ? .retroCream : .classicMilk
    settings.petInteraction = petting != 0
    for (code, down) in cat.events {
        if code == -1 {
            cat.keys.removeAll(); cat.left = false; cat.right = false
            cat.physics = CatPhysics()
        } else if code == -2 || code == -3 {
            if code == -2 { cat.left = down } else { cat.right = down }
            cat.lastClick = now
            cat.physics.triggerMouseClick(button: code == -2 ? 0 : 1, isDown: down)
        } else if code >= 0, let key = PhysicalKey.fromCGKeyCode(UInt16(code)) {
            cat.lastKey = now
            if down {
                if !cat.keys.contains(key) { cat.keys.append(key) }
                InputEngine.shared.activeKeys = Set(cat.keys)
                cat.physics.triggerKeyDown(key, at: now)
            } else { cat.keys.removeAll { $0 == key } }
        }
    }
    cat.events.removeAll(keepingCapacity: true)
    let point = CGPoint(x: x, y: y)
    let old = cat.previous ?? point
    let dx = point.x - old.x, dy = point.y - old.y
    cat.previous = point
    if hypot(dx, dy) > 0.1 {
        cat.lastMove = now
        if petting != 0 {
            let zone = CatRenderer.hitTest(point: point, physics: cat.physics, showPermissionPill: false)
            if zone == .head || zone == .body {
                cat.physics.registerPetStroke(canvasPoint: point, delta: hypot(dx, dy), isHead: zone == .head, at: now)
            }
        }
    }
    // PetNest supplies the inactivity age, respecting its sleep preference.
    let activity = now - max(0, idle)
    let input = ScriptedFrameInput(now: now, activeKeys: Set(cat.keys), orderedKeys: cat.keys,
        mouseScreenPos: look != 0 ? CGPoint(x: x, y: 320-y) : CGPoint(x: 184, y: 196),
        mouseVelocity: look != 0 ? CGVector(dx: dx/dt, dy: -dy/dt) : .zero,
        leftMouseDown: cat.left, rightMouseDown: cat.right,
        lastMouseMoveTime: look != 0 ? cat.lastMove : 0,
        lastMouseClickTime: cat.lastClick, lastKeyActivityTime: activity, idleSeconds: idle)
    InputEngine.shared.activeKeys = Set(cat.keys)
    cat.physics.step(dt: dt, windowFrameInScreen: CGRect(x: 0, y: 0, width: 360, height: 320), scripted: input)
    guard let ctx = CGContext(data: pixels, width: 360, height: 320, bitsPerComponent: 8,
        bytesPerRow: 360*4, space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return 0 }
    ctx.clear(CGRect(x: 0, y: 0, width: 360, height: 320))
    ctx.translateBy(x: 0, y: 320)
    ctx.scaleBy(x: 1, y: -1)
    CatRenderer.draw(in: ctx, physics: cat.physics, showPermissionPill: false)
    return 1
    }
}
