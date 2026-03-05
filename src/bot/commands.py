"""Telegram command handlers."""

from __future__ import annotations

import html
from pathlib import Path

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from src.bot.auth import build_tenant_context, is_authorized_user
from src.infra.storage import StateStore
from src.obsidian.search import find_notes, latest_notes
from src.rag.retriever import RagManager

DELETE_ALL_CONFIRM_TTL_SECONDS = 120
CARD_DIVIDER = "────────────"


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

    def _actor_ids(message: Message) -> tuple[int, int]:
        user_id = message.from_user.id if message.from_user else 0
        chat_id = message.chat.id if message.chat else user_id
        return user_id, chat_id

    def _delete_all_notes(tenant_id: str) -> tuple[int, int, int]:
        rag = rag_manager.for_tenant(tenant_id)
        tracked_notes = store.list_notes(tenant_id=tenant_id)
        file_deleted = 0
        index_deleted = 0

        for note in tracked_notes:
            note_path = (rag.vault_path / str(note["file_name"])).resolve()
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
        if not _authorized(message):
            await message.answer("❌ <i>В доступе отказано:</i> ваш ID не в белом списке.", parse_mode="HTML")
            return
        await message.answer(
            "🤖 <b>Привет. Я готов помогать с твоим Obsidian.</b>\n"
            f"{CARD_DIVIDER}\n"
            "Отправляй текст, мысли, ссылки и голосовые, а я аккуратно сохраню их в базу.\n\n"
            "🏷 <b>Поддерживаемые теги:</b>\n"
            "• <code>#save</code>\n"
            "• <code>#summary</code>\n"
            "• <code>#task</code>\n"
            "• <code>#translate</code>\n\n"
            "🧭 <b>Команды:</b>\n"
            "• <code>/status</code> — общая сводка по системе\n"
            "• <code>/find &lt;запрос&gt;</code> — поиск по заметкам\n"
            "• <code>/summary &lt;вопрос&gt;</code> — ответ по базе (RAG)\n"
            "• <code>/job &lt;job_id | prefix&gt;</code> — статус конкретной задачи\n"
            "• <code>/retry &lt;job_id&gt;</code> — перезапуск упавшей задачи\n"
            "• <code>/delete &lt;ID|файл&gt;</code> — удалить заметку\n"
            "• <code>/delete all</code> — запросить массовое удаление\n"
            "• <code>/delete confirm &lt;token&gt;</code> — подтвердить удаление\n"
            "• <code>/delete cancel</code> — отменить удаление\n\n"
            "✅ <b>Можешь просто отправить сообщение, остальное беру на себя.</b>",
            parse_mode="HTML"
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

        lines = ["🤖 <b>Проверил текущее состояние.</b>", "Ниже краткая сводка по системе.", "", "📊 <b>Статус системы</b>", CARD_DIVIDER]
        
        # Индекс и хранилище
        rag_stats = rag.stats()
        db_status = "✅ OK" if integrity_ok else f"❌ Ошибка ({html.escape(integrity_details)})"
        lines.append("📁 <b>База знаний</b>")
        lines.append(f"• RAG индекс: <b>{rag_stats['documents']}</b> док. / <b>{rag_stats['chunks']}</b> фрагм.")
        lines.append(f"• Хранилище: {db_status}")
        lines.append("")

        # Последние файлы
        recent_done_paths = [item.get("note_path", "") for item in recent if item.get("status") == "done"]
        recent_done_paths = [path for path in recent_done_paths if path]
        if recent_done_paths:
            lines.append("📝 <b>Недавние заметки</b>")
            for path in recent_done_paths[:3]:
                # Показываем только имя файла, чтобы не мусорить длинными путями
                file_name = html.escape(Path(path).name)
                lines.append(f"• <code>{file_name}</code>")
            lines.append("")

        # Очередь задач
        lines.append("⚙️ <b>Очередь</b>")
        if counts:
            for key, value in sorted(counts.items(), key=lambda item: item[0]):
                emoji = _job_status_emoji(_normalize_job_status(key))
                label = _status_label(key)
                lines.append(f"• {emoji} {label}: <b>{value}</b>")
        else:
            lines.append("• Очередь пуста")

        # Ошибки
        if failures:
            lines.append("")
            lines.append("❌ <b>Последние ошибки</b>")
            for item in failures:
                error_text = html.escape((item.get("error") or "no error text").replace("\n", " ")[:100])
                lines.append(f"• <code>{html.escape(_short_job(item['job_id']))}</code>: {error_text}...")
        else:
            lines.append("")
            lines.append("✅ <b>Ошибок в последних задачах не вижу.</b>")

        await message.answer("\n".join(lines), parse_mode="HTML")

    @router.message(Command("find"))
    async def find_handler(message: Message) -> None:
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
                f"🤖 <b>Нашёл релевантные фрагменты по запросу</b> <code>{safe_query}</code>.",
                "",
                f"🔍 <b>Поиск</b>: <code>{safe_query}</code>",
                CARD_DIVIDER,
                "✨ <b>Семантические совпадения</b>",
                "",
            ]
            for idx, hit in enumerate(hits, start=1):
                snippet = html.escape(" ".join(hit.chunk_text.split())[:200])
                safe_file = html.escape(hit.file_name)
                lines.append(f"<b>{idx}.</b> <code>{safe_file}</code> <i>(схожесть: {hit.score:.2f})</i>")
                lines.append(f"💬 <i>{snippet}...</i>")
                lines.append("")
            await message.answer("\n".join(lines), parse_mode="HTML")
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
            f"🤖 <b>Семантических совпадений не нашлось, но есть текстовые результаты для</b> <code>{safe_query}</code>.",
            "",
            f"🔍 <b>Поиск</b>: <code>{safe_query}</code>",
            CARD_DIVIDER,
            "📌 <b>Текстовые совпадения</b>",
            "",
        ]
        for idx, item in enumerate(matches, start=1):
            safe_file = html.escape(item['file_name'])
            safe_snippet = html.escape(item['snippet'])
            lines.append(f"<b>{idx}.</b> <code>{safe_file}</code>")
            lines.append(f"💬 <i>{safe_snippet}</i>")
            lines.append("")
        await message.answer("\n".join(lines), parse_mode="HTML")

    @router.message(Command("summary"))
    async def summary_handler(message: Message) -> None:
        if not _authorized(message):
            return

        tenant_id = _tenant_id(message)
        rag = rag_manager.for_tenant(tenant_id)
        query = _extract_args(message)
        if query:
            answer = rag.answer(query, top_k=4)
            safe_query = html.escape(query)
            if not answer.sources:
                await message.answer(
                    "🤖 <b>Пока не могу ответить уверенно на этот вопрос.</b>\n"
                    f"В базе не хватает контекста для: <code>{safe_query}</code>",
                    parse_mode="HTML",
                )
                return
            safe_answer = html.escape(answer.answer)
            lines = [
                "🤖 <b>Вот что получилось по твоему вопросу:</b>",
                "",
                f"🧠 <b>Вопрос</b>: <code>{safe_query}</code>",
                CARD_DIVIDER,
                f"{safe_answer}",
                "",
                "📚 <b>На основе заметок</b>",
            ]
            for src in answer.sources:
                safe_file = html.escape(src.file_name)
                lines.append(f"• <code>{safe_file}</code> <i>(схожесть: {src.score:.2f})</i>")
            await message.answer("\n".join(lines), parse_mode="HTML")
            return

        latest = latest_notes(rag.vault_path, limit=3)
        if not latest:
            await message.answer("📭 База знаний пока пуста.", parse_mode="HTML")
            return
        lines = ["🤖 <b>Сейчас покажу последние записи из базы.</b>", "", "📋 <b>Последние записи</b>", CARD_DIVIDER]
        for idx, item in enumerate(latest, start=1):
            safe_file = html.escape(item['file_name'])
            safe_snippet = html.escape(item['snippet'])
            lines.append(f"<b>{idx}.</b> <code>{safe_file}</code>")
            lines.append(f"💬 <i>{safe_snippet}</i>")
            lines.append("")
        await message.answer("\n".join(lines), parse_mode="HTML")

    @router.message(Command("retry"))
    async def retry_handler(message: Message) -> None:
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
        note_path = (rag.vault_path / str(note["file_name"])).resolve()
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
