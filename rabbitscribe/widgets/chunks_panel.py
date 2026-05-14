from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStyledItemDelegate,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from rabbitscribe import paths, settings
from rabbitscribe.models.chunks import Chunk, ChunksTableModel, parse_timecode
from rabbitscribe.models.project import Project
from rabbitscribe.widgets.progress_strip import ProgressStrip
from rabbitscribe.workers import ffprobe
from rabbitscribe.workers.chunk_split import ChunkSplitter, chunk_filename
from rabbitscribe.workers.srt_split import split_srt_by_chunks


log = logging.getLogger(__name__)


class TimecodeDelegate(QStyledItemDelegate):
    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        rx = QRegularExpression(r"^\d{1,3}:[0-5]\d:[0-5]\d$")
        editor.setValidator(QRegularExpressionValidator(rx, editor))
        return editor


class ChunksPanel(QWidget):
    """Tab 4: editable chunks table + ffmpeg stream-copy splitting."""

    def __init__(
        self,
        project: Project,
        progress: ProgressStrip,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._progress = progress
        self._worker: ChunkSplitter | None = None

        self._model = ChunksTableModel(self)
        self._table = QTableView()
        self._table.setModel(self._model)
        self._table.setItemDelegateForColumn(ChunksTableModel.COL_START, TimecodeDelegate(self))
        self._table.setItemDelegateForColumn(ChunksTableModel.COL_END, TimecodeDelegate(self))
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(ChunksTableModel.COL_INDEX, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(ChunksTableModel.COL_LABEL, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(ChunksTableModel.COL_START, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(ChunksTableModel.COL_END, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(ChunksTableModel.COL_DURATION, QHeaderView.ResizeMode.ResizeToContents)

        add_btn = QPushButton("Add row")
        del_btn = QPushButton("Delete row")
        up_btn = QPushButton("Move up")
        down_btn = QPushButton("Move down")
        load_btn = QPushButton("Load preset…")
        save_btn = QPushButton("Save preset…")
        validate_btn = QPushButton("Validate")
        add_btn.clicked.connect(self._on_add)
        del_btn.clicked.connect(self._on_delete)
        up_btn.clicked.connect(lambda: self._on_move(-1))
        down_btn.clicked.connect(lambda: self._on_move(1))
        load_btn.clicked.connect(self._on_load_preset)
        save_btn.clicked.connect(self._on_save_preset)
        validate_btn.clicked.connect(self._on_validate)

        btn_row = QHBoxLayout()
        for b in (add_btn, del_btn, up_btn, down_btn, load_btn, save_btn, validate_btn):
            btn_row.addWidget(b)
        btn_row.addStretch(1)

        self._skip_existing = QCheckBox("Skip existing")
        self._skip_existing.setChecked(True)
        self._overwrite = QCheckBox("Overwrite")
        self._frame_accurate = QCheckBox("Frame-accurate (re-encode, slower, no quality loss claim)")
        self._frame_accurate.setToolTip(
            "Off by default. Stream-copy (-c copy) is lossless but snaps to keyframes. "
            "Frame-accurate re-encodes the video at CRF 18 - quality degrading."
        )

        self._split_srt = QCheckBox("Also split SRT per chunk")
        self._split_srt.setToolTip(
            "After video chunks are written, slice the loaded SRT to match each chunk. "
            "Cues are clamped to the chunk range and re-zeroed to start at 00:00:00."
        )
        self._srt_path_edit = QLineEdit()
        self._srt_path_edit.setReadOnly(True)
        self._srt_path_edit.setPlaceholderText("(no SRT loaded)")
        self._srt_browse = QPushButton("SRT…")
        self._srt_browse.clicked.connect(self._on_pick_srt)

        self._split_btn = QPushButton("Split All")
        self._split_btn.clicked.connect(self._on_split_all)

        opts_row = QHBoxLayout()
        opts_row.addWidget(self._skip_existing)
        opts_row.addWidget(self._overwrite)
        opts_row.addWidget(self._frame_accurate)
        opts_row.addWidget(self._split_srt)
        opts_row.addStretch(1)
        opts_row.addWidget(self._split_btn)

        srt_row = QHBoxLayout()
        srt_row.addWidget(QLabel("SRT to split:"))
        srt_row.addWidget(self._srt_path_edit, 1)
        srt_row.addWidget(self._srt_browse)
        self._srt_picked: Path | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Chunks (timecodes as HH:MM:SS):"))
        layout.addWidget(self._table, 1)
        layout.addLayout(btn_row)
        layout.addLayout(opts_row)
        layout.addLayout(srt_row)

        self._project.mp4_changed.connect(self._on_mp4_changed)
        self._project.cleaned_srt_changed.connect(lambda _p: self._refresh_srt_path())
        self._project.raw_srt_changed.connect(lambda _p: self._refresh_srt_path())
        if self._project.mp4:
            self._on_mp4_changed(self._project.mp4)
        self._refresh_srt_path()

    def _on_mp4_changed(self, mp4: Path | None) -> None:
        if not mp4 or not mp4.is_file():
            self._model.set_max_duration(None)
            return
        try:
            info = ffprobe.probe(mp4)
        except ffprobe.FfprobeError:
            self._model.set_max_duration(None)
            return
        self._model.set_max_duration(int(info.duration_seconds))

    def _on_add(self) -> None:
        self._model.add_chunk()

    def _on_delete(self) -> None:
        rows = sorted({i.row() for i in self._table.selectionModel().selectedIndexes()}, reverse=True)
        for r in rows:
            self._model.remove_chunk(r)

    def _on_move(self, delta: int) -> None:
        rows = sorted({i.row() for i in self._table.selectionModel().selectedIndexes()})
        if not rows:
            return
        new_row = self._model.move_chunk(rows[0], delta)
        self._table.selectRow(new_row)

    def _on_load_preset(self) -> None:
        start_dir = str(paths.presets_dir()) if paths.presets_dir().is_dir() else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Load chunks preset", start_dir, "JSON (*.json);;All files (*.*)"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, "Load failed", f"{path}\n{exc}")
            return
        chunks_data = data.get("chunks") if isinstance(data, dict) else data
        if not isinstance(chunks_data, list):
            QMessageBox.warning(self, "Bad preset", "Expected JSON with a 'chunks' array.")
            return
        chunks = []
        for entry in chunks_data:
            try:
                chunks.append(
                    Chunk(
                        label=str(entry.get("label", "")),
                        start=str(entry.get("start", "00:00:00")),
                        end=str(entry.get("end", "00:00:00")),
                    )
                )
            except (AttributeError, TypeError):
                continue
        self._model.set_chunks(chunks)
        settings.set_("chunks/last_preset", path)
        log.info("Loaded preset %s (%d chunks)", path, len(chunks))

    def _on_save_preset(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save chunks preset", "", "JSON (*.json)"
        )
        if not path:
            return
        chunks = [
            {"label": c.label, "start": c.start, "end": c.end}
            for c in self._model.chunks()
        ]
        data = {"name": Path(path).stem, "chunks": chunks}
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("Saved preset %s (%d chunks)", path, len(chunks))

    def _on_validate(self) -> bool:
        errors = self._model.validate()
        if errors:
            QMessageBox.warning(self, "Validation errors", "\n".join(errors))
            return False
        QMessageBox.information(self, "Validation", "All rows valid.")
        return True

    def _on_split_all(self) -> None:
        source = self._project.mp4
        out_dir_root = self._project.output_dir
        if not source or not out_dir_root:
            QMessageBox.warning(
                self, "Missing source",
                "Pick an MP4 on the Source tab before splitting.",
            )
            return
        errors = self._model.validate()
        if errors:
            QMessageBox.warning(self, "Validation errors", "\n".join(errors))
            return
        if not self._model.chunks():
            QMessageBox.warning(self, "No chunks", "Add at least one chunk row.")
            return

        out_dir = out_dir_root / "chunks"
        worker = ChunkSplitter(self)
        worker.overall_progress.connect(self._progress.set_progress)
        worker.chunk_started.connect(
            lambda row, label: self._progress.set_status(
                f"Splitting [{row + 1}/{len(self._model.chunks())}] {label}"
            )
        )
        worker.log.connect(lambda line: log.info("ffmpeg: %s", line))
        worker.finished_all.connect(self._on_split_finished)
        worker.error.connect(self._on_split_error)
        self._worker = worker

        self._split_btn.setEnabled(False)
        self._progress.set_progress(0.0)
        self._progress.set_busy(True)
        self._progress.cancel_requested.connect(worker.cancel)
        log.info("Splitting %s into %d chunks -> %s", source, len(self._model.chunks()), out_dir)
        worker.start(
            source,
            self._model.chunks(),
            out_dir,
            skip_existing=self._skip_existing.isChecked(),
            overwrite=self._overwrite.isChecked(),
            frame_accurate=self._frame_accurate.isChecked(),
        )

    def _refresh_srt_path(self) -> None:
        if self._srt_picked is not None:
            self._srt_path_edit.setText(str(self._srt_picked))
            return
        candidate = self._project.cleaned_srt or self._project.raw_srt
        self._srt_path_edit.setText(str(candidate) if candidate else "")

    def _on_pick_srt(self) -> None:
        from PySide6.QtWidgets import QFileDialog
        start_dir = ""
        if self._project.output_dir and self._project.output_dir.is_dir():
            start_dir = str(self._project.output_dir)
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick SRT to split", start_dir, "SubRip (*.srt);;All files (*.*)"
        )
        if not path:
            return
        self._srt_picked = Path(path)
        self._refresh_srt_path()
        self._split_srt.setChecked(True)

    def _effective_srt(self) -> Path | None:
        if self._srt_picked is not None and self._srt_picked.is_file():
            return self._srt_picked
        text = self._srt_path_edit.text().strip()
        if text:
            p = Path(text)
            if p.is_file():
                return p
        return None

    def _on_split_finished(self, outputs: list) -> None:
        self._progress.set_status(f"Split complete: {len(outputs)} chunks")
        self._progress.set_busy(False)
        self._split_btn.setEnabled(True)
        log.info("Split complete: %d output files", len(outputs))

        if self._split_srt.isChecked():
            self._run_srt_split()

    def _run_srt_split(self) -> None:
        srt = self._effective_srt()
        if srt is None:
            QMessageBox.information(
                self, "No SRT to split",
                "Tick a cleaned/raw SRT via the SRT picker, or run Cleanup first.",
            )
            return
        if not self._project.output_dir:
            return
        out_dir = self._project.output_dir / "chunks"
        chunks = self._model.chunks()
        actual_starts = self._compute_actual_starts(chunks, out_dir)
        try:
            written = split_srt_by_chunks(
                srt,
                chunks,
                out_dir,
                # SRT split is essentially free; always rewrite so corrected
                # timing replaces any stale per-chunk SRT from a prior run.
                overwrite=True,
                actual_starts=actual_starts,
            )
        except (FileNotFoundError, OSError) as exc:
            QMessageBox.warning(self, "SRT split failed", str(exc))
            log.error("SRT split failed: %s", exc)
            return
        self._progress.set_status(
            f"Wrote {len(written)} per-chunk SRT file(s) alongside the video chunks."
        )
        log.info("SRT split wrote %d files", len(written))

    def _compute_actual_starts(self, chunks: list[Chunk], out_dir: Path) -> list[float]:
        """For each chunk, probe the produced MP4 to find its true start
        time in the source. With stream-copy (`-c copy`), ffmpeg snaps cuts
        backward to the nearest keyframe, so the MP4's duration is usually
        a bit longer than `end - user_start`. The true start in the source
        is `user_end - actual_duration`.

        Falls back to the user-typed start for chunks whose MP4 isn't on
        disk or doesn't probe cleanly.
        """
        total = len(chunks)
        starts: list[float] = []
        for i, chunk in enumerate(chunks, start=1):
            user_start = parse_timecode(chunk.start) or 0
            user_end = parse_timecode(chunk.end) or 0
            chunk_path = out_dir / chunk_filename(i, chunk.label, total)
            if user_end > 0 and chunk_path.is_file():
                try:
                    info = ffprobe.probe(chunk_path)
                    if info.duration_seconds > 0:
                        # actual_start = user_end - actual_duration
                        starts.append(max(0.0, user_end - info.duration_seconds))
                        continue
                except ffprobe.FfprobeError as exc:
                    log.warning("Could not ffprobe %s for SRT alignment: %s", chunk_path, exc)
            starts.append(float(user_start))
        return starts

    def _on_split_error(self, message: str) -> None:
        self._progress.set_status(f"Split failed: {message}")
        self._progress.set_busy(False)
        self._split_btn.setEnabled(True)
        QMessageBox.warning(self, "Split failed", message)
