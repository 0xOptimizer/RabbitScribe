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
    # Newer whisper.cpp builds renamed `main.exe` to `whisper-cli.exe`;
    # `main.exe` now ships as a deprecation stub that prints a warning
    # and exits 1, so we must prefer `whisper-cli.exe` everywhere.
    try:
        from rabbitscribe import settings as _settings
        override = _settings.get("paths/whisper_cpp")
    except Exception:
        override = None
    if override:
        p = Path(str(override))
        if p.is_file():
            sibling = p.with_name("whisper-cli.exe")
            if p.name.lower() == "main.exe" and sibling.is_file():
                return sibling
            return p

    for name in ("whisper-cli.exe", "whisper.exe", "main.exe"):
        candidate = _bundled("tools", "whisper.cpp", name)
        if candidate.is_file():
            return candidate
    for name in ("whisper-cli", "whisper", "main"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def list_whisper_models() -> list[Path]:
    models_dir = _bundled("tools", "models")
    if not models_dir.is_dir():
        return []
    return sorted(models_dir.glob("ggml-*.bin"))


def list_whisper_binaries() -> list[Path]:
    """Every usable whisper.cpp binary under tools/whisper.cpp/.

    Skips `main.exe` because in recent releases it is a deprecation stub
    that prints a warning and exits with code 1.
    """
    root = _bundled("tools", "whisper.cpp")
    if not root.is_dir():
        return []
    seen: set[Path] = set()
    out: list[Path] = []
    for name in ("whisper-cli.exe", "whisper.exe"):
        for path in sorted(root.rglob(name)):
            if path.is_file() and path not in seen:
                seen.add(path)
                out.append(path)
    return out


def default_output_root() -> Path:
    """Where every video's outputs live: <project_root>/output/."""
    return _project_root() / "output"


def default_output_dir(source_mp4: Path) -> Path:
    """Default output for a specific video: <project_root>/output/<video_stem>/.

    Sub-foldering by stem prevents chunk-name collisions when processing
    multiple videos.
    """
    return default_output_root() / source_mp4.stem


def presets_dir() -> Path:
    return _bundled("rabbitscribe", "resources", "presets")
