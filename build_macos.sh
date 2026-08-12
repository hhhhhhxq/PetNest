#!/usr/bin/env sh
set -eu
if [ ! -x ".venv/bin/python" ]; then
  echo "未找到 .venv，请先创建并安装依赖。" >&2
  exit 1
fi
. .venv/bin/activate
RESOURCE_DATA="--add-data pets:pets --add-data assets:assets"
if [ -d "effects" ]; then
  RESOURCE_DATA="$RESOURCE_DATA --add-data effects:effects"
fi
if [ -f "google-services.json" ]; then
  RESOURCE_DATA="$RESOURCE_DATA --add-data google-services.json:."
fi
pyinstaller --noconfirm --clean --onedir --windowed --name PetNest --paths src $RESOURCE_DATA -m petnest
