@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo First-run setup: creating .venv and installing dependencies.
    echo This downloads PySide6 + PyTorch + openai-whisper (~2 GB) and will take several minutes.
    echo.

    where python >nul 2>nul
    if errorlevel 1 (
        echo ERROR: python not found on PATH. Install Python 3.11+ first.
        pause
        exit /b 1
    )

    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: failed to create .venv
        pause
        exit /b 1
    )

    .venv\Scripts\python.exe -m pip install --upgrade pip
    if errorlevel 1 (
        echo ERROR: failed to upgrade pip
        pause
        exit /b 1
    )

    .venv\Scripts\python.exe -m pip install -e ".[dev]"
    if errorlevel 1 (
        echo ERROR: dependency install failed
        pause
        exit /b 1
    )

    echo.
    echo Setup complete. Launching RabbitScribe...
    echo.
)

.venv\Scripts\python.exe -m rabbitscribe
if errorlevel 1 pause
