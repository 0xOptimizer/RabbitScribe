from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal


class Project(QObject):
    """Shared mutable state across the four tabs.

    Panels read the current paths via attribute access and react to the
    `*_changed` signals to enable/disable their own controls.
    """

    mp4_changed = Signal(object)
    output_dir_changed = Signal(object)
    mp3_changed = Signal(object)
    raw_srt_changed = Signal(object)
    cleaned_srt_changed = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._mp4: Path | None = None
        self._output_dir: Path | None = None
        self._mp3: Path | None = None
        self._raw_srt: Path | None = None
        self._cleaned_srt: Path | None = None

    @property
    def mp4(self) -> Path | None:
        return self._mp4

    def set_mp4(self, path: Path | None) -> None:
        self._mp4 = path
        self.mp4_changed.emit(path)

    @property
    def output_dir(self) -> Path | None:
        return self._output_dir

    def set_output_dir(self, path: Path | None) -> None:
        self._output_dir = path
        self.output_dir_changed.emit(path)

    @property
    def mp3(self) -> Path | None:
        return self._mp3

    def set_mp3(self, path: Path | None) -> None:
        self._mp3 = path
        self.mp3_changed.emit(path)

    @property
    def raw_srt(self) -> Path | None:
        return self._raw_srt

    def set_raw_srt(self, path: Path | None) -> None:
        self._raw_srt = path
        self.raw_srt_changed.emit(path)

    @property
    def cleaned_srt(self) -> Path | None:
        return self._cleaned_srt

    def set_cleaned_srt(self, path: Path | None) -> None:
        self._cleaned_srt = path
        self.cleaned_srt_changed.emit(path)

    def stem(self) -> str:
        return self._mp4.stem if self._mp4 else "untitled"
