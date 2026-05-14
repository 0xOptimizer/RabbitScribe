from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QMainWindow,
    QStatusBar,
    QTabWidget,
    QWidget,
)

from rabbitscribe import logging_setup, settings
from rabbitscribe.models.project import Project
from rabbitscribe.widgets.chunks_panel import ChunksPanel
from rabbitscribe.widgets.cleanup_panel import CleanupPanel
from rabbitscribe.widgets.log_view import LogView
from rabbitscribe.widgets.progress_strip import ProgressStrip
from rabbitscribe.widgets.source_panel import SourcePanel
from rabbitscribe.widgets.transcribe_panel import TranscribePanel


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("RabbitScribe")
        self.resize(1100, 720)

        self._project = Project(self)
        self._progress = ProgressStrip(self)

        log_dir = Path.home() / ".rabbitscribe" / "logs"
        bridge = logging_setup.configure(log_dir)
        self._log_view = LogView(self)
        bridge.record_emitted.connect(self._log_view.append_line)

        self._tabs = QTabWidget(self)
        self._tabs.addTab(SourcePanel(self._project, self._progress, self), "Source")
        self._tabs.addTab(
            TranscribePanel(self._project, self._progress, self), "Transcribe"
        )
        self._tabs.addTab(CleanupPanel(self._project, self._progress, self), "Cleanup")
        self._tabs.addTab(ChunksPanel(self._project, self._progress, self), "Chunks")
        self.setCentralWidget(self._tabs)

        self._log_dock = QDockWidget("Log", self)
        self._log_dock.setObjectName("LogDock")
        self._log_dock.setWidget(self._log_view)
        self._log_dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._log_dock)

        status_bar = QStatusBar(self)
        status_bar.addPermanentWidget(self._progress, 1)
        self.setStatusBar(status_bar)

        self._build_menus()
        self._apply_stylesheet()
        self._restore_geometry()
        self.setAcceptDrops(True)

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = self.menuBar().addMenu("&View")
        toggle_log = self._log_dock.toggleViewAction()
        toggle_log.setText("Toggle &Log")
        view_menu.addAction(toggle_log)

    def _apply_stylesheet(self) -> None:
        qss_path = Path(__file__).resolve().parent / "resources" / "style.qss"
        if qss_path.is_file():
            self.setStyleSheet(qss_path.read_text(encoding="utf-8"))

    def _restore_geometry(self) -> None:
        geom = settings.get("ui/geometry")
        if isinstance(geom, QByteArray) and not geom.isEmpty():
            self.restoreGeometry(geom)
        state = settings.get("ui/window_state")
        if isinstance(state, QByteArray) and not state.isEmpty():
            self.restoreState(state)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        settings.set_("ui/geometry", self.saveGeometry())
        settings.set_("ui/window_state", self.saveState())
        super().closeEvent(event)

    @property
    def project(self) -> Project:
        return self._project

    @property
    def progress(self) -> ProgressStrip:
        return self._progress
