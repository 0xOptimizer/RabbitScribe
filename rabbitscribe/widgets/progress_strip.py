from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QWidget,
)


class ProgressStrip(QWidget):
    """Persistent footer: status label + progress bar + Cancel button."""

    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._status = QLabel("Idle")
        self._status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setFixedWidth(220)

        self._cancel = QPushButton("Cancel")
        self._cancel.setEnabled(False)
        self._cancel.clicked.connect(self.cancel_requested)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.addWidget(self._status)
        layout.addWidget(self._bar)
        layout.addWidget(self._cancel)

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def set_progress(self, fraction: float) -> None:
        clamped = max(0.0, min(1.0, fraction))
        self._bar.setValue(int(round(clamped * 100)))

    def set_busy(self, busy: bool) -> None:
        self._cancel.setEnabled(busy)
        if not busy:
            self._bar.setValue(0)
