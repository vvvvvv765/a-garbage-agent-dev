@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist "..\.venv\Scripts\python.exe" (
  set "PY=..\.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

if not exist "%~dp0Session_Storage" mkdir "%~dp0Session_Storage"
start "" http://127.0.0.1:5000
"%PY%" -m MoBo.main web
pause
