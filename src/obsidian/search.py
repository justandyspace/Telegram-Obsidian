"""Simple vault search helpers for Phase 2 UX commands."""

from __future__ import annotations

import logging
from pathlib import Path

LOGGER = logging.getLogger(__name__)


def find_notes(vault_path: Path, query: str, limit: int = 5) -> list[dict[str, str]]:
    needle = query.strip().lower()
    if not needle:
        return []

    matches: list[dict[str, str]] = []
    for note_file in sorted(vault_path.glob("*.md")):
        try:
            content = note_file.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Failed to read note for search path=%s reason=%s", note_file, exc)
            continue
        haystack = content.lower()
        if needle not in haystack:
            continue
        index = haystack.find(needle)
        start = max(0, index - 80)
        end = min(len(content), index + len(needle) + 120)
        snippet = " ".join(content[start:end].split())
        score = haystack.count(needle)
        matches.append(
            {
                "file_name": note_file.name,
                "snippet": snippet[:280],
                "score": str(score),
            }
        )

    matches.sort(key=lambda item: int(item["score"]), reverse=True)
    return matches[:limit]


def latest_notes(vault_path: Path, limit: int = 5) -> list[dict[str, str]]:
    files = sorted(vault_path.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    items: list[dict[str, str]] = []
    for note_file in files[:limit]:
        try:
            content = note_file.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Failed to read note for latest path=%s reason=%s", note_file, exc)
            continue
        first_line = next((line.strip() for line in content.splitlines() if line.strip()), "")
        items.append(
            {
                "file_name": note_file.name,
                "snippet": first_line[:160],
            }
        )
    return items
