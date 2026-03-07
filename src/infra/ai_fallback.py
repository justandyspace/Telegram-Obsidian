"""Shared quota-aware fallback gate for remote AI providers."""

from __future__ import annotations

import os
import time

_DEFAULT_COOLDOWN_SECONDS = 900.0
_fallback_until: dict[str, float] = {}


def is_remote_ai_available(scope: str) -> bool:
    until = _fallback_until.get(scope, 0.0)
    return time.monotonic() >= until


def mark_remote_ai_failure(scope: str, exc: Exception) -> None:
    if not is_quota_error(exc):
        return
    _fallback_until[scope] = time.monotonic() + _cooldown_seconds()


def reset_remote_ai(scope: str) -> None:
    _fallback_until.pop(scope, None)


def is_quota_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return (
        "429" in text
        or "resource_exhausted" in text
        or "quota" in text
        or "rate limit" in text
        or "too many requests" in text
    )


def _cooldown_seconds() -> float:
    raw = (os.getenv("AI_REMOTE_COOLDOWN_SECONDS") or "").strip()
    if not raw:
        return _DEFAULT_COOLDOWN_SECONDS
    try:
        return max(30.0, float(raw))
    except ValueError:
        return _DEFAULT_COOLDOWN_SECONDS
