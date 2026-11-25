#!/bin/sh
# Build a named application for local testing and macOS privacy authorization.
set -eu
PETNEST_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PETNEST_ROOT"
PETNEST_SIGN_IDENTITY=${PETNEST_CODESIGN_IDENTITY:--}
set --
if [ -d "$PETNEST_ROOT/effects" ]; then
  set -- "$@" --add-data "$PETNEST_ROOT/effects:effects"
fi
"$PETNEST_ROOT/.venv/bin/python" -m PyInstaller \
  --noconfirm --clean --onedir --windowed --name PetNest \
  --osx-bundle-identifier com.petnest.app \
  --codesign-identity "$PETNEST_SIGN_IDENTITY" \
  --hidden-import ServiceManagement --hidden-import Quartz --hidden-import CoreFoundation \
  --icon "$PETNEST_ROOT/assets/icons/petnest-app.png" \
  --paths "$PETNEST_ROOT/src" \
  --add-data "$PETNEST_ROOT/assets:assets" \
  --add-data "$PETNEST_ROOT/pets/sample_pet:pets/sample_pet" \
  --add-data "$PETNEST_ROOT/pets/keyboard_cat:pets/keyboard_cat" \
  --distpath "$PETNEST_ROOT/dist/local-macos" \
  --workpath "$PETNEST_ROOT/build/local-macos" \
  --specpath "$PETNEST_ROOT/build/local-macos" \
  "$@" \
  "$PETNEST_ROOT/src/petnest_launcher.py"
PETNEST_VERSION=$(PYTHONPATH=src "$PETNEST_ROOT/.venv/bin/python" -c 'from petnest import __version__; print(__version__)')
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $PETNEST_VERSION" dist/local-macos/PetNest.app/Contents/Info.plist
if ! /usr/libexec/PlistBuddy -c "Set :CFBundleVersion $PETNEST_VERSION" dist/local-macos/PetNest.app/Contents/Info.plist 2>/dev/null; then
  /usr/libexec/PlistBuddy -c "Add :CFBundleVersion string $PETNEST_VERSION" dist/local-macos/PetNest.app/Contents/Info.plist
fi
codesign --force --deep --sign "$PETNEST_SIGN_IDENTITY" dist/local-macos/PetNest.app
codesign --verify --deep --strict dist/local-macos/PetNest.app
if [ "$PETNEST_SIGN_IDENTITY" = "-" ]; then
  echo "注意：本次使用临时签名。替换旧应用后，系统可能仍显示输入监控已开启，但旧授权不匹配新版。"
  echo "此时需在输入监控列表移除旧 PetNest，重新添加 /Applications/PetNest.app 并开启，再重新启动。"
  echo "持续开发请通过 PETNEST_CODESIGN_IDENTITY 指定同一有效签名证书，以保持应用身份。"
fi
