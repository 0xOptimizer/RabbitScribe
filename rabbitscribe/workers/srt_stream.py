"""Streaming SRT writer + resume helpers.

Lets the transcribe workers append cues to disk as whisper produces each
segment, instead of waiting for the full run to finish. The same module
provides `read_resume_state` so a cancelled/crashed run can pick up at
the next launch without re-transcribing what's already on disk.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pysrt


log = logging.getLogger(__name__)


_SEGMENT_RE = re.compile(
    r"\[(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)\s*-->\s*(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)\]"
)


def format_srt_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_segment_line(line: str) -> tuple[float, float, str] | None:
    """Extract (start_seconds, end_seconds, text) from a whisper segment
    line. Handles `[HH:MM:SS.mmm --> ...]` (whisper.cpp) and the short
    `[MM:SS.mmm --> ...]` form (openai-whisper for sub-hour audio).

    Returns None for non-segment lines (status, headers, language
    detection notices). Returns None for nonsensical ranges (end < start).
    """
    m = _SEGMENT_RE.search(line)
    if not m:
        return None
    start_h = int(m.group(1)) if m.group(1) else 0
    start = start_h * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    end_h = int(m.group(4)) if m.group(4) else 0
    end = end_h * 3600 + int(m.group(5)) * 60 + float(m.group(6))
    if end < start:
        return None
    text = line[m.end():].strip()
    return (start, end, text)


def read_resume_state(srt_path: Path) -> tuple[float, int, int] | None:
    """If a usable partial SRT exists at this path, return
    (last_end_seconds, next_index_to_write, cue_count). Otherwise None.

    None is returned for missing, empty, or malformed files; the caller
    should then treat the run as fresh.
    """
    if not srt_path.is_file() or srt_path.stat().st_size == 0:
        return None
    try:
        subs = pysrt.open(str(srt_path), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        log.warning("Could not parse partial SRT for resume: %s", exc)
        return None
    if len(subs) == 0:
        return None
    last = subs[-1]
    return (last.end.ordinal / 1000.0, last.index + 1, len(subs))


class SegmentStreamer:
    """Append SRT cues to a file one at a time, flushing after each.

    Opens the file lazily on first `add` so callers don't accidentally
    truncate a file when no segments end up being written. Safe in resume
    mode: if the file already has content, a separator newline is inserted
    before the first new cue.
    """

    def __init__(self, path: Path, start_index: int = 1) -> None:
        self._path = path
        self._index = start_index
        self._fh = None
        self._count = 0

    @property
    def cues_written(self) -> int:
        return self._count

    def add(self, start: float, end: float, text: str) -> None:
        if self._fh is None:
            self._open()
        try:
            self._fh.write(
                f"{self._index}\n"
                f"{format_srt_timestamp(start)} --> {format_srt_timestamp(end)}\n"
                f"{text}\n\n"
            )
            self._fh.flush()
            self._index += 1
            self._count += 1
        except OSError as exc:
            log.warning("SegmentStreamer write failed (%s); subsequent writes may be lost", exc)

    def _open(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.is_file() and self._path.stat().st_size > 0:
            try:
                with open(self._path, "a", encoding="utf-8", newline="") as f:
                    f.write("\n\n")
            except OSError as exc:
                log.warning("Could not append separator to %s: %s", self._path, exc)
        try:
            self._fh = open(self._path, "a", encoding="utf-8", newline="")
        except OSError as exc:
            log.warning("Could not open %s for append: %s", self._path, exc)
            self._fh = None

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.flush()
                self._fh.close()
            except OSError:
                pass
            self._fh = None
