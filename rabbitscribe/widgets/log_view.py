from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QPlainTextEdit, QWidget


class LogView(QPlainTextEdit):
    """Read-only log pane. Connect `append_line` to a QtLogBridge signal
    or to any worker's `log` signal.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(5000)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(mono)

    def append_line(self, line: str) -> None:
        self.appendPlainText(line.rstrip("\n"))
