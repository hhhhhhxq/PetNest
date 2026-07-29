@echo off
setlocal
if not exist ".venv\Scripts\python.exe" (
  echo Missing .venv. Create it and install requirements-dev.txt first.
  exit /b 1
)
call .venv\Scripts\activate.bat
pyinstaller --noconfirm --clean --onedir --windowed --name PetNest --paths src --add-data "pets\sample_pet;pets\sample_pet" --add-data "assets;assets" src\petnest_launcher.py
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
