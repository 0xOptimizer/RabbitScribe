@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo .venv not found. Set it up first:
    echo     python -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -e ".[dev]"
    pause
    exit /b 1
)

.venv\Scripts\python.exe -m rabbitscribe
if errorlevel 1 pause
