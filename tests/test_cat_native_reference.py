"""Optional verification of the preserved Swift reference, never production code."""
import os
import sys
import pytest

pytestmark = pytest.mark.skipif(os.environ.get("PETNEST_TEST_NATIVE_REFERENCE") != "1", reason="optional Swift reference")

@pytest.mark.skipif(sys.platform != "darwin", reason="CoreGraphics bitmap coordinates")
def test_native_limb_sampling_and_paw_overlap(tmp_path):
    """Sample the actual coat; overlapping arm and paw must never make a hole."""
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    harness = tmp_path / "main.swift"
    harness.write_text('''
import AppKit
let ctx = CGContext(data: nil, width: 360, height: 320, bitsPerComponent: 8,
    bytesPerRow: 1440, space: CGColorSpaceCreateDeviceRGB(),
    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
ctx.translateBy(x: 0, y: 320); ctx.scaleBy(x: 1, y: -1)
ctx.translateBy(x: 8, y: 5); ctx.scaleBy(x: 1.1, y: 0.9)
let appearance = PetAppearance()
ctx.setFillColor(NSColor(srgbRed: 0.85, green: 0.65, blue: 0.42, alpha: 1).cgColor)
ctx.fill(CGRect(x: 150, y: 160, width: 30, height: 30))
let sample = appearance.shoulderColor(ctx, at: CGPoint(x: 160, y: 170)).usingColorSpace(.deviceRGB)!
precondition(abs(sample.redComponent - 0.85) < 0.01)
precondition(abs(sample.greenComponent - 0.65) < 0.01)
precondition(abs(sample.blueComponent - 0.42) < 0.01)
// Out-of-bounds or transparent pixels fall back safely to the base coat.
precondition(appearance.shoulderColor(ctx, at: CGPoint(x: -100, y: -100)) == appearance.fur)
let canvas = CGContext(data: nil, width: 100, height: 100, bitsPerComponent: 8,
    bytesPerRow: 400, space: CGColorSpaceCreateDeviceRGB(),
    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
canvas.translateBy(x: 0, y: 100); canvas.scaleBy(x: 1, y: -1)
let corners = [CGPoint(x: 40, y: 10), CGPoint(x: 60, y: 10),
               CGPoint(x: 60, y: 80), CGPoint(x: 40, y: 80)]
// Real animated limbs and ellipses can have opposite winding directions.
for points in [corners, Array(corners.reversed())] {
    canvas.clear(CGRect(x: 0, y: 0, width: 100, height: 100))
    let arm = CGMutablePath(); arm.move(to: points[0])
    for point in points.dropFirst() { arm.addLine(to: point) }
    arm.closeSubpath()
    appearance.limb(canvas, path: arm, paw: CGRect(x: 38, y: 70, width: 24, height: 20),
                    start: CGPoint(x: 50, y: 10), end: CGPoint(x: 50, y: 80))
    let pixels = canvas.data!.assumingMemoryBound(to: UInt8.self)
    for y in 73...85 {
        for x in 46...54 {
            precondition(pixels[y * 400 + x * 4 + 3] == 255, "Hole in overlapping paw")
        }
    }
    precondition(pixels[3] == 0, "Outside silhouette must stay transparent")
    precondition(pixels[11 * 400 + 50 * 4 + 3] < 100, "Keep the soft shoulder blend")
}
''')
    executable = tmp_path / "shoulder-check"
    subprocess.run(["xcrun", "swiftc", "-O", *map(str, sorted((root / "native/kurocat").glob("*.swift"))),
                    str(harness), "-framework", "AppKit", "-framework", "QuartzCore", "-o", str(executable)],
                   check=True, capture_output=True, text=True)
    subprocess.run([str(executable)], check=True, capture_output=True, text=True)
