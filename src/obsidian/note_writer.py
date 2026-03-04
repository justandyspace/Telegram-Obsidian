"""Obsidian managed-block writer."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.infra.storage import StateStore
from src.infra.tenancy import tenant_vault_path
from src.obsidian.block_merge import merge_managed_blocks
from src.obsidian.note_schema import NotePayload, render_meta
from src.obsidian.vault_router import deterministic_file_name
from src.pipeline.normalize import short_summary


class ObsidianNoteWriter:
    def __init__(self, vault_path: Path, store: StateStore, *, multi_tenant: bool) -> None:
        self._vault_path = vault_path
        self._store = store
        self._multi_tenant = multi_tenant

    def write(self, *, job_id: str, payload: dict) -> str:
        tenant_id = str(payload.get("tenant_id") or "legacy")
        resolved_vault = tenant_vault_path(
            self._vault_path,
            tenant_id,
            multi_tenant=self._multi_tenant,
        )
        resolved_vault.mkdir(parents=True, exist_ok=True)

        content_fingerprint = payload["content_fingerprint"]
        note_id = content_fingerprint[:8].upper()

        existing = self._store.get_note(content_fingerprint, tenant_id)
        source_datetime = datetime.fromisoformat(payload["source"]["message_datetime"])

        if existing:
            file_name = existing["file_name"]
        else:
            file_name = deterministic_file_name(
                created_at=source_datetime,
                title=payload["title"],
                note_id=note_id,
            )

        note_path = resolved_vault / file_name
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

        actions = set(payload["actions"])
        blocks = {
            "BOT_META": render_meta(note_payload),
            "BOT_LINKS": self._render_links(payload),
        }

        if (not existing) or ("task" in actions):
            blocks["BOT_TASKS"] = self._render_tasks(payload)

        should_update_summary = (
            (not existing)
            or ("summary" in actions)
            or ("resummarize" in actions)
            or ("translate" in actions)
        )
        if should_update_summary:
            blocks["BOT_SUMMARY"] = self._render_summary(payload, actions)

        merged = merge_managed_blocks(document, blocks)
        note_path.write_text(merged, encoding="utf-8")

        self._store.upsert_note(
            content_fingerprint=content_fingerprint,
            tenant_id=tenant_id,
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

    def _render_summary(self, payload: dict, actions: set[str]) -> str:
        source_text = payload.get("enriched_text") or payload["content"]
        summary = short_summary(source_text, max_chars=700)
        if "translate" in actions:
            summary = "Translation requested (#translate). Original language preserved in Phase 2.\n\n" + summary
        return summary

    def _render_tasks(self, payload: dict) -> str:
        extracted_tasks = []
        for line in str(payload.get("content", "")).splitlines():
            stripped = line.strip()
            if stripped.startswith("- [ ]") or stripped.startswith("- [x]") or stripped.startswith("* [ ]"):
                extracted_tasks.append(stripped.replace("* [ ]", "- [ ]"))

        if extracted_tasks:
            return "\n".join(extracted_tasks[:20])

        title = payload.get("title") or "captured note"
        return "\n".join(
            [
                f"- [ ] Review: {title}",
                "- [ ] Decide next action",
                "- [ ] Archive or link related notes",
            ]
        )

    def _render_links(self, payload: dict) -> str:
        source = payload.get("source", {})
        lines = [
            (
                "- telegram: "
                f"chat_id={source.get('chat_id')} "
                f"message_id={source.get('message_id')}"
            )
        ]
        for item in payload.get("parsed_items", []):
            parser_name = item.get("parser", "unknown")
            status = item.get("status", "unknown")
            title = item.get("title", "").strip() or "untitled"
            source_url = item.get("source_url", "")
            lines.append(f"- [{parser_name}/{status}] {title} :: {source_url}")
            for extra_link in item.get("links", []):
                if extra_link and extra_link != source_url:
                    lines.append(f"- mirror: {extra_link}")
            if item.get("error"):
                lines.append(f"- parser_error: {item['error']}")
        return "\n".join(lines)
