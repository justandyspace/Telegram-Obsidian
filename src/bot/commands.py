"""Telegram command handlers."""

from __future__ import annotations

import html
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from src.bot.auth import build_tenant_context, is_authorized_user
from src.bot.keyboards import build_quick_actions_keyboard
from src.bot.miniapp import build_mini_app_markup
from src.infra.logging import get_logger
from src.infra.runtime_state import last_error, uptime_human
from src.infra.storage import StateStore
from src.infra.telemetry import track_event
from src.obsidian.display import humanize_note_label
from src.obsidian.search import find_notes, latest_notes
from src.rag.retriever import _humanize_chunk_text

DELETE_ALL_CONFIRM_TTL_SECONDS = 120
SUMMARY_MAX_QUERY_CHARS = 1000
SUMMARY_MAX_QUERY_WORDS = 120
CARD_DIVIDER = "────────────"
LOGGER = get_logger(__name__)


def build_command_router(
    store: StateStore,
    allowed_user_ids: set[int],
    rag_manager,
    mini_app_base_url: str = "",
) -> Router:
    if rag_manager is None:
        raise RuntimeError("build_command_router requires a RagManager instance.")
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

    def _actor_ids(message: Message) -> tuple[int, int]:
        user_id = message.from_user.id if message.from_user else 0
        chat_id = message.chat.id if message.chat else user_id
        return user_id, chat_id

    def _log_command(message: Message, command_name: str) -> None:
        user_id = message.from_user.id if message.from_user else None
        chat_id = message.chat.id if message.chat else None
        LOGGER.info(
            "Incoming command=%s user_id=%s chat_id=%s",
            command_name,
            user_id,
            chat_id,
        )
        track_event(
            "command_used",
            command=command_name,
            user_id=user_id,
            chat_id=chat_id,
            has_args=bool(_extract_args(message)),
        )

    def _mini_app_markup(
        *,
        label: str,
        screen: str,
        query: str = "",
        note_id: str = "",
        job_id: str = "",
    ):
        markup = build_mini_app_markup(
            mini_app_base_url,
            label=label,
            screen=screen,
            query=query,
            note_id=note_id,
            job_id=job_id,
        )
        if markup is not None:
            track_event("miniapp_cta_rendered", label=label, screen=screen)
        return markup

    def _quick_actions_markup():
        return build_quick_actions_keyboard(mini_app_base_url)

    def _delete_all_notes(tenant_id: str) -> tuple[int, int, int]:
        rag = rag_manager.for_tenant(tenant_id)
        tracked_notes = store.list_notes(tenant_id=tenant_id)
        file_deleted = 0
        index_deleted = 0

        for note in tracked_notes:
            note_path = _resolve_note_path(rag.vault_path, str(note["file_name"]))
            if not _is_within(note_path, rag.vault_path.resolve()):
                continue
            if note_path.exists():
                note_path.unlink()
                file_deleted += 1
            if rag.remove_note(note_path):
                index_deleted += 1

        db_deleted = store.delete_all_note_records(tenant_id=tenant_id)
        return file_deleted, index_deleted, db_deleted

    def _card(title: str, lines: list[str]) -> str:
        body = [f"<b>{html.escape(title)}</b>", CARD_DIVIDER]
        body.extend(lines)
        return "\n".join(body)

    @router.message(Command("start"))
    async def start_handler(message: Message) -> None:
        _log_command(message, "/start")
        if not _authorized(message):
            await message.answer("❌ <i>В доступе отказано:</i> ваш ID не в белом списке.", parse_mode="HTML")
            return
        await message.answer(
            "🤖 <b>Привет. Это твой быстрый inbox для знаний.</b>\n"
            f"{CARD_DIVIDER}\n"
            "Перешли сюда ссылку, текст, заметку или голосовое. Я сохраню это и помогу потом найти по смыслу.\n\n"
            "⚡ <b>Что можно сделать прямо сейчас</b>\n"
            "• Отправить первую ссылку или мысль\n"
            "• <code>/find &lt;запрос&gt;</code> для быстрого поиска\n"
            "• <code>/summary &lt;вопрос&gt;</code> для ответа по базе\n"
            "• <code>/status</code> для короткой сводки\n\n"
            "Через Mini App потом будет удобнее смотреть базу целиком, но для старта чатовых команд уже достаточно.",
            parse_mode="HTML",
            reply_markup=_quick_actions_markup(),
        )

    @router.message((F.text == "⚙️ Управление") | (F.text == "📊 Статус"))
    async def quick_status_handler(message: Message) -> None:
        if message.text == "⚙️ Управление":
            if not _authorized(message):
                return
            await message.answer(
                "⚙️ <b>Управление</b>\n\n"
                "Здесь всё служебное:\n"
                "• <code>/status</code> для состояния очереди и индекса\n"
                "• <code>/delete имя_файла.md</code> для удаления одной заметки\n"
                "• <code>/delete cancel</code> для отмены массового удаления",
                parse_mode="HTML",
                reply_markup=_quick_actions_markup(),
            )
            return
        await status_handler(message)

    @router.message((F.text == "➕ Добавить") | (F.text == "🕘 Последние"))
    async def quick_latest_handler(message: Message) -> None:
        if message.text == "➕ Добавить":
            if not _authorized(message):
                return
            await message.answer(
                "➕ <b>Добавить</b>\n\n"
                "Просто отправь сюда:\n"
                "• текст или идею\n"
                "• ссылку\n"
                "• голосовое\n"
                "• фото или документ\n\n"
                "Если нужно, можешь дописать теги вроде <code>#save</code> или <code>#summary</code>.",
                parse_mode="HTML",
                reply_markup=_quick_actions_markup(),
            )
            return
        message.text = "/summary"
        await summary_handler(message)

    @router.message((F.text == "🔎 Найти") | (F.text == "🔎 Поиск"))
    async def quick_search_handler(message: Message) -> None:
        if not _authorized(message):
            return
        await message.answer(
            "🔎 <b>Поиск по базе</b>\n\n"
            "Что можно сделать:\n"
            "• <code>/find запрос</code> для быстрого поиска\n"
            "• <code>/summary вопрос</code> для ответа по базе\n"
            "• кнопка <b>📲 База</b> для полного поиска и просмотра заметок",
            parse_mode="HTML",
            reply_markup=_mini_app_markup(label="🔎 Открыть поиск", screen="search"),
        )

    @router.message(F.text == "🗑 Удаление")
    async def quick_delete_handler(message: Message) -> None:
        if not _authorized(message):
            return
        await message.answer(
            "🗑 <b>Удаление заметок</b>\n\n"
            "Быстро отменить массовое удаление: <code>/delete cancel</code>\n"
            "Удалить конкретную заметку: <code>/delete имя_файла.md</code>",
            parse_mode="HTML",
            reply_markup=_quick_actions_markup(),
        )

    @router.message(Command("status"))
    async def status_handler(message: Message) -> None:
        _log_command(message, "/status")
        if not _authorized(message):
            await message.answer("❌ Доступ закрыт. Этот Telegram-аккаунт не добавлен в список разрешённых.")
            return

        tenant_id = _tenant_id(message)
        counts = store.status_counts(tenant_id=tenant_id)
        failures = store.recent_failures(limit=3, tenant_id=tenant_id)
        recent = store.recent_jobs(limit=3, tenant_id=tenant_id)
        rag = rag_manager.for_tenant(tenant_id)
        integrity_ok, integrity_details = store.integrity_check()
        rag_stats = rag.stats()
        err_text, err_at = last_error()
        recent_done_paths = [item.get("note_path", "") for item in recent if item.get("status") == "done"]
        recent_done_paths = [path for path in recent_done_paths if path]
        lines = ["📊 <b>Короткая сводка</b>", CARD_DIVIDER]
        if counts:
            for key, value in sorted(counts.items(), key=lambda item: item[0]):
                emoji = _job_status_emoji(_normalize_job_status(key))
                label = _status_label(key)
                lines.append(f"• {emoji} {label}: <b>{value}</b>")
        else:
            lines.append("• Очередь пуста")
        lines.append(f"• Индекс: <b>{rag_stats['documents']}</b> заметок / <b>{rag_stats['chunks']}</b> фрагментов")
        lines.append(f"• Хранилище: {'✅ OK' if integrity_ok else '❌ требует внимания'}")
        lines.append(f"• Аптайм: <code>{uptime_human()}</code>")
        if failures:
            first_error = html.escape((failures[0].get("error") or "no error text").replace("\n", " ")[:80])
            lines.append(f"• Последняя ошибка: <code>{first_error}</code>")
        else:
            lines.append("✅ <b>Ошибок в последних задачах не вижу.</b>")
        if err_text:
            lines.append(f"• Runtime: <code>{html.escape(err_text[:80])}</code>")
        else:
            lines.append("• Runtime: <b>без ошибок</b>")
        if not integrity_ok:
            lines.append(f"• Проверка БД: <code>{html.escape(integrity_details[:80])}</code>")
        if recent_done_paths:
            latest_note = html.escape(humanize_note_label(Path(recent_done_paths[0]).name))
            lines.append(f"• Последняя заметка: <code>{latest_note}</code>")

        await message.answer(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=_mini_app_markup(label="📊 Открыть Jobs", screen="activity"),
        )

    @router.message(Command("find"))
    async def find_handler(message: Message) -> None:
        _log_command(message, "/find")
        if not _authorized(message):
            return

        query = _extract_args(message)
        if not query:
            await message.answer("⚠️ Использование: <code>/find &lt;запрос&gt;</code>", parse_mode="HTML")
            return

        tenant_id = _tenant_id(message)
        rag = rag_manager.for_tenant(tenant_id)
        hits = rag.find(query, top_k=5)
        safe_query = html.escape(query)
        
        if hits:
            lines = [
                f"🔍 <b>Быстрые результаты для</b> <code>{safe_query}</code>",
                "",
                CARD_DIVIDER,
            ]
            for idx, hit in enumerate(_dedupe_hits_by_file(hits)[:3], start=1):
                safe_file = html.escape(_source_label(hit.file_name, idx))
                snippet = html.escape(_preview_text(hit.chunk_text))
                lines.append(f"<b>{idx}.</b> <code>{safe_file}</code>")
                lines.append(f"💬 <i>{snippet}</i>")
                lines.append("")
            await message.answer(
                "\n".join(lines),
                parse_mode="HTML",
                reply_markup=_mini_app_markup(label="🔎 Открыть расширенный поиск", screen="search", query=query),
            )
            return

        matches = find_notes(rag.vault_path, query, limit=5)
        if not matches:
            await message.answer(
                "🤖 <b>Проверил базу, но точных совпадений пока нет.</b>\n"
                f"Попробуй переформулировать запрос: <code>{safe_query}</code>",
                parse_mode="HTML",
            )
            return

        lines = [
            f"🔍 <b>Текстовые совпадения для</b> <code>{safe_query}</code>",
            "",
            CARD_DIVIDER,
        ]
        for idx, item in enumerate(matches[:3], start=1):
            safe_file = html.escape(item.get("display_name") or humanize_note_label(item["file_name"]))
            safe_snippet = html.escape(item['snippet'])
            lines.append(f"<b>{idx}.</b> <code>{safe_file}</code>")
            lines.append(f"💬 <i>{safe_snippet}</i>")
            lines.append("")
        await message.answer(
            "\n".join(lines),
            parse_mode="HTML",
            reply_markup=_mini_app_markup(label="🔎 Открыть расширенный поиск", screen="search", query=query),
        )

    @router.message(Command("summary"))
    async def summary_handler(message: Message) -> None:
        _log_command(message, "/summary")
        if not _authorized(message):
            return

        tenant_id = _tenant_id(message)
        rag = rag_manager.for_tenant(tenant_id)
        query = _extract_args(message)
        if query:
            word_count = len(query.split())
            if len(query) > SUMMARY_MAX_QUERY_CHARS or word_count > SUMMARY_MAX_QUERY_WORDS:
                await message.answer(
                    "⚠️ <b>Слишком длинный запрос для /summary.</b>\n"
                    "Сократи вопрос до "
                    f"<code>{SUMMARY_MAX_QUERY_CHARS}</code> символов "
                    f"или <code>{SUMMARY_MAX_QUERY_WORDS}</code> слов и повтори попытку.",
                    parse_mode="HTML",
                )
                return
            answer = rag.answer(query, top_k=4)
            safe_query = html.escape(query)
            if not answer.sources:
                await message.answer(
                    "🤖 <b>Пока не могу ответить уверенно на этот вопрос.</b>\n"
                    "Похоже, в заметках пока нет достаточно ясного материала, чтобы ответить нормально.\n"
                    f"Попробуй сузить формулировку или добавить больше контекста по теме: <code>{safe_query}</code>",
                    parse_mode="HTML",
                )
                return
            safe_answer = html.escape(answer.answer)
            source_hits = _dedupe_hits_by_file(answer.sources)
            if answer.mode == "extractive":
                lines = [
                    "🧠 <b>Что удалось собрать по базе</b>",
                    "",
                    f"Вопрос: <code>{safe_query}</code>",
                    CARD_DIVIDER,
                    "Нашёл несколько заметок по теме. Вот что выглядит самым полезным и близким к твоему вопросу:",
                    "",
                ]
                for idx, src in enumerate(source_hits[:3], start=1):
                    safe_file = html.escape(_source_label(src.file_name, idx))
                    snippet = html.escape(_preview_text(src.chunk_text))
                    lines.append(f"{idx}. <b>{safe_file}</b>")
                    lines.append(f"   {snippet}")
                lines.append("")
                lines.append("Если хочешь, могу потом помочь углубиться в любой из этих материалов.")
                lines.append("")
                lines.append("📚 <b>Откуда это взято</b>")
                for idx, src in enumerate(source_hits[:4], start=1):
                    safe_file = html.escape(_source_label(src.file_name, idx))
                    lines.append(f"• <code>{safe_file}</code>")
                await message.answer(
                    "\n".join(lines),
                    parse_mode="HTML",
                    reply_markup=_mini_app_markup(label="📲 Открыть поиск по вопросу", screen="search", query=query),
                )
                return
            lines = [
                "🧠 <b>Ответ по заметкам</b>",
                "",
                f"Вопрос: <code>{safe_query}</code>",
                CARD_DIVIDER,
                f"{safe_answer}",
                "",
                "📚 <b>Опирался на заметки</b>",
            ]
            for idx, src in enumerate(source_hits[:4], start=1):
                safe_file = html.escape(_source_label(src.file_name, idx))
                lines.append(f"• <code>{safe_file}</code>")
            await message.answer(
                "\n".join(lines),
                parse_mode="HTML",
                reply_markup=_mini_app_markup(label="📲 Открыть поиск по вопросу", screen="search", query=query),
            )
            return

        latest = latest_notes(rag.vault_path, limit=3)
        if not latest:
            await message.answer("📭 База знаний пока пуста.", parse_mode="HTML")
            return
        lines = [
            "🤖 <b>Вот что у тебя добавлялось последним.</b>",
            "",
            "📋 <b>Последние записи</b>",
            CARD_DIVIDER,
        ]
        for idx, item in enumerate(latest, start=1):
            safe_file = html.escape(item.get("display_name") or humanize_note_label(item["file_name"]))
            safe_snippet = html.escape(item['snippet'])
            lines.append(f"<b>{idx}.</b> <code>{safe_file}</code>")
            lines.append(f"💬 <i>{safe_snippet}</i>")
            lines.append("")
        await message.answer("\n".join(lines), parse_mode="HTML")

    @router.message(Command("retry"))
    async def retry_handler(message: Message) -> None:
        _log_command(message, "/retry")
        if not _authorized(message):
            return

        job_ref = _extract_args(message)
        if not job_ref:
            await message.answer("⚠️ Использование: <code>/retry &lt;job_id&gt;</code>", parse_mode="HTML")
            return

        tenant_id = _tenant_id(message)
        ok, details = store.retry_job(job_ref, tenant_id=tenant_id)
        safe_details = html.escape(str(details))
        if ok:
            await message.answer(
                _card(
                    "♻️ Повторный запуск принят",
                    [
                        "Задача принята в повторную обработку.",
                        "",
                        f"• Задача: <code>{_short_job(safe_details)}</code>",
                        "• Статус: возвращена в <code>retry</code>",
                    ],
                ),
                parse_mode="HTML",
            )
        else:
            await message.answer(_card("❌ Не удалось перезапустить", [safe_details]), parse_mode="HTML")

    @router.message(Command("job"))
    async def job_handler(message: Message) -> None:
        _log_command(message, "/job")
        if not _authorized(message):
            return

        job_ref = _extract_args(message)
        if not job_ref:
            await message.answer("⚠️ Использование: <code>/job &lt;job_id | prefix&gt;</code>", parse_mode="HTML")
            return

        tenant_id = _tenant_id(message)
        ok, resolved = store.resolve_job_ref(job_ref, tenant_id=tenant_id)
        if not ok:
            await message.answer(f"❌ <b>Ошибка:</b> {html.escape(str(resolved))}", parse_mode="HTML")
            return
        if not isinstance(resolved, dict):
            await message.answer("❌ <b>Внутренняя ошибка:</b> не удалось прочитать задачу.", parse_mode="HTML")
            return

        raw_status = str(resolved.get("status") or "")
        status = _normalize_job_status(raw_status)
        status_emoji = _job_status_emoji(status)
        safe_job_id = html.escape(str(resolved.get("job_id") or ""))
        safe_updated = html.escape(str(resolved.get("updated_at") or "unknown"))

        lines = [
            "🤖 <b>Проверил задачу. Вот её актуальный статус:</b>",
            "",
            "🧾 <b>Статус задачи</b>",
            CARD_DIVIDER,
            f"• <b>ID:</b> <code>{safe_job_id}</code>",
            f"• <b>Статус:</b> {status_emoji} <code>{html.escape(status)}</code>",
            f"• <b>Обновлено:</b> <code>{safe_updated}</code>",
        ]

        note_path = str(resolved.get("note_path") or "")
        if status == "done" and note_path:
            safe_note = html.escape(Path(note_path).name)
            lines.append(f"• <b>Файл:</b> <code>{safe_note}</code>")

        await message.answer("\n".join(lines), parse_mode="HTML")

    @router.message(Command("delete"))
    async def delete_handler(message: Message) -> None:
        _log_command(message, "/delete")
        if not _authorized(message):
            return

        note_ref = _extract_args(message)
        if not note_ref:
            await message.answer(
                "⚠️ Использование:\n"
                "• <code>/delete &lt;note_id | job_id | имя файла&gt;</code>\n"
                "• <code>/delete all</code>\n"
                "• <code>/delete confirm &lt;token&gt;</code>\n"
                "• <code>/delete cancel</code>",
                parse_mode="HTML",
            )
            return

        tenant_id = _tenant_id(message)
        normalized = note_ref.strip()
        lowered = normalized.lower()

        if lowered == "all":
            user_id, chat_id = _actor_ids(message)
            confirmation = store.create_delete_all_confirmation(
                tenant_id=tenant_id,
                user_id=user_id,
                chat_id=chat_id,
                ttl_seconds=DELETE_ALL_CONFIRM_TTL_SECONDS,
            )
            safe_token = html.escape(str(confirmation["token"]))
            await message.answer(
                "⚠️ <b>Подтверждение обязательно</b>\n\n"
                "Команда <code>/delete all</code> не выполнена сразу.\n"
                f"Для подтверждения отправьте <code>/delete confirm {safe_token}</code> в течение 2 минут.\n"
                "Для отмены отправьте <code>/delete cancel</code>.",
                parse_mode="HTML",
            )
            return

        if lowered == "cancel":
            user_id, _ = _actor_ids(message)
            canceled = store.cancel_delete_all_confirmation(tenant_id=tenant_id, user_id=user_id)
            if canceled:
                await message.answer(_card("✅ Массовое удаление отменено", ["Ожидающее подтверждение удалено."]), parse_mode="HTML")
            else:
                await message.answer(_card("ℹ️ Нечего отменять", ["Нет активного подтверждения на /delete all."]), parse_mode="HTML")
            return

        if lowered == "confirm" or lowered.startswith("confirm "):
            token_parts = normalized.split(maxsplit=1)
            provided_token = token_parts[1].strip() if len(token_parts) > 1 else None
            user_id, _ = _actor_ids(message)
            confirmed, reason = store.consume_delete_all_confirmation(
                tenant_id=tenant_id,
                user_id=user_id,
                token=provided_token,
            )
            if not confirmed:
                if reason == "expired":
                    await message.answer(
                        "⌛ Подтверждение истекло. Повторите <code>/delete all</code>.",
                        parse_mode="HTML",
                    )
                    return
                if reason == "token_mismatch":
                    await message.answer(
                        "❌ Неверный токен подтверждения. Повторите <code>/delete all</code>.",
                        parse_mode="HTML",
                    )
                    return
                await message.answer(
                    "ℹ️ Нет активного подтверждения. Сначала отправьте <code>/delete all</code>.",
                    parse_mode="HTML",
                )
                return

            file_deleted, index_deleted, db_deleted = _delete_all_notes(tenant_id)
            await message.answer(
                "🗑 <b>Массовое удаление завершено</b>\n"
                f"{CARD_DIVIDER}\n"
                "Готово, очистка выполнена.\n\n"
                f"• Файлов удалено: <b>{file_deleted}</b>\n"
                f"• Документов удалено из RAG: <b>{index_deleted}</b>\n"
                f"• Записей удалено из БД: <b>{db_deleted}</b>",
                parse_mode="HTML",
            )
            return

        resolved_ok, resolved = store.resolve_note_ref(note_ref, tenant_id=tenant_id)
        if not resolved_ok:
            safe_err = html.escape(str(resolved))
            await message.answer(f"❌ <b>Удаление отклонено:</b> {safe_err}", parse_mode="HTML")
            return
        if not isinstance(resolved, dict):
            await message.answer("❌ <b>Внутренняя ошибка:</b> не удалось определить заметку.", parse_mode="HTML")
            return

        note = resolved
        rag = rag_manager.for_tenant(tenant_id)
        note_path = _resolve_note_path(rag.vault_path, str(note["file_name"]))
        if not _is_within(note_path, rag.vault_path.resolve()):
            await message.answer("❌ <b>Удаление отклонено:</b> путь заметки вне хранилища.", parse_mode="HTML")
            return

        file_deleted = False
        if note_path.exists():
            note_path.unlink()
            file_deleted = True

        rag.remove_note(note_path)
        db_deleted = store.delete_note_record(
            tenant_id=tenant_id,
            content_fingerprint=str(note["content_fingerprint"]),
        )
        if not db_deleted:
            await message.answer("⚠️ <b>Частичное удаление:</b> файл и индекс обновлены, но запись в БД не найдена.", parse_mode="HTML")
            return

        file_status = "да" if file_deleted else "уже отсутствовал"
        safe_file = html.escape(str(note['file_name']))
        await message.answer(
            f"🗑 <b>Заметка удалена</b>\n"
            f"{CARD_DIVIDER}\n"
            "Сделано, запись удалена из хранилища и индекса.\n\n"
            f"• Файл: <code>{safe_file}</code>\n"
            f"• Файл физически стерт: {file_status}\n"
            f"• Индекс RAG: очищен",
            parse_mode="HTML"
        )

    return router


def _extract_args(message: Message) -> str:
    text = (message.text or "").strip()
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _short_job(job_id: str) -> str:
    return str(job_id)[:10]


def _normalize_job_status(status: str) -> str:
    normalized = status.strip().lower()
    if normalized == "pending":
        return "queued"
    return normalized or "unknown"


def _job_status_emoji(status: str) -> str:
    if status == "queued":
        return "🕒"
    if status == "retry":
        return "♻️"
    if status == "processing":
        return "⏳"
    if status == "done":
        return "✅"
    if status == "failed":
        return "❌"
    return "⚠️"


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _status_label(status: str) -> str:
    normalized = _normalize_job_status(status)
    labels = {
        "queued": "В очереди",
        "processing": "В обработке",
        "retry": "Повтор",
        "done": "Готово",
        "failed": "Ошибка",
    }
    return labels.get(normalized, normalized.capitalize() or "Unknown")


def _display_note_name(file_name: str) -> str:
    return humanize_note_label(file_name)


def _source_label(file_name: str, index: int) -> str:
    display = _display_note_name(file_name).strip()
    if display in {"", "Сохранённая заметка"}:
        return f"Заметка {index}"
    if display == "Сохранённый материал":
        return f"Материал {index}"
    return display


def _preview_text(text: str, max_chars: int = 180) -> str:
    cleaned = _humanize_chunk_text(text)
    if not cleaned:
        return "Сохранил материал, но в коротком фрагменте здесь нечего показать. Если хочешь, можно открыть саму заметку."
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."


def _dedupe_hits_by_file(hits) -> list:
    seen: set[str] = set()
    deduped = []
    for hit in hits:
        key = str(getattr(hit, "file_name", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(hit)
    return deduped


def _resolve_note_path(vault_root: Path, file_name: str) -> Path:
    direct = (vault_root / file_name).resolve()
    if direct.exists():
        return direct

    matches = sorted(
        candidate.resolve()
        for candidate in vault_root.rglob(file_name)
        if candidate.is_file()
    )
    if matches:
        return matches[0]
    return direct
