from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt


_TIMECODE_RE = re.compile(r"^(\d{1,3}):([0-5]\d):([0-5]\d)$")


@dataclass
class Chunk:
    label: str = ""
    start: str = "00:00:00"
    end: str = "00:00:00"


def parse_timecode(tc: str) -> int | None:
    """Return total seconds for `HH:MM:SS`, or None if malformed."""
    m = _TIMECODE_RE.match(tc.strip())
    if not m:
        return None
    h, mn, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return h * 3600 + mn * 60 + s


def format_seconds(total: int) -> str:
    h, rem = divmod(max(0, total), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class ChunksTableModel(QAbstractTableModel):
    HEADERS = ("#", "Label", "Start", "End", "Duration")
    COL_INDEX, COL_LABEL, COL_START, COL_END, COL_DURATION = range(5)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._chunks: list[Chunk] = []
        self._max_duration_seconds: int | None = None

    def set_max_duration(self, seconds: int | None) -> None:
        self._max_duration_seconds = seconds

    def chunks(self) -> list[Chunk]:
        return list(self._chunks)

    def set_chunks(self, chunks: list[Chunk]) -> None:
        self.beginResetModel()
        self._chunks = [Chunk(c.label, c.start, c.end) for c in chunks]
        self.endResetModel()

    def add_chunk(self, chunk: Chunk | None = None) -> None:
        row = len(self._chunks)
        self.beginInsertRows(QModelIndex(), row, row)
        self._chunks.append(chunk or Chunk(label=f"Chunk {row + 1}"))
        self.endInsertRows()

    def remove_chunk(self, row: int) -> None:
        if not 0 <= row < len(self._chunks):
            return
        self.beginRemoveRows(QModelIndex(), row, row)
        del self._chunks[row]
        self.endRemoveRows()

    def move_chunk(self, row: int, delta: int) -> int:
        target = row + delta
        if not (0 <= row < len(self._chunks)) or not (0 <= target < len(self._chunks)):
            return row
        self.beginResetModel()
        self._chunks[row], self._chunks[target] = self._chunks[target], self._chunks[row]
        self.endResetModel()
        return target

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._chunks)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return section + 1

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        if role not in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            return None
        chunk = self._chunks[index.row()]
        col = index.column()
        if col == self.COL_INDEX:
            return index.row() + 1
        if col == self.COL_LABEL:
            return chunk.label
        if col == self.COL_START:
            return chunk.start
        if col == self.COL_END:
            return chunk.end
        if col == self.COL_DURATION:
            start_s = parse_timecode(chunk.start)
            end_s = parse_timecode(chunk.end)
            if start_s is None or end_s is None:
                return "-"
            return format_seconds(max(0, end_s - start_s))
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        base = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        col = index.column()
        if col in (self.COL_LABEL, self.COL_START, self.COL_END):
            return base | Qt.ItemFlag.ItemIsEditable
        return base

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False
        chunk = self._chunks[index.row()]
        col = index.column()
        if col == self.COL_LABEL:
            chunk.label = str(value)
        elif col == self.COL_START:
            tc = str(value).strip()
            if parse_timecode(tc) is None:
                return False
            chunk.start = tc
        elif col == self.COL_END:
            tc = str(value).strip()
            if parse_timecode(tc) is None:
                return False
            chunk.end = tc
        else:
            return False
        self.dataChanged.emit(index, self.index(index.row(), self.COL_DURATION))
        return True

    def validate(self) -> list[str]:
        """Return a list of human-readable error strings; empty == valid."""
        errors: list[str] = []
        for i, c in enumerate(self._chunks, start=1):
            start_s = parse_timecode(c.start)
            end_s = parse_timecode(c.end)
            if start_s is None:
                errors.append(f"Row {i}: invalid start '{c.start}' (expected HH:MM:SS)")
                continue
            if end_s is None:
                errors.append(f"Row {i}: invalid end '{c.end}' (expected HH:MM:SS)")
                continue
            if end_s <= start_s:
                errors.append(f"Row {i}: end ({c.end}) must be after start ({c.start})")
            if self._max_duration_seconds is not None and end_s > self._max_duration_seconds:
                errors.append(
                    f"Row {i}: end ({c.end}) exceeds video duration "
                    f"({format_seconds(self._max_duration_seconds)})"
                )
            if not c.label.strip():
                errors.append(f"Row {i}: label is empty")
        return errors
