#!/usr/bin/env sh
set -eu
if [ ! -x ".venv/bin/python" ]; then
  echo "未找到 .venv，请先创建并安装依赖。" >&2
  exit 1
fi
. .venv/bin/activate
pyinstaller --noconfirm --clean --onedir --windowed --name PetNest --paths src --add-data "pets:pets" --add-data "assets:assets" -m petnest
