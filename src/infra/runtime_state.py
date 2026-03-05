"""In-process runtime state for lightweight monitoring."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

_LOCK = threading.Lock()
_STARTED_AT = datetime.now(UTC)
_STARTED_MONOTONIC = time.monotonic()
_LAST_ERROR = ""
_LAST_ERROR_AT = ""


def uptime_seconds() -> int:
    return max(0, int(time.monotonic() - _STARTED_MONOTONIC))


def uptime_human() -> str:
    total = uptime_seconds()
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def started_at_iso() -> str:
    return _STARTED_AT.isoformat()


def record_error(message: str) -> None:
    value = (message or "").strip()[:800]
    if not value:
        return
    now = datetime.now(UTC).isoformat()
    with _LOCK:
        global _LAST_ERROR
        global _LAST_ERROR_AT
        _LAST_ERROR = value
        _LAST_ERROR_AT = now


def last_error() -> tuple[str, str]:
    with _LOCK:
        return _LAST_ERROR, _LAST_ERROR_AT
