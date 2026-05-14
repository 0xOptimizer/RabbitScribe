@echo off
setlocal
cd /d "%~dp0"

REM ---------- Python on PATH ----------
where python >nul 2>nul
if errorlevel 1 goto :no_python

if not exist ".venv\Scripts\python.exe" goto :create_venv
goto :verify_deps

:create_venv
echo.
echo First-run setup: creating .venv and installing dependencies.
echo This downloads PySide6 + PyTorch + openai-whisper (~2 GB) and will take several minutes.
echo.

python -m venv .venv
if errorlevel 1 goto :venv_failed

.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto :pip_upgrade_failed

.venv\Scripts\python.exe -m pip install -e ".[dev]"
if errorlevel 1 goto :install_failed

echo.
echo Setup complete.
echo.
goto :ffmpeg_check

:verify_deps
.venv\Scripts\python.exe -c "import importlib.util,sys; sys.exit(any(importlib.util.find_spec(m) is None for m in ('PySide6','pysrt','whisper','rabbitscribe')))" >nul 2>nul
if errorlevel 1 goto :reinstall
goto :ffmpeg_check

:reinstall
echo.
echo One or more dependencies are missing or broken. Reinstalling...
echo.
.venv\Scripts\python.exe -m pip install -e ".[dev]"
if errorlevel 1 goto :install_failed
goto :ffmpeg_check

:ffmpeg_check
where ffmpeg >nul 2>nul
if errorlevel 1 goto :ffmpeg_warn
goto :launch

:ffmpeg_warn
echo.
echo WARNING: ffmpeg not found on PATH.
echo The app will launch, but MP3 extraction and chunk splitting will fail.
echo Install with: winget install Gyan.FFmpeg
echo.
goto :launch

:launch
.venv\Scripts\python.exe -m rabbitscribe
if errorlevel 1 pause
goto :end

:no_python
echo ERROR: python not found on PATH. Install Python 3.11+ first.
pause
exit /b 1

:venv_failed
echo ERROR: failed to create .venv
pause
exit /b 1

:pip_upgrade_failed
echo ERROR: failed to upgrade pip
pause
exit /b 1

:install_failed
echo ERROR: dependency install failed
pause
exit /b 1

:end
endlocal
