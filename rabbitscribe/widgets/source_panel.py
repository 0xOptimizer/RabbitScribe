from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
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
from rabbitscribe.workers.mp3_extract import Mp3Extractor
from rabbitscribe.workers.setup_downloader import FileDownloader
from rabbitscribe.workers.url_downloader import (
    GoogleDriveDownloader,
    default_download_dir,
    filename_from_url,
    is_google_drive_url,
    is_http_url,
)


log = logging.getLogger(__name__)


class SourcePanel(QWidget):
    """Tab 1: pick MP4, show metadata, extract MP3."""

    def __init__(
        self,
        project: Project,
        progress: ProgressStrip,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._progress = progress
        self._media_info: ffprobe.MediaInfo | None = None
        self._worker: Mp3Extractor | None = None

        self._mp4_edit = QLineEdit()
        self._mp4_edit.setReadOnly(True)
        self._mp4_browse = QPushButton("Browse…")
        self._mp4_browse.clicked.connect(self._on_browse_mp4)
        self._mp4_url = QPushButton("Download from URL…")
        self._mp4_url.setToolTip("Google Drive share link or direct .mp4 URL")
        self._mp4_url.clicked.connect(self._on_download_url)

        mp4_row = QHBoxLayout()
        mp4_row.addWidget(self._mp4_edit, 1)
        mp4_row.addWidget(self._mp4_browse)
        mp4_row.addWidget(self._mp4_url)

        self._duration_label = QLabel("-")
        self._video_codec_label = QLabel("-")
        self._resolution_label = QLabel("-")
        self._audio_codec_label = QLabel("-")
        self._audio_bitrate_label = QLabel("-")

        info_form = QFormLayout()
        info_form.addRow("Duration:", self._duration_label)
        info_form.addRow("Video codec:", self._video_codec_label)
        info_form.addRow("Resolution:", self._resolution_label)
        info_form.addRow("Audio codec:", self._audio_codec_label)
        info_form.addRow("Audio bitrate:", self._audio_bitrate_label)
        info_box = QGroupBox("Media metadata")
        info_box.setLayout(info_form)

        self._out_edit = QLineEdit()
        self._out_browse = QPushButton("Browse…")
        self._out_browse.clicked.connect(self._on_browse_out)
        out_row = QHBoxLayout()
        out_row.addWidget(self._out_edit, 1)
        out_row.addWidget(self._out_browse)

        self._extract_button = QPushButton("Extract MP3")
        self._extract_button.setEnabled(False)
        self._extract_button.clicked.connect(self._on_extract)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Source MP4:"))
        layout.addLayout(mp4_row)
        layout.addWidget(info_box)
        layout.addWidget(QLabel("Output directory:"))
        layout.addLayout(out_row)
        layout.addWidget(self._extract_button)
        layout.addStretch(1)

        self.setAcceptDrops(True)

        last_mp4 = settings.get("source/last_mp4")
        if last_mp4 and Path(str(last_mp4)).is_file():
            QTimer.singleShot(0, lambda: self._load_mp4(Path(str(last_mp4))))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith((".mp4", ".mkv", ".mov", ".webm")):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # type: ignore[override]
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local.lower().endswith((".mp4", ".mkv", ".mov", ".webm")):
                self._load_mp4(Path(local))
                event.acceptProposedAction()
                return
        event.ignore()

    def _on_download_url(self) -> None:
        last_url = settings.get("source/last_url", "")
        url, ok = QInputDialog.getText(
            self,
            "Download video from URL",
            "Paste a Google Drive share link or a direct .mp4 URL:",
            QLineEdit.EchoMode.Normal,
            str(last_url) if last_url else "",
        )
        url = url.strip()
        if not ok or not url:
            return
        if not is_http_url(url):
            QMessageBox.warning(self, "Bad URL", "Expected an http(s) URL.")
            return
        settings.set_("source/last_url", url)

        dest_dir = default_download_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)

        if is_google_drive_url(url):
            dest = dest_dir / filename_from_url(url, fallback_stem="drive_video")
            worker = GoogleDriveDownloader(self)
        else:
            dest = dest_dir / filename_from_url(url, fallback_stem="video")
            worker = FileDownloader(url, dest, self)

        worker.progress.connect(self._progress.set_progress)
        worker.log.connect(lambda line: log.info("download: %s", line))
        worker.finished.connect(self._on_download_finished)
        worker.error.connect(self._on_download_error)
        self._url_worker = worker

        self._mp4_url.setEnabled(False)
        self._mp4_browse.setEnabled(False)
        self._progress.set_status(f"Downloading {dest.name}…")
        self._progress.set_progress(0.0)
        self._progress.set_busy(True)
        self._progress.cancel_requested.connect(worker.cancel)
        log.info("Starting URL download: %s -> %s", url, dest)

        if isinstance(worker, GoogleDriveDownloader):
            worker.start(url, dest)
        else:
            worker.start()

    def _on_download_finished(self, path: str) -> None:
        self._progress.set_busy(False)
        self._mp4_url.setEnabled(True)
        self._mp4_browse.setEnabled(True)
        downloaded = Path(path)
        if not downloaded.is_file():
            for candidate in default_download_dir().iterdir():
                if candidate.is_file() and candidate.stat().st_size > 0:
                    downloaded = candidate
                    break
        if not downloaded.is_file():
            QMessageBox.warning(self, "Download finished but file missing", path)
            return
        self._progress.set_status(f"Downloaded: {downloaded.name}")
        self._load_mp4(downloaded)
        log.info("URL download complete: %s", downloaded)

    def _on_download_error(self, message: str) -> None:
        self._progress.set_busy(False)
        self._mp4_url.setEnabled(True)
        self._mp4_browse.setEnabled(True)
        self._progress.set_status(f"Download failed: {message}")
        if message != "Cancelled":
            QMessageBox.warning(self, "Download failed", message)
        log.error("URL download failed: %s", message)

    def _on_browse_mp4(self) -> None:
        last = settings.get("source/last_mp4")
        start_dir = str(Path(str(last)).parent) if last else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Select source video",
            start_dir,
            "Video (*.mp4 *.mkv *.mov *.webm);;All files (*.*)",
        )
        if path:
            self._load_mp4(Path(path))

    def _on_browse_out(self) -> None:
        start_dir = self._out_edit.text() or ""
        path = QFileDialog.getExistingDirectory(self, "Select output directory", start_dir)
        if path:
            self._out_edit.setText(path)
            self._project.set_output_dir(Path(path))

    def _load_mp4(self, mp4: Path) -> None:
        self._mp4_edit.setText(str(mp4))
        try:
            info = ffprobe.probe(mp4)
        except ffprobe.FfprobeError as exc:
            QMessageBox.warning(self, "ffprobe failed", str(exc))
            return

        self._media_info = info
        self._duration_label.setText(ffprobe.format_duration(info.duration_seconds))
        self._video_codec_label.setText(info.video_codec or "-")
        self._resolution_label.setText(info.resolution or "-")
        self._audio_codec_label.setText(info.audio_codec or "-")
        self._audio_bitrate_label.setText(
            f"{info.audio_bitrate_bps // 1000} kbps" if info.audio_bitrate_bps else "-"
        )

        out_dir = paths.default_output_dir(mp4)
        self._out_edit.setText(str(out_dir))

        self._project.set_mp4(mp4)
        self._project.set_output_dir(out_dir)
        settings.set_("source/last_mp4", str(mp4))

        self._extract_button.setEnabled(True)

    def _on_extract(self) -> None:
        mp4 = self._project.mp4
        out_dir_text = self._out_edit.text().strip()
        if not mp4 or not out_dir_text:
            return
        if paths.find_ffmpeg() is None:
            QMessageBox.warning(
                self,
                "ffmpeg not found",
                "ffmpeg is not on PATH. Install with: winget install Gyan.FFmpeg",
            )
            return
        out_dir = Path(out_dir_text)
        out_dir.mkdir(parents=True, exist_ok=True)
        output_mp3 = out_dir / f"{mp4.stem}.mp3"

        worker = Mp3Extractor(self)
        worker.progress.connect(self._progress.set_progress)
        worker.log.connect(lambda line: log.info("ffmpeg: %s", line))
        worker.finished.connect(self._on_finished)
        worker.error.connect(self._on_error)
        self._worker = worker

        self._extract_button.setEnabled(False)
        self._progress.set_status(f"Extracting MP3 from {mp4.name}")
        self._progress.set_progress(0.0)
        self._progress.set_busy(True)
        self._progress.cancel_requested.connect(worker.cancel)
        log.info("Starting MP3 extraction: %s -> %s", mp4, output_mp3)
        duration = self._media_info.duration_seconds if self._media_info else 0.0
        worker.start(mp4, output_mp3, duration)

    def _on_finished(self, output_path: str) -> None:
        self._progress.set_status(f"MP3 ready: {Path(output_path).name}")
        self._progress.set_busy(False)
        self._extract_button.setEnabled(True)
        self._project.set_mp3(Path(output_path))
        log.info("MP3 extraction complete: %s", output_path)

    def _on_error(self, message: str) -> None:
        self._progress.set_status(f"MP3 extraction failed: {message}")
        self._progress.set_busy(False)
        self._extract_button.setEnabled(True)
        QMessageBox.warning(self, "MP3 extraction failed", message)
        log.error("MP3 extraction failed: %s", message)
