from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from rabbitscribe.paths import find_ffprobe


class FfprobeError(RuntimeError):
    pass


@dataclass(frozen=True)
class MediaInfo:
    duration_seconds: float
    video_codec: str | None
    width: int | None
    height: int | None
    audio_codec: str | None
    audio_bitrate_bps: int | None

    @property
    def resolution(self) -> str | None:
        if self.width is None or self.height is None:
            return None
        return f"{self.width}x{self.height}"


def probe(media_path: Path) -> MediaInfo:
    ffprobe = find_ffprobe()
    if ffprobe is None:
        raise FfprobeError(
            "ffprobe not found on PATH or in tools/ffmpeg/bin/. Install with `winget install Gyan.FFmpeg`."
        )
    if not media_path.is_file():
        raise FfprobeError(f"File does not exist: {media_path}")

    cmd = [
        str(ffprobe),
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(media_path),
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.CalledProcessError as exc:
        raise FfprobeError(f"ffprobe failed: {exc.stderr.strip() or exc}") from exc

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise FfprobeError(f"ffprobe returned unparseable JSON: {exc}") from exc

    return _parse(data)


def _parse(data: dict) -> MediaInfo:
    fmt = data.get("format") or {}
    streams = data.get("streams") or []

    try:
        duration = float(fmt.get("duration", 0.0))
    except (TypeError, ValueError):
        duration = 0.0

    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    video_codec = video.get("codec_name") if video else None
    width = video.get("width") if video else None
    height = video.get("height") if video else None

    audio_codec = audio.get("codec_name") if audio else None
    audio_bitrate: int | None = None
    if audio:
        bit_rate = audio.get("bit_rate")
        if bit_rate:
            try:
                audio_bitrate = int(bit_rate)
            except (TypeError, ValueError):
                audio_bitrate = None

    return MediaInfo(
        duration_seconds=duration,
        video_codec=video_codec,
        width=width,
        height=height,
        audio_codec=audio_codec,
        audio_bitrate_bps=audio_bitrate,
    )


def format_duration(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
