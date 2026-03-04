"""Telegram command handlers."""

from __future__ import annotations

from pathlib import Path

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.bot.auth import build_tenant_context, is_authorized_user
from src.infra.storage import StateStore
from src.obsidian.search import find_notes, latest_notes
from src.rag.retriever import RagManager


def build_command_router(
    store: StateStore,
    allowed_user_ids: set[int],
    vault_path: Path,  # kept for API compatibility with existing wiring
    rag_manager: RagManager,
) -> Router:
    router = Router(name="commands")

    def _authorized(message: Message) -> bool:
        incoming = message.from_user.id if message.from_user else None
        return is_authorized_user(
            incoming_user_id=incoming,
            allowed_user_ids=allowed_user_ids,
        )

    def _tenant_id(message: Message) -> str:
        if message.from_user is None:
            return "legacy"
        return build_tenant_context(message.from_user.id).tenant_id

    @router.message(Command("start"))
    async def start_handler(message: Message) -> None:
        if not _authorized(message):
            await message.answer("Access denied: this Telegram user is not in allowlist.")
            return
        await message.answer(
            "Bot is active and authorized.\n\n"
            "Send any text or URL with hashtags:\n"
            "- #save\n"
            "- #summary\n"
            "- #task\n"
            "- #resummarize\n"
            "- #translate\n\n"
            "Commands:\n"
            "- /status\n"
            "- /find <query>\n"
            "- /summary <question>\n"
            "- /retry <job_id_or_prefix>"
        )

    @router.message(Command("status"))
    async def status_handler(message: Message) -> None:
        if not _authorized(message):
            await message.answer("Access denied: this Telegram user is not in allowlist.")
            return

        tenant_id = _tenant_id(message)
        counts = store.status_counts(tenant_id=tenant_id)
        failures = store.recent_failures(limit=3, tenant_id=tenant_id)
        recent = store.recent_jobs(limit=3, tenant_id=tenant_id)
        rag = rag_manager.for_tenant(tenant_id)
        integrity_ok, integrity_details = store.integrity_check()

        lines = [f"Status: {tenant_id}", ""]
        if counts:
            lines.append("Queue:")
            for key, value in sorted(counts.items()):
                lines.append(f"- {key}: {value}")
        else:
            lines.append("Queue:")
            lines.append("- empty")

        if recent:
            lines.append("")
            lines.append("Recent jobs:")
            for item in recent:
                lines.append(
                    f"- {_short_job(item['job_id'])}: {item['status']} "
                    f"(attempts {item['attempts']}/{item['max_attempts']})"
                )

        if failures:
            lines.append("")
            lines.append("Recent errors:")
            for item in failures:
                error_text = (item.get("error") or "no error text").replace("\n", " ")
                lines.append(f"- {_short_job(item['job_id'])} [{item['status']}] {error_text[:180]}")

        rag_stats = rag.stats()
        lines.append("")
        lines.append("RAG:")
        lines.append(f"- provider: {rag_stats['provider']}")
        lines.append(f"- documents: {rag_stats['documents']}")
        lines.append(f"- chunks: {rag_stats['chunks']}")
        lines.append("")
        lines.append("Storage:")
        lines.append(f"- schema_version: {store.schema_version()}")
        lines.append(f"- integrity: {'ok' if integrity_ok else integrity_details}")

        await message.answer("\n".join(lines))

    @router.message(Command("find"))
    async def find_handler(message: Message) -> None:
        if not _authorized(message):
            await message.answer("Access denied: this Telegram user is not in allowlist.")
            return

        query = _extract_args(message)
        if not query:
            await message.answer("Usage:\n/find <query>")
            return

        tenant_id = _tenant_id(message)
        rag = rag_manager.for_tenant(tenant_id)
        hits = rag.find(query, top_k=5)
        if hits:
            lines = [f"Find: {query}", "", "Semantic results:"]
            for idx, hit in enumerate(hits, start=1):
                snippet = " ".join(hit.chunk_text.split())[:220]
                lines.append(f"{idx}. {hit.file_name} (score {hit.score:.3f})")
                lines.append(f"   {snippet}")
            await message.answer("\n".join(lines))
            return

        matches = find_notes(rag.vault_path, query, limit=5)
        if not matches:
            await message.answer("No matching notes found.")
            return

        lines = [f"Find: {query}", "", "Keyword fallback results:"]
        for idx, item in enumerate(matches, start=1):
            lines.append(f"{idx}. {item['file_name']}")
            lines.append(f"   {item['snippet']}")
        await message.answer("\n".join(lines))

    @router.message(Command("summary"))
    async def summary_handler(message: Message) -> None:
        if not _authorized(message):
            await message.answer("Access denied: this Telegram user is not in allowlist.")
            return

        tenant_id = _tenant_id(message)
        rag = rag_manager.for_tenant(tenant_id)
        query = _extract_args(message)
        if query:
            answer = rag.answer(query, top_k=4)
            if not answer.sources:
                await message.answer(f"No notes found for summary query: '{query}'")
                return
            lines = [f"Summary ({answer.mode})", "", answer.answer, "", "Sources:"]
            for idx, src in enumerate(answer.sources, start=1):
                lines.append(f"{idx}. {src.file_name} (score {src.score:.3f})")
            await message.answer("\n".join(lines))
            return

        latest = latest_notes(rag.vault_path, limit=3)
        if not latest:
            await message.answer("No notes available for summary.")
            return
        lines = ["Summary of latest notes:"]
        for idx, item in enumerate(latest, start=1):
            lines.append(f"{idx}. {item['file_name']}")
            lines.append(f"   {item['snippet']}")
        await message.answer("\n".join(lines))

    @router.message(Command("retry"))
    async def retry_handler(message: Message) -> None:
        if not _authorized(message):
            await message.answer("Access denied: this Telegram user is not in allowlist.")
            return

        job_ref = _extract_args(message)
        if not job_ref:
            await message.answer("Usage:\n/retry <job_id_or_prefix>")
            return

        tenant_id = _tenant_id(message)
        ok, details = store.retry_job(job_ref, tenant_id=tenant_id)
        if ok:
            await message.answer(f"Retry scheduled.\nJob: {_short_job(details)}")
        else:
            await message.answer(f"Retry rejected.\nReason: {details}")

    return router


def _extract_args(message: Message) -> str:
    text = (message.text or "").strip()
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _short_job(job_id: str) -> str:
    return str(job_id)[:10]
