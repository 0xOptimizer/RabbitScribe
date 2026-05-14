from __future__ import annotations

import json
import logging
from pathlib import Path

import pysrt
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rabbitscribe import paths, settings
from rabbitscribe.models.project import Project
from rabbitscribe.widgets.progress_strip import ProgressStrip
from rabbitscribe.workers.srt_cleaner import CleanupRules, clean


log = logging.getLogger(__name__)


class CleanupPanel(QWidget):
    """Tab 3: SRT cleanup with before/after preview."""

    def __init__(
        self,
        project: Project,
        progress: ProgressStrip,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._progress = progress
        self._loaded_srt_path: Path | None = None
        self._loaded_subs: pysrt.SubRipFile | None = None
        self._syncing_scroll = False

        # Source SRT picker
        self._srt_edit = QLineEdit()
        self._srt_edit.setReadOnly(True)
        open_btn = QPushButton("Open other SRT…")
        open_btn.clicked.connect(self._on_open_srt)
        src_row = QHBoxLayout()
        src_row.addWidget(self._srt_edit, 1)
        src_row.addWidget(open_btn)

        # Rules form
        self._min_dur = QDoubleSpinBox()
        self._min_dur.setRange(0.0, 60.0)
        self._min_dur.setSingleStep(0.5)
        self._min_dur.setValue(2.0)
        self._max_dur = QDoubleSpinBox()
        self._max_dur.setRange(1.0, 60.0)
        self._max_dur.setSingleStep(0.5)
        self._max_dur.setValue(6.0)
        self._max_chars = QSpinBox()
        self._max_chars.setRange(20, 500)
        self._max_chars.setValue(84)
        self._strip_ellipsis = QCheckBox("Strip ellipsis")
        self._strip_ellipsis.setChecked(True)
        self._mark_unclear = QCheckBox("Mark blanks / unclear")
        self._mark_unclear.setChecked(True)
        self._unclear_token = QLineEdit("[onverstaanbaar]")
        self._capitalise = QCheckBox("Capitalise sentence starts")
        self._capitalise.setChecked(True)

        rules_form = QFormLayout()
        rules_form.addRow("Min cue duration (s):", self._min_dur)
        rules_form.addRow("Max cue duration (s):", self._max_dur)
        rules_form.addRow("Max chars per cue:", self._max_chars)
        rules_form.addRow(self._strip_ellipsis)
        rules_form.addRow(self._mark_unclear)
        rules_form.addRow("Unclear token:", self._unclear_token)
        rules_form.addRow(self._capitalise)
        rules_box = QGroupBox("Rules")
        rules_box.setLayout(rules_form)

        # Substitution dictionary
        self._subs_table = QTableWidget(0, 2)
        self._subs_table.setHorizontalHeaderLabels(["Find", "Replace with"])
        self._subs_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        subs_add = QPushButton("Add")
        subs_del = QPushButton("Delete")
        subs_load = QPushButton("Load…")
        subs_save = QPushButton("Save substitutions…")
        subs_add.clicked.connect(self._on_subs_add)
        subs_del.clicked.connect(self._on_subs_delete)
        subs_load.clicked.connect(self._on_subs_load)
        subs_save.clicked.connect(self._on_subs_save)

        subs_btns = QHBoxLayout()
        for b in (subs_add, subs_del, subs_load, subs_save):
            subs_btns.addWidget(b)
        subs_btns.addStretch(1)

        subs_layout = QVBoxLayout()
        subs_layout.addWidget(self._subs_table)
        subs_layout.addLayout(subs_btns)
        subs_box = QGroupBox("Word substitutions")
        subs_box.setLayout(subs_layout)

        rules_column = QVBoxLayout()
        rules_column.addWidget(rules_box)
        rules_column.addWidget(subs_box)
        rules_column.addStretch(1)
        rules_widget = QWidget()
        rules_widget.setLayout(rules_column)

        # Preview panes
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self._before = QPlainTextEdit()
        self._before.setReadOnly(True)
        self._before.setFont(mono)
        self._after = QPlainTextEdit()
        self._after.setReadOnly(True)
        self._after.setFont(mono)

        before_box = QGroupBox("Before (raw)")
        before_layout = QVBoxLayout()
        before_layout.addWidget(self._before)
        before_box.setLayout(before_layout)

        after_box = QGroupBox("After (cleaned)")
        after_layout = QVBoxLayout()
        after_layout.addWidget(self._after)
        after_box.setLayout(after_layout)

        preview_splitter = QSplitter(Qt.Orientation.Horizontal)
        preview_splitter.addWidget(before_box)
        preview_splitter.addWidget(after_box)
        preview_splitter.setSizes([400, 400])

        # Sync scrolling
        self._before.verticalScrollBar().valueChanged.connect(self._on_before_scroll)
        self._after.verticalScrollBar().valueChanged.connect(self._on_after_scroll)

        # Action buttons
        preview_btn = QPushButton("Preview")
        preview_btn.clicked.connect(self._update_preview)
        self._clean_btn = QPushButton("Clean and save")
        self._clean_btn.clicked.connect(self._on_clean)
        action_row = QHBoxLayout()
        action_row.addWidget(preview_btn)
        action_row.addWidget(self._clean_btn)
        action_row.addStretch(1)

        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter.addWidget(rules_widget)
        main_splitter.addWidget(preview_splitter)
        main_splitter.setSizes([280, 820])

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Source SRT:"))
        layout.addLayout(src_row)
        layout.addWidget(main_splitter, 1)
        layout.addLayout(action_row)

        self._restore_rules()
        self._project.raw_srt_changed.connect(self._on_raw_srt_changed)
        if self._project.raw_srt:
            self._load_srt(self._project.raw_srt)

    # ---------- scroll sync ----------

    def _on_before_scroll(self, v: int) -> None:
        if self._syncing_scroll:
            return
        self._syncing_scroll = True
        self._after.verticalScrollBar().setValue(v)
        self._syncing_scroll = False

    def _on_after_scroll(self, v: int) -> None:
        if self._syncing_scroll:
            return
        self._syncing_scroll = True
        self._before.verticalScrollBar().setValue(v)
        self._syncing_scroll = False

    # ---------- file loading ----------

    def _on_raw_srt_changed(self, path: Path | None) -> None:
        if path is not None:
            self._load_srt(path)

    def _on_open_srt(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open SRT", "", "SubRip (*.srt);;All files (*.*)"
        )
        if path:
            self._load_srt(Path(path))

    def _load_srt(self, path: Path) -> None:
        try:
            subs = pysrt.open(str(path), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Load failed", f"{path}\n{exc}")
            return
        self._loaded_srt_path = path
        self._loaded_subs = subs
        self._srt_edit.setText(str(path))
        self._before.setPlainText(self._render(subs))
        self._after.clear()

    @staticmethod
    def _render(subs: pysrt.SubRipFile) -> str:
        lines: list[str] = []
        for item in subs:
            lines.append(f"{item.index}")
            lines.append(f"{item.start} --> {item.end}")
            lines.append(item.text)
            lines.append("")
        return "\n".join(lines)

    # ---------- substitutions table ----------

    def _subs_dict(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for r in range(self._subs_table.rowCount()):
            k_item = self._subs_table.item(r, 0)
            v_item = self._subs_table.item(r, 1)
            if not k_item:
                continue
            k = k_item.text().strip()
            v = v_item.text() if v_item else ""
            if k:
                out[k] = v
        return out

    def _set_subs_dict(self, subs: dict[str, str]) -> None:
        self._subs_table.setRowCount(0)
        for k, v in subs.items():
            self._add_subs_row(k, v)

    def _add_subs_row(self, key: str = "", value: str = "") -> None:
        row = self._subs_table.rowCount()
        self._subs_table.insertRow(row)
        self._subs_table.setItem(row, 0, QTableWidgetItem(key))
        self._subs_table.setItem(row, 1, QTableWidgetItem(value))

    def _on_subs_add(self) -> None:
        self._add_subs_row()

    def _on_subs_delete(self) -> None:
        rows = sorted({i.row() for i in self._subs_table.selectedIndexes()}, reverse=True)
        for r in rows:
            self._subs_table.removeRow(r)

    def _on_subs_load(self) -> None:
        start_dir = str(paths.presets_dir()) if paths.presets_dir().is_dir() else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Load substitutions", start_dir, "JSON (*.json);;All files (*.*)"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, "Load failed", f"{path}\n{exc}")
            return
        subs = data.get("substitutions") if isinstance(data, dict) and "substitutions" in data else data
        if not isinstance(subs, dict):
            QMessageBox.warning(self, "Bad file", "Expected a JSON object of find/replace pairs.")
            return
        self._set_subs_dict({str(k): str(v) for k, v in subs.items()})

    def _on_subs_save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save substitutions", "", "JSON (*.json)"
        )
        if not path:
            return
        data = {"substitutions": self._subs_dict()}
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # ---------- rules persistence ----------

    def _current_rules(self) -> CleanupRules:
        return CleanupRules(
            min_duration_s=self._min_dur.value(),
            max_duration_s=self._max_dur.value(),
            max_chars=self._max_chars.value(),
            strip_ellipsis=self._strip_ellipsis.isChecked(),
            mark_unclear=self._mark_unclear.isChecked(),
            unclear_token=self._unclear_token.text() or "[onverstaanbaar]",
            capitalise_sentences=self._capitalise.isChecked(),
            substitutions=self._subs_dict(),
        )

    def _persist_rules(self) -> None:
        rules = self._current_rules()
        settings.set_json(
            "cleanup/rules",
            {
                "min_duration_s": rules.min_duration_s,
                "max_duration_s": rules.max_duration_s,
                "max_chars": rules.max_chars,
                "strip_ellipsis": rules.strip_ellipsis,
                "mark_unclear": rules.mark_unclear,
                "unclear_token": rules.unclear_token,
                "capitalise_sentences": rules.capitalise_sentences,
                "substitutions": rules.substitutions,
            },
        )

    def _restore_rules(self) -> None:
        data = settings.get_json("cleanup/rules", None)
        if not isinstance(data, dict):
            return
        self._min_dur.setValue(float(data.get("min_duration_s", 2.0)))
        self._max_dur.setValue(float(data.get("max_duration_s", 6.0)))
        self._max_chars.setValue(int(data.get("max_chars", 84)))
        self._strip_ellipsis.setChecked(bool(data.get("strip_ellipsis", True)))
        self._mark_unclear.setChecked(bool(data.get("mark_unclear", True)))
        self._unclear_token.setText(str(data.get("unclear_token", "[onverstaanbaar]")))
        self._capitalise.setChecked(bool(data.get("capitalise_sentences", True)))
        subs = data.get("substitutions", {})
        if isinstance(subs, dict):
            self._set_subs_dict({str(k): str(v) for k, v in subs.items()})

    # ---------- preview + save ----------

    def _update_preview(self) -> None:
        if not self._loaded_subs:
            QMessageBox.information(
                self, "No SRT loaded",
                "Run transcription first, or use 'Open other SRT…'.",
            )
            return
        cleaned = clean(self._loaded_subs, self._current_rules())
        self._after.setPlainText(self._render(cleaned))

    def _on_clean(self) -> None:
        if not self._loaded_subs or not self._loaded_srt_path:
            QMessageBox.information(self, "No SRT loaded", "Load an SRT first.")
            return
        rules = self._current_rules()
        cleaned = clean(self._loaded_subs, rules)
        self._after.setPlainText(self._render(cleaned))

        out_dir = self._project.output_dir or self._loaded_srt_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = self._project.stem() if self._project.mp4 else self._loaded_srt_path.stem.replace(".raw", "")
        output = out_dir / f"{stem}.cleaned.srt"
        cleaned.save(str(output), encoding="utf-8")

        self._project.set_cleaned_srt(output)
        self._persist_rules()
        self._progress.set_status(f"Cleaned SRT saved: {output.name}")
        log.info("Cleaned SRT written: %s", output)
        QMessageBox.information(
            self, "Cleaned",
            f"Saved {len(cleaned)} cues to:\n{output}",
        )
