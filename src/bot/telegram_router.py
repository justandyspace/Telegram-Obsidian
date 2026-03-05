"""Telegram long-polling router and ingest bridge."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC
from pathlib import Path
from typing import Any
from urllib.parse import quote

from aiogram import Bot, F, Router
from aiogram.types import Message

from src.bot.auth import build_tenant_context, is_authorized_user
from src.bot.commands import build_command_router
from src.infra.logging import get_logger
from src.pipeline.ai_service import AIService
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
    ai_service: AIService,
) -> Router:
    router = Router(name="telegram")
    router.include_router(build_command_router(store, allowed_user_ids, vault_path, rag_manager))

    async def _submit_media_ingest(message: Message, *, from_user: int) -> None:
        media_url = await _extract_telegram_media_url(message)
        if not media_url:
            await message.answer(
                "❌ <b>Ошибка чтения аудио</b>\n\n"
                "Не удалось получить файл из Telegram. Попробуй отправить голосовое ещё раз.",
                parse_mode="HTML",
            )
            return

        message_dt = message.date
        if message_dt.tzinfo is None:
            message_dt = message_dt.replace(tzinfo=UTC)

        tenant = build_tenant_context(from_user)
        caption = (message.caption or "").strip()
        raw_text = _build_voice_ingest_text(caption=caption, media_url=media_url)
        forward_source = _extract_forward_source(message)

        ingest_request = IngestRequest(
            tenant_id=tenant.tenant_id,
            user_id=tenant.user_id,
            chat_id=message.chat.id,
            message_id=message.message_id,
            message_datetime=message_dt,
            raw_text=raw_text,
            forward_source=forward_source,
        )

        result = job_service.submit(ingest_request)
        if result.is_new:
            await message.answer(
                "🎙 <b>Принято!</b>\n\n"
                "Понял, сохраняю голосовое сообщение.\n"
                "Начинаю его транскрипцию.",
                parse_mode="HTML",
            )
            asyncio.create_task(
                _watch_job_and_notify(
                    bot=message.bot,
                    store=store,
                    tenant_id=tenant.tenant_id,
                    job_id=result.job_id,
                    chat_id=message.chat.id,
                )
            )
            return

        await message.answer("Я уже обрабатываю эту информацию. Дубликат пропущен.")

    @router.message((F.text | F.caption) & ~(F.text.startswith("/") | F.caption.startswith("/")))
    async def intake_handler(message: Message) -> None:
        from_user = message.from_user.id if message.from_user else None
        if not is_authorized_user(incoming_user_id=from_user, allowed_user_ids=allowed_user_ids):
            LOGGER.warning("Rejected unauthorized message: user_id=%s", from_user)
            if message.chat.type == "private":
                await message.answer("Access denied: this Telegram user is not in allowlist.")
            return

        if from_user is None:
            await message.answer("Unsupported message source.")
            return

        if _is_transcribable_media_message(message):
            await _submit_media_ingest(message, from_user=from_user)
            return

        raw_text = (message.text or message.caption or "").strip()
        if not raw_text:
            await message.answer("Send text or a link with optional hashtags.")
            return

        message_dt = message.date
        if message_dt.tzinfo is None:
            message_dt = message_dt.replace(tzinfo=UTC)

        tenant = build_tenant_context(from_user)
        forward_source = _extract_forward_source(message)

        ingest_request = IngestRequest(
            tenant_id=tenant.tenant_id,
            user_id=tenant.user_id,
            chat_id=message.chat.id,
            message_id=message.message_id,
            message_datetime=message_dt,
            raw_text=raw_text,
            forward_source=forward_source,
        )

        result = job_service.submit(ingest_request)
        if result.is_new:
            context = f"Действия: {', '.join(sorted(result.actions))}"
            reply_text = await ai_service.generate_reply(raw_text, context_info=context)
            await message.answer(reply_text)
            return

        await message.answer("Я уже обрабатываю эту информацию. Дубликат пропущен.")

    @router.message(F.voice | F.audio | F.video_note | F.video | F.document)
    async def media_intake_handler(message: Message) -> None:
        if not _is_transcribable_media_message(message):
            return

        from_user = message.from_user.id if message.from_user else None
        if not is_authorized_user(incoming_user_id=from_user, allowed_user_ids=allowed_user_ids):
            LOGGER.warning("Rejected unauthorized media message: user_id=%s", from_user)
            if message.chat.type == "private":
                await message.answer("Access denied: this Telegram user is not in allowlist.")
            return

        if from_user is None:
            await message.answer("Unsupported message source.")
            return

        await _submit_media_ingest(message, from_user=from_user)

    return router


async def _extract_telegram_media_url(message: Message) -> str:
    media, mime_hint = _extract_transcribable_media_and_hint(message)
    if media is None:
        return ""
    if message.bot is None:
        return ""
    try:
        file = await message.bot.get_file(media.file_id)
    except Exception:  # noqa: BLE001
        return ""
    file_path = str(getattr(file, "file_path", "") or "")
    if not file_path:
        return ""
    media_url = f"https://api.telegram.org/file/bot{message.bot.token}/{file_path}"
    if mime_hint:
        encoded_mime = quote(mime_hint, safe="")
        return f"{media_url}#tgmime={encoded_mime}"
    return media_url


def _is_transcribable_media_message(message: Message) -> bool:
    media, _ = _extract_transcribable_media_and_hint(message)
    return media is not None


def _extract_transcribable_media_and_hint(message: Message) -> tuple[Any | None, str]:
    if message.voice is not None:
        return message.voice, ""
    if message.audio is not None:
        mime = str(getattr(message.audio, "mime_type", "") or "").strip().lower()
        return message.audio, mime if _is_media_mime_hint(mime) else ""
    if message.video_note is not None:
        return message.video_note, "video/mp4"
    if message.video is not None:
        mime = str(getattr(message.video, "mime_type", "") or "").strip().lower()
        return message.video, mime if _is_media_mime_hint(mime) else "video/mp4"
    document = getattr(message, "document", None)
    if document is not None:
        mime = str(getattr(document, "mime_type", "") or "").strip().lower()
        if _is_media_mime_hint(mime):
            return document, mime
    return None, ""


def _is_media_mime_hint(mime_type: str) -> bool:
    return mime_type.startswith("audio/") or mime_type.startswith("video/")


async def _watch_job_and_notify(
    *,
    bot: Bot,
    store,
    tenant_id: str,
    job_id: str,
    chat_id: int,
    timeout_seconds: int = 180,
    poll_seconds: float = 2.0,
) -> None:
    elapsed = 0.0
    while elapsed < timeout_seconds:
        try:
            await bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:  # noqa: BLE001
            pass

        status_row = store.get_job_status(job_id, tenant_id=tenant_id)
        if status_row is None:
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    "⚠️ <b>Статус недоступен</b>\n\n"
                    "Не смог найти задачу транскрипции. Попробуй отправить голосовое ещё раз."
                ),
                parse_mode="HTML",
            )
            return

        status = str(status_row.get("status") or "")
        if status == "done":
            note_path = str(status_row.get("note_path") or "")
            if note_path:
                note_name = Path(note_path).name
                display_name = _display_note_name(note_name)
                await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        "✅ <b>Готово!</b>\n\n"
                        "Транскрипция завершена и сохранена в Obsidian.\n"
                        f"📝 <b>Заметка:</b> <code>{display_name}</code>"
                    ),
                    parse_mode="HTML",
                )
            else:
                await bot.send_message(
                    chat_id=chat_id,
                    text="✅ <b>Готово!</b>\n\nТранскрипция завершена и сохранена в Obsidian.",
                    parse_mode="HTML",
                )
            return
        if status == "failed":
            error = str(status_row.get("error") or "unknown error")
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    "❌ <b>Транскрипция не завершена</b>\n\n"
                    f"Причина: <code>{error[:300]}</code>"
                ),
                parse_mode="HTML",
            )
            return

        await asyncio.sleep(poll_seconds)
        elapsed += poll_seconds

    await bot.send_message(
        chat_id=chat_id,
        text=(
            "⏳ <b>Все еще обрабатываю голосовое</b>\n\n"
            "Задача пока в очереди. Проверь <code>/status</code> чуть позже."
        ),
        parse_mode="HTML",
    )


def _build_voice_ingest_text(*, caption: str, media_url: str) -> str:
    lines = ["Voice message transcript from Telegram audio #voice #save"]
    if caption:
        lines.append(f"Context: {caption}")
    lines.append(f"Media URL: {media_url}")
    return "\n".join(lines)


def _display_note_name(file_name: str) -> str:
    stem = Path(file_name).stem
    match = re.match(r"^\d{8}-\d{4}\s*-\s*(.+)\s+\([A-Z0-9]{8}\)$", stem)
    if match:
        return match.group(1).strip()[:80]
    return stem[:80]

def _extract_forward_source(message: Message) -> str | None:
    if not hasattr(message, "forward_origin") or not message.forward_origin:
        return None
    origin = message.forward_origin
    if hasattr(origin, "chat") and origin.chat:
        return origin.chat.title or origin.chat.username or str(origin.chat.id)
    if hasattr(origin, "sender_user_name") and origin.sender_user_name:
        return origin.sender_user_name
    if hasattr(origin, "sender_user") and origin.sender_user:
        return origin.sender_user.full_name or origin.sender_user.username
    return "Unknown Forward"
