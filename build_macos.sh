#!/usr/bin/env sh
set -eu
if [ ! -x ".venv/bin/python" ]; then
  echo "未找到 .venv，请先创建并安装依赖。" >&2
  exit 1
fi
if [ "$(uname -m)" != "x86_64" ]; then
  echo "当前脚本只发布 macOS x64 包，请在 Intel Mac 构建。" >&2
  exit 1
fi
. .venv/bin/activate
VERSION="$(PYTHONPATH=src python -c 'from petnest import __version__; print(__version__)')"
RESOURCE_DATA="--add-data pets/sample_pet:pets/sample_pet --add-data assets:assets"
if [ -d "effects" ]; then
  RESOURCE_DATA="$RESOURCE_DATA --add-data effects:effects"
fi
if [ -f "google-services.json" ]; then
  RESOURCE_DATA="$RESOURCE_DATA --add-data google-services.json:."
fi
pyinstaller --noconfirm --clean --onefile --console --name PetNestUpdater --paths src src/petnest_updater.py
pyinstaller --noconfirm --clean --onedir --windowed --name PetNest \
  --osx-bundle-identifier com.petnest.app \
  --hidden-import ServiceManagement \
  --icon assets/icons/petnest.png \
  --paths src $RESOURCE_DATA src/petnest_launcher.py
cp dist/PetNestUpdater dist/PetNest.app/Contents/MacOS/PetNestUpdater
chmod +x dist/PetNest.app/Contents/MacOS/PetNestUpdater
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" dist/PetNest.app/Contents/Info.plist
if ! /usr/libexec/PlistBuddy -c "Set :CFBundleVersion $VERSION" dist/PetNest.app/Contents/Info.plist 2>/dev/null; then
  /usr/libexec/PlistBuddy -c "Add :CFBundleVersion string $VERSION" dist/PetNest.app/Contents/Info.plist
fi
codesign --force --deep --sign - dist/PetNest.app
mkdir -p dist/release
ditto -c -k --keepParent --norsrc dist/PetNest.app "dist/release/PetNest-macOS-x64-$VERSION.zip"
echo "macOS 更新包：dist/release/PetNest-macOS-x64-$VERSION.zip"
