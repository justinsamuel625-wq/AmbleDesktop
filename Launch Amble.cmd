@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
  echo Amble's Python environment was not found.
  echo Expected: %~dp0.venv\Scripts\pythonw.exe
  echo.
  echo Please keep this launcher inside the Amble Desktop Platform folder.
  pause
  exit /b 1
)

start "Amble Research" ".venv\Scripts\pythonw.exe" -m amble
endlocal
