@echo off
setlocal
if not exist ".venv\Scripts\python.exe" (
  echo 未找到 .venv。请先执行：python -m venv .venv
  exit /b 1
)
call .venv\Scripts\activate.bat
set PYTHONPATH=src
python -m petnest
set EXIT_CODE=%ERRORLEVEL%
if not "%EXIT_CODE%"=="0" echo PetNest 已退出，错误码：%EXIT_CODE%
exit /b %EXIT_CODE%
