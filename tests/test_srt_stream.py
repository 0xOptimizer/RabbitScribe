from __future__ import annotations

from pathlib import Path

import pysrt

from rabbitscribe.workers.srt_stream import (
    SegmentStreamer,
    format_srt_timestamp,
    parse_segment_line,
    read_resume_state,
)


# ---------- format_srt_timestamp ----------

def test_format_srt_timestamp_zero():
    assert format_srt_timestamp(0.0) == "00:00:00,000"


def test_format_srt_timestamp_negative_clamped_to_zero():
    assert format_srt_timestamp(-1.5) == "00:00:00,000"


def test_format_srt_timestamp_hours_minutes_seconds_ms():
    assert format_srt_timestamp(3723.456) == "01:02:03,456"


def test_format_srt_timestamp_rounds_milliseconds():
    # 0.0007 unambiguously rounds to 1 ms regardless of banker's rounding.
    assert format_srt_timestamp(0.0007) == "00:00:00,001"


# ---------- parse_segment_line ----------

def test_parse_segment_line_whisper_cpp_format():
    parsed = parse_segment_line("[00:00:23.560 --> 00:00:27.120]  hello world")
    assert parsed == (23.560, 27.120, "hello world")


def test_parse_segment_line_short_format():
    parsed = parse_segment_line("[01:42.000 --> 01:47.500]  short fmt")
    assert parsed == (102.0, 107.5, "short fmt")


def test_parse_segment_line_hour_format():
    parsed = parse_segment_line("[1:02:03.000 --> 1:02:04.000]  long audio")
    assert parsed == (3723.0, 3724.0, "long audio")


def test_parse_segment_line_non_segment_returns_none():
    assert parse_segment_line("INFO: loading model ggml-large-v3.bin") is None
    assert parse_segment_line("") is None
    assert parse_segment_line("Detected language: Dutch") is None


def test_parse_segment_line_rejects_nonsense_range():
    # end before start
    assert parse_segment_line("[00:00:10.000 --> 00:00:05.000]  bad") is None


def test_parse_segment_line_empty_text_ok():
    parsed = parse_segment_line("[00:00:00.000 --> 00:00:01.000]")
    assert parsed == (0.0, 1.0, "")


# ---------- SegmentStreamer ----------

def test_segment_streamer_writes_sequential_cues(tmp_path: Path):
    srt = tmp_path / "out.srt"
    s = SegmentStreamer(srt, start_index=1)
    s.add(0.0, 1.5, "Alpha")
    s.add(1.5, 3.0, "Beta")
    s.close()

    subs = pysrt.open(str(srt), encoding="utf-8")
    assert [item.text for item in subs] == ["Alpha", "Beta"]
    assert [item.index for item in subs] == [1, 2]
    assert subs[0].start.ordinal == 0
    assert subs[1].end.ordinal == 3000


def test_segment_streamer_appends_to_existing_file(tmp_path: Path):
    srt = tmp_path / "out.srt"
    s1 = SegmentStreamer(srt, start_index=1)
    s1.add(0.0, 2.0, "First")
    s1.close()

    s2 = SegmentStreamer(srt, start_index=2)
    s2.add(2.0, 4.0, "Second")
    s2.close()

    subs = pysrt.open(str(srt), encoding="utf-8")
    assert [item.text for item in subs] == ["First", "Second"]
    assert [item.index for item in subs] == [1, 2]


def test_segment_streamer_does_not_truncate_if_no_writes(tmp_path: Path):
    srt = tmp_path / "out.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nexisting\n\n", encoding="utf-8")

    s = SegmentStreamer(srt, start_index=99)
    s.close()  # no `add` calls

    assert "existing" in srt.read_text(encoding="utf-8")


def test_segment_streamer_cues_written_count(tmp_path: Path):
    srt = tmp_path / "out.srt"
    s = SegmentStreamer(srt)
    assert s.cues_written == 0
    s.add(0.0, 1.0, "a")
    s.add(1.0, 2.0, "b")
    assert s.cues_written == 2
    s.close()


# ---------- read_resume_state ----------

def test_read_resume_state_missing_file_returns_none(tmp_path: Path):
    assert read_resume_state(tmp_path / "nope.srt") is None


def test_read_resume_state_empty_file_returns_none(tmp_path: Path):
    srt = tmp_path / "empty.srt"
    srt.write_text("", encoding="utf-8")
    assert read_resume_state(srt) is None


def test_read_resume_state_returns_last_cue_state(tmp_path: Path):
    srt = tmp_path / "partial.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:02,500\nfirst\n\n"
        "2\n00:00:02,500 --> 00:00:05,000\nsecond\n\n",
        encoding="utf-8",
    )
    state = read_resume_state(srt)
    assert state is not None
    last_end, next_index, count = state
    assert last_end == 5.0
    assert next_index == 3
    assert count == 2


def test_read_resume_state_malformed_returns_none(tmp_path: Path):
    srt = tmp_path / "bad.srt"
    srt.write_text("this is not an SRT file at all", encoding="utf-8")
    state = read_resume_state(srt)
    # Some malformed inputs may still parse to zero cues; either way we
    # should not crash and should signal "no resume" for a non-conforming
    # file with no cues recovered.
    assert state is None
