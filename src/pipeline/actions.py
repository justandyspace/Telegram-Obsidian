"""Action tag handling."""

from __future__ import annotations

KNOWN_ACTIONS = {"save", "summary", "task", "resummarize", "translate"}


def parse_actions(hashtags: set[str]) -> set[str]:
    actions = {tag for tag in hashtags if tag in KNOWN_ACTIONS}
    return actions or {"save"}
