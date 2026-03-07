from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from aiogram.types import InlineKeyboardMarkup

from src.bot.commands import build_command_router
from src.bot.miniapp import build_mini_app_markup, build_mini_app_url
from src.infra.storage import StateStore
from src.rag.retriever import QueryAnswer, RetrievedChunk


class _FakeMessage:
    def __init__(
        self,
        text: str,
        *,
        user_id: int = 1,
        chat_id: int = 1,
        from_user: bool = True,
    ) -> None:
        self.text = text
        self.caption = None
        self.bot = None
        self.date = datetime(2026, 3, 5, 12, 0, tzinfo=UTC)
        self.chat = SimpleNamespace(id=chat_id, type="private")
        self.from_user = SimpleNamespace(id=user_id) if from_user else None
        self.answers: list[tuple[str, str | None]] = []
        self.reply_markups: list[InlineKeyboardMarkup | None] = []

    async def answer(
        self,
        text: str,
        parse_mode: str | None = None,
        reply_markup: InlineKeyboardMarkup | None = None,
    ) -> None:
        self.answers.append((text, parse_mode))
        self.reply_markups.append(reply_markup)


class _FakeRagService:
    def __init__(self, vault_path: Path) -> None:
        self.vault_path = vault_path
        self.find_hits: list[RetrievedChunk] = []
        self.answer_value = QueryAnswer(answer="", sources=[], mode="empty")
        self.stats_value: dict[str, int | str] = {"documents": 0, "chunks": 0, "provider": "hash-fallback"}
        self.removed_paths: list[Path] = []

    def stats(self) -> dict[str, int | str]:
        return self.stats_value

    def find(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        _ = (query, top_k)
        return list(self.find_hits)

    def answer(self, question: str, top_k: int = 4) -> QueryAnswer:
        _ = (question, top_k)
        return self.answer_value

    def remove_note(self, note_path: Path) -> bool:
        self.removed_paths.append(note_path)
        return True


class _FakeRagManager:
    def __init__(self, service: _FakeRagService) -> None:
        self._service = service
        self.tenant_ids: list[str] = []

    def for_tenant(self, tenant_id: str) -> _FakeRagService:
        self.tenant_ids.append(tenant_id)
        return self._service


def _handlers(
    store,
    rag_manager,
    vault_path: Path,
    allowed: set[int] | None = None,
    *,
    mini_app_base_url: str = "https://miniapp.example.test/app",
):
    router = build_command_router(
        store,
        allowed or {1},
        vault_path,
        rag_manager,
        mini_app_base_url=mini_app_base_url,
    )
    return {item.callback.__name__: item.callback for item in router.message.handlers}


class CommandRouterRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name) / "vault"
        self.vault.mkdir(parents=True, exist_ok=True)
        self.rag = _FakeRagService(self.vault)
        self.rag_manager = _FakeRagManager(self.rag)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_start_handler_authorized_and_unauthorized(self) -> None:
        store = MagicMock()
        callbacks = _handlers(store, self.rag_manager, self.vault)

        allowed = _FakeMessage("/start")
        asyncio.run(callbacks["start_handler"](allowed))
        self.assertIn("Привет", allowed.answers[0][0])
        self.assertIsNotNone(allowed.reply_markups[0])

        denied_router = _handlers(store, self.rag_manager, self.vault, allowed={2})
        denied = _FakeMessage("/start")
        asyncio.run(denied_router["start_handler"](denied))
        self.assertIn("отказано", denied.answers[0][0])

    def test_status_handler_renders_full_status_and_unauthorized(self) -> None:
        store = MagicMock()
        store.status_counts.return_value = {"pending": 2, "failed": 1}
        store.recent_failures.return_value = [{"job_id": "abcdef123456", "error": "boom"}]
        store.recent_jobs.return_value = [{"status": "done", "note_path": str(self.vault / "note.md")}]
        store.integrity_check.return_value = (False, "db broken")
        self.rag.stats_value = {"documents": 3, "chunks": 7, "provider": "hash-fallback"}
        callbacks = _handlers(store, self.rag_manager, self.vault)

        with patch("src.bot.commands.uptime_human", return_value="1m"), patch(
            "src.bot.commands.last_error",
            return_value=("fatal", "2026-03-05T12:01:00+00:00"),
        ):
            msg = _FakeMessage("/status")
            asyncio.run(callbacks["status_handler"](msg))

        text = msg.answers[0][0]
        self.assertIn("Короткая сводка", text)
        self.assertIn("требует внимания", text)
        self.assertIn("note.md", text)
        self.assertIn("fatal", text)
        self.assertIsNotNone(msg.reply_markups[0])

        denied_router = _handlers(store, self.rag_manager, self.vault, allowed={2})
        denied = _FakeMessage("/status")
        asyncio.run(denied_router["status_handler"](denied))
        self.assertIn("Доступ закрыт", denied.answers[0][0])

    def test_find_handler_covers_semantic_text_and_empty_paths(self) -> None:
        store = MagicMock()
        callbacks = _handlers(store, self.rag_manager, self.vault)

        no_args = _FakeMessage("/find")
        asyncio.run(callbacks["find_handler"](no_args))
        self.assertIn("Использование", no_args.answers[0][0])

        self.rag.find_hits = [
            RetrievedChunk(
                note_path=str((self.vault / "semantic.md").resolve()),
                chunk_id="c1",
                chunk_text="semantic answer body",
                score=0.8,
            )
        ]
        semantic = _FakeMessage("/find body")
        asyncio.run(callbacks["find_handler"](semantic))
        self.assertIn("semantic", semantic.answers[0][0])
        self.assertIn("semantic answer body", semantic.answers[0][0])
        self.assertIsNotNone(semantic.reply_markups[0])

        self.rag.find_hits = []
        with patch("src.bot.commands.find_notes", return_value=[]):
            empty = _FakeMessage("/find missing")
            asyncio.run(callbacks["find_handler"](empty))
            self.assertIn("точных совпадений пока нет", empty.answers[0][0])

        with patch(
            "src.bot.commands.find_notes",
            return_value=[{"file_name": "text.md", "snippet": "plain text"}],
        ):
            fallback = _FakeMessage("/find plain")
            asyncio.run(callbacks["find_handler"](fallback))
            self.assertIn("text.md", fallback.answers[0][0])
            self.assertIsNotNone(fallback.reply_markups[0])

    def test_summary_handler_covers_question_and_latest_views(self) -> None:
        store = MagicMock()
        callbacks = _handlers(store, self.rag_manager, self.vault)

        too_long = _FakeMessage("/summary " + ("оченьдлинныйтекст " * 100))
        asyncio.run(callbacks["summary_handler"](too_long))
        self.assertIn("Слишком длинный запрос", too_long.answers[0][0])

        too_many_words = _FakeMessage("/summary " + ("слово " * 130))
        asyncio.run(callbacks["summary_handler"](too_many_words))
        self.assertIn("Слишком длинный запрос", too_many_words.answers[0][0])

        self.rag.answer_value = QueryAnswer(answer="No relevant indexed notes found.", sources=[], mode="empty")
        no_sources = _FakeMessage("/summary why")
        asyncio.run(callbacks["summary_handler"](no_sources))
        self.assertIn("не могу ответить уверенно", no_sources.answers[0][0])

        self.rag.answer_value = QueryAnswer(
            answer="Grounded answer",
            sources=[
                RetrievedChunk(
                    note_path=str((self.vault / "source.md").resolve()),
                    chunk_id="c1",
                    chunk_text="context",
                    score=0.9,
                )
            ],
            mode="extractive",
        )
        with_sources = _FakeMessage("/summary why")
        asyncio.run(callbacks["summary_handler"](with_sources))
        self.assertIn("Нашёл несколько заметок по теме", with_sources.answers[0][0])
        self.assertIn("context", with_sources.answers[0][0])
        self.assertIn("source.md", with_sources.answers[0][0])
        self.assertIsNotNone(with_sources.reply_markups[0])

        with patch("src.bot.commands.latest_notes", return_value=[]):
            latest_empty = _FakeMessage("/summary")
            asyncio.run(callbacks["summary_handler"](latest_empty))
            self.assertIn("База знаний пока пуста", latest_empty.answers[0][0])

        with patch(
            "src.bot.commands.latest_notes",
            return_value=[{"file_name": "latest.md", "snippet": "latest line"}],
        ):
            latest = _FakeMessage("/summary")
            asyncio.run(callbacks["summary_handler"](latest))
            self.assertIn("latest.md", latest.answers[0][0])

    def test_retry_and_job_handlers_cover_success_and_failures(self) -> None:
        store = MagicMock()
        store.retry_job.return_value = (True, "abcdef1234567890")
        store.resolve_job_ref.side_effect = [
            (False, "missing"),
            (True, "bad payload"),
            (
                True,
                {
                    "job_id": "abcdef1234567890",
                    "status": "done",
                    "updated_at": "2026-03-05",
                    "note_path": str(self.vault / "done.md"),
                },
            ),
        ]
        callbacks = _handlers(store, self.rag_manager, self.vault)

        no_retry_arg = _FakeMessage("/retry")
        asyncio.run(callbacks["retry_handler"](no_retry_arg))
        self.assertIn("Использование", no_retry_arg.answers[0][0])

        retry_ok = _FakeMessage("/retry abc")
        asyncio.run(callbacks["retry_handler"](retry_ok))
        self.assertIn("Повторный запуск принят", retry_ok.answers[0][0])

        store.retry_job.return_value = (False, "cannot retry")
        retry_fail = _FakeMessage("/retry abc")
        asyncio.run(callbacks["retry_handler"](retry_fail))
        self.assertIn("Не удалось перезапустить", retry_fail.answers[0][0])

        no_job_arg = _FakeMessage("/job")
        asyncio.run(callbacks["job_handler"](no_job_arg))
        self.assertIn("Использование", no_job_arg.answers[0][0])

        missing = _FakeMessage("/job abc")
        asyncio.run(callbacks["job_handler"](missing))
        self.assertIn("Ошибка", missing.answers[0][0])

        wrong_type = _FakeMessage("/job abc")
        asyncio.run(callbacks["job_handler"](wrong_type))
        self.assertIn("Внутренняя ошибка", wrong_type.answers[0][0])

        found = _FakeMessage("/job abc")
        asyncio.run(callbacks["job_handler"](found))
        self.assertIn("done.md", found.answers[0][0])

    def test_delete_handler_covers_confirmations_and_single_note_deletion(self) -> None:
        store = StateStore(Path(self._tmp.name) / "state.sqlite3")
        store.initialize()
        try:
            callbacks = _handlers(store, self.rag_manager, self.vault)

            no_args = _FakeMessage("/delete")
            asyncio.run(callbacks["delete_handler"](no_args))
            self.assertIn("Использование", no_args.answers[0][0])

            request_all = _FakeMessage("/delete all")
            asyncio.run(callbacks["delete_handler"](request_all))
            self.assertIn("Подтверждение обязательно", request_all.answers[0][0])
            token = request_all.answers[0][0].split("/delete confirm ")[1].split("</code>")[0]

            mismatch = _FakeMessage("/delete confirm wrong")
            asyncio.run(callbacks["delete_handler"](mismatch))
            self.assertIn("Неверный токен", mismatch.answers[0][0])

            note_path = self.vault / "tracked.md"
            note_path.write_text("tracked", encoding="utf-8")
            store.upsert_note(
                tenant_id="tg_1",
                content_fingerprint="fp-1",
                note_id="NOTE1",
                file_name=note_path.name,
                job_id="job-1",
            )

            confirm = _FakeMessage(f"/delete confirm {token}")
            asyncio.run(callbacks["delete_handler"](confirm))
            self.assertIn("Массовое удаление завершено", confirm.answers[0][0])
            self.assertFalse(note_path.exists())

            cancel_none = _FakeMessage("/delete cancel")
            asyncio.run(callbacks["delete_handler"](cancel_none))
            self.assertIn("Нечего отменять", cancel_none.answers[0][0])

            expired_msg = _FakeMessage("/delete all")
            asyncio.run(callbacks["delete_handler"](expired_msg))
            token2 = expired_msg.answers[0][0].split("/delete confirm ")[1].split("</code>")[0]
            store.cancel_delete_all_confirmation(tenant_id="tg_1", user_id=1)

            with patch.object(store, "consume_delete_all_confirmation", return_value=(False, "expired")):
                expired = _FakeMessage(f"/delete confirm {token2}")
                asyncio.run(callbacks["delete_handler"](expired))
                self.assertIn("Подтверждение истекло", expired.answers[0][0])

            with patch.object(store, "consume_delete_all_confirmation", return_value=(False, "missing")):
                missing_confirm = _FakeMessage("/delete confirm x")
                asyncio.run(callbacks["delete_handler"](missing_confirm))
                self.assertIn("Нет активного подтверждения", missing_confirm.answers[0][0])

            with patch.object(store, "resolve_note_ref", return_value=(False, "missing")):
                missing_note = _FakeMessage("/delete missing")
                asyncio.run(callbacks["delete_handler"](missing_note))
                self.assertIn("Удаление отклонено", missing_note.answers[0][0])

            with patch.object(store, "resolve_note_ref", return_value=(True, "oops")):
                wrong_note = _FakeMessage("/delete weird")
                asyncio.run(callbacks["delete_handler"](wrong_note))
                self.assertIn("Внутренняя ошибка", wrong_note.answers[0][0])

            outside = _FakeMessage("/delete outside")
            with patch.object(
                store,
                "resolve_note_ref",
                return_value=(True, {"file_name": "../outside.md", "content_fingerprint": "fp"}),
            ):
                asyncio.run(callbacks["delete_handler"](outside))
            self.assertIn("путь заметки вне хранилища", outside.answers[0][0])

            ghost_note = {"file_name": "ghost.md", "content_fingerprint": "ghost"}
            with patch.object(store, "resolve_note_ref", return_value=(True, ghost_note)), patch.object(
                store,
                "delete_note_record",
                return_value=0,
            ):
                ghost = _FakeMessage("/delete ghost")
                asyncio.run(callbacks["delete_handler"](ghost))
                self.assertIn("Частичное удаление", ghost.answers[0][0])

            keep_path = self.vault / "keep.md"
            keep_path.write_text("keep", encoding="utf-8")
            with patch.object(
                store,
                "resolve_note_ref",
                return_value=(True, {"file_name": "keep.md", "content_fingerprint": "fp-keep"}),
            ), patch.object(store, "delete_note_record", return_value=1):
                single = _FakeMessage("/delete keep")
                asyncio.run(callbacks["delete_handler"](single))
            self.assertIn("Заметка удалена", single.answers[0][0])
            self.assertIn("keep.md", single.answers[0][0])

            nested_dir = self.vault / "2026" / "03"
            nested_dir.mkdir(parents=True, exist_ok=True)
            nested_path = nested_dir / "nested.md"
            nested_path.write_text("nested", encoding="utf-8")
            with patch.object(
                store,
                "resolve_note_ref",
                return_value=(True, {"file_name": "nested.md", "content_fingerprint": "fp-nested"}),
            ), patch.object(store, "delete_note_record", return_value=1):
                nested = _FakeMessage("/delete nested.md")
                asyncio.run(callbacks["delete_handler"](nested))
            self.assertIn("Заметка удалена", nested.answers[0][0])
            self.assertFalse(nested_path.exists())
        finally:
            store.close()

    def test_miniapp_helpers_cover_url_and_markup_paths(self) -> None:
        self.assertEqual(build_mini_app_url("", screen="home"), "")
        self.assertEqual(build_mini_app_url("ftp://example.test", screen="home"), "")
        url = build_mini_app_url(
            "https://miniapp.example.test/app?from=bot",
            screen="search",
            query="metrics",
            note_id="n1",
            job_id="j1",
        )
        self.assertIn("screen=search", url)
        self.assertIn("q=metrics", url)
        self.assertIn("note_id=n1", url)
        self.assertIn("job_id=j1", url)
        markup = build_mini_app_markup(
            "https://miniapp.example.test/app",
            label="Open",
            screen="home",
        )
        self.assertIsNotNone(markup)
        self.assertEqual(markup.inline_keyboard[0][0].text, "Open")
        self.assertIsNone(build_mini_app_markup("", label="Open", screen="home"))


if __name__ == "__main__":
    unittest.main()
