"""Managed block merge logic."""

from __future__ import annotations

import re

MANAGED_BLOCKS = ["BOT_META", "BOT_SUMMARY", "BOT_TASKS", "BOT_LINKS"]


def _start_marker(name: str) -> str:
    return f"<!-- {name}:START -->"


def _end_marker(name: str) -> str:
    return f"<!-- {name}:END -->"


def build_block(name: str, body: str) -> str:
    body = body.strip("\n")
    return f"{_start_marker(name)}\n{body}\n{_end_marker(name)}"


def replace_or_append_block(document: str, *, name: str, body: str) -> str:
    block_text = build_block(name, body)
    pattern = re.compile(
        rf"{re.escape(_start_marker(name))}.*?{re.escape(_end_marker(name))}",
        flags=re.DOTALL,
    )
    if pattern.search(document):
        return pattern.sub(block_text, document, count=1)

    suffix = "\n\n" if document.rstrip() else ""
    return f"{document.rstrip()}{suffix}{block_text}\n"


def merge_managed_blocks(document: str, blocks: dict[str, str]) -> str:
    merged = document
    for block_name in MANAGED_BLOCKS:
        if block_name in blocks:
            merged = replace_or_append_block(merged, name=block_name, body=blocks[block_name])
    return merged
