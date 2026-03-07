"""Obsidian note schema primitives."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class NotePayload:
    note_id: str
    file_name: str
    title: str
    content: str
    hashtags: list[str]
    actions: list[str]
    source_chat_id: int
    source_message_id: int
    source_user_id: int
    source_datetime: datetime
    forward_source: str | None = None


def render_meta(payload: NotePayload) -> str:
    tags = "[" + ", ".join(payload.hashtags) + "]" if payload.hashtags else "[]"
    actions = "[" + ", ".join(payload.actions) + "]" if payload.actions else "[]"
    meta_str = (
        "---\n"
        f"id: {payload.note_id}\n"
        f"chat_id: {payload.source_chat_id}\n"
        f"message_id: {payload.source_message_id}\n"
        f"user_id: {payload.source_user_id}\n"
        f"date: {payload.source_datetime.isoformat()}\n"
    )
    if payload.forward_source:
        meta_str += f"forward: \"{payload.forward_source}\"\n"
    meta_str += f"actions: {actions}\n"
    meta_str += f"tags: {tags}\n"
    meta_str += "---"
    return meta_str
