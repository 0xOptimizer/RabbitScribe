from __future__ import annotations

import pysrt
from pysrt import SubRipFile, SubRipItem, SubRipTime

from rabbitscribe.workers.srt_cleaner import (
    CleanupRules,
    apply_substitutions,
    capitalise_sentences,
    clean,
    mark_unclear,
    merge_short_cues,
    strip_ellipsis,
)


def _item(index: int, start_ms: int, end_ms: int, text: str) -> SubRipItem:
    return SubRipItem(
        index=index,
        start=SubRipTime.from_ordinal(start_ms),
        end=SubRipTime.from_ordinal(end_ms),
        text=text,
    )


def _file(*items: SubRipItem) -> SubRipFile:
    f = SubRipFile()
    for item in items:
        f.append(item)
    return f


# ---------- apply_substitutions ----------

def test_substitutions_replaces_whole_phrase_case_insensitive():
    out = apply_substitutions("semovo te is great", {"semovo te": "Semovote"})
    assert out == "Semovote is great"


def test_substitutions_longest_match_first():
    subs = {"semo": "SEMO", "semo vote": "Semovote"}
    assert apply_substitutions("semo vote launch", subs) == "Semovote launch"


def test_substitutions_respects_word_boundary():
    out = apply_substitutions("semolina is not semo", {"semo": "SEMO"})
    assert out == "semolina is not SEMO"


def test_substitutions_noop_on_empty_input():
    assert apply_substitutions("", {"a": "b"}) == ""
    assert apply_substitutions("hello", {}) == "hello"


# ---------- strip_ellipsis ----------

def test_strip_ellipsis_three_dots():
    assert strip_ellipsis("well... maybe") == "well  maybe"


def test_strip_ellipsis_unicode_horizontal_ellipsis():
    assert strip_ellipsis("well… maybe") == "well  maybe"


def test_strip_ellipsis_more_than_three_dots():
    assert strip_ellipsis("hmm...... right") == "hmm  right"


# ---------- mark_unclear ----------

def test_mark_unclear_empty_string_replaced_with_token():
    assert mark_unclear("   ", "[onverstaanbaar]") == "[onverstaanbaar]"


def test_mark_unclear_bracketed_marker_replaced():
    assert mark_unclear("[*unclear*]", "[onverstaanbaar]") == "[onverstaanbaar]"
    assert mark_unclear("[inaudible]", "[onverstaanbaar]") == "[onverstaanbaar]"


def test_mark_unclear_leaves_normal_text_alone():
    assert mark_unclear("hello world", "[X]") == "hello world"


# ---------- capitalise_sentences ----------

def test_capitalise_first_letter_of_cue():
    assert capitalise_sentences("hello there") == "Hello there"


def test_capitalise_after_terminator():
    assert capitalise_sentences("hi. how are you? fine!") == "Hi. How are you? Fine!"


def test_capitalise_does_not_lowercase_existing_caps():
    assert capitalise_sentences("hello WORLD") == "Hello WORLD"


def test_capitalise_handles_leading_whitespace():
    assert capitalise_sentences("  hello") == "  Hello"


# ---------- merge_short_cues ----------

def test_merge_short_into_next():
    f = _file(
        _item(1, 0, 800, "hi"),
        _item(2, 1000, 4000, "there"),
    )
    out = merge_short_cues(f, min_duration_s=2.0, max_duration_s=6.0, max_chars=80)
    assert len(out) == 1
    assert out[0].text == "hi there"
    assert out[0].start.ordinal == 0
    assert out[0].end.ordinal == 4000


def test_merge_skipped_when_combined_too_long():
    f = _file(
        _item(1, 0, 800, "hi"),
        _item(2, 1000, 10_000, "long"),
    )
    out = merge_short_cues(f, min_duration_s=2.0, max_duration_s=6.0, max_chars=80)
    assert len(out) == 2


def test_merge_skipped_when_combined_too_many_chars():
    f = _file(
        _item(1, 0, 800, "a" * 50),
        _item(2, 1000, 3000, "b" * 50),
    )
    out = merge_short_cues(f, min_duration_s=2.0, max_duration_s=6.0, max_chars=80)
    assert len(out) == 2


def test_merge_long_cue_left_alone():
    f = _file(
        _item(1, 0, 3000, "long"),
        _item(2, 3000, 6000, "enough"),
    )
    out = merge_short_cues(f, min_duration_s=2.0, max_duration_s=6.0, max_chars=80)
    assert len(out) == 2


def test_merge_trailing_short_into_previous():
    f = _file(
        _item(1, 0, 3000, "first"),
        _item(2, 3000, 3500, "tail"),
    )
    out = merge_short_cues(f, min_duration_s=2.0, max_duration_s=6.0, max_chars=80)
    assert len(out) == 1
    assert out[0].text == "first tail"
    assert out[0].end.ordinal == 3500


def test_merge_empty_input_returns_unchanged():
    f = _file()
    out = merge_short_cues(f, min_duration_s=2.0, max_duration_s=6.0, max_chars=80)
    assert len(out) == 0


def test_merge_zero_min_duration_is_noop():
    f = _file(
        _item(1, 0, 100, "a"),
        _item(2, 200, 300, "b"),
    )
    out = merge_short_cues(f, min_duration_s=0.0, max_duration_s=6.0, max_chars=80)
    assert len(out) == 2


# ---------- clean (integration) ----------

def test_clean_runs_all_rules_in_order():
    f = _file(
        _item(1, 0, 800, "semovo te... is cool"),
        _item(2, 1000, 4000, "hello WORLD."),
        _item(3, 4500, 5000, "[*unclear*]"),
        _item(4, 5500, 8000, "next sentence"),
    )
    rules = CleanupRules(
        min_duration_s=2.0,
        max_duration_s=6.0,
        max_chars=200,
        substitutions={"semovo te": "Semovote"},
    )
    out = clean(f, rules)
    texts = [item.text for item in out]
    # First two cues merged (cue 1 was 0.8s), substitution + ellipsis applied
    assert texts[0].startswith("Semovote")
    assert "..." not in texts[0]
    # Unclear marker resolved to default Dutch token
    assert "[onverstaanbaar]" in "\n".join(texts)
    # Indices re-numbered from 1
    assert [item.index for item in out] == list(range(1, len(out) + 1))


def test_clean_with_all_rules_disabled_returns_equivalent_cues():
    f = _file(
        _item(1, 0, 3000, "hi there"),
        _item(2, 3000, 6000, "second cue"),
    )
    rules = CleanupRules(
        min_duration_s=0.0,
        max_duration_s=999.0,
        max_chars=10_000,
        strip_ellipsis=False,
        mark_unclear=False,
        capitalise_sentences=False,
    )
    out = clean(f, rules)
    assert [item.text for item in out] == ["hi there", "second cue"]


def test_clean_drops_no_cues_when_nothing_to_merge():
    f = _file(
        _item(1, 0, 3000, "alpha"),
        _item(2, 3000, 6000, "beta"),
        _item(3, 6000, 9000, "gamma"),
    )
    out = clean(f, CleanupRules())
    assert len(out) == 3
