"""Shared parser result model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParseResult:
    parser: str
    source_url: str
    status: str
    title: str
    text: str
    links: list[str] = field(default_factory=list)
    error: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "parser": self.parser,
            "source_url": self.source_url,
            "status": self.status,
            "title": self.title,
            "text": self.text,
            "links": self.links,
            "error": self.error,
        }

