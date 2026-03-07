"""Obsidian managed-block writer."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from src.infra.storage import StateStore
from src.infra.tenancy import tenant_vault_path
from src.obsidian.block_merge import merge_managed_blocks
from src.obsidian.couchdb_bridge import CouchDBBridge
from src.obsidian.note_schema import NotePayload, render_meta
from src.obsidian.vault_router import deterministic_file_name
from src.pipeline.normalize import short_summary


class ObsidianNoteWriter:
    def __init__(self, vault_path: Path, store: StateStore, *, multi_tenant: bool) -> None:
        self._vault_path = vault_path
        self._store = store
        self._multi_tenant = multi_tenant

        # Initialize CouchDB bridge if configured
        self._couchdb: CouchDBBridge | None = None
        cdb_user = os.getenv("COUCHDB_USER")
        cdb_pass = os.getenv("COUCHDB_PASSWORD")
        cdb_db = os.getenv("COUCHDB_DATABASE", "obsidian")
        cdb_url = os.getenv("COUCHDB_URL", "http://couchdb:5984")
        if cdb_user and cdb_pass:
            self._couchdb = CouchDBBridge(
                url=cdb_url,
                user=cdb_user,
                password=cdb_pass,
                db_name=cdb_db,
            )

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
            forward_source=payload["source"].get("forward_source"),
        )

        actions = set(payload["actions"])
        blocks = {
            "BOT_META": render_meta(note_payload),
            "BOT_LINKS": self._render_links(
                payload=payload,
                resolved_vault=resolved_vault,
                current_file_name=file_name,
            ),
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
            
        if "translate" in actions and payload.get("translation"):
            blocks["BOT_TRANSLATION"] = payload["translation"]

        merged = merge_managed_blocks(document, blocks)
        note_path.write_text(merged, encoding="utf-8")

        # Sync to CouchDB if bridge is available
        if self._couchdb:
            self._couchdb.push_note(file_name, merged)

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
            "<!-- BOT_META:START -->\n"
            "pending\n"
            "<!-- BOT_META:END -->\n\n"
            f"# {title}\n\n"
            "<!-- BOT_SUMMARY:START -->\n"
            "pending\n"
            "<!-- BOT_SUMMARY:END -->\n\n"
            "<!-- BOT_TASKS:START -->\n"
            "pending\n"
            "<!-- BOT_TASKS:END -->\n\n"
            "<!-- BOT_TRANSLATION:START -->\n"
            "pending\n"
            "<!-- BOT_TRANSLATION:END -->\n\n"
            "--- \n\n"
            "## 📝 User Content\n"
            f"{content}\n\n"
            "--- \n\n"
            "<!-- BOT_LINKS:START -->\n"
            "pending\n"
            "<!-- BOT_LINKS:END -->\n"
        )

    def _render_summary(self, payload: dict, actions: set[str]) -> str:
        ai_summary = payload.get("ai_summary")
        if not ai_summary:
            source_text = payload.get("enriched_text") or payload["content"]
            ai_summary = short_summary(source_text, max_chars=700)

        return (
            "> [!abstract] 🤖 AI Summary\n"
            f"> {ai_summary.strip().replace(chr(10), chr(10) + '> ')}\n"
        )

    def _render_tasks(self, payload: dict) -> str:
        extracted_tasks = []
        for line in str(payload.get("content", "")).splitlines():
            stripped = line.strip()
            if stripped.startswith("- [ ]") or stripped.startswith("- [x]") or stripped.startswith("* [ ]"):
                extracted_tasks.append(stripped.replace("* [ ]", "- [ ]"))

        if not extracted_tasks:
            title = payload.get("title") or "captured note"
            extracted_tasks = [
                f"- [ ] Review: {title}",
                "- [ ] Decide next action",
                "- [ ] Archive or link related notes",
            ]

        task_lines = "\n".join(extracted_tasks[:20])
        return (
            "> [!todo] ✅ Tasks\n"
            f"{task_lines.replace('- [', '> - [')}\n"
        )

    def _render_links(self, payload: dict, resolved_vault: Path, current_file_name: str) -> str:
        source = payload.get("source", {})
        lines = [
            (
                "- 📱 telegram: "
                f"chat_id={source.get('chat_id')} "
                f"message_id={source.get('message_id')}"
            )
        ]
        for attachment in payload.get("cloud_attachments", []):
            name = str(attachment.get("name") or "attachment")
            web_link = str(attachment.get("web_view_link") or "").strip()
            if web_link:
                lines.append(f"- ☁️ drive: {name} :: {web_link}")
        for item in payload.get("parsed_items", []):
            parser_name = item.get("parser", "unknown")
            status = item.get("status", "unknown")
            title = item.get("title", "").strip() or "untitled"
            source_url = self._sanitize_link(item.get("source_url", ""))
            lines.append(f"- [{parser_name}/{status}] {title} :: {source_url}")
            for extra_link in item.get("links", []):
                safe_link = self._sanitize_link(extra_link)
                if safe_link and safe_link != source_url:
                    label = "drive" if "drive.google.com" in urlparse(safe_link).netloc.lower() else "mirror"
                    lines.append(f"- 🔗 {label}: {safe_link}")
            if item.get("error"):
                lines.append(f"- ❌ parser_error: {item['error']}")

        related = self._discover_related_notes(
            resolved_vault=resolved_vault,
            current_file_name=current_file_name,
            payload=payload,
        )

        related_block = ""
        if related:
            related_block = "\n\n### 🔗 Related notes (auto)\n"
            related_block += "\n".join(f"- [[{note_stem}]]" for note_stem in related)

        link_lines = "\n".join(lines)
        return (
            "> [!info] 🔗 Context & Links\n"
            f"{link_lines.replace('- ', '> - ')}"
            f"{related_block.replace(chr(10), chr(10) + '> ')}\n"
        )

    def _sanitize_link(self, link: str) -> str:
        value = str(link or "").strip()
        if "api.telegram.org/file/bot" not in value:
            return value
        file_name = Path(urlparse(value).path).name or "telegram-media"
        return f"telegram://redacted/{file_name}"

    def _discover_related_notes(
        self,
        *,
        resolved_vault: Path,
        current_file_name: str,
        payload: dict,
        max_related: int = 8,
    ) -> list[str]:
        content = str(payload.get("content", ""))
        title = str(payload.get("title", ""))
        semantic_hashtags = [str(tag) for tag in payload.get("semantic_hashtags", [])]
        parsed_titles = [
            str(item.get("title", ""))
            for item in payload.get("parsed_items", [])
            if str(item.get("title", "")).strip()
        ]
        raw_candidates = " ".join([title, content, *semantic_hashtags, *parsed_titles]).lower()
        query_tokens = self._extract_link_tokens(raw_candidates)
        if not query_tokens:
            return []

        results: list[tuple[int, str]] = []
        for note_path in resolved_vault.rglob("*.md"):
            if note_path.name == current_file_name:
                continue
            note_stem = note_path.stem
            note_label = self._humanize_note_stem(note_stem).lower()
            note_tokens = self._extract_link_tokens(note_label)
            if not note_tokens:
                continue
            overlap = len(query_tokens.intersection(note_tokens))
            if overlap > 0:
                results.append((overlap, note_stem))

        results.sort(key=lambda item: (-item[0], item[1].lower()))
        return [note_stem for _, note_stem in results[:max_related]]

    def _extract_link_tokens(self, text: str) -> set[str]:
        return {token for token in re.findall(r"[a-z0-9]{4,}", text.lower())}

    def _humanize_note_stem(self, note_stem: str) -> str:
        # Normalize deterministic names like "20260305-1200 - title (AB12CD34)".
        value = re.sub(r"^\d{8}-\d{4}\s*-\s*", "", note_stem)
        value = re.sub(r"\s*\([A-Z0-9]{8}\)$", "", value)
        return value.strip() or note_stem
