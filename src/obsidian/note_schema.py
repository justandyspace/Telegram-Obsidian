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
    tags = ", ".join(f"#{tag}" for tag in payload.hashtags) if payload.hashtags else "none"
    actions = ", ".join(f"#{action}" for action in payload.actions)
    meta_str = (
        f"note_id: {payload.note_id}\n"
        f"source_chat_id: {payload.source_chat_id}\n"
        f"source_message_id: {payload.source_message_id}\n"
        f"source_user_id: {payload.source_user_id}\n"
        f"source_datetime: {payload.source_datetime.isoformat()}\n"
    )
    if payload.forward_source:
        meta_str += f"forward_source: {payload.forward_source}\n"
    meta_str += f"actions: {actions}\n"
    meta_str += f"tags: {tags}"
    return meta_str
