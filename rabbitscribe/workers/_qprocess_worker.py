"""Shared `QProcess` wrapper used by ffmpeg / whisper.cpp workers.

Subclasses override `_parse_progress(line)` to return a fraction in 0..1
(or None to leave progress unchanged) and provide a `description` for
status messages.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal


class QProcessWorker(QObject):
    progress = Signal(float)
    log = Signal(str)
    finished = Signal(str)  # output path string (workers that have one)
    error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._output_path: Path | None = None
        self._cancelled = False

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.state() != QProcess.ProcessState.NotRunning

    def cancel(self) -> None:
        self._cancelled = True
        if self._proc is not None and self._proc.state() != QProcess.ProcessState.NotRunning:
            self._proc.kill()

    def _start(self, program: str, args: list[str], *, output_path: Path | None) -> None:
        self._output_path = output_path
        self._cancelled = False
        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._on_output)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(self._on_qprocess_error)
        self._proc.start(program, args)

    def _on_output(self) -> None:
        assert self._proc is not None
        raw = bytes(self._proc.readAllStandardOutput().data())
        text = raw.decode("utf-8", errors="replace")
        for line in text.splitlines():
            if not line:
                continue
            self.log.emit(line)
            fraction = self._parse_progress(line)
            if fraction is not None:
                self.progress.emit(max(0.0, min(1.0, fraction)))

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        if self._cancelled:
            self._cleanup_partial()
            self.error.emit("Cancelled")
            return
        if exit_code == 0 and (self._output_path is None or self._output_path.exists()):
            self.progress.emit(1.0)
            self.finished.emit(str(self._output_path) if self._output_path else "")
            return
        self._cleanup_partial()
        self.error.emit(f"Process exited with code {exit_code}")

    def _on_qprocess_error(self, err: QProcess.ProcessError) -> None:
        if self._cancelled:
            return
        self.error.emit(f"Process error: {err.name}")

    def _cleanup_partial(self) -> None:
        if self._output_path and self._output_path.exists():
            try:
                self._output_path.unlink()
            except OSError:
                pass

    def _parse_progress(self, line: str) -> float | None:  # pragma: no cover
        return None
