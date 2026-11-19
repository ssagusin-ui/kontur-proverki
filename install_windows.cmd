@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
)
if errorlevel 1 (
  echo Cannot create Python virtual environment. Ensure Python 3.13 x64 is installed.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo Package installation failed. Check internet and pip logs.
  pause
  exit /b 1
)
echo Installation completed. You can run start_windows.cmd
pause
