"""Transcription workers — whisper.cpp and openai-whisper, both backed
by a QProcess subprocess so Cancel is honest. Segments are streamed to
the SRT file as whisper produces them (see srt_stream.SegmentStreamer);
runs can be resumed by passing a start offset.
"""

from __future__ import annotations

import logging
import shutil
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QProcess

from rabbitscribe.paths import find_whisper_cpp
from rabbitscribe.workers._qprocess_worker import QProcessWorker
from rabbitscribe.workers.srt_stream import (
    SegmentStreamer,
    parse_segment_line,
)


log = logging.getLogger(__name__)


class _StreamingWhisperBase(QProcessWorker):
    """Shared logic: maintain a SegmentStreamer, push parsed segments to it,
    compute progress, never delete the partial on cancel/error (so resume
    works next time).
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._total_seconds = 0.0
        self._streamer: SegmentStreamer | None = None

    def _make_streamer(self, output_srt: Path, start_index: int) -> None:
        self._streamer = SegmentStreamer(output_srt, start_index=start_index)
        # Touch so the parent class's success check sees the file even if
        # no segments end up being produced (silent audio, etc).
        try:
            output_srt.parent.mkdir(parents=True, exist_ok=True)
            output_srt.touch(exist_ok=True)
        except OSError as exc:
            log.warning("Could not touch %s: %s", output_srt, exc)

    def _parse_progress(self, line: str) -> float | None:
        parsed = parse_segment_line(line)
        if parsed is None:
            return None
        start, end, text = parsed
        if text and self._streamer is not None:
            self._streamer.add(start, end, text)
        if self._total_seconds <= 0:
            return None
        return end / self._total_seconds

    def _cleanup_partial(self) -> None:
        # Preserve the partial SRT for resume; just close the file handle.
        if self._streamer is not None:
            self._streamer.close()

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        if self._streamer is not None:
            self._streamer.close()
        super()._on_finished(exit_code, exit_status)


class WhisperCppWorker(_StreamingWhisperBase):
    def start(
        self,
        audio: Path,
        model: Path,
        language: str,
        output_srt: Path,
        total_duration_s: float,
        binary_override: Path | None = None,
        start_offset_seconds: float = 0.0,
        start_index: int = 1,
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

        self._total_seconds = total_duration_s
        self._make_streamer(output_srt, start_index=start_index)

        # No -osrt / -of: we write the SRT ourselves from streamed segments.
        args = [
            "-m", str(model),
            "-l", language,
            "-f", str(audio),
        ]
        if start_offset_seconds > 0:
            args.extend(["-ot", str(int(start_offset_seconds * 1000))])
        self._start(str(binary), args, output_path=output_srt)


class PythonWhisperWorker(_StreamingWhisperBase):
    """Wraps the openai-whisper CLI (installed by the `openai-whisper`
    package). The CLI insists on writing some output file; we point it
    at a temp dir and discard everything it writes there — our streamed
    SRT is the source of truth.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tmp_dir: Path | None = None

    def start(
        self,
        audio: Path,
        model_name: str,
        language: str,
        output_srt: Path,
        total_duration_s: float,
        start_offset_seconds: float = 0.0,
        start_index: int = 1,
    ) -> None:
        cli = _find_whisper_cli()
        if cli is None:
            self.error.emit("openai-whisper CLI not found. Install with: pip install openai-whisper")
            return
        if not audio.is_file():
            self.error.emit(f"Audio file does not exist: {audio}")
            return

        self._total_seconds = total_duration_s
        self._make_streamer(output_srt, start_index=start_index)
        self._tmp_dir = Path(tempfile.mkdtemp(prefix="rabbitscribe_whisper_"))

        args = [
            "--model", model_name,
            "--output_format", "txt",  # smallest; discarded after run
            "--output_dir", str(self._tmp_dir),
            "--verbose", "True",
            str(audio),
        ]
        if language and language != "auto":
            args = ["--language", language, *args]
        if start_offset_seconds > 0:
            args.extend(["--clip_timestamps", f"{start_offset_seconds:.3f}"])
        self._start(str(cli), args, output_path=output_srt)

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        if self._tmp_dir and self._tmp_dir.is_dir():
            try:
                shutil.rmtree(self._tmp_dir)
            except OSError:
                pass
            self._tmp_dir = None
        super()._on_finished(exit_code, exit_status)


def _find_whisper_cli() -> Path | None:
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
