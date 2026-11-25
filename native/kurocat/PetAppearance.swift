// PetNest coat layers, clipped to the upstream animated geometry (never recolor pixels).
import AppKit
import ImageIO

final class PetAppearance {
    static var current = PetAppearance()
    static var masks: [String: CGImage] = [:]
    var pattern = "black"
    var enabled = false
    var palette: [String: NSColor] = [:]
    var customEyes = false
    var customKeyboard = false
    var face = "none"
    var chest: CGFloat = 0
    var paws: CGFloat = 0
    var amount: CGFloat = 0.55
    var maskPath = ""
    let white = NSColor(srgbRed: 0.98, green: 0.965, blue: 0.935, alpha: 1)

    init(_ data: Data? = nil) {
        guard let data = data, let raw = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return }
        pattern = raw["coat"] as? String ?? "black"
        enabled = raw["custom_coat"] as? Bool ?? false
        customEyes = raw["custom_eyes"] as? Bool ?? false
        customKeyboard = raw["custom_keyboard"] as? Bool ?? false
        maskPath = raw["mask_path"] as? String ?? ""
        if let colors = raw["colors"] as? [String: String] {
            for (key, hex) in colors {
                if let n = UInt32(hex.dropFirst(), radix: 16) {
                    palette[key] = NSColor(srgbRed: CGFloat((n >> 16) & 255)/255,
                        green: CGFloat((n >> 8) & 255)/255, blue: CGFloat(n & 255)/255, alpha: 1)
                }
            }
        }
        if let marks = raw["white_markings"] as? [String: Any] {
            face = marks["face"] as? String ?? "none"
            chest = CGFloat(marks["chest"] as? Double ?? 0)
            paws = CGFloat(marks["paws"] as? Double ?? 0)
            amount = CGFloat(marks["amount"] as? Double ?? 0.55)
        }
    }

    var fur: NSColor { palette["fur"] ?? .black }
    var point: NSColor { palette["point"] ?? fur }
    var secondary: NSColor { palette["secondary"] ?? point }
    var eye: NSColor { palette["eyes"] ?? .green }
    var line: NSColor {
        let c = fur.usingColorSpace(.deviceRGB) ?? fur
        return c.redComponent * 0.3 + c.greenComponent * 0.6 + c.blueComponent * 0.1 > 0.45
            ? NSColor(srgbRed: 0.30, green: 0.27, blue: 0.24, alpha: 0.70)
            : NSColor(srgbRed: 0.82, green: 0.88, blue: 0.85, alpha: 0.76)
    }
    var pawColor: NSColor { paws > 0 ? white : pattern == "siamese" ? point : fur }
    func earColor(_ left: Bool) -> NSColor {
        switch pattern {
        case "siamese": return point
        case "tortie": return left ? point : fur
        case "calico": return left ? point : secondary
        case "shaded": return fur.blended(withFraction: 0.55, of: point) ?? fur
        default: return fur
        }
    }

    static func fill(_ ctx: CGContext, _ path: CGPath, _ color: NSColor) {
        ctx.setFillColor(color.cgColor); ctx.addPath(path); ctx.fillPath()
    }

    // Opaque centers and translucent feathered edges: retain the two-color tortie style.
    func spot(_ ctx: CGContext, _ x: CGFloat, _ y: CGFloat, _ rx: CGFloat, _ ry: CGFloat,
              _ color: NSColor, _ opacity: CGFloat = 1) {
        ctx.saveGState(); ctx.translateBy(x: x, y: y); ctx.scaleBy(x: rx, y: ry)
        let colors = [color.withAlphaComponent(opacity).cgColor,
                      color.withAlphaComponent(opacity * 0.92).cgColor,
                      color.withAlphaComponent(0).cgColor] as CFArray
        if let grad = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: colors, locations: [0, 0.5, 1]) {
            ctx.drawRadialGradient(grad, startCenter: .zero, startRadius: 0,
                                   endCenter: .zero, endRadius: 1, options: [])
        }
        ctx.restoreGState()
    }

    func texture(_ ctx: CGContext, rect: CGRect, head: Bool) {
        let key = maskPath + (head ? ":head" : ":body")
        if Self.masks[key] == nil,
           let source = CGImageSourceCreateWithURL(URL(fileURLWithPath: maskPath) as CFURL, nil),
           let image = CGImageSourceCreateImageAtIndex(source, 0, nil) {
            // Downsample once, then cache the luminance mask; no per-frame pixel scans.
            let w = 256, h = 384
            var bytes = [UInt8](repeating: 0, count: w * h)
            bytes.withUnsafeMutableBytes { buffer in
                if let context = CGContext(data: buffer.baseAddress, width: w, height: h,
                    bitsPerComponent: 8, bytesPerRow: w, space: CGColorSpaceCreateDeviceGray(), bitmapInfo: 0) {
                    context.interpolationQuality = .high
                    context.draw(image, in: CGRect(x: 0, y: 0, width: w, height: h))
                }
            }
            if let provider = CGDataProvider(data: Data(bytes) as CFData) {
                let decode: [CGFloat] = [1, 0]
                if let mask = CGImage(maskWidth: w, height: h, bitsPerComponent: 8, bitsPerPixel: 8,
                    bytesPerRow: w, provider: provider, decode: decode, shouldInterpolate: true) {
                    let cut = head ? CGRect(x: 0, y: 0, width: w, height: 115)
                                   : CGRect(x: 0, y: 115, width: w, height: h - 115)
                    Self.masks[key] = mask.cropping(to: cut)
                }
            }
        }
        guard let mask = Self.masks[key] else { return }
        ctx.saveGState()
        // CGContext mask rows need the same top-down orientation as the cat canvas.
        ctx.translateBy(x: rect.minX, y: rect.maxY); ctx.scaleBy(x: 1, y: -1)
        let local = CGRect(origin: .zero, size: rect.size)
        ctx.clip(to: local, mask: mask)
        ctx.setFillColor(point.withAlphaComponent(0.75).cgColor); ctx.fill(local)
        ctx.restoreGState()
    }

    func body(_ ctx: CGContext, path: CGPath, seat: CGPoint, head: CGPoint, physics: CatPhysics) {
        Self.fill(ctx, path, fur)
        ctx.saveGState(); ctx.addPath(path); ctx.clip()
        ctx.saveGState(); ctx.translateBy(x: seat.x, y: seat.y); ctx.rotate(by: physics.bodyTilt.value)
        let sy = physics.bodySquash.value
        ctx.scaleBy(x: 1 + (1 - sy) * 0.55, y: sy)
        switch pattern {
        case "tabby": texture(ctx, rect: CGRect(x: -53, y: -100, width: 106, height: 114), head: false)
        case "shaded":
            spot(ctx, -53, -66, 47, 105, point, 0.72)
            spot(ctx, 53, -66, 47, 105, point, 0.72)
        case "tortie":
            spot(ctx, 43, -58, 32, 34, point)
            spot(ctx, 37, -39, 28, 26, point, 0.85)
            spot(ctx, -43, -10, 32, 42, point)
            spot(ctx, -25, 7, 15, 21, point, 0.72)
        case "calico":
            spot(ctx, -40, -34, 35, 48, point)
            spot(ctx, 35, -6, 32, 37, secondary)
        default: break
        }
        ctx.restoreGState()
        ctx.saveGState(); ctx.translateBy(x: head.x, y: head.y); ctx.rotate(by: physics.headTilt.value)
        ctx.translateBy(x: physics.headYaw.value * 12, y: physics.headPitch.value * 8)
        ctx.scaleBy(x: max(0.75, cos(physics.headYaw.value * 0.5)), y: 1)
        switch pattern {
        case "tabby": texture(ctx, rect: CGRect(x: -42, y: -34, width: 84, height: 43), head: true)
        case "shaded": spot(ctx, 0, -42, 56, 42, point, 0.8)
        case "siamese": spot(ctx, 0, -12, 72, 67, point)
        case "tortie":
            spot(ctx, -35, -29, 27, 42, point)
            spot(ctx, -31, -8, 24, 19, point, 0.70)
        case "calico":
            spot(ctx, -32, -29, 35, 39, point)
            spot(ctx, 33, -8, 28, 37, secondary)
        default: break
        }
        if face != "none" {
            let width: CGFloat = face == "inverted_v" ? 21 + amount * 13 : 8 + amount * 9
            let blaze = CGMutablePath()
            blaze.move(to: CGPoint(x: 0, y: -24 - amount * 5))
            blaze.addCurve(to: CGPoint(x: -width, y: 24), control1: CGPoint(x: -6, y: -22), control2: CGPoint(x: -5, y: 10))
            blaze.addQuadCurve(to: CGPoint(x: width, y: 24), control: CGPoint(x: 0, y: 49))
            blaze.addCurve(to: CGPoint(x: 0, y: -24 - amount * 5), control1: CGPoint(x: 5, y: 10), control2: CGPoint(x: 6, y: -22))
            blaze.closeSubpath(); Self.fill(ctx, blaze, white)
        }
        ctx.restoreGState()
        ctx.saveGState(); ctx.translateBy(x: seat.x, y: seat.y); ctx.rotate(by: physics.bodyTilt.value)
        ctx.scaleBy(x: 1 + (1 - sy) * 0.55, y: sy)
        if chest > 0 {
            let w = 17 + amount * 15
            let bottom: CGFloat = -55 + chest * 65
            let bib = CGMutablePath()
            bib.move(to: CGPoint(x: -18, y: -91))
            bib.addCurve(to: CGPoint(x: 0, y: bottom), control1: CGPoint(x: -w - 12, y: -56), control2: CGPoint(x: -w, y: bottom - 24))
            bib.addCurve(to: CGPoint(x: 18, y: -91), control1: CGPoint(x: w, y: bottom - 24), control2: CGPoint(x: w + 12, y: -56))
            bib.closeSubpath(); Self.fill(ctx, bib, white)
        }
        ctx.restoreGState(); ctx.restoreGState()
    }

    func tail(_ ctx: CGContext, path: CGPath, root: CGPoint, tip: CGPoint) {
        ctx.saveGState(); ctx.addPath(path); ctx.clip()
        ctx.setFillColor((pattern == "siamese" ? point : fur).cgColor); ctx.fill(path.boundingBoxOfPath)
        if pattern == "shaded" || pattern == "tortie" || pattern == "calico" {
            spot(ctx, tip.x - 10, tip.y + 3, 24, 22, pattern == "calico" ? secondary : point)
        } else if pattern == "tabby" {
            let dx = tip.x - root.x, dy = tip.y - root.y
            ctx.translateBy(x: root.x, y: root.y); ctx.rotate(by: atan2(dy, dx))
            ctx.setFillColor(point.withAlphaComponent(0.75).cgColor)
            for t in [0.30, 0.57, 0.84] as [CGFloat] {
                ctx.fill(CGRect(x: hypot(dx, dy) * t, y: -25, width: 6, height: 50))
            }
        }
        ctx.restoreGState()
    }

    // Read a tiny patch of the already-painted coat, before adding this limb.
    // The bridge supplies RGBA8; conversion includes its flipped canvas transform
    // and yields bitmap row coordinates (do not invert Y a second time).
    func shoulderColor(_ ctx: CGContext, at point: CGPoint) -> NSColor {
        guard ctx.bitsPerPixel == 32, let data = ctx.data else { return fur }
        let device = ctx.convertToDeviceSpace(point)
        let x = Int(device.x.rounded()), y = Int(device.y.rounded())
        let bytes = data.assumingMemoryBound(to: UInt8.self)
        var red: CGFloat = 0, green: CGFloat = 0, blue: CGFloat = 0, count: CGFloat = 0
        for dy in -1...1 {
            for dx in -1...1 {
                let px = x + dx, py = y + dy
                guard px >= 0, px < ctx.width, py >= 0, py < ctx.height else { continue }
                let i = py * ctx.bytesPerRow + px * 4
                guard bytes[i + 3] > 240 else { continue }
                let alpha = CGFloat(bytes[i + 3])
                red += CGFloat(bytes[i]) / alpha
                green += CGFloat(bytes[i + 1]) / alpha
                blue += CGFloat(bytes[i + 2]) / alpha
                count += 1
            }
        }
        guard count > 0 else { return fur }
        return NSColor(srgbRed: red / count, green: green / count, blue: blue / count, alpha: 1)
    }

    func limb(_ ctx: CGContext, path: CGPath, paw: CGRect, start: CGPoint, end: CGPoint) {
        let shoulder = shoulderColor(ctx, at: start)
        let arm = shoulder.blended(withFraction: 0.20, of: fur) ?? shoulder
        let tip = paws > 0 || pattern == "siamese" ? pawColor : arm
        // Reveal the actual coat underneath at the shoulder, including its white bib
        // and colored patches. An opaque base fill here would defeat this blend.
        let fade = min(0.30, 18 / max(1, hypot(end.x - start.x, end.y - start.y)))
        let edge: CGFloat = paws > 0 ? 0.92 - paws * 0.52 : 0.62
        let sockStart = max(fade + 0.01, edge - 0.18)
        let sockEnd = min(1, edge + 0.14)
        let colors = [shoulder.withAlphaComponent(0).cgColor,
                      shoulder.withAlphaComponent(0.35).cgColor, shoulder.cgColor,
                      arm.cgColor, tip.cgColor, tip.cgColor] as CFArray
        if let grad = CGGradient(colorsSpace: CGColorSpaceCreateDeviceRGB(), colors: colors,
                                locations: [0, fade * 0.45, fade, sockStart, sockEnd, 1]) {
            // The animated arm polygon and ellipse can have opposite winding.
            // Clipping their compound path subtracts the overlap, exposing the mouse.
            // Paint each shape with the same gradient instead; their overlap is opaque.
            let pawPath = CGPath(ellipseIn: paw, transform: nil)
            for shape in [path, pawPath] {
                ctx.saveGState(); ctx.addPath(shape); ctx.clip()
                ctx.drawLinearGradient(grad, start: start, end: end,
                                       options: [.drawsBeforeStartLocation, .drawsAfterEndLocation])
                ctx.restoreGState()
            }
        }
    }
}
