from __future__ import annotations

from pathlib import Path

from typing import Callable

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QMainWindow,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rabbitscribe import logging_setup, paths, settings
from rabbitscribe.models.project import Project
from rabbitscribe.widgets.log_view import LogView
from rabbitscribe.widgets.progress_strip import ProgressStrip


class _LazyTab(QWidget):
    """Container that builds its real panel on first show.

    Defers the cost of constructing three of the four panels (and their
    transitive imports) until the user actually clicks into the tab.
    """

    def __init__(
        self,
        factory: Callable[[QWidget], QWidget],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._factory = factory
        self._inner: QWidget | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._layout = layout

    def ensure_built(self) -> QWidget:
        if self._inner is None:
            self._inner = self._factory(self)
            self._layout.addWidget(self._inner)
        return self._inner

    def inner(self) -> QWidget | None:
        return self._inner


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("RabbitScribe")
        self.resize(1100, 720)
        from rabbitscribe.widgets.about_dialog import app_icon
        self.setWindowIcon(app_icon())

        self._project = Project(self)
        self._progress = ProgressStrip(self)

        log_dir = Path.home() / ".rabbitscribe" / "logs"
        bridge = logging_setup.configure(log_dir)
        self._log_view = LogView(self)
        bridge.record_emitted.connect(self._log_view.append_line)

        self._tabs = QTabWidget(self)
        self._tabs.addTab(_LazyTab(self._make_source_panel, self), "Source")
        self._tabs.addTab(_LazyTab(self._make_transcribe_panel, self), "Transcribe")
        self._tabs.addTab(_LazyTab(self._make_cleanup_panel, self), "Cleanup")
        self._tabs.addTab(_LazyTab(self._make_chunks_panel, self), "Chunks")
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self._tabs)
        self._on_tab_changed(0)  # build the initial tab synchronously

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

        QTimer.singleShot(0, self._maybe_first_run_setup)

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        setup_action = QAction("&Setup wizard…", self)
        setup_action.triggered.connect(self.open_setup_dialog)
        file_menu.addAction(setup_action)
        file_menu.addSeparator()
        quit_action = QAction("&Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = self.menuBar().addMenu("&View")
        toggle_log = self._log_dock.toggleViewAction()
        toggle_log.setText("Toggle &Log")
        view_menu.addAction(toggle_log)

        help_menu = self.menuBar().addMenu("&Help")
        about_action = QAction("&About RabbitScribe…", self)
        about_action.triggered.connect(self.open_about_dialog)
        help_menu.addAction(about_action)

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

    def _on_tab_changed(self, index: int) -> None:
        widget = self._tabs.widget(index)
        if isinstance(widget, _LazyTab):
            widget.ensure_built()

    def _make_source_panel(self, parent: QWidget) -> QWidget:
        from rabbitscribe.widgets.source_panel import SourcePanel
        return SourcePanel(self._project, self._progress, parent)

    def _make_transcribe_panel(self, parent: QWidget) -> QWidget:
        from rabbitscribe.widgets.transcribe_panel import TranscribePanel
        return TranscribePanel(self._project, self._progress, parent)

    def _make_cleanup_panel(self, parent: QWidget) -> QWidget:
        from rabbitscribe.widgets.cleanup_panel import CleanupPanel
        return CleanupPanel(self._project, self._progress, parent)

    def _make_chunks_panel(self, parent: QWidget) -> QWidget:
        from rabbitscribe.widgets.chunks_panel import ChunksPanel
        return ChunksPanel(self._project, self._progress, parent)

    def open_setup_dialog(self, *, first_run: bool = False) -> None:
        from rabbitscribe.widgets.setup_dialog import SetupDialog
        dlg = SetupDialog(self, first_run=first_run)
        dlg.exec()
        if first_run and dlg.dont_ask_again():
            settings.set_("setup/skip_first_run", True)

    def open_about_dialog(self) -> None:
        from rabbitscribe.widgets.about_dialog import AboutDialog
        AboutDialog(self).exec()

    def _maybe_first_run_setup(self) -> None:
        if settings.get("setup/skip_first_run"):
            return
        if paths.find_whisper_cpp() is not None and paths.list_whisper_models():
            return
        self.open_setup_dialog(first_run=True)
