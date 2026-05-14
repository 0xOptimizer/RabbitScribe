"""Transcription workers. Both engines run as QProcess subprocesses so
Cancel actually kills the work (no flag-only cooperative cancel).

whisper.cpp: invokes `main.exe` directly.
openai-whisper: invokes the `whisper` console script that ships with the
package, then renames the output to match the project's stem.
"""

from __future__ import annotations

import logging
import re
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess

from rabbitscribe.paths import find_whisper_cpp
from rabbitscribe.workers._qprocess_worker import QProcessWorker


log = logging.getLogger(__name__)


# Matches both whisper.cpp `[HH:MM:SS.mmm --> HH:MM:SS.mmm]` and
# openai-whisper `[MM:SS.mmm --> MM:SS.mmm]` (verbose output).
_SEGMENT_RE = re.compile(
    r"\[(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)\s*-->\s*(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)\]"
)


def _segment_elapsed_seconds(line: str) -> float | None:
    m = _SEGMENT_RE.search(line)
    if not m:
        return None
    h = int(m.group(4)) if m.group(4) else 0
    mn = int(m.group(5))
    s = float(m.group(6))
    return h * 3600 + mn * 60 + s


class WhisperCppWorker(QProcessWorker):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._total_seconds = 0.0

    def start(
        self,
        audio: Path,
        model: Path,
        language: str,
        output_srt: Path,
        total_duration_s: float,
        binary_override: Path | None = None,
    ) -> None:
        binary = binary_override if binary_override and binary_override.is_file() else find_whisper_cpp()
        if binary is None:
            self.error.emit(
                "whisper.cpp binary not found. Open the Setup wizard or pick one with the Browse button."
            )
            return
        if not audio.is_file():
            self.error.emit(f"Audio file does not exist: {audio}")
            return
        if not model.is_file():
            self.error.emit(f"Model file does not exist: {model}")
            return

        output_srt.parent.mkdir(parents=True, exist_ok=True)
        self._total_seconds = total_duration_s

        # whisper.cpp appends .srt to whatever -of points at
        output_stem = output_srt.with_suffix("")
        args = [
            "-m", str(model),
            "-l", language,
            "-osrt",
            "-f", str(audio),
            "-of", str(output_stem),
        ]
        self._start(str(binary), args, output_path=output_srt)

    def _parse_progress(self, line: str) -> float | None:
        if self._total_seconds <= 0:
            return None
        elapsed = _segment_elapsed_seconds(line)
        if elapsed is None:
            return None
        return elapsed / self._total_seconds


def _find_whisper_cli() -> Path | None:
    """Locate the `whisper` console script installed by openai-whisper."""
    candidates = [
        Path(sys.prefix) / "Scripts" / "whisper.exe",
        Path(sys.prefix) / "Scripts" / "whisper",
        Path(sys.prefix) / "bin" / "whisper",
    ]
    for c in candidates:
        if c.is_file():
            return c
    found = shutil.which("whisper")
    return Path(found) if found else None


class PythonWhisperWorker(QProcessWorker):
    """Subprocess wrapper around openai-whisper's `whisper` CLI.

    Cancel works via QProcess.kill() (unlike the prior QThread version,
    which only flipped a cooperative flag that whisper.transcribe() never
    checked).
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._total_seconds = 0.0
        self._intermediate_srt: Path | None = None
        self._final_srt: Path | None = None

    def start(
        self,
        audio: Path,
        model_name: str,
        language: str,
        output_srt: Path,
        total_duration_s: float,
    ) -> None:
        cli = _find_whisper_cli()
        if cli is None:
            self.error.emit(
                "openai-whisper CLI not found. Install with: pip install openai-whisper"
            )
            return
        if not audio.is_file():
            self.error.emit(f"Audio file does not exist: {audio}")
            return

        output_dir = output_srt.parent
        output_dir.mkdir(parents=True, exist_ok=True)
        self._total_seconds = total_duration_s
        self._final_srt = output_srt
        # The CLI writes <audio_stem>.srt into --output_dir; we rename on success.
        self._intermediate_srt = output_dir / f"{audio.stem}.srt"

        args = [
            "--model", model_name,
            "--output_format", "srt",
            "--output_dir", str(output_dir),
            "--verbose", "True",
            str(audio),
        ]
        if language and language != "auto":
            args = ["--language", language, *args]

        self._start(str(cli), args, output_path=self._intermediate_srt)

    def _parse_progress(self, line: str) -> float | None:
        if self._total_seconds <= 0:
            return None
        elapsed = _segment_elapsed_seconds(line)
        if elapsed is None:
            return None
        return elapsed / self._total_seconds

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        if self._cancelled:
            self._cleanup_partial()
            self.error.emit("Cancelled")
            return
        if (
            exit_code == 0
            and self._intermediate_srt is not None
            and self._intermediate_srt.exists()
            and self._final_srt is not None
        ):
            try:
                if self._intermediate_srt != self._final_srt:
                    if self._final_srt.exists():
                        self._final_srt.unlink()
                    self._intermediate_srt.rename(self._final_srt)
                self.progress.emit(1.0)
                self.finished.emit(str(self._final_srt))
            except OSError as exc:
                self.error.emit(f"Failed to write SRT to {self._final_srt}: {exc}")
            return
        self._cleanup_partial()
        self.error.emit(f"openai-whisper exited with code {exit_code}")

    def _cleanup_partial(self) -> None:
        for p in (self._intermediate_srt, self._final_srt):
            if p and p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass
