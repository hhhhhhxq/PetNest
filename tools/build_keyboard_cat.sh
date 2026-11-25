#!/bin/sh
set -eu
PETNEST_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mkdir -p "$PETNEST_ROOT/build/native"
xcrun swiftc -O -emit-library -module-name PetNestCat \
  -target "$(uname -m)-apple-macosx12.0" \
  "$PETNEST_ROOT"/native/kurocat/*.swift \
  -framework AppKit -framework QuartzCore \
  -o "$PETNEST_ROOT/build/native/libpetnest_cat.dylib"
