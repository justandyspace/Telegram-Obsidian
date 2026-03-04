"""Telegram long-polling router and ingest bridge."""

from __future__ import annotations

from datetime import timezone

from aiogram import F, Router
from aiogram.types import Message

from src.bot.auth import is_authorized_user
from src.bot.commands import build_command_router
from src.infra.logging import get_logger
from src.pipeline.ingest import IngestRequest
from src.pipeline.jobs import JobService

LOGGER = get_logger(__name__)


def build_router(*, job_service: JobService, allowed_user_id: int, store) -> Router:
    router = Router(name="telegram")
    router.include_router(build_command_router(store, allowed_user_id))

    @router.message(F.text | F.caption)
    async def intake_handler(message: Message) -> None:
        from_user = message.from_user.id if message.from_user else None
        if not is_authorized_user(incoming_user_id=from_user, allowed_user_id=allowed_user_id):
            LOGGER.warning("Rejected unauthorized message: user_id=%s", from_user)
            if message.chat.type == "private":
                await message.answer("Unauthorized")
            return

        raw_text = (message.text or message.caption or "").strip()
        if not raw_text:
            await message.answer("Send text or a link with optional hashtags.")
            return

        if raw_text.startswith("/"):
            return

        message_dt = message.date
        if message_dt.tzinfo is None:
            message_dt = message_dt.replace(tzinfo=timezone.utc)

        ingest_request = IngestRequest(
            user_id=from_user,
            chat_id=message.chat.id,
            message_id=message.message_id,
            message_datetime=message_dt,
            raw_text=raw_text,
        )

        result = job_service.submit(ingest_request)
        if result.is_new:
            await message.answer(
                f"Accepted. job_id={result.job_id[:10]} action={','.join(sorted(result.actions))}"
            )
            return

        await message.answer(
            f"Duplicate skipped. existing_job_id={result.job_id[:10]} status={result.status}"
        )

    return router
