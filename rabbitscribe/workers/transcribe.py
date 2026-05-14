"""Transcription workers: whisper.cpp via QProcess, openai-whisper via QThread.

Both expose the same signals so the panel can swap engines transparently.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QThread, Signal

from rabbitscribe.paths import find_whisper_cpp


log = logging.getLogger(__name__)


_SEGMENT_RE = re.compile(
    r"\[(\d+):(\d+):(\d+(?:\.\d+)?)\s*-->\s*(\d+):(\d+):(\d+(?:\.\d+)?)\]"
)


def _segment_elapsed(line: str) -> float | None:
    m = _SEGMENT_RE.search(line)
    if not m:
        return None
    h, mn, s = int(m.group(4)), int(m.group(5)), float(m.group(6))
    return h * 3600 + mn * 60 + s


class WhisperCppWorker(QObject):
    progress = Signal(float)
    log = Signal(str)
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._output_srt: Path | None = None
        self._total_seconds = 0.0
        self._cancelled = False

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.state() != QProcess.ProcessState.NotRunning

    def cancel(self) -> None:
        self._cancelled = True
        if self._proc is not None and self._proc.state() != QProcess.ProcessState.NotRunning:
            self._proc.kill()

    def start(
        self,
        audio: Path,
        model: Path,
        language: str,
        output_srt: Path,
        total_duration_s: float,
    ) -> None:
        binary = find_whisper_cpp()
        if binary is None:
            self.error.emit(
                "whisper.cpp binary not found. Place main.exe at tools/whisper.cpp/main.exe."
            )
            return
        if not audio.is_file():
            self.error.emit(f"Audio file does not exist: {audio}")
            return
        if not model.is_file():
            self.error.emit(f"Model file does not exist: {model}")
            return

        output_srt.parent.mkdir(parents=True, exist_ok=True)
        output_stem = output_srt.with_suffix("")  # whisper.cpp appends .srt
        self._output_srt = output_srt
        self._total_seconds = total_duration_s
        self._cancelled = False

        args = [
            "-m", str(model),
            "-l", language,
            "-osrt",
            "-f", str(audio),
            "-of", str(output_stem),
        ]
        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._on_output)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(self._on_qprocess_error)
        self._proc.start(str(binary), args)

    def _on_output(self) -> None:
        if self._proc is None:
            return
        raw = bytes(self._proc.readAllStandardOutput().data())
        text = raw.decode("utf-8", errors="replace")
        for line in text.splitlines():
            if not line:
                continue
            self.log.emit(line)
            elapsed = _segment_elapsed(line)
            if elapsed is not None and self._total_seconds > 0:
                self.progress.emit(min(1.0, elapsed / self._total_seconds))

    def _on_finished(self, exit_code: int, _exit_status) -> None:
        if self._cancelled:
            self._cleanup_partial()
            self.error.emit("Cancelled")
            return
        if exit_code == 0 and self._output_srt and self._output_srt.exists():
            self.progress.emit(1.0)
            self.finished.emit(str(self._output_srt))
            return
        self._cleanup_partial()
        self.error.emit(f"whisper.cpp exited with code {exit_code}")

    def _on_qprocess_error(self, err: QProcess.ProcessError) -> None:
        if self._cancelled:
            return
        self.error.emit(f"whisper.cpp process error: {err.name}")

    def _cleanup_partial(self) -> None:
        if self._output_srt and self._output_srt.exists():
            try:
                self._output_srt.unlink()
            except OSError:
                pass


class PythonWhisperWorker(QThread):
    progress = Signal(float)
    log = Signal(str)
    finished = Signal(str)
    error = Signal(str)

    def __init__(
        self,
        audio: Path,
        output_srt: Path,
        language: str,
        model_name: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._audio = audio
        self._output_srt = output_srt
        self._language = language
        self._model_name = model_name
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:  # type: ignore[override]
        try:
            import whisper
        except ImportError as exc:
            self.error.emit(f"openai-whisper not installed: {exc}")
            return

        try:
            self.log.emit(f"Loading model {self._model_name} (CPU/GPU per torch availability)")
            model = whisper.load_model(self._model_name)
            if self._cancelled:
                self.error.emit("Cancelled")
                return
            self.log.emit(f"Transcribing {self._audio.name} ({self._language})")
            result = model.transcribe(
                str(self._audio),
                language=self._language,
                verbose=False,
            )
            if self._cancelled:
                self.error.emit("Cancelled")
                return
            segments = result.get("segments", [])
            self._write_srt(segments)
            self.progress.emit(1.0)
            self.finished.emit(str(self._output_srt))
        except Exception as exc:  # noqa: BLE001
            log.exception("openai-whisper transcription failed")
            self.error.emit(f"openai-whisper failed: {exc}")

    def _write_srt(self, segments) -> None:
        self._output_srt.parent.mkdir(parents=True, exist_ok=True)
        lines: list[str] = []
        for i, seg in enumerate(segments, start=1):
            start = _srt_timestamp(float(seg["start"]))
            end = _srt_timestamp(float(seg["end"]))
            text = str(seg.get("text", "")).strip()
            lines.append(f"{i}")
            lines.append(f"{start} --> {end}")
            lines.append(text)
            lines.append("")
        self._output_srt.write_text("\n".join(lines), encoding="utf-8")


def _srt_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    ms_total = int(round(seconds * 1000))
    h, rem = divmod(ms_total, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
