from __future__ import annotations

import shutil
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _bundled(*parts: str) -> Path:
    return _project_root().joinpath(*parts)


def find_ffmpeg() -> Path | None:
    candidate = _bundled("tools", "ffmpeg", "bin", "ffmpeg.exe")
    if candidate.is_file():
        return candidate
    found = shutil.which("ffmpeg")
    return Path(found) if found else None


def find_ffprobe() -> Path | None:
    candidate = _bundled("tools", "ffmpeg", "bin", "ffprobe.exe")
    if candidate.is_file():
        return candidate
    found = shutil.which("ffprobe")
    return Path(found) if found else None


def find_whisper_cpp() -> Path | None:
    try:
        from rabbitscribe import settings as _settings
        override = _settings.get("paths/whisper_cpp")
    except Exception:
        override = None
    if override:
        p = Path(str(override))
        if p.is_file():
            return p

    for name in ("main.exe", "whisper.exe", "whisper-cli.exe"):
        candidate = _bundled("tools", "whisper.cpp", name)
        if candidate.is_file():
            return candidate
    for name in ("whisper-cli", "main"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def list_whisper_models() -> list[Path]:
    models_dir = _bundled("tools", "models")
    if not models_dir.is_dir():
        return []
    return sorted(models_dir.glob("ggml-*.bin"))


def default_output_dir(source_mp4: Path) -> Path:
    """Default output: <project_root>/output/<video_stem>/.

    Putting it under the project keeps every run discoverable in one place
    (and lets .gitignore cover them all). Sub-foldering by stem prevents
    chunk-name collisions when processing multiple videos.
    """
    return _project_root() / "output" / source_mp4.stem


def presets_dir() -> Path:
    return _bundled("rabbitscribe", "resources", "presets")
