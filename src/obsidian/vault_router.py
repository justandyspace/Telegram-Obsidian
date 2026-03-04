"""Deterministic vault filename routing."""

from __future__ import annotations

from datetime import datetime

from src.pipeline.normalize import ascii_safe_title


def deterministic_file_name(*, created_at: datetime, title: str, note_id: str) -> str:
    prefix = created_at.strftime("%Y%m%d-%H%M")
    safe_title = ascii_safe_title(title)
    return f"{prefix} - {safe_title} ({note_id}).md"
