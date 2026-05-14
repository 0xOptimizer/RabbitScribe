"""Split a single SRT into per-chunk SRTs that mirror video chunks.

Pure Python, no Qt — unit-tested in tests/test_srt_split.py. Cues are
clamped to each chunk's [start, end] range and re-zeroed so each
chunk's SRT begins at 00:00:00,000.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pysrt
from pysrt import SubRipFile, SubRipItem, SubRipTime

from rabbitscribe.models.chunks import Chunk, parse_timecode
from rabbitscribe.workers.chunk_split import chunk_filename


log = logging.getLogger(__name__)


def split_srt_by_chunks(
    srt_path: Path,
    chunks: list[Chunk],
    out_dir: Path,
    *,
    overwrite: bool = True,
) -> list[Path]:
    """Write one SRT per chunk into `out_dir`.

    Returns the list of written paths. A chunk with no overlapping cues
    produces no file. Files are named `<NN>_<slug>.srt` to mirror the
    corresponding `<NN>_<slug>.mp4`.
    """
    if not srt_path.is_file():
        raise FileNotFoundError(f"SRT does not exist: {srt_path}")
    subs = pysrt.open(str(srt_path), encoding="utf-8")
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(chunks)
    written: list[Path] = []

    for i, chunk in enumerate(chunks, start=1):
        chunk_start = parse_timecode(chunk.start)
        chunk_end = parse_timecode(chunk.end)
        if chunk_start is None or chunk_end is None or chunk_end <= chunk_start:
            log.warning("Skipping chunk %d with invalid range: %s..%s", i, chunk.start, chunk.end)
            continue

        chunk_start_ms = chunk_start * 1000
        chunk_end_ms = chunk_end * 1000
        out_subs = SubRipFile()
        next_index = 1

        for cue in subs:
            cue_start_ms = cue.start.ordinal
            cue_end_ms = cue.end.ordinal
            # No overlap (cue ends before chunk starts, or starts after chunk ends)
            if cue_end_ms <= chunk_start_ms or cue_start_ms >= chunk_end_ms:
                continue
            # Clamp + re-zero to chunk start
            new_start_ms = max(cue_start_ms, chunk_start_ms) - chunk_start_ms
            new_end_ms = min(cue_end_ms, chunk_end_ms) - chunk_start_ms
            if new_end_ms <= new_start_ms:
                continue
            out_subs.append(
                SubRipItem(
                    index=next_index,
                    start=SubRipTime.from_ordinal(new_start_ms),
                    end=SubRipTime.from_ordinal(new_end_ms),
                    text=cue.text,
                )
            )
            next_index += 1

        if len(out_subs) == 0:
            continue

        srt_name = chunk_filename(i, chunk.label, total).removesuffix(".mp4") + ".srt"
        out_path = out_dir / srt_name
        if out_path.exists() and not overwrite:
            log.info("Skipping existing %s", out_path)
            continue
        out_subs.save(str(out_path), encoding="utf-8")
        written.append(out_path)

    return written
