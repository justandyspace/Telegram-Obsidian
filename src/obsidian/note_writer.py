"""Obsidian managed-block writer."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.infra.storage import StateStore
from src.obsidian.block_merge import merge_managed_blocks
from src.obsidian.note_schema import NotePayload, render_meta
from src.obsidian.vault_router import deterministic_file_name
from src.pipeline.normalize import short_summary


class ObsidianNoteWriter:
    def __init__(self, vault_path: Path, store: StateStore) -> None:
        self._vault_path = vault_path
        self._store = store

    def write(self, *, job_id: str, payload: dict) -> str:
        self._vault_path.mkdir(parents=True, exist_ok=True)

        content_fingerprint = payload["content_fingerprint"]
        note_id = content_fingerprint[:8].upper()

        existing = self._store.get_note(content_fingerprint)
        source_datetime = datetime.fromisoformat(payload["source"]["message_datetime"])

        if existing:
            file_name = existing["file_name"]
        else:
            file_name = deterministic_file_name(
                created_at=source_datetime,
                title=payload["title"],
                note_id=note_id,
            )

        note_path = self._vault_path / file_name
        if note_path.exists():
            document = note_path.read_text(encoding="utf-8")
        else:
            document = self._bootstrap_document(payload["title"], payload["content"])

        note_payload = NotePayload(
            note_id=note_id,
            file_name=file_name,
            title=payload["title"],
            content=payload["content"],
            hashtags=payload["hashtags"],
            actions=payload["actions"],
            source_chat_id=int(payload["source"]["chat_id"]),
            source_message_id=int(payload["source"]["message_id"]),
            source_user_id=int(payload["source"]["user_id"]),
            source_datetime=source_datetime,
        )

        blocks = {
            "BOT_META": render_meta(note_payload),
            "BOT_TASKS": "- no auto tasks generated in phase 1",
            "BOT_LINKS": "- source: telegram message",
        }

        should_update_summary = (not existing) or ("resummarize" in payload["actions"])
        if should_update_summary:
            blocks["BOT_SUMMARY"] = short_summary(payload["content"])

        merged = merge_managed_blocks(document, blocks)
        note_path.write_text(merged, encoding="utf-8")

        self._store.upsert_note(
            content_fingerprint=content_fingerprint,
            note_id=note_id,
            file_name=file_name,
            job_id=job_id,
        )

        return str(note_path)

    def _bootstrap_document(self, title: str, content: str) -> str:
        return (
            f"# {title}\n\n"
            "<!-- BOT_META:START -->\n"
            "pending\n"
            "<!-- BOT_META:END -->\n\n"
            "<!-- BOT_SUMMARY:START -->\n"
            "pending\n"
            "<!-- BOT_SUMMARY:END -->\n\n"
            "<!-- BOT_TASKS:START -->\n"
            "pending\n"
            "<!-- BOT_TASKS:END -->\n\n"
            "<!-- BOT_LINKS:START -->\n"
            "pending\n"
            "<!-- BOT_LINKS:END -->\n\n"
            "## User Content\n"
            f"{content}\n"
        )
