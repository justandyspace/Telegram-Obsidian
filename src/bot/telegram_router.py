"""Telegram long-polling router and ingest bridge."""

from __future__ import annotations

from datetime import UTC

from aiogram import F, Router
from aiogram.types import Message

from src.bot.auth import build_tenant_context, is_authorized_user
from src.bot.commands import build_command_router
from src.infra.logging import get_logger
from src.pipeline.ingest import IngestRequest
from src.pipeline.jobs import JobService
from src.rag.retriever import RagManager

LOGGER = get_logger(__name__)


def build_router(
    *,
    job_service: JobService,
    allowed_user_ids: set[int],
    store,
    vault_path,
    rag_manager: RagManager,
) -> Router:
    router = Router(name="telegram")
    router.include_router(build_command_router(store, allowed_user_ids, vault_path, rag_manager))

    @router.message((F.text | F.caption) & ~(F.text.startswith("/") | F.caption.startswith("/")))
    async def intake_handler(message: Message) -> None:
        from_user = message.from_user.id if message.from_user else None
        if not is_authorized_user(incoming_user_id=from_user, allowed_user_ids=allowed_user_ids):
            LOGGER.warning("Rejected unauthorized message: user_id=%s", from_user)
            if message.chat.type == "private":
                await message.answer("Access denied: this Telegram user is not in allowlist.")
            return

        raw_text = (message.text or message.caption or "").strip()
        if not raw_text:
            await message.answer("Send text or a link with optional hashtags.")
            return

        message_dt = message.date
        if message_dt.tzinfo is None:
            message_dt = message_dt.replace(tzinfo=UTC)

        if from_user is None:
            await message.answer("Unsupported message source.")
            return
        tenant = build_tenant_context(from_user)

        ingest_request = IngestRequest(
            tenant_id=tenant.tenant_id,
            user_id=tenant.user_id,
            chat_id=message.chat.id,
            message_id=message.message_id,
            message_datetime=message_dt,
            raw_text=raw_text,
        )

        result = job_service.submit(ingest_request)
        if result.is_new:
            await message.answer(
                "Accepted.\n"
                f"Job: {result.job_id[:10]}\n"
                f"Tenant: {tenant.tenant_id}\n"
                f"Actions: {', '.join(sorted(result.actions))}\n"
                "Track with: /status"
            )
            return

        await message.answer(
            "Duplicate skipped.\n"
            f"Existing job: {result.job_id[:10]}\n"
            f"Status: {result.status}"
        )

    return router
