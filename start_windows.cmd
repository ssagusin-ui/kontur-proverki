@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_windows.ps1"
set "KONTUR_EXIT=%errorlevel%"
if not "%KONTUR_EXIT%"=="0" pause
exit /b %KONTUR_EXIT%
