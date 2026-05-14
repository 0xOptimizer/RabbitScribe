"""Pure-Python SRT cleanup. No Qt imports allowed.

The single public entry point is `clean(subs, rules)`. Each transform is
exposed as a module-level helper so the test suite can pin behaviour rule
by rule.
"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Iterable

import pysrt
from pysrt import SubRipFile, SubRipItem, SubRipTime


@dataclass
class CleanupRules:
    min_duration_s: float = 2.0
    max_duration_s: float = 6.0
    max_chars: int = 84
    strip_ellipsis: bool = True
    mark_unclear: bool = True
    unclear_token: str = "[onverstaanbaar]"
    capitalise_sentences: bool = True
    substitutions: dict[str, str] = field(default_factory=dict)


_UNCLEAR_BRACKETED = re.compile(r"\[\s*\*?[^\]]*\*?\s*\]")
_ELLIPSIS = re.compile(r"\.{3,}|…")
_MULTISPACE = re.compile(r"[ \t]{2,}")


def clean(subs: SubRipFile, rules: CleanupRules) -> SubRipFile:
    """Apply every rule in `rules` and return a fresh SubRipFile.

    Order: text-level transforms first (substitutions, ellipsis, unclear,
    capitalisation), then structural merging of short cues into the next.
    Re-indexed at the end so output indices start at 1.
    """
    out = SubRipFile()
    for item in subs:
        new_item = SubRipItem(
            index=item.index,
            start=SubRipTime.from_ordinal(item.start.ordinal),
            end=SubRipTime.from_ordinal(item.end.ordinal),
            text=item.text,
        )
        out.append(new_item)

    for item in out:
        if rules.substitutions:
            item.text = apply_substitutions(item.text, rules.substitutions)
        if rules.strip_ellipsis:
            item.text = strip_ellipsis(item.text)
        if rules.capitalise_sentences:
            item.text = capitalise_sentences(item.text)
        if rules.mark_unclear:
            item.text = mark_unclear(item.text, rules.unclear_token)
        item.text = _normalise_whitespace(item.text)

    out = merge_short_cues(
        out,
        min_duration_s=rules.min_duration_s,
        max_duration_s=rules.max_duration_s,
        max_chars=rules.max_chars,
    )

    for i, item in enumerate(out, start=1):
        item.index = i

    return out


def apply_substitutions(text: str, substitutions: dict[str, str]) -> str:
    """Case-insensitive whole-phrase substitution, longest keys first."""
    if not text or not substitutions:
        return text
    keys = sorted(substitutions.keys(), key=len, reverse=True)
    for key in keys:
        replacement = substitutions[key]
        pattern = re.compile(
            r"(?<![A-Za-z0-9])" + re.escape(key) + r"(?![A-Za-z0-9])",
            flags=re.IGNORECASE,
        )
        text = pattern.sub(replacement, text)
    return text


def strip_ellipsis(text: str) -> str:
    return _ELLIPSIS.sub(" ", text)


def mark_unclear(text: str, token: str) -> str:
    stripped = text.strip()
    if not stripped:
        return token
    replaced = _UNCLEAR_BRACKETED.sub(token, text)
    return replaced


def capitalise_sentences(text: str) -> str:
    """Capitalise the first alphabetic char of the cue and any char that
    follows a sentence terminator. Leaves the rest of each word untouched.
    """
    if not text:
        return text

    result: list[str] = []
    capitalise_next = True
    for ch in text:
        if capitalise_next and ch.isalpha():
            result.append(ch.upper())
            capitalise_next = False
            continue
        result.append(ch)
        if ch in ".!?":
            capitalise_next = True
        elif ch.isalnum():
            capitalise_next = False
    return "".join(result)


def merge_short_cues(
    subs: SubRipFile,
    *,
    min_duration_s: float,
    max_duration_s: float,
    max_chars: int,
) -> SubRipFile:
    """Merge cues shorter than `min_duration_s` into the following cue,
    unless doing so would exceed `max_duration_s` or `max_chars`.

    A trailing too-short cue (no next cue) is merged into the previous one
    if that does not violate the limits; otherwise it is kept as-is.
    """
    if min_duration_s <= 0 or len(subs) < 2:
        return subs

    min_ms = int(min_duration_s * 1000)
    max_ms = int(max_duration_s * 1000)

    items: list[SubRipItem] = list(subs)
    merged: list[SubRipItem] = []
    i = 0
    while i < len(items):
        current = items[i]
        if i == len(items) - 1:
            if (
                merged
                and (current.end.ordinal - current.start.ordinal) < min_ms
                and _can_combine(merged[-1], current, max_ms, max_chars)
            ):
                _combine_into_first(merged[-1], current)
            else:
                merged.append(current)
            break

        nxt = items[i + 1]
        cur_dur = current.end.ordinal - current.start.ordinal
        if cur_dur < min_ms and _can_combine(current, nxt, max_ms, max_chars):
            _combine_into_first(current, nxt)
            merged.append(current)
            i += 2
        else:
            merged.append(current)
            i += 1

    out = SubRipFile()
    for item in merged:
        out.append(item)
    return out


def _can_combine(first: SubRipItem, second: SubRipItem, max_ms: int, max_chars: int) -> bool:
    combined_ms = second.end.ordinal - first.start.ordinal
    if combined_ms > max_ms:
        return False
    combined_chars = len(first.text) + 1 + len(second.text)
    return combined_chars <= max_chars


def _combine_into_first(first: SubRipItem, second: SubRipItem) -> None:
    first.end = SubRipTime.from_ordinal(second.end.ordinal)
    a = first.text.strip()
    b = second.text.strip()
    first.text = f"{a} {b}".strip() if a and b else (a or b)


def _normalise_whitespace(text: str) -> str:
    lines = [_MULTISPACE.sub(" ", line).strip() for line in text.splitlines()]
    cleaned = "\n".join(line for line in lines if line)
    return cleaned
