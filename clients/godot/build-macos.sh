#!/usr/bin/env sh
set -eu

PROJECT_DIRECTORY=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPOSITORY_ROOT=$(CDPATH= cd -- "$PROJECT_DIRECTORY/../.." && pwd)
APPLICATION="$REPOSITORY_ROOT/dist/PetNest Advanced.app"
ARCHIVE="$REPOSITORY_ROOT/dist/PetNest-Advanced-macOS.zip"

find_godot() {
  if [ -n "${PETNEST_GODOT_EXE:-}" ] && [ -x "$PETNEST_GODOT_EXE" ]; then
    printf '%s\n' "$PETNEST_GODOT_EXE"
    return 0
  fi
  for command_name in godot4 godot; do
    if command -v "$command_name" >/dev/null 2>&1; then
      command -v "$command_name"
      return 0
    fi
  done
  if [ -x "/Applications/Godot.app/Contents/MacOS/Godot" ]; then
    printf '%s\n' "/Applications/Godot.app/Contents/MacOS/Godot"
    return 0
  fi
  return 1
}

if [ "$(uname -s)" != "Darwin" ]; then
  echo "PetNest Advanced .app must be assembled on macOS." >&2
  exit 1
fi

GODOT=$(find_godot) || {
  echo "Godot 4.7 was not found. Set PETNEST_GODOT_EXE to the Godot executable." >&2
  exit 1
}

if [ "${PETNEST_SKIP_GODOT_TESTS:-0}" != "1" ]; then
  "$GODOT" --headless --path "$PROJECT_DIRECTORY" --script res://tests/smoke_test.gd
fi
"$GODOT" --headless --path "$PROJECT_DIRECTORY" --editor --quit

mkdir -p "$REPOSITORY_ROOT/dist"
if [ -d "$APPLICATION" ]; then
  rm -rf "$APPLICATION"
fi
"$GODOT" --headless --path "$PROJECT_DIRECTORY" --export-release macOS "$APPLICATION"

CONTENTS="$APPLICATION/Contents"
RESOURCES="$CONTENTS/Resources"
HELPERS="$CONTENTS/Helpers"
mkdir -p "$RESOURCES/pets" "$RESOURCES/effects" "$RESOURCES/cursors" "$HELPERS"
cp -R "$REPOSITORY_ROOT/pets/sample_pet" "$RESOURCES/pets/sample_pet"
if [ -d "$REPOSITORY_ROOT/effects" ]; then
  cp -R "$REPOSITORY_ROOT/effects/." "$RESOURCES/effects/"
fi
if [ -d "$REPOSITORY_ROOT/assets/cursors" ]; then
  cp -R "$REPOSITORY_ROOT/assets/cursors/." "$RESOURCES/cursors/"
fi

xcrun --sdk macosx clang -O2 -arch x86_64 -arch arm64 \
  -framework CoreFoundation -framework IOKit \
  "$PROJECT_DIRECTORY/macos-idle-bridge.c" \
  -o "$HELPERS/macos-idle-bridge"
chmod 755 "$HELPERS/macos-idle-bridge"

if [ "${PETNEST_SKIP_CODESIGN:-0}" != "1" ]; then
  CODESIGN_IDENTITY=${PETNEST_CODESIGN_IDENTITY:--}
  if [ "$CODESIGN_IDENTITY" = "-" ]; then
    codesign --force --deep --sign - "$APPLICATION"
  else
    codesign --force --deep --options runtime --timestamp --sign "$CODESIGN_IDENTITY" "$APPLICATION"
  fi
fi

if [ -f "$ARCHIVE" ]; then
  rm -f "$ARCHIVE"
fi
ditto -c -k --sequesterRsrc --keepParent "$APPLICATION" "$ARCHIVE"
echo "PetNest Advanced exported to $APPLICATION"
echo "Distribution archive: $ARCHIVE"
