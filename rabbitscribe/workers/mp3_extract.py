from __future__ import annotations

import re
from pathlib import Path

from rabbitscribe.paths import find_ffmpeg
from rabbitscribe.workers._qprocess_worker import QProcessWorker


_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")


class Mp3Extractor(QProcessWorker):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._total_seconds = 0.0

    def start(self, input_mp4: Path, output_mp3: Path, total_duration_s: float) -> None:
        ffmpeg = find_ffmpeg()
        if ffmpeg is None:
            self.error.emit("ffmpeg not found on PATH. Install: winget install Gyan.FFmpeg")
            return
        if not input_mp4.is_file():
            self.error.emit(f"Input file does not exist: {input_mp4}")
            return
        output_mp3.parent.mkdir(parents=True, exist_ok=True)
        self._total_seconds = total_duration_s

        args = [
            "-y",
            "-i", str(input_mp4),
            "-vn",
            "-acodec", "libmp3lame",
            "-q:a", "2",
            str(output_mp3),
        ]
        self._start(str(ffmpeg), args, output_path=output_mp3)

    def _parse_progress(self, line: str) -> float | None:
        if self._total_seconds <= 0:
            return None
        m = _TIME_RE.search(line)
        if not m:
            return None
        h, mn, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        elapsed = h * 3600 + mn * 60 + s
        return elapsed / self._total_seconds
