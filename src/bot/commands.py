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
            await message.answer("❌ <i>В доступе отказано:</i> ваш ID не в белом списке.", parse_mode="HTML")
            return
        await message.answer(
            "👋 <b>Привет! Я твой AI-ассистент для Obsidian.</b>\n\n"
            "Отправь мне текст, мысль или ссылку, и я сохраню это в твою базу знаний.\n"
            "Поддерживаемые теги: <code>#save</code>, <code>#summary</code>, <code>#task</code>, <code>#translate</code>\n\n"
            "🛠 <b>Доступные команды:</b>\n"
            "• /status — 📊 Статус системы и базы\n"
            "• <code>/find &lt;запрос&gt;</code> — 🔍 Поиск по заметкам\n"
            "• <code>/summary &lt;вопрос&gt;</code> — 🧠 Задать вопрос по базе (RAG)\n"
            "• <code>/retry &lt;job_id&gt;</code> — ♻️ Перезапустить упавшую задачу\n"
            "• <code>/delete &lt;ID|файл&gt;</code> — 🗑 Удалить заметку",
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

        lines = ["📊 <b>Статус системы</b>", ""]
        
        # Индекс и хранилище
        rag_stats = rag.stats()
        db_status = "✅ OK" if integrity_ok else f"❌ Ошибка ({html.escape(integrity_details)})"
        lines.append("📁 <b>База знаний (Obsidian)</b>")
        lines.append(f"• Индекс RAG: {rag_stats['documents']} док. / {rag_stats['chunks']} фрагм.")
        lines.append(f"• БД: {db_status}")
        lines.append("")

        # Последние файлы
        recent_done_paths = [item.get("note_path", "") for item in recent if item.get("status") == "done"]
        recent_done_paths = [path for path in recent_done_paths if path]
        if recent_done_paths:
            lines.append("📝 <b>Недавние заметки:</b>")
            for path in recent_done_paths[:3]:
                # Показываем только имя файла, чтобы не мусорить длинными путями
                file_name = html.escape(Path(path).name)
                lines.append(f"• <code>{file_name}</code>")
            lines.append("")

        # Очередь задач
        lines.append("⚙️ <b>Очередь обработки:</b>")
        if counts:
            for key, value in sorted(counts.items()):
                emoji = "✅" if key == "done" else "⏳" if key in ("new", "processing") else "⚠️"
                lines.append(f"{emoji} {html.escape(key.capitalize())}: {value}")
        else:
            lines.append("• Очередь пуста")

        # Ошибки
        if failures:
            lines.append("")
            lines.append("❌ <b>Последние ошибки:</b>")
            for item in failures:
                error_text = html.escape((item.get("error") or "no error text").replace("\n", " ")[:100])
                lines.append(f"• ID: <code>{html.escape(_short_job(item['job_id']))}</code> ➔ {error_text}...")

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
            lines = [f"🔍 <b>Поиск:</b> <code>{safe_query}</code>", "", "✨ <b>Семантические совпадения:</b>", ""]
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
            await message.answer(f"🤷‍♂️ По запросу <code>{safe_query}</code> ничего не найдено.", parse_mode="HTML")
            return

        lines = [f"🔍 <b>Поиск:</b> <code>{safe_query}</code>", "", "📌 <b>Текстовые совпадения:</b>", ""]
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
                await message.answer(f"🤷‍♂️ Для ответа на <code>{safe_query}</code> в базе не нашлось подходящих данных.", parse_mode="HTML")
                return
            safe_answer = html.escape(answer.answer)
            lines = [f"🧠 <b>Вопрос:</b> <code>{safe_query}</code>", "", f"{safe_answer}", "", "📚 <b>На основе заметок:</b>"]
            for idx, src in enumerate(answer.sources, start=1):
                safe_file = html.escape(src.file_name)
                lines.append(f"• <code>{safe_file}</code> <i>(схожесть: {src.score:.2f})</i>")
            await message.answer("\n".join(lines), parse_mode="HTML")
            return

        latest = latest_notes(rag.vault_path, limit=3)
        if not latest:
            await message.answer("📭 База знаний пока пуста.", parse_mode="HTML")
            return
        lines = ["📋 <b>Последние записи:</b>", ""]
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
            await message.answer(f"♻️ <b>Успешно:</b> задача <code>{_short_job(safe_details)}</code> возвращена в очередь.", parse_mode="HTML")
        else:
            await message.answer(f"❌ <b>Ошибка:</b> {safe_details}", parse_mode="HTML")

    @router.message(Command("delete"))
    async def delete_handler(message: Message) -> None:
        if not _authorized(message):
            return

        note_ref = _extract_args(message)
        if not note_ref:
            await message.answer("⚠️ Использование: <code>/delete &lt;note_id | job_id | имя файла&gt;</code>", parse_mode="HTML")
            return

        tenant_id = _tenant_id(message)
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
            f"🗑 <b>Заметка удалена!</b>\n\n"
            f"• <b>Файл:</b> <code>{safe_file}</code>\n"
            f"• <b>Файл физически стерт:</b> {file_status}\n"
            f"• <b>Индекс RAG:</b> очищен",
            parse_mode="HTML"
        )

    return router


def _extract_args(message: Message) -> str:
    text = (message.text or "").strip()
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _short_job(job_id: str) -> str:
    return str(job_id)[:10]


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
