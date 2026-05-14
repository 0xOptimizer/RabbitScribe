@echo off
setlocal
cd /d "%~dp0"

REM ---------- Python on PATH ----------
where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: python not found on PATH. Install Python 3.11+ first.
    pause
    exit /b 1
)

REM ---------- Create .venv if missing ----------
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo First-run setup: creating .venv and installing dependencies.
    echo This downloads PySide6 + PyTorch + openai-whisper (~2 GB) and will take several minutes.
    echo.

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
    echo Setup complete.
    echo.
) else (
    REM ---------- venv exists; verify the key modules are actually importable ----------
    .venv\Scripts\python.exe -c "import PySide6, pysrt, whisper, rabbitscribe" >nul 2>nul
    if errorlevel 1 (
        echo.
        echo One or more dependencies are missing or broken. Reinstalling...
        echo.
        .venv\Scripts\python.exe -m pip install -e ".[dev]"
        if errorlevel 1 (
            echo ERROR: dependency reinstall failed
            pause
            exit /b 1
        )
    )
)

REM ---------- ffmpeg warning (non-fatal) ----------
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo.
    echo WARNING: ffmpeg not found on PATH.
    echo The app will launch, but MP3 extraction and chunk splitting will fail.
    echo Install with: winget install Gyan.FFmpeg
    echo.
)

REM ---------- Launch ----------
.venv\Scripts\python.exe -m rabbitscribe
if errorlevel 1 pause

endlocal
