"""Persistent settings backed by ~/.rabbitscribe/state.json.

API mirrors what QSettings would expose (`get`, `set_`, `get_json`,
`set_json`) so call sites don't need to know about the underlying file.

Window-geometry blobs (QByteArray) are transparently base64-encoded on
write and reconstructed on read, so the whole file stays human-readable
JSON.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import QByteArray


log = logging.getLogger(__name__)

ORG = "rabbitscribe"
APP = "rabbitscribe"

_BYTES_TAG = "__bytes_b64__"


def state_file() -> Path:
    return Path.home() / ".rabbitscribe" / "state.json"


_state: dict[str, Any] | None = None


def _load() -> dict[str, Any]:
    global _state
    if _state is not None:
        return _state
    path = state_file()
    if not path.is_file():
        _state = {}
        return _state
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        _state = data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Could not read %s, starting fresh: %s", path, exc)
        _state = {}
    return _state


def _save() -> None:
    if _state is None:
        return
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(
            json.dumps(_state, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except OSError as exc:
        log.warning("Could not write %s: %s", path, exc)
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _encode(value: Any) -> Any:
    if isinstance(value, QByteArray):
        return {_BYTES_TAG: base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, bytes):
        return {_BYTES_TAG: base64.b64encode(value).decode("ascii")}
    if isinstance(value, Path):
        return str(value)
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, dict) and _BYTES_TAG in value and len(value) == 1:
        try:
            return QByteArray(base64.b64decode(value[_BYTES_TAG]))
        except (ValueError, TypeError):
            return None
    return value


def get(key: str, default: Any = None) -> Any:
    raw = _load().get(key)
    if raw is None:
        return default
    return _decode(raw)


def set_(key: str, value: Any) -> None:
    state = _load()
    state[key] = _encode(value)
    _save()


def get_json(key: str, default: Any) -> Any:
    """JSON-shaped values pass through unchanged; alias kept for callers
    that previously round-tripped through a JSON string in QSettings.
    """
    value = get(key, default)
    return value if value is not None else default


def set_json(key: str, value: Any) -> None:
    set_(key, value)


def clear() -> None:
    """Wipe the state file. Mostly useful for tests."""
    global _state
    _state = {}
    path = state_file()
    if path.is_file():
        try:
            path.unlink()
        except OSError:
            pass
