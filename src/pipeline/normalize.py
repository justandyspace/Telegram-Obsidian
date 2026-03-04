"""Normalization and title derivation."""

from __future__ import annotations

import re
import unicodedata

HASHTAG_RE = re.compile(r"(?<!\w)#(\w+)", re.UNICODE)
WHITESPACE_RE = re.compile(r"\s+")


def extract_hashtags(text: str) -> set[str]:
    return {match.group(1).lower() for match in HASHTAG_RE.finditer(text)}


def strip_hashtags(text: str) -> str:
    return HASHTAG_RE.sub("", text)


def normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ").strip()
    return WHITESPACE_RE.sub(" ", text)


def derive_title(content: str, max_words: int = 8) -> str:
    cleaned = re.sub(r"[^\w\s-]", " ", content)
    tokens = [token for token in cleaned.split() if token]
    if not tokens:
        return "Untitled"
    return " ".join(tokens[:max_words])


def ascii_safe_title(title: str, max_length: int = 64) -> str:
    normalized = (
        unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    )
    normalized = re.sub(r"[^A-Za-z0-9\s_-]", "", normalized)
    normalized = normalize_text(normalized)
    if not normalized:
        normalized = "Note"
    return normalized[:max_length].rstrip()


def short_summary(content: str, max_chars: int = 280) -> str:
    normalized = normalize_text(content)
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3].rstrip() + "..."
