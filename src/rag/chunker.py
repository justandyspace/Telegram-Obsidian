"""Multilingual chunking utilities for vault notes."""

from __future__ import annotations

import re

from src.pipeline.normalize import normalize_text

PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")


def chunk_text(text: str, max_chars: int = 1200, overlap_chars: int = 180) -> list[str]:
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []

    paragraphs = [part.strip() for part in PARAGRAPH_SPLIT_RE.split(normalized) if part.strip()]
    if not paragraphs:
        paragraphs = [normalized]

    chunks: list[str] = []
    current = ""

    for paragraph in paragraphs:
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= max_chars:
            current = candidate
            continue

        if current:
            chunks.append(normalize_text(current))
            current = paragraph
            if len(current) > max_chars:
                chunks.extend(_slice_large_text(current, max_chars, overlap_chars))
                current = ""
            continue

        chunks.extend(_slice_large_text(paragraph, max_chars, overlap_chars))

    if current:
        chunks.append(normalize_text(current))

    deduped: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        compact = normalize_text(chunk)
        if not compact:
            continue
        if compact in seen:
            continue
        seen.add(compact)
        deduped.append(compact)
    return deduped


def _slice_large_text(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    compact = normalize_text(text)
    if len(compact) <= max_chars:
        return [compact]

    result: list[str] = []
    start = 0
    while start < len(compact):
        end = min(start + max_chars, len(compact))
        segment = compact[start:end].strip()
        if segment:
            result.append(segment)
        if end >= len(compact):
            break
        start = max(0, end - overlap_chars)
    return result
