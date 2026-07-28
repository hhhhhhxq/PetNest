@echo off
setlocal
if not exist ".venv\Scripts\python.exe" (
  echo 未找到 .venv，请先创建并安装依赖。
  exit /b 1
)
call .venv\Scripts\activate.bat
pyinstaller --noconfirm --clean --onedir --windowed --name PetNest --paths src --add-data "pets;pets" --add-data "assets;assets" -m petnest
