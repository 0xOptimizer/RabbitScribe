from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QObject, Signal


class QtLogBridge(QObject):
    """A QObject that re-emits log records as a Qt signal.

    Connect to `record_emitted` from any widget (e.g. LogView) that wants
    to mirror file logs into the UI.
    """

    record_emitted = Signal(str)


class _QtBridgeHandler(logging.Handler):
    def __init__(self, bridge: QtLogBridge) -> None:
        super().__init__()
        self._bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            return
        self._bridge.record_emitted.emit(msg)


_bridge: QtLogBridge | None = None


def configure(log_dir: Path) -> QtLogBridge:
    """Idempotent: attach file + Qt handlers to the root logger.

    Returns the singleton QtLogBridge; connect widgets to its
    `record_emitted` signal.
    """
    global _bridge

    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s  %(levelname)-5s  %(name)s  %(message)s")

    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        file_handler = RotatingFileHandler(
            log_dir / "app.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    if _bridge is None:
        _bridge = QtLogBridge()
        qt_handler = _QtBridgeHandler(_bridge)
        qt_handler.setFormatter(fmt)
        root.addHandler(qt_handler)

    return _bridge


def bridge() -> QtLogBridge | None:
    return _bridge
