from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rabbitscribe import paths, settings
from rabbitscribe.models.project import Project
from rabbitscribe.widgets.progress_strip import ProgressStrip
from rabbitscribe.workers import ffprobe
from rabbitscribe.workers.transcribe import PythonWhisperWorker, WhisperCppWorker


log = logging.getLogger(__name__)

ENGINE_WHISPER_CPP = "whisper.cpp"
ENGINE_PYTHON = "openai-whisper"

# Whisper-supported language codes, default Dutch.
LANGUAGES: list[tuple[str, str]] = [
    ("nl", "Dutch"),
    ("en", "English"),
    ("de", "German"),
    ("fr", "French"),
    ("es", "Spanish"),
    ("it", "Italian"),
    ("pt", "Portuguese"),
    ("pl", "Polish"),
    ("ru", "Russian"),
    ("ja", "Japanese"),
    ("zh", "Chinese"),
    ("ko", "Korean"),
    ("ar", "Arabic"),
    ("tr", "Turkish"),
    ("sv", "Swedish"),
    ("da", "Danish"),
    ("no", "Norwegian"),
    ("fi", "Finnish"),
    ("cs", "Czech"),
    ("uk", "Ukrainian"),
    ("hi", "Hindi"),
    ("auto", "Auto-detect"),
]


class TranscribePanel(QWidget):
    """Tab 2: choose engine + language + model + audio, run transcription."""

    def __init__(
        self,
        project: Project,
        progress: ProgressStrip,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._progress = progress
        self._worker: WhisperCppWorker | PythonWhisperWorker | None = None
        self._audio_override: Path | None = None

        self._engine_combo = QComboBox()
        self._engine_combo.addItem("whisper.cpp (recommended)", ENGINE_WHISPER_CPP)
        self._engine_combo.addItem("openai-whisper (Python fallback)", ENGINE_PYTHON)
        self._engine_combo.currentIndexChanged.connect(self._refresh_models)

        self._language_combo = QComboBox()
        for code, label in LANGUAGES:
            self._language_combo.addItem(f"{label} ({code})", code)

        self._model_combo = QComboBox()

        self._audio_edit = QLineEdit()
        self._audio_edit.setReadOnly(True)
        self._audio_override_btn = QPushButton("Override…")
        self._audio_override_btn.clicked.connect(self._on_override_audio)
        audio_row = QHBoxLayout()
        audio_row.addWidget(self._audio_edit, 1)
        audio_row.addWidget(self._audio_override_btn)

        form = QFormLayout()
        form.addRow("Engine:", self._engine_combo)
        form.addRow("Language:", self._language_combo)
        form.addRow("Model:", self._model_combo)
        form.addRow("Audio:", audio_row)

        box = QGroupBox("Transcription")
        box.setLayout(form)

        self._transcribe_btn = QPushButton("Transcribe")
        self._transcribe_btn.clicked.connect(self._on_transcribe)

        layout = QVBoxLayout(self)
        layout.addWidget(box)
        layout.addWidget(self._transcribe_btn, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)

        self._restore_settings()
        self._refresh_models()
        self._project.mp3_changed.connect(self._on_mp3_changed)

        if self._project.mp3:
            self._audio_edit.setText(str(self._project.mp3))

    def _restore_settings(self) -> None:
        last_engine = settings.get("transcribe/engine", ENGINE_WHISPER_CPP)
        idx = self._engine_combo.findData(last_engine)
        if idx >= 0:
            self._engine_combo.setCurrentIndex(idx)

        last_lang = settings.get("transcribe/language", "nl")
        idx = self._language_combo.findData(last_lang)
        if idx >= 0:
            self._language_combo.setCurrentIndex(idx)

    def _refresh_models(self) -> None:
        engine = self._engine_combo.currentData()
        self._model_combo.clear()
        if engine == ENGINE_WHISPER_CPP:
            for model in paths.list_whisper_models():
                self._model_combo.addItem(model.name, str(model))
            if self._model_combo.count() == 0:
                self._model_combo.addItem("(no models in tools/models/)", None)
        else:
            try:
                import whisper

                for name in whisper.available_models():
                    self._model_combo.addItem(name, name)
            except ImportError:
                self._model_combo.addItem("(openai-whisper not installed)", None)

        last_model = settings.get("transcribe/model")
        if last_model:
            idx = self._model_combo.findData(last_model)
            if idx >= 0:
                self._model_combo.setCurrentIndex(idx)

    def _on_mp3_changed(self, mp3: Path | None) -> None:
        if self._audio_override is not None:
            return
        self._audio_edit.setText(str(mp3) if mp3 else "")

    def _on_override_audio(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Pick audio file", "",
            "Audio (*.mp3 *.wav *.m4a *.flac *.ogg);;All files (*.*)",
        )
        if path:
            self._audio_override = Path(path)
            self._audio_edit.setText(path)

    def _audio_path(self) -> Path | None:
        if self._audio_override is not None:
            return self._audio_override
        return self._project.mp3

    def _on_transcribe(self) -> None:
        audio = self._audio_path()
        if not audio or not audio.is_file():
            QMessageBox.warning(
                self, "No audio",
                "Extract MP3 on the Source tab first, or pick an audio file via Override.",
            )
            return

        out_dir = self._project.output_dir or audio.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = self._project.stem() if self._project.mp4 else audio.stem
        output_srt = out_dir / f"{stem}.raw.srt"

        engine = self._engine_combo.currentData()
        language = self._language_combo.currentData()
        model_data = self._model_combo.currentData()
        settings.set_("transcribe/engine", engine)
        settings.set_("transcribe/language", language)
        if model_data:
            settings.set_("transcribe/model", str(model_data))

        if engine == ENGINE_WHISPER_CPP:
            if paths.find_whisper_cpp() is None:
                self._prompt_missing_binary()
                return
            if not model_data:
                QMessageBox.warning(
                    self, "No model",
                    "Place ggml-*.bin in tools/models/. Recommended: ggml-large-v3.bin.",
                )
                return
            self._start_whisper_cpp(audio, Path(model_data), language, output_srt)
        else:
            if not model_data:
                QMessageBox.warning(
                    self, "openai-whisper not installed",
                    "Install with: pip install openai-whisper",
                )
                return
            self._start_python_whisper(audio, str(model_data), language, output_srt)

    def _prompt_missing_binary(self) -> None:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("whisper.cpp binary missing")
        box.setText(
            "Could not find whisper.cpp main.exe.\n\n"
            "Place it at tools/whisper.cpp/main.exe, or pick it manually."
        )
        download_btn = box.addButton("Open releases page", QMessageBox.ButtonRole.ActionRole)
        browse_btn = box.addButton("Browse for main.exe…", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is download_btn:
            QDesktopServices.openUrl(QUrl("https://github.com/ggerganov/whisper.cpp/releases"))
        elif clicked is browse_btn:
            path, _ = QFileDialog.getOpenFileName(
                self, "Locate whisper.cpp main.exe", "",
                "Executables (*.exe);;All files (*.*)",
            )
            if path:
                settings.set_("paths/whisper_cpp", path)
                QMessageBox.information(
                    self, "Saved", f"Saved. Try Transcribe again.\n{path}",
                )

    def _start_whisper_cpp(
        self, audio: Path, model: Path, language: str, output_srt: Path
    ) -> None:
        total = self._audio_duration(audio)
        worker = WhisperCppWorker(self)
        self._wire_worker(worker, output_srt)
        worker.start(audio, model, language, output_srt, total)
        self._worker = worker

    def _start_python_whisper(
        self, audio: Path, model_name: str, language: str, output_srt: Path
    ) -> None:
        total = self._audio_duration(audio)
        worker = PythonWhisperWorker(self)
        self._wire_worker(worker, output_srt)
        worker.start(audio, model_name, language, output_srt, total)
        self._worker = worker

    def _wire_worker(self, worker, output_srt: Path) -> None:
        worker.progress.connect(self._progress.set_progress)
        worker.log.connect(lambda line: log.info("whisper: %s", line))
        worker.finished.connect(self._on_finished)
        worker.error.connect(self._on_error)
        self._transcribe_btn.setEnabled(False)
        self._progress.set_status(f"Transcribing -> {output_srt.name}")
        self._progress.set_progress(0.0)
        self._progress.set_busy(True)
        self._progress.cancel_requested.connect(worker.cancel)

    def _audio_duration(self, audio: Path) -> float:
        try:
            return ffprobe.probe(audio).duration_seconds
        except ffprobe.FfprobeError:
            return 0.0

    def _on_finished(self, output_path: str) -> None:
        self._progress.set_status(f"Transcription ready: {Path(output_path).name}")
        self._progress.set_busy(False)
        self._transcribe_btn.setEnabled(True)
        self._project.set_raw_srt(Path(output_path))
        log.info("Transcription complete: %s", output_path)

    def _on_error(self, message: str) -> None:
        self._progress.set_status(f"Transcription failed: {message}")
        self._progress.set_busy(False)
        self._transcribe_btn.setEnabled(True)
        QMessageBox.warning(self, "Transcription failed", message)
        log.error("Transcription failed: %s", message)
