#!/usr/bin/env sh
set -eu
if [ ! -x ".venv/bin/python" ]; then
  echo "未找到 .venv，请先创建并安装依赖。" >&2
  exit 1
fi
. .venv/bin/activate
RESOURCE_DATA="--add-data pets/sample_pet:pets/sample_pet --add-data assets/countdown:assets/countdown --add-data assets/cursors:assets/cursors --add-data assets/icons:assets/icons"
if [ -d "effects" ]; then
  RESOURCE_DATA="$RESOURCE_DATA --add-data effects:effects"
fi
pyinstaller --noconfirm --clean --onedir --windowed --name PetNest --paths src $RESOURCE_DATA -m petnest
if [ "${PETNEST_BUILD_GODOT:-1}" != "0" ]; then
  sh clients/godot/build-macos.sh
fi
