from __future__ import annotations

import logging
import re
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

from rabbitscribe.models.chunks import Chunk, parse_timecode
from rabbitscribe.paths import find_ffmpeg


log = logging.getLogger(__name__)


_SLUG_RE = re.compile(r"[^A-Za-z0-9_]+")


def slugify(label: str) -> str:
    s = _SLUG_RE.sub("_", label).strip("_")
    return s or "chunk"


def chunk_filename(index: int, label: str, total: int) -> str:
    width = max(2, len(str(total)))
    return f"{index:0{width}d}_{slugify(label)}.mp4"


class ChunkSplitter(QObject):
    """Runs ffmpeg in sequence, one stream-copy per chunk."""

    overall_progress = Signal(float)  # 0..1 across all chunks
    chunk_started = Signal(int, str)  # row index (0-based), label
    chunk_finished = Signal(int, str)  # row index, output path
    log = Signal(str)
    finished_all = Signal(list)  # list of output path strings
    error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._chunks: list[Chunk] = []
        self._source: Path | None = None
        self._out_dir: Path | None = None
        self._skip_existing = True
        self._overwrite = False
        self._frame_accurate = False
        self._i = 0
        self._outputs: list[str] = []
        self._cancelled = False

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.state() != QProcess.ProcessState.NotRunning

    def cancel(self) -> None:
        self._cancelled = True
        if self._proc is not None and self._proc.state() != QProcess.ProcessState.NotRunning:
            self._proc.kill()

    def start(
        self,
        source: Path,
        chunks: list[Chunk],
        out_dir: Path,
        *,
        skip_existing: bool = True,
        overwrite: bool = False,
        frame_accurate: bool = False,
    ) -> None:
        if find_ffmpeg() is None:
            self.error.emit("ffmpeg not found on PATH")
            return
        if not source.is_file():
            self.error.emit(f"Source file does not exist: {source}")
            return
        if not chunks:
            self.error.emit("No chunks to split")
            return

        out_dir.mkdir(parents=True, exist_ok=True)
        self._source = source
        self._chunks = list(chunks)
        self._out_dir = out_dir
        self._skip_existing = skip_existing
        self._overwrite = overwrite
        self._frame_accurate = frame_accurate
        self._i = 0
        self._outputs = []
        self._cancelled = False
        self._run_next()

    def _run_next(self) -> None:
        if self._cancelled:
            self.error.emit("Cancelled")
            return
        if self._i >= len(self._chunks):
            self.overall_progress.emit(1.0)
            self.finished_all.emit(self._outputs)
            return

        assert self._source is not None and self._out_dir is not None
        chunk = self._chunks[self._i]
        total = len(self._chunks)
        out_name = chunk_filename(self._i + 1, chunk.label, total)
        out_path = self._out_dir / out_name

        self.chunk_started.emit(self._i, chunk.label)
        self.log.emit(f"[{self._i + 1}/{total}] {chunk.label} -> {out_name}")

        if out_path.exists() and self._skip_existing and not self._overwrite:
            self.log.emit(f"Skipping existing: {out_name}")
            self._outputs.append(str(out_path))
            self._advance()
            return

        ffmpeg = find_ffmpeg()
        assert ffmpeg is not None
        args = self._build_args(self._source, chunk, out_path)

        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._on_output)
        self._proc.finished.connect(self._on_proc_finished)
        self._proc.errorOccurred.connect(self._on_proc_error)
        self._proc.start(str(ffmpeg), args)

    def _build_args(self, source: Path, chunk: Chunk, out_path: Path) -> list[str]:
        if self._frame_accurate:
            args = [
                "-y" if self._overwrite else "-n",
                "-i", str(source),
                "-ss", chunk.start,
                "-to", chunk.end,
                "-c:v", "libx264", "-crf", "18",
                "-c:a", "copy",
                "-avoid_negative_ts", "make_zero",
                "-map", "0",
                str(out_path),
            ]
        else:
            args = [
                "-y" if self._overwrite else "-n",
                "-ss", chunk.start,
                "-to", chunk.end,
                "-i", str(source),
                "-c", "copy",
                "-avoid_negative_ts", "make_zero",
                "-map", "0",
                str(out_path),
            ]
        return args

    def _on_output(self) -> None:
        if self._proc is None:
            return
        raw = bytes(self._proc.readAllStandardOutput().data())
        text = raw.decode("utf-8", errors="replace")
        for line in text.splitlines():
            if line:
                self.log.emit(line)

    def _on_proc_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        if self._cancelled:
            self.error.emit("Cancelled")
            return
        if exit_code != 0:
            chunk = self._chunks[self._i]
            self.error.emit(
                f"ffmpeg exited with code {exit_code} on chunk {self._i + 1} ({chunk.label})"
            )
            return

        assert self._out_dir is not None
        out_name = chunk_filename(self._i + 1, self._chunks[self._i].label, len(self._chunks))
        out_path = self._out_dir / out_name
        if out_path.exists():
            self._outputs.append(str(out_path))
            self.chunk_finished.emit(self._i, str(out_path))
        self._advance()

    def _on_proc_error(self, err: QProcess.ProcessError) -> None:
        if self._cancelled:
            return
        self.error.emit(f"ffmpeg process error: {err.name}")

    def _advance(self) -> None:
        self._i += 1
        self.overall_progress.emit(self._i / len(self._chunks))
        self._run_next()
