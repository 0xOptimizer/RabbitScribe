from __future__ import annotations

from pathlib import Path

import pysrt
from pysrt import SubRipFile, SubRipItem, SubRipTime

from rabbitscribe.models.chunks import Chunk
from rabbitscribe.workers.srt_split import split_srt_by_chunks


def _write_srt(path: Path, cues: list[tuple[int, int, str]]) -> None:
    """cues: list of (start_ms, end_ms, text)"""
    f = SubRipFile()
    for i, (start_ms, end_ms, text) in enumerate(cues, start=1):
        f.append(
            SubRipItem(
                index=i,
                start=SubRipTime.from_ordinal(start_ms),
                end=SubRipTime.from_ordinal(end_ms),
                text=text,
            )
        )
    f.save(str(path), encoding="utf-8")


def test_cues_fully_inside_chunk_re_zeroed_to_chunk_start(tmp_path: Path):
    srt = tmp_path / "src.srt"
    _write_srt(srt, [
        (10_000, 12_000, "A"),
        (13_000, 15_000, "B"),
    ])
    chunks = [Chunk(label="part1", start="00:00:08", end="00:00:20")]
    written = split_srt_by_chunks(srt, chunks, tmp_path / "out")
    assert len(written) == 1

    parts = pysrt.open(str(written[0]), encoding="utf-8")
    # Cue [10s, 12s] - 8s offset = [2s, 4s]
    assert parts[0].start.ordinal == 2000
    assert parts[0].end.ordinal == 4000
    assert parts[0].text == "A"
    assert parts[1].text == "B"


def test_cue_clamped_at_chunk_start(tmp_path: Path):
    srt = tmp_path / "src.srt"
    _write_srt(srt, [(5_000, 12_000, "spans into chunk")])
    chunks = [Chunk(label="part1", start="00:00:10", end="00:00:20")]
    written = split_srt_by_chunks(srt, chunks, tmp_path / "out")
    parts = pysrt.open(str(written[0]), encoding="utf-8")
    # Cue starts at 5s, chunk starts at 10s -> clamp to 10s
    # After re-zero: [0, 12-10] = [0, 2000]
    assert parts[0].start.ordinal == 0
    assert parts[0].end.ordinal == 2000


def test_cue_clamped_at_chunk_end(tmp_path: Path):
    srt = tmp_path / "src.srt"
    _write_srt(srt, [(15_000, 25_000, "spans out of chunk")])
    chunks = [Chunk(label="part1", start="00:00:10", end="00:00:20")]
    written = split_srt_by_chunks(srt, chunks, tmp_path / "out")
    parts = pysrt.open(str(written[0]), encoding="utf-8")
    # Cue [15, 25] clamped to [15, 20] -> re-zero -> [5, 10]
    assert parts[0].start.ordinal == 5000
    assert parts[0].end.ordinal == 10000


def test_cue_spans_two_chunks_appears_in_both(tmp_path: Path):
    srt = tmp_path / "src.srt"
    _write_srt(srt, [(8_000, 22_000, "very long cue")])
    chunks = [
        Chunk(label="part1", start="00:00:00", end="00:00:15"),
        Chunk(label="part2", start="00:00:15", end="00:00:30"),
    ]
    written = split_srt_by_chunks(srt, chunks, tmp_path / "out")
    assert len(written) == 2

    a = pysrt.open(str(written[0]), encoding="utf-8")
    b = pysrt.open(str(written[1]), encoding="utf-8")
    # In chunk1 [0,15]: cue [8,22] clamps to [8,15] -> [8000, 15000]
    assert a[0].start.ordinal == 8000
    assert a[0].end.ordinal == 15000
    # In chunk2 [15,30]: cue clamps to [15,22] -> re-zero -> [0, 7000]
    assert b[0].start.ordinal == 0
    assert b[0].end.ordinal == 7000


def test_chunk_with_no_overlap_produces_no_file(tmp_path: Path):
    srt = tmp_path / "src.srt"
    _write_srt(srt, [(0, 5_000, "early"), (60_000, 65_000, "late")])
    chunks = [
        Chunk(label="middle", start="00:00:10", end="00:00:30"),
    ]
    written = split_srt_by_chunks(srt, chunks, tmp_path / "out")
    assert written == []
    assert not (tmp_path / "out" / "1_middle.srt").exists()


def test_invalid_chunk_range_skipped(tmp_path: Path):
    srt = tmp_path / "src.srt"
    _write_srt(srt, [(0, 5_000, "x")])
    # end <= start -> skipped, end empty -> skipped
    chunks = [
        Chunk(label="bad", start="00:00:10", end="00:00:05"),
    ]
    written = split_srt_by_chunks(srt, chunks, tmp_path / "out")
    assert written == []


def test_output_filenames_match_video_naming_convention(tmp_path: Path):
    srt = tmp_path / "src.srt"
    _write_srt(srt, [(1_000, 2_000, "x")])
    chunks = [
        Chunk(label="Intro Chat & QA", start="00:00:00", end="00:00:05"),
        Chunk(label="Outro", start="00:00:05", end="00:00:10"),
    ]
    _write_srt(srt, [(1_000, 7_000, "spans both")])
    written = split_srt_by_chunks(srt, chunks, tmp_path / "out")
    names = sorted(p.name for p in written)
    # Width is 2 (since total=2 -> max(2, len("2"))=2)
    assert names == ["01_Intro_Chat_QA.srt", "02_Outro.srt"]


def test_missing_srt_raises(tmp_path: Path):
    chunks = [Chunk(label="a", start="00:00:00", end="00:00:05")]
    try:
        split_srt_by_chunks(tmp_path / "nope.srt", chunks, tmp_path / "out")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("expected FileNotFoundError")


def test_overwrite_false_preserves_existing(tmp_path: Path):
    srt = tmp_path / "src.srt"
    _write_srt(srt, [(0, 1_000, "x")])
    chunks = [Chunk(label="a", start="00:00:00", end="00:00:05")]
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    target = out_dir / "01_a.srt"
    target.write_text("EXISTING", encoding="utf-8")

    written = split_srt_by_chunks(srt, chunks, out_dir, overwrite=False)
    assert written == []
    assert target.read_text(encoding="utf-8") == "EXISTING"
