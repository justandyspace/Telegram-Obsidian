"""Telegram long-polling router and ingest bridge."""

from __future__ import annotations

import asyncio
from datetime import UTC
from pathlib import Path
from typing import Any
from urllib.parse import quote

from aiogram import Bot, F, Router
from aiogram.types import Message

from src.bot.auth import build_tenant_context, is_authorized_user
from src.bot.commands import build_command_router
from src.bot.keyboards import build_quick_actions_keyboard
from src.infra.logging import get_logger
from src.infra.telemetry import track_event
from src.obsidian.display import humanize_note_label
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
    mini_app_base_url: str = "",
    **_compat_kwargs,
) -> Router:
    router = Router(name="telegram")
    router.include_router(
        build_command_router(
            store,
            allowed_user_ids,
            rag_manager,
            mini_app_base_url=mini_app_base_url,
        )
    )

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
        track_event(
            "capture_voice_submitted",
            tenant_id=tenant.tenant_id,
            user_id=tenant.user_id,
            is_new=result.is_new,
            action_count=len(result.actions),
        )
        if result.is_new:
            bot = message.bot
            await message.answer(
                "🎙 <b>Принято!</b>\n\n"
                "Понял, сохраняю голосовое сообщение.\n"
                "Начинаю его транскрипцию.",
                parse_mode="HTML",
                reply_markup=build_quick_actions_keyboard(mini_app_base_url),
            )
            if bot is not None:
                asyncio.create_task(
                    _watch_job_and_notify(
                        bot=bot,
                        store=store,
                        tenant_id=tenant.tenant_id,
                        job_id=result.job_id,
                        chat_id=message.chat.id,
                        base_vault_path=Path(vault_path),
                        mini_app_base_url=mini_app_base_url,
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
                await message.answer("❌ Доступ закрыт. Этот Telegram-аккаунт не добавлен в список разрешённых.")
            return

        if from_user is None:
            await message.answer("⚠️ Не удалось определить источник сообщения.")
            return

        if _is_transcribable_media_message(message):
            await _submit_media_ingest(message, from_user=from_user)
            return

        raw_text = (message.text or message.caption or "").strip()
        quick_action = _match_quick_action_alias(raw_text)
        if quick_action == "add":
            await message.answer(
                "➕ <b>Добавить</b>\n\n"
                "Просто отправь сюда:\n"
                "• текст или идею\n"
                "• ссылку\n"
                "• голосовое\n"
                "• фото или документ\n\n"
                "Если нужно, можешь дописать теги вроде <code>#save</code> или <code>#summary</code>.",
                parse_mode="HTML",
                reply_markup=build_quick_actions_keyboard(mini_app_base_url),
            )
            return
        if quick_action == "search":
            await message.answer(
                "🔎 <b>Поиск по базе</b>\n\n"
                "Что можно сделать:\n"
                "• <code>/find запрос</code> для быстрого поиска\n"
                "• <code>/summary вопрос</code> для ответа по базе\n"
                "• Mini App пока нет, так что полный поиск тоже временно через чат-команды",
                parse_mode="HTML",
                reply_markup=build_quick_actions_keyboard(mini_app_base_url),
            )
            return
        if quick_action == "manage":
            await message.answer(
                "⚙️ <b>Управление</b>\n\n"
                "Здесь всё служебное:\n"
                "• <code>/status</code> для состояния очереди и индекса\n"
                "• <code>/delete имя_файла.md</code> для удаления одной заметки\n"
                "• <code>/delete cancel</code> для отмены массового удаления",
                parse_mode="HTML",
                reply_markup=build_quick_actions_keyboard(mini_app_base_url),
            )
            return
        if not raw_text:
            await message.answer("Пришли текст, ссылку или заметку. Если хочешь, можешь добавить теги вроде <code>#save</code>.", parse_mode="HTML")
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
        track_event(
            "capture_text_submitted",
            tenant_id=tenant.tenant_id,
            user_id=tenant.user_id,
            is_new=result.is_new,
            action_count=len(result.actions),
        )
        if result.is_new:
            context = f"Действия: {', '.join(sorted(result.actions))}"
            reply_text = await ai_service.generate_reply(raw_text, context_info=context)
            await message.answer(
                f"{reply_text}\n\n"
                "Когда заметка будет готова, я пришлю отдельное сообщение с папкой и названием файла.",
                reply_markup=build_quick_actions_keyboard(mini_app_base_url),
            )
            bot = message.bot
            if bot is not None:
                asyncio.create_task(
                    _watch_job_and_notify(
                        bot=bot,
                        store=store,
                        tenant_id=tenant.tenant_id,
                        job_id=result.job_id,
                        chat_id=message.chat.id,
                        base_vault_path=Path(vault_path),
                        mini_app_base_url=mini_app_base_url,
                    )
                )
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
                await message.answer("❌ Доступ закрыт. Этот Telegram-аккаунт не добавлен в список разрешённых.")
            return

        if from_user is None:
            await message.answer("⚠️ Не удалось определить источник сообщения.")
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
    base_vault_path: Path | None = None,
    mini_app_base_url: str = "",
) -> None:
    quick_actions = build_quick_actions_keyboard(mini_app_base_url)
    elapsed = 0.0
    while elapsed < timeout_seconds:
        try:
            await bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:  # noqa: BLE001
            LOGGER.debug("Failed to send typing action for transcription status update", exc_info=True)

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
                folder_name, relative_note_path = _humanize_note_destination(
                    note_path=Path(note_path),
                    base_vault_path=base_vault_path,
                )
                await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        "✅ <b>Готово!</b>\n\n"
                        "Материал обработан и сохранён в Obsidian.\n"
                        f"📝 <b>Заметка:</b> <code>{display_name}</code>\n"
                        f"📁 <b>Папка:</b> <code>{folder_name}</code>\n"
                        f"📍 <b>Путь:</b> <code>{relative_note_path}</code>"
                    ),
                    parse_mode="HTML",
                    reply_markup=quick_actions,
                )
            else:
                await bot.send_message(
                    chat_id=chat_id,
                    text="✅ <b>Готово!</b>\n\nМатериал обработан и сохранён в Obsidian.",
                    parse_mode="HTML",
                    reply_markup=quick_actions,
                )
            return
        if status == "failed":
            error = str(status_row.get("error") or "unknown error")
            await bot.send_message(
                chat_id=chat_id,
                text=(
                    "❌ <b>Обработка не завершена</b>\n\n"
                    f"Причина: <code>{error[:300]}</code>"
                ),
                parse_mode="HTML",
                reply_markup=quick_actions,
            )
            return

        await asyncio.sleep(poll_seconds)
        elapsed += poll_seconds

    await bot.send_message(
        chat_id=chat_id,
        text=(
            "⏳ <b>Материал всё ещё обрабатывается</b>\n\n"
            "Задача пока в очереди. Проверь <code>/status</code> чуть позже."
        ),
        parse_mode="HTML",
        reply_markup=quick_actions,
    )


def _build_voice_ingest_text(*, caption: str, media_url: str) -> str:
    lines = ["Voice message transcript from Telegram audio #voice #save"]
    if caption:
        lines.append(f"Context: {caption}")
    lines.append(f"Media URL: {media_url}")
    return "\n".join(lines)


def _display_note_name(file_name: str) -> str:
    display = humanize_note_label(file_name)
    if display == Path(file_name).name:
        display = Path(file_name).stem
    return display[:80]


def _match_quick_action_alias(text: str) -> str:
    normalized = (
        str(text or "")
        .replace("⚙️", "")
        .replace("⚙", "")
        .replace("🔎", "")
        .replace("➕", "")
        .replace("📊", "")
        .replace("🕘", "")
        .replace("🗑", "")
        .replace("\uFE0F", "")
        .strip()
        .lower()
    )
    if normalized == "добавить":
        return "add"
    if normalized in {"найти", "поиск"}:
        return "search"
    if normalized in {"управление", "статус"}:
        return "manage"
    return ""


def _humanize_note_destination(*, note_path: Path, base_vault_path: Path | None) -> tuple[str, str]:
    resolved_note = note_path.resolve()
    if base_vault_path is not None:
        try:
            relative = resolved_note.relative_to(base_vault_path.resolve())
            folder = relative.parent.as_posix() if relative.parent.as_posix() != "." else "корень vault"
            return folder, relative.as_posix()
        except ValueError:
            pass
    folder = resolved_note.parent.name or "корень vault"
    return folder, resolved_note.name


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
