@echo off
setlocal
if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. Create it and install requirements-dev.txt first.
  exit /b 1
)
call .venv\Scripts\activate.bat
set "RESOURCE_DATA=--add-data assets\countdown;assets\countdown --add-data assets\cursors;assets\cursors --add-data assets\icons;assets\icons"
if exist "effects" set "RESOURCE_DATA=%RESOURCE_DATA% --add-data effects;effects"
pyinstaller --noconfirm --clean --onedir --windowed --name PetNest --icon assets\icons\petnest-app.ico --paths src %RESOURCE_DATA% src\petnest_launcher.py
if errorlevel 1 exit /b 1
pyinstaller --noconfirm --clean --onefile --windowed --name PetNestUpdater --paths src src\petnest_updater.py
if errorlevel 1 exit /b 1

if /I "%PETNEST_BUILD_GODOT%"=="0" goto skip_godot
powershell -NoProfile -ExecutionPolicy Bypass -File clients\godot\build-windows.ps1 -Optional
if errorlevel 1 exit /b 1
:skip_godot

set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo dist\PetNest was generated, but Inno Setup 6 ISCC.exe was not found.
  echo Install Inno Setup and run this script again: https://jrsoftware.org/isinfo.php
  exit /b 1
)
"%ISCC%" installer\PetNest.iss
