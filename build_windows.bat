@echo off
setlocal
if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. Create it and install requirements-dev.txt first.
  exit /b 1
)
call .venv\Scripts\activate.bat
set "RESOURCE_DATA=--add-data assets;assets"
if exist "effects" set "RESOURCE_DATA=%RESOURCE_DATA% --add-data effects;effects"
if defined PETNEST_FIREBASE_CONFIG if not exist "%PETNEST_FIREBASE_CONFIG%" (
  echo PETNEST_FIREBASE_CONFIG does not point to a readable file.
  exit /b 1
)
if defined PETNEST_FIREBASE_CONFIG set RESOURCE_DATA=%RESOURCE_DATA% --add-data "%PETNEST_FIREBASE_CONFIG%;."
if not defined PETNEST_FIREBASE_CONFIG if exist "google-services.json" set "RESOURCE_DATA=%RESOURCE_DATA% --add-data google-services.json;."
pyinstaller --noconfirm --clean --onedir --windowed --name PetNest --icon assets\icons\petnest-app.ico --paths src %RESOURCE_DATA% src\petnest_launcher.py
if errorlevel 1 exit /b 1
pyinstaller --noconfirm --clean --onefile --windowed --name PetNestUpdateHost --paths src src\petnest_updater.py
if errorlevel 1 exit /b 1

set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
  echo dist\PetNest was generated, but Inno Setup 6 ISCC.exe was not found.
  echo Install Inno Setup and run this script again: https://jrsoftware.org/isinfo.php
  exit /b 1
)
"%ISCC%" installer\PetNest.iss
