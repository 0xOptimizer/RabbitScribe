from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import QSettings


ORG = "rabbitscribe"
APP = "rabbitscribe"


def settings() -> QSettings:
    return QSettings(ORG, APP)


def get(key: str, default: Any = None) -> Any:
    return settings().value(key, default)


def set_(key: str, value: Any) -> None:
    settings().setValue(key, value)


def get_json(key: str, default: Any) -> Any:
    raw = settings().value(key)
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def set_json(key: str, value: Any) -> None:
    settings().setValue(key, json.dumps(value))
