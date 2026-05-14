from __future__ import annotations

import platform
from pathlib import Path

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rabbitscribe import __version__


def icon_path() -> Path:
    return Path(__file__).resolve().parent.parent / "resources" / "icon.svg"


def app_icon() -> QIcon:
    p = icon_path()
    if p.is_file():
        return QIcon(str(p))
    return QIcon()


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About RabbitScribe")
        self.setFixedWidth(440)

        icon_label = QLabel()
        pix = app_icon().pixmap(QSize(96, 96))
        if not pix.isNull():
            icon_label.setPixmap(pix)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)

        text = QLabel()
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setOpenExternalLinks(True)
        text.setWordWrap(True)
        text.setText(
            f"<h2 style='margin:0'>RabbitScribe</h2>"
            f"<p style='color:#666;margin-top:2px'>Version {__version__}</p>"
            f"<p>A PySide6 GUI for the video &rarr; SRT &rarr; chunks pipeline. "
            f"Runs ffmpeg for audio extraction and stream-copy splitting, "
            f"and whisper.cpp (or openai-whisper) for transcription.</p>"
            f"<p style='margin-top:14px'><b>Created by @Optimizer</b></p>"
            f"<p style='color:#666;font-size:11px;margin-top:14px'>"
            f"Python {platform.python_version()} &middot; PySide6 {pyside_version} &middot; "
            f"{platform.system()} {platform.release()}"
            f"</p>"
        )

        top = QHBoxLayout()
        top.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)
        top.addSpacing(16)
        top.addWidget(text, 1)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(bottom)
