from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rabbitscribe import paths
from rabbitscribe.workers.setup_downloader import (
    HUGGINGFACE_MODEL_BASE,
    WHISPER_MODELS,
    FileDownloader,
    ReleaseListFetcher,
    extract_zip,
    flatten_whisper_extract,
)


log = logging.getLogger(__name__)


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def whisper_cpp_dir() -> Path:
    return _project_root() / "tools" / "whisper.cpp"


def models_dir() -> Path:
    return _project_root() / "tools" / "models"


class _DownloadRow(QWidget):
    """Progress bar + status label + cancel button used for both downloads."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._status = QLabel("Idle")
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._cancel = QPushButton("Cancel")
        self._cancel.setEnabled(False)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._status, 1)
        row.addWidget(self._bar)
        row.addWidget(self._cancel)

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def set_progress(self, fraction: float) -> None:
        self._bar.setValue(int(round(max(0.0, min(1.0, fraction)) * 100)))

    def set_busy(self, busy: bool) -> None:
        self._cancel.setEnabled(busy)
        if not busy:
            self._bar.setValue(0)

    def cancel_button(self) -> QPushButton:
        return self._cancel


class SetupDialog(QDialog):
    """One-stop wizard for fetching whisper.cpp + a model into tools/."""

    def __init__(self, parent: QWidget | None = None, *, first_run: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle("RabbitScribe setup")
        self.setMinimumWidth(680)
        self._fetcher: ReleaseListFetcher | None = None
        self._binary_dl: FileDownloader | None = None
        self._model_dl: FileDownloader | None = None
        self._assets: list[dict] = []
        self._zip_target: Path | None = None

        self._dont_ask_again_cb: QCheckBox | None = None

        layout = QVBoxLayout(self)
        if first_run:
            intro = QLabel(
                "Welcome to RabbitScribe.\n\n"
                "To transcribe video, the app needs the whisper.cpp engine and a model file. "
                "You can download both here, or skip this and configure later via File -> Setup wizard. "
                "The Source, Cleanup, and Chunks tabs work without these."
            )
            intro.setWordWrap(True)
            intro.setStyleSheet("padding: 8px; background: #eef4fb; border: 1px solid #c5d6e6;")
            layout.addWidget(intro)
        layout.addWidget(self._build_binary_box())
        layout.addWidget(self._build_model_box())

        bottom = QHBoxLayout()
        if first_run:
            self._dont_ask_again_cb = QCheckBox("Don't show on startup again")
            bottom.addWidget(self._dont_ask_again_cb)
        bottom.addStretch(1)
        close_btn = QPushButton("Close" if not first_run else "Skip for now")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        layout.addLayout(bottom)

        self._refresh_statuses()

    def dont_ask_again(self) -> bool:
        return self._dont_ask_again_cb is not None and self._dont_ask_again_cb.isChecked()

    # ---------- binary section ----------

    def _build_binary_box(self) -> QGroupBox:
        box = QGroupBox("whisper.cpp binary")
        v = QVBoxLayout(box)

        self._binary_status = QLabel("...")
        self._binary_status.setTextFormat(Qt.TextFormat.PlainText)

        self._fetch_btn = QPushButton("Fetch latest release list")
        self._fetch_btn.clicked.connect(self._on_fetch_releases)
        self._variant_combo = QComboBox()
        self._variant_combo.setEnabled(False)
        self._download_binary_btn = QPushButton("Download && install")
        self._download_binary_btn.setEnabled(False)
        self._download_binary_btn.clicked.connect(self._on_download_binary)

        controls = QHBoxLayout()
        controls.addWidget(self._fetch_btn)
        controls.addWidget(self._variant_combo, 1)
        controls.addWidget(self._download_binary_btn)

        self._binary_row = _DownloadRow()

        v.addWidget(self._binary_status)
        v.addLayout(controls)
        v.addWidget(self._binary_row)

        help_label = QLabel(
            "Pick a build that matches your hardware:\n"
            "  - 'bin-x64' alone = CPU (works everywhere)\n"
            "  - 'cublas' = NVIDIA GPU (fastest)\n"
            "  - 'vulkan' = AMD/Intel GPU"
        )
        help_label.setStyleSheet("color: #666;")
        v.addWidget(help_label)
        return box

    def _on_fetch_releases(self) -> None:
        self._fetch_btn.setEnabled(False)
        self._binary_row.set_status("Fetching release list from GitHub...")
        fetcher = ReleaseListFetcher(self)
        fetcher.finished_list.connect(self._on_release_list)
        fetcher.error.connect(self._on_fetch_error)
        fetcher.finished.connect(lambda: self._fetch_btn.setEnabled(True))
        self._fetcher = fetcher
        fetcher.start()

    def _on_release_list(self, assets: list) -> None:
        self._assets = assets
        self._variant_combo.clear()
        for a in assets:
            size_mb = a["size"] / 1024 / 1024 if a["size"] else 0
            label = f"{a['name']}  ({size_mb:.1f} MB)" if size_mb else a["name"]
            self._variant_combo.addItem(label, a)
        self._variant_combo.setEnabled(True)
        self._download_binary_btn.setEnabled(True)
        self._binary_row.set_status(f"Found {len(assets)} variant(s). Pick one and click Download.")

    def _on_fetch_error(self, message: str) -> None:
        self._binary_row.set_status(f"Fetch failed: {message}")
        QMessageBox.warning(self, "Could not fetch release list", message)

    def _on_download_binary(self) -> None:
        idx = self._variant_combo.currentIndex()
        if idx < 0:
            return
        asset = self._variant_combo.itemData(idx)
        url = asset["url"]
        target_dir = whisper_cpp_dir()
        target_dir.mkdir(parents=True, exist_ok=True)
        zip_target = target_dir / asset["name"]
        self._zip_target = zip_target

        dl = FileDownloader(url, zip_target, self)
        dl.progress.connect(self._binary_row.set_progress)
        dl.log.connect(lambda line: log.info("setup: %s", line))
        dl.finished.connect(self._on_binary_zip_done)
        dl.error.connect(self._on_binary_error)
        self._binary_dl = dl

        self._download_binary_btn.setEnabled(False)
        self._binary_row.set_status(f"Downloading {asset['name']}...")
        self._binary_row.set_busy(True)
        self._binary_row.cancel_button().clicked.connect(dl.cancel)
        dl.start()

    def _on_binary_zip_done(self, zip_path_str: str) -> None:
        zip_path = Path(zip_path_str)
        self._binary_row.set_status(f"Extracting {zip_path.name}...")
        try:
            extract_zip(zip_path, whisper_cpp_dir())
            flatten_whisper_extract(whisper_cpp_dir())
            try:
                zip_path.unlink()
            except OSError:
                pass
        except Exception as exc:  # noqa: BLE001
            self._binary_row.set_busy(False)
            self._binary_row.set_status(f"Extract failed: {exc}")
            QMessageBox.warning(self, "Extract failed", str(exc))
            self._download_binary_btn.setEnabled(True)
            return

        self._binary_row.set_busy(False)
        self._download_binary_btn.setEnabled(True)
        self._refresh_statuses()
        QMessageBox.information(
            self, "Installed",
            f"whisper.cpp installed at:\n{whisper_cpp_dir()}",
        )

    def _on_binary_error(self, message: str) -> None:
        self._binary_row.set_busy(False)
        self._binary_row.set_status(f"Download failed: {message}")
        self._download_binary_btn.setEnabled(True)
        if message != "Cancelled":
            QMessageBox.warning(self, "Download failed", message)

    # ---------- model section ----------

    def _build_model_box(self) -> QGroupBox:
        box = QGroupBox("Whisper model")
        v = QVBoxLayout(box)

        self._model_status = QLabel("...")
        self._model_combo = QComboBox()
        for label, filename, size_mb in WHISPER_MODELS:
            self._model_combo.addItem(label, filename)
        self._model_combo.setCurrentIndex(len(WHISPER_MODELS) - 1)  # large-v3
        self._download_model_btn = QPushButton("Download model")
        self._download_model_btn.clicked.connect(self._on_download_model)

        controls = QHBoxLayout()
        controls.addWidget(self._model_combo, 1)
        controls.addWidget(self._download_model_btn)

        self._model_row = _DownloadRow()

        v.addWidget(self._model_status)
        v.addLayout(controls)
        v.addWidget(self._model_row)
        return box

    def _on_download_model(self) -> None:
        idx = self._model_combo.currentIndex()
        if idx < 0:
            return
        filename = self._model_combo.itemData(idx)
        dest = models_dir() / filename
        if dest.exists():
            ret = QMessageBox.question(
                self, "Already present",
                f"{filename} already exists ({dest.stat().st_size / 1024 / 1024:.0f} MB).\n\nRe-download?",
            )
            if ret != QMessageBox.StandardButton.Yes:
                return

        url = f"{HUGGINGFACE_MODEL_BASE}/{filename}"
        dl = FileDownloader(url, dest, self)
        dl.progress.connect(self._model_row.set_progress)
        dl.log.connect(lambda line: log.info("setup: %s", line))
        dl.finished.connect(self._on_model_done)
        dl.error.connect(self._on_model_error)
        self._model_dl = dl

        self._download_model_btn.setEnabled(False)
        self._model_row.set_status(f"Downloading {filename}...")
        self._model_row.set_busy(True)
        self._model_row.cancel_button().clicked.connect(dl.cancel)
        dl.start()

    def _on_model_done(self, path: str) -> None:
        self._model_row.set_busy(False)
        self._download_model_btn.setEnabled(True)
        self._refresh_statuses()
        QMessageBox.information(self, "Done", f"Model saved:\n{path}")

    def _on_model_error(self, message: str) -> None:
        self._model_row.set_busy(False)
        self._download_model_btn.setEnabled(True)
        self._model_row.set_status(f"Download failed: {message}")
        if message != "Cancelled":
            QMessageBox.warning(self, "Download failed", message)

    # ---------- status refresh ----------

    def _refresh_statuses(self) -> None:
        binary = paths.find_whisper_cpp()
        if binary is not None:
            self._binary_status.setText(f"Found: {binary}")
        else:
            self._binary_status.setText("Not found. Fetch the release list and pick a variant.")

        models = paths.list_whisper_models()
        if models:
            names = ", ".join(m.name for m in models)
            self._model_status.setText(f"Found {len(models)} model(s): {names}")
        else:
            self._model_status.setText("No models in tools/models/. Pick one and download.")
