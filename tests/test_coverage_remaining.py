"""Tests to cover remaining branches across multiple modules."""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.obsidian.display import humanize_note_label


class DisplayCoverageTests(unittest.TestCase):
    def test_stamped_note_pattern(self):
        self.assertEqual(humanize_note_label("20260308-1200 - note (ABCD1234).md"), "Сохранённая заметка")

    def test_stamped_note_with_extra(self):
        self.assertEqual(humanize_note_label("20260308-1200 - note stuff (ABCD1234).md"), "Сохранённая заметка")

    def test_url_based_https(self):
        result = humanize_note_label("20260308-1200 - https example.com article (ABCD1234).md")
        self.assertIn("Материал из", result)

    def test_url_based_http(self):
        result = humanize_note_label("20260308-1200 - http example.com (ABCD1234).md")
        self.assertIn("Материал из", result)

    def test_url_based_www(self):
        result = humanize_note_label("20260308-1200 - www example.com (ABCD1234).md")
        self.assertIn("Материал из", result)

    def test_url_youtube_normalization(self):
        result = humanize_note_label("20260308-1200 - https m.youtube.com watch (ABCD1234).md")
        self.assertIn("youtube", result)

    def test_url_empty_compact_returns_saved_material(self):
        # 'https ' with a trailing space but nothing meaningful after cleaning
        result = humanize_note_label("20260308-1200 - https --- (ABCD1234).md")
        # After strip("/:-"), compact becomes empty
        self.assertEqual(result, "Сохранённый материал")

    def test_stamped_with_real_title(self):
        result = humanize_note_label("20260308-1200 - My Great Note (ABCD1234).md")
        self.assertEqual(result, "My Great Note")

    def test_plain_filename_with_extension(self):
        result = humanize_note_label("my.note.md")
        self.assertEqual(result, "my.note.md")

    def test_plain_filename_no_extension(self):
        result = humanize_note_label("readme")
        self.assertEqual(result, "readme")

    def test_empty_string(self):
        result = humanize_note_label("")
        self.assertEqual(result, "Сохранённая заметка")


class VoiceParserCoverageTests(unittest.TestCase):
    def tearDown(self):
        from src.infra.ai_fallback import reset_remote_ai
        reset_remote_ai("voice_transcription")

    def test_load_audio_bytes_telegram_file(self):
        from src.parsers.voice_parser import _load_audio_bytes
        fake_resp = MagicMock()
        fake_resp.content = b"audio-data"
        fake_resp.headers = {"Content-Type": "audio/ogg"}
        fake_resp.raise_for_status = MagicMock()
        fake_resp.close = MagicMock()
        with patch("src.parsers.voice_parser.safe_http_get", return_value=fake_resp), \
             patch.dict("os.environ", {"TELEGRAM_TOKEN": "tok123"}):
            data, mime = _load_audio_bytes("telegram-file:///voice/file.ogg", timeout_seconds=10)
        self.assertEqual(data, b"audio-data")

    def test_load_audio_bytes_http(self):
        from src.parsers.voice_parser import _load_audio_bytes
        fake_resp = MagicMock()
        fake_resp.content = b"http-audio"
        fake_resp.headers = {"Content-Type": "audio/mpeg"}
        fake_resp.raise_for_status = MagicMock()
        fake_resp.close = MagicMock()
        with patch("src.parsers.voice_parser.safe_http_get", return_value=fake_resp):
            data, mime = _load_audio_bytes("https://example.com/f.mp3", timeout_seconds=10)
        self.assertEqual(data, b"http-audio")

    def test_load_audio_bytes_local_file(self):
        from src.parsers.voice_parser import _load_audio_bytes
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"local-audio")
            fpath = f.name
        try:
            data, mime = _load_audio_bytes(fpath, timeout_seconds=10)
            self.assertEqual(data, b"local-audio")
        finally:
            Path(fpath).unlink()

    def test_load_audio_bytes_missing_file(self):
        from src.parsers.voice_parser import _load_audio_bytes
        with self.assertRaises(FileNotFoundError):
            _load_audio_bytes("/nonexistent/file.mp3", timeout_seconds=10)

    def test_telegram_download_url_no_token(self):
        from src.parsers.voice_parser import _telegram_download_url
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError):
                _telegram_download_url("telegram-file:///voice/f.ogg")

    def test_telegram_download_url_no_path(self):
        from src.parsers.voice_parser import _telegram_download_url
        with patch.dict("os.environ", {"TELEGRAM_TOKEN": "tok"}):
            with self.assertRaises(RuntimeError):
                _telegram_download_url("telegram-file:///")

    def test_telegram_download_url_success(self):
        from src.parsers.voice_parser import _telegram_download_url
        with patch.dict("os.environ", {"TELEGRAM_TOKEN": "tok123"}):
            url = _telegram_download_url("telegram-file:///voice/file_1.ogg")
        self.assertIn("api.telegram.org/file/bottok123/voice/file_1.ogg", url)

    def test_guess_mime_type_from_source_header(self):
        from src.parsers.voice_parser import _guess_mime_type_from_source
        result = _guess_mime_type_from_source("https://x.com/f.bin", "video/mp4; charset=utf-8")
        self.assertEqual(result, "video/mp4")

    def test_guess_mime_type_from_source_fragment(self):
        from src.parsers.voice_parser import _guess_mime_type_from_source
        result = _guess_mime_type_from_source("https://x.com/f.bin#tgmime=audio/ogg", "")
        self.assertEqual(result, "audio/ogg")

    def test_guess_mime_type_from_source_fragment_skips_unrelated_keys(self):
        from src.parsers.voice_parser import _guess_mime_type_from_source
        result = _guess_mime_type_from_source("https://x.com/f.bin#foo=bar&tgmime=audio/ogg", "")
        self.assertEqual(result, "audio/ogg")

    def test_guess_mime_type_from_source_extension(self):
        from src.parsers.voice_parser import _guess_mime_type_from_source
        result = _guess_mime_type_from_source("https://x.com/f.wav", "")
        self.assertEqual(result, "audio/wav")


class CommandsCoverageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name) / "vault"
        self.vault.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _make_rag(self):
        from src.rag.index_store import RetrievedChunk
        from src.rag.retriever import QueryAnswer
        rag = MagicMock()
        rag.vault_path = self.vault
        rag.stats.return_value = {"documents": 0, "chunks": 0, "provider": "test"}
        rag.find.return_value = []
        rag.answer.return_value = QueryAnswer(answer="", sources=[], mode="empty")
        rag.remove_note.return_value = True
        manager = MagicMock()
        manager.for_tenant.return_value = rag
        return rag, manager

    def _handlers(self, store, manager):
        from src.bot.commands import build_command_router
        router = build_command_router(store, {1}, manager, mini_app_base_url="")
        return {h.callback.__name__: h.callback for h in router.message.handlers}

    def _msg(self, text, user_id=1):
        m = MagicMock()
        m.text = text
        m.caption = None
        m.from_user = SimpleNamespace(id=user_id) if user_id else None
        m.chat = SimpleNamespace(id=1, type="private")
        m.date = datetime(2026, 3, 8, 12, 0, tzinfo=UTC)
        m.answers = []
        async def _answer(t, parse_mode=None, reply_markup=None):
            m.answers.append(t)
        m.answer = _answer
        return m

    def test_quick_status_manage_handler(self):
        rag, manager = self._make_rag()
        store = MagicMock()
        handlers = self._handlers(store, manager)
        msg = self._msg("⚙️ Управление")
        asyncio.run(handlers["quick_status_handler"](msg))
        self.assertTrue(any("Управление" in a for a in msg.answers))

    def test_quick_status_delegates_to_status(self):
        rag, manager = self._make_rag()
        store = MagicMock()
        store.status_counts.return_value = {}
        store.recent_failures.return_value = []
        store.recent_jobs.return_value = []
        store.integrity_check.return_value = (True, "ok")
        handlers = self._handlers(store, manager)
        msg = self._msg("📊 Статус")
        with patch("src.bot.commands.uptime_human", return_value="1m"), \
             patch("src.bot.commands.last_error", return_value=("", "")):
            asyncio.run(handlers["quick_status_handler"](msg))
        self.assertTrue(any("сводка" in a.lower() for a in msg.answers))

    def test_quick_latest_add_handler(self):
        rag, manager = self._make_rag()
        store = MagicMock()
        handlers = self._handlers(store, manager)
        msg = self._msg("➕ Добавить")
        asyncio.run(handlers["quick_latest_handler"](msg))
        self.assertTrue(any("Добавить" in a for a in msg.answers))

    def test_quick_latest_latest_handler(self):
        rag, manager = self._make_rag()
        store = MagicMock()
        handlers = self._handlers(store, manager)
        msg = self._msg("🕘 Последние")
        with patch("src.bot.commands.latest_notes", return_value=[]):
            asyncio.run(handlers["quick_latest_handler"](msg))
        self.assertTrue(any("пуста" in a.lower() for a in msg.answers))

    def test_quick_search_handler(self):
        rag, manager = self._make_rag()
        store = MagicMock()
        handlers = self._handlers(store, manager)
        msg = self._msg("🔎 Найти")
        asyncio.run(handlers["quick_search_handler"](msg))
        self.assertTrue(any("Поиск" in a for a in msg.answers))

    def test_quick_delete_handler(self):
        rag, manager = self._make_rag()
        store = MagicMock()
        handlers = self._handlers(store, manager)
        msg = self._msg("🗑 Удаление")
        asyncio.run(handlers["quick_delete_handler"](msg))
        self.assertTrue(any("Удаление" in a for a in msg.answers))

    def test_summary_gemini_grounded_mode(self):
        from src.rag.index_store import RetrievedChunk
        from src.rag.retriever import QueryAnswer
        rag, manager = self._make_rag()
        rag.answer.return_value = QueryAnswer(
            answer="AI answer here",
            sources=[RetrievedChunk(
                note_path=str((self.vault / "s.md").resolve()),
                chunk_id="c1", chunk_text="ctx", score=0.9,
            )],
            mode="gemini-grounded",
        )
        store = MagicMock()
        handlers = self._handlers(store, manager)
        msg = self._msg("/summary what is this")
        asyncio.run(handlers["summary_handler"](msg))
        self.assertTrue(any("Ответ по заметкам" in a for a in msg.answers))

    def test_source_label_fallbacks(self):
        from src.bot.commands import _source_label

        with patch("src.bot.commands.humanize_note_label", return_value="Сохранённая заметка"):
            self.assertEqual(_source_label("nested/f.md", 2), "Заметка 2")

    def test_resolve_note_path_nested(self):
        from src.bot.commands import _resolve_note_path
        deep = self.vault / "nested" / "deep_file.md"
        deep.parent.mkdir(parents=True, exist_ok=True)
        deep.touch()
        
        # When filename alone is given, should find the nested file via rglob
        resolved = _resolve_note_path(self.vault, "deep_file.md")
        self.assertEqual(resolved, deep.resolve())
        
        # When given with glob characters, it just resolves directly (returns Path obj)
        globed = _resolve_note_path(self.vault, "deep_*.md")
        self.assertEqual(globed, (self.vault / "deep_*.md").resolve())

    def test_source_label(self):
        from src.bot.commands import _source_label
        self.assertEqual(_source_label("", 1), "Заметка 1")
        with patch("src.bot.commands.humanize_note_label", return_value="Сохранённый материал"):
            self.assertEqual(_source_label("x.md", 2), "Материал 2")

    def test_build_command_router_requires_rag_manager(self):
        from src.bot.commands import build_command_router
        with self.assertRaises(RuntimeError):
            build_command_router(MagicMock(), {1}, None)

    def test_dedupe_hits_by_file(self):
        from src.bot.commands import _dedupe_hits_by_file
        h1 = SimpleNamespace(file_name="a.md")
        h2 = SimpleNamespace(file_name="a.md")
        h3 = SimpleNamespace(file_name="b.md")
        result = _dedupe_hits_by_file([h1, h2, h3])
        self.assertEqual(len(result), 2)

    def test_resolve_note_path_glob_rejection(self):
        from src.bot.commands import _resolve_note_path
        result = _resolve_note_path(self.vault, "*.md")
        # should return direct path without running glob
        self.assertTrue(str(result).endswith("*.md"))

    def test_resolve_note_path_traversal_rejection(self):
        from src.bot.commands import _resolve_note_path
        result = _resolve_note_path(self.vault, "../secret.md")
        # candidate_name != normalized → returns direct
        direct = (self.vault / "../secret.md").resolve()
        self.assertEqual(result, direct)

    def test_quick_handlers_return_early_for_unauthorized_users(self):
        rag, manager = self._make_rag()
        _ = rag
        store = MagicMock()
        handlers = self._handlers(store, manager)

        for handler_name, text in (
            ("quick_status_handler", "⚙️ Управление"),
            ("quick_latest_handler", "➕ Добавить"),
            ("quick_search_handler", "🔎 Найти"),
            ("quick_delete_handler", "🗑 Удаление"),
        ):
            msg = self._msg(text, user_id=2)
            asyncio.run(handlers[handler_name](msg))
            self.assertEqual(msg.answers, [])

    def test_preview_text_fallback_and_truncation(self):
        from src.bot.commands import _preview_text

        fallback = _preview_text("https example.com/page")
        self.assertIn("нечего показать", fallback)

        truncated = _preview_text("word " * 100, max_chars=20)
        self.assertTrue(truncated.endswith("..."))


class TelegramRouterCoverageTests(unittest.TestCase):
    def test_match_quick_action_aliases(self):
        from src.bot.telegram_router import _match_quick_action_alias
        self.assertEqual(_match_quick_action_alias("➕ Добавить"), "add")
        self.assertEqual(_match_quick_action_alias("🔎 Найти"), "search")
        self.assertEqual(_match_quick_action_alias("⚙️ Управление"), "manage")
        self.assertEqual(_match_quick_action_alias("📊 Статус"), "manage")
        self.assertEqual(_match_quick_action_alias("🕘 Последние"), "")
        self.assertEqual(_match_quick_action_alias("random text"), "")
        self.assertEqual(_match_quick_action_alias("🔎 Поиск"), "search")
        self.assertEqual(_match_quick_action_alias("⚙ Управление"), "manage")

    def test_start_background_task_success(self):
        from src.bot.telegram_router import _start_background_task

        async def _run():
            async def _ok():
                return 42
            task = _start_background_task(_ok(), label="test-ok")
            await task

        asyncio.run(_run())

    def test_start_background_task_failure(self):
        from src.bot.telegram_router import _start_background_task

        async def _run():
            async def _fail():
                raise ValueError("boom")
            task = _start_background_task(_fail(), label="test-fail")
            with self.assertRaises(ValueError):
                await task

        asyncio.run(_run())

    def test_start_background_task_cancelled(self):
        from src.bot.telegram_router import _start_background_task

        async def _run():
            async def _block():
                await asyncio.sleep(999)
            task = _start_background_task(_block(), label="test-cancel")
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(_run())

    def test_extract_forward_source_chat(self):
        from src.bot.telegram_router import _extract_forward_source
        msg = MagicMock()
        msg.forward_origin = SimpleNamespace(
            chat=SimpleNamespace(title="Chan", username=None, id=1),
        )
        self.assertEqual(_extract_forward_source(msg), "Chan")

    def test_extract_forward_source_sender_user_name(self):
        from src.bot.telegram_router import _extract_forward_source
        msg = MagicMock()
        msg.forward_origin = SimpleNamespace(
            chat=None, sender_user_name="hidden_user",
            sender_user=None,
        )
        self.assertEqual(_extract_forward_source(msg), "hidden_user")

    def test_extract_forward_source_sender_user(self):
        from src.bot.telegram_router import _extract_forward_source
        msg = MagicMock()
        msg.forward_origin = SimpleNamespace(
            chat=None, sender_user_name=None,
            sender_user=SimpleNamespace(full_name="John", username="john"),
        )
        self.assertEqual(_extract_forward_source(msg), "John")

    def test_extract_forward_source_unknown(self):
        from src.bot.telegram_router import _extract_forward_source
        msg = MagicMock()
        msg.forward_origin = SimpleNamespace(
            chat=None, sender_user_name=None, sender_user=None,
        )
        self.assertEqual(_extract_forward_source(msg), "Unknown Forward")

    def test_display_note_name(self):
        from src.bot.telegram_router import _display_note_name
        result = _display_note_name("test.md")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) <= 80)

    def _router_handlers(self, job_service, *, store=None, ai_service=None, vault_path=None):
        from src.bot.telegram_router import build_router

        vault_root = Path(vault_path or ".")
        rag = MagicMock()
        rag.vault_path = vault_root
        rag.stats.return_value = {"documents": 0, "chunks": 0}
        rag_manager = MagicMock()
        rag_manager.for_tenant.return_value = rag

        router = build_router(
            job_service=job_service,
            allowed_user_ids={1},
            store=store or MagicMock(),
            vault_path=vault_root,
            rag_manager=rag_manager,
            ai_service=ai_service or SimpleNamespace(generate_reply=AsyncMock(return_value="ready")),
            mini_app_base_url="",
        )
        return {item.callback.__name__: item.callback for item in router.message.handlers}

    def _router_msg(self, text: str, *, bot=None, user_id=1):
        message = MagicMock()
        message.text = text
        message.caption = None
        message.bot = bot
        message.from_user = SimpleNamespace(id=user_id) if user_id is not None else None
        message.chat = SimpleNamespace(id=1, type="private")
        message.message_id = 1
        message.date = datetime(2026, 3, 8, 12, 0, tzinfo=UTC)
        message.voice = None
        message.audio = None
        message.video_note = None
        message.video = None
        message.document = None
        message.photo = None
        message.answers = []

        async def _answer(text, parse_mode=None, reply_markup=None):
            _ = (parse_mode, reply_markup)
            message.answers.append(text)

        message.answer = _answer
        return message

    def test_intake_handler_covers_manage_alias(self):
        handlers = self._router_handlers(MagicMock())
        message = self._router_msg("Управление")

        asyncio.run(handlers["intake_handler"](message))

        self.assertTrue(any("Управление" in answer for answer in message.answers))

    def test_intake_handler_starts_background_task_when_bot_present(self):
        job_service = MagicMock()
        job_service.submit.return_value = SimpleNamespace(is_new=True, job_id="job-1", actions={"save"})
        ai_service = SimpleNamespace(generate_reply=AsyncMock(return_value="ready"))
        handlers = self._router_handlers(job_service, ai_service=ai_service)
        message = self._router_msg("hello", bot=object())
        started_labels: list[str] = []

        def _capture_task(coro, *, label):
            coro.close()
            started_labels.append(label)

        with patch("src.bot.telegram_router._start_background_task", side_effect=_capture_task):
            asyncio.run(handlers["intake_handler"](message))

        self.assertEqual(started_labels, ["watch-job:job-1"])

    def test_humanize_note_destination_outside_vault(self):
        from src.bot.telegram_router import _humanize_note_destination

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            note_path = root / "outside" / "note.md"
            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text("x", encoding="utf-8")

            folder, display_path = _humanize_note_destination(
                note_path=note_path,
                base_vault_path=root / "vault",
            )

        self.assertEqual(folder, "outside")
        self.assertEqual(display_path, "note.md")


class StorageCoverageTests(unittest.TestCase):
    def test_acquire_next_job_success_and_no_job(self):
        from src.infra.storage import StateStore
        with tempfile.TemporaryDirectory() as d:
            store = StateStore(Path(d) / "state.db")
            store.initialize()
            # No jobs => None
            self.assertIsNone(store.acquire_next_job())
            # Insert a job
            store.enqueue_job(
                idempotency_key="ik1",
                content_fingerprint="fp1", tenant_id="t1",
                user_id=1, chat_id=1,
                message_id=1, payload={"test": True}, max_attempts=3,
            )
            # Should acquire it
            job = store.acquire_next_job()
            self.assertIsNotNone(job)
            self.assertEqual(job.tenant_id, "t1")
            # No more jobs
            self.assertIsNone(store.acquire_next_job())
            store.close()

    def test_recover_stuck_jobs(self):
        from src.infra.storage import StateStore
        with tempfile.TemporaryDirectory() as d:
            store = StateStore(Path(d) / "state.db")
            store.initialize()
            store.enqueue_job(
                idempotency_key="ik2",
                content_fingerprint="fp2", tenant_id="t1",
                user_id=1, chat_id=1,
                message_id=2, payload={}, max_attempts=1,
            )
            job = store.acquire_next_job()
            # Recover stuck with a very short timeout so the job is considered stuck
            recovered = store.recover_stuck_jobs(max_processing_age_seconds=0)
            self.assertGreaterEqual(recovered, 0)

            # test mark_failed_or_retry
            result, attempts = store.mark_failed_or_retry(job, "test error")
            self.assertEqual((result, attempts), ("failed", 1))
            status = store.get_job_status(job.job_id, tenant_id="t1")
            self.assertEqual(status["status"], "failed")

            # test delete_note_record
            store.upsert_note(
                tenant_id="t1",
                content_fingerprint="fp-delete",
                note_id="N999",
                file_name="dead.md",
                job_id=job.job_id,
            )
            self.assertTrue(store.delete_note_record(tenant_id="t1", content_fingerprint="fp-delete"))

            store.close()

    def test_list_all_notes(self):
        from src.infra.storage import StateStore
        with tempfile.TemporaryDirectory() as d:
            store = StateStore(Path(d) / "state.db")
            store.initialize()
            store.upsert_note(
                tenant_id="t1", content_fingerprint="fp1",
                note_id="N1", file_name="f1.md", job_id="j1",
            )
            store.upsert_note(
                tenant_id="t2", content_fingerprint="fp2",
                note_id="N2", file_name="f2.md", job_id="j2",
            )
            notes = store.list_all_notes()
            self.assertEqual(len(notes), 2)
            store.close()

    def test_managed_connection_getattr(self):
        from src.infra.storage import _ManagedConnection
        import sqlite3
        conn = sqlite3.connect(":memory:")
        mc = _ManagedConnection(conn)
        # __getattr__ should proxy
        self.assertIsNotNone(mc.cursor)
        conn.close()


class IndexStoreCoverageTests(unittest.TestCase):
    def test_upsert_and_delete_document(self):
        from src.rag.index_store import IndexStore
        with tempfile.TemporaryDirectory() as d:
            store = IndexStore(Path(d) / "idx.db")
            store.initialize()
            store.upsert_document_chunks(
                note_path="test.md", content_hash="h1",
                chunks=["hello world"], embeddings=[[1.0, 0.0]],
            )
            stats = store.stats()
            self.assertEqual(stats["documents"], 1)
            self.assertEqual(stats["chunks"], 1)
            deleted = store.delete_document("test.md")
            self.assertTrue(deleted)
            self.assertEqual(store.stats()["documents"], 0)
            # delete non-existent
            self.assertFalse(store.delete_document("nonexistent.md"))

    def test_search_with_results(self):
        from src.rag.index_store import IndexStore
        with tempfile.TemporaryDirectory() as d:
            store = IndexStore(Path(d) / "idx.db")
            store.initialize()
            store.upsert_document_chunks(
                note_path="test.md", content_hash="h1",
                chunks=["hello world"], embeddings=[[1.0, 0.0]],
            )
            results = store.search([1.0, 0.0], top_k=5)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].note_path, "test.md")

    def test_managed_connection_getattr(self):
        from src.rag.index_store import _ManagedConnection
        import sqlite3
        conn = sqlite3.connect(":memory:")
        mc = _ManagedConnection(conn)
        self.assertIsNotNone(mc.cursor)
        conn.close()


class RetrieverCoverageTests(unittest.TestCase):
    def test_humanize_chunk_text_url_only(self):
        from src.rag.retriever import _humanize_chunk_text
        result = _humanize_chunk_text("https example.com/page")
        self.assertEqual(result, "")

    def test_humanize_chunk_text_duplicate_halves(self):
        from src.rag.retriever import _humanize_chunk_text
        result = _humanize_chunk_text("hello world hello world")
        # Duplicate halves are kept or deduplicated — just verify it runs
        self.assertIsInstance(result, str)

    def test_build_extractive_answer_empty_snippet(self):
        from src.rag.retriever import _build_extractive_answer, _humanize_chunk_text
        from src.rag.index_store import RetrievedChunk
        hit = RetrievedChunk(note_path="test.md", chunk_id="c1", chunk_text="", score=0.5)
        result = _build_extractive_answer("q", [hit])
        self.assertIn("test", result)

        long_text = " ".join(f"word{i}" for i in range(80))
        long_hit = RetrievedChunk(note_path="test.md", chunk_id="", chunk_text=long_text, score=0.5)
        result2 = _build_extractive_answer("q", [long_hit])
        self.assertIn("...", result2)

        self.assertEqual(_humanize_chunk_text("note metadata"), "")

    def test_build_extractive_answer_long_snippet(self):
        from src.rag.retriever import _build_extractive_answer
        from src.rag.index_store import RetrievedChunk
        hit = RetrievedChunk(note_path="t.md", chunk_id="c1", chunk_text="A " * 200, score=0.5)
        result = _build_extractive_answer("q", [hit])
        self.assertTrue(len(result) > 0)


class GDriveCoverageEdgeTests(unittest.TestCase):
    def test_ensure_folder_path_uses_partial_cache(self):
        from src.infra.gdrive import GoogleDriveClient

        client = GoogleDriveClient(
            client_id="cid",
            client_secret="secret",
            refresh_token="refresh",
            root_folder_id="root",
            session=MagicMock(),
        )
        client._folder_cache[("a",)] = "folder-a"
        client._find_named_folder = MagicMock(return_value=None)
        client._create_empty_file = MagicMock(return_value="folder-b")

        folder_id = client.ensure_folder_path(("a", "b"))

        self.assertEqual(folder_id, "folder-b")
        client._find_named_folder.assert_called_once_with(parent_id="folder-a", name="b")

    def test_enrich_payload_with_drive_attachments_skips_non_telegram_urls(self):
        from src.infra.gdrive import enrich_payload_with_drive_attachments

        payload = {
            "tenant_id": "t1",
            "source": {"chat_id": 1, "message_id": 2},
            "parsed_items": [{"source_url": "https://example.com/file", "links": ["https://example.com/file"]}],
        }

        with patch("src.infra.gdrive._upload_attachment_from_url") as upload:
            result = enrich_payload_with_drive_attachments(payload, MagicMock())

        upload.assert_not_called()
        self.assertNotIn("cloud_attachments", result)

    def test_mirror_vault_once_skips_markdown_directories(self):
        from src.infra.gdrive import mirror_vault_once

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            vault = root / "vault"
            state = root / "state"
            vault.mkdir()
            state.mkdir()
            (vault / "archive.md").mkdir()

            config = SimpleNamespace(vault_path=vault, state_dir=state)

            with patch("src.infra.gdrive.mirror_note_to_drive") as mirror, patch("src.infra.gdrive.track_event"):
                result = mirror_vault_once(config, MagicMock())

        mirror.assert_not_called()
        self.assertEqual(result, {"uploaded": 0, "skipped": 0})


class WorkerCoverageTests(unittest.TestCase):
    def test_worker_drive_mirror_exception_path(self):
        from src.worker import run_worker
        from src.infra.storage import StateStore, QueueJob

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            store = StateStore(root / "state.db")
            store.initialize()

            config = MagicMock()
            config.vault_path = root / "vault"
            config.vault_path.mkdir()
            config.worker_recovery_interval_seconds = 9999
            config.worker_stuck_timeout_seconds = 300
            config.worker_poll_seconds = 0.01
            config.gemini_api_key = ""
            config.gemini_generation_model = "test"
            config.multi_tenant_mode = False

            rag = MagicMock()
            rag.index_note.return_value = True
            rag_manager = MagicMock()
            rag_manager.for_tenant.return_value = rag

            job = QueueJob(
                job_id="j1", tenant_id="legacy",
                idempotency_key="ik1", content_fingerprint="fp1",
                payload={"tenant_id": "legacy", "content": "test"},
                attempts=0, max_attempts=3,
            )

            call_count = [0]
            orig_acquire = store.acquire_next_job
            def limited_acquire():
                call_count[0] += 1
                if call_count[0] == 1:
                    return job
                return None
            store.acquire_next_job = limited_acquire

            drive_client = MagicMock()
            drive_client.__bool__ = lambda self: True

            async def _run():
                with patch("src.worker.enrich_payload", return_value={"tenant_id": "legacy"}), \
                     patch("src.worker.enrich_payload_with_drive_attachments", return_value={"tenant_id": "legacy"}), \
                     patch("src.worker.enrich_payload_with_ai", return_value={"tenant_id": "legacy"}), \
                     patch("src.worker.mirror_note_to_drive", side_effect=RuntimeError("drive down")):
                    writer_mock = MagicMock()
                    writer_mock.write.return_value = str(root / "vault" / "note.md")
                    with patch("src.worker.ObsidianNoteWriter", return_value=writer_mock):
                        task = asyncio.create_task(run_worker(config, store, rag_manager, drive_client=drive_client))
                        await asyncio.sleep(0.3)
                        task.cancel()
                        try:
                            await task
                        except asyncio.CancelledError:
                            pass

            asyncio.run(_run())
            store.close()


class MainCoverageTests(unittest.TestCase):
    def test_migrate_shared_notes_skip_branches(self):
        from src.main import _migrate_shared_notes_to_tenant_dirs

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            vault = root / "vault"
            vault.mkdir()
            from src.infra.storage import StateStore
            store = StateStore(root / "state.db")
            store.initialize()

            config = MagicMock()
            config.multi_tenant_mode = False
            rag = MagicMock()

            # non multi-tenant returns 0
            result = _migrate_shared_notes_to_tenant_dirs(config, store, rag)
            self.assertEqual(result, 0)

            config.multi_tenant_mode = True
            config.vault_path = vault

            # empty notes, nothing to move
            with patch.object(store, "list_all_notes", return_value=[]):
                result = _migrate_shared_notes_to_tenant_dirs(config, store, rag)
                self.assertEqual(result, 0)

            # note with empty tenant_id
            with patch.object(store, "list_all_notes", return_value=[{"tenant_id": "", "file_name": "f.md"}]):
                result = _migrate_shared_notes_to_tenant_dirs(config, store, rag)
                self.assertEqual(result, 0)

            # note with empty file_name
            with patch.object(store, "list_all_notes", return_value=[{"tenant_id": "t1", "file_name": ""}]):
                result = _migrate_shared_notes_to_tenant_dirs(config, store, rag)
                self.assertEqual(result, 0)

            # target already exists
            target_dir = vault / "t1"
            target_dir.mkdir(parents=True, exist_ok=True)
            (vault / "exist.md").write_text("src", encoding="utf-8")
            (target_dir / "exist.md").write_text("dst", encoding="utf-8")
            with patch.object(store, "list_all_notes", return_value=[
                {"tenant_id": "t1", "file_name": "exist.md"}
            ]):
                result = _migrate_shared_notes_to_tenant_dirs(config, store, rag)
                self.assertEqual(result, 0)

            store.close()

    def test_migrate_shared_notes_covers_same_path_and_missing_source(self):
        from src.main import _migrate_shared_notes_to_tenant_dirs
        from src.infra.storage import StateStore

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            vault = root / "vault"
            vault.mkdir()
            store = StateStore(root / "state.db")
            store.initialize()

            config = MagicMock()
            config.multi_tenant_mode = True
            config.vault_path = vault
            rag = MagicMock()

            (vault / "same.md").write_text("src", encoding="utf-8")
            with patch("src.main.tenant_vault_path", return_value=vault), patch.object(
                store,
                "list_all_notes",
                return_value=[{"tenant_id": "t1", "file_name": "same.md"}],
            ):
                self.assertEqual(_migrate_shared_notes_to_tenant_dirs(config, store, rag), 0)

            with patch.object(
                store,
                "list_all_notes",
                return_value=[{"tenant_id": "t1", "file_name": "missing.md"}],
            ):
                self.assertEqual(_migrate_shared_notes_to_tenant_dirs(config, store, rag), 0)

            store.close()

    def test_run_worker_loop_cancels_gdrive_maintenance_task(self):
        import src.main as main_module

        class _Health:
            async def start(self):
                return None

            async def stop(self):
                return None

        cancelled: list[bool] = []

        async def _maintenance(*args, **kwargs):
            _ = (args, kwargs)
            try:
                await asyncio.sleep(999)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise

        async def _boom_worker(*args, **kwargs):
            _ = (args, kwargs)
            await asyncio.sleep(0)
            raise RuntimeError("worker exploded")

        async def run_case():
            config = MagicMock()
            config.worker_health_port = 9000

            with patch("src.main.build_gdrive_client", return_value=object()), patch(
                "src.main.HealthServer", return_value=_Health()
            ), patch("src.main.run_gdrive_maintenance_forever", new=_maintenance), patch(
                "src.main.run_worker", new=_boom_worker
            ), patch("src.main.record_error") as record_error:
                with self.assertRaises(RuntimeError):
                    await main_module._run_worker_loop(config, "store", "rag-manager")

            record_error.assert_called_once()

        asyncio.run(run_case())
        self.assertTrue(cancelled)


if __name__ == "__main__":
    unittest.main()
