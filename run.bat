@echo off
setlocal
set "PETNEST_ROOT=%~dp0"
if not exist "%PETNEST_ROOT%.venv\Scripts\pythonw.exe" (
  echo PetNest virtual environment not found.
  exit /b 1
)
set "PYTHONPATH=%PETNEST_ROOT%src"
rem Start pythonw without attaching the GUI process to this CMD session.
start "" /b "%PETNEST_ROOT%.venv\Scripts\pythonw.exe" -m petnest
set "EXIT_CODE=%ERRORLEVEL%"
exit /b %EXIT_CODE%
