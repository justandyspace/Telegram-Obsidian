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


def render_meta(payload: NotePayload) -> str:
    tags = ", ".join(f"#{tag}" for tag in payload.hashtags) if payload.hashtags else "none"
    actions = ", ".join(f"#{action}" for action in payload.actions)
    return (
        f"note_id: {payload.note_id}\n"
        f"source_chat_id: {payload.source_chat_id}\n"
        f"source_message_id: {payload.source_message_id}\n"
        f"source_user_id: {payload.source_user_id}\n"
        f"source_datetime: {payload.source_datetime.isoformat()}\n"
        f"actions: {actions}\n"
        f"tags: {tags}"
    )
