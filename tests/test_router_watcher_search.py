from __future__ import annotations

import asyncio
import sys
import tempfile
import types
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from aiogram.types import ReplyKeyboardMarkup

from src.bot.telegram_router import (
    _display_note_name,
    _extract_forward_source,
    _extract_telegram_media_url,
    _humanize_note_destination,
    _is_transcribable_media_message,
    _watch_job_and_notify,
    build_router,
)
from src.obsidian.search import find_notes, latest_notes
from src.watcher import _event_path, _run_polling_loop, _scan_markdown_files, run_watcher


class _FakeBot:
    def __init__(self, *, token: str = "token", file_path: str = "voice/file.ogg", fail_get: bool = False) -> None:
        self.token = token
        self.file_path = file_path
        self.fail_get = fail_get
        self.sent_messages: list[str] = []
        self.actions: list[str] = []

    async def get_file(self, file_id: str):
        _ = file_id
        if self.fail_get:
            raise RuntimeError("no file")
        return SimpleNamespace(file_path=self.file_path)

    async def send_chat_action(self, *, chat_id: int, action: str) -> None:
        _ = chat_id
        self.actions.append(action)

    async def send_message(self, *, chat_id: int, text: str, parse_mode: str, reply_markup=None) -> None:
        _ = (chat_id, parse_mode, reply_markup)
        self.sent_messages.append(text)


class _FakeMessage:
    def __init__(
        self,
        *,
        text: str | None = None,
        caption: str | None = None,
        user_id: int | None = 1,
        bot: _FakeBot | None = None,
        voice=None,
        audio=None,
        video=None,
        video_note=None,
        document=None,
        forward_origin=None,
    ) -> None:
        self.text = text
        self.caption = caption
        self.bot = bot
        self.voice = voice
        self.audio = audio
        self.video = video
        self.video_note = video_note
        self.document = document
        self.forward_origin = forward_origin
        self.date = datetime(2026, 3, 5, 12, 0, tzinfo=UTC)
        self.message_id = 7
        self.chat = SimpleNamespace(id=11, type="private")
        self.from_user = SimpleNamespace(id=user_id) if user_id is not None else None
        self.answers: list[str] = []
        self.reply_markups: list[object | None] = []

    async def answer(self, text: str, parse_mode: str | None = None, **kwargs) -> None:
        self.reply_markups.append(kwargs.get("reply_markup"))
        _ = parse_mode
        self.answers.append(text)


class _FakeJobService:
    def __init__(self, results: list[object]) -> None:
        self.results = list(results)

    def submit(self, request) -> object:
        self.last_request = request
        return self.results.pop(0)


class _FakeAIService:
    def __init__(self, reply: str = "saved") -> None:
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    async def generate_reply(self, raw_text: str, *, context_info: str = "") -> str:
        self.calls.append((raw_text, context_info))
        return self.reply


class _FakeRagManager:
    def for_tenant(self, tenant_id: str):
        _ = tenant_id
        return SimpleNamespace(vault_path=Path("."), stats=lambda: {"documents": 0, "chunks": 0})


def _router_handlers(job_service, allowed_user_ids, store=None, ai_service=None):
    router = build_router(
        job_service=job_service,
        allowed_user_ids=allowed_user_ids,
        store=store or MagicMock(),
        vault_path=Path("."),
        rag_manager=_FakeRagManager(),
        ai_service=ai_service or _FakeAIService(),
        mini_app_base_url="https://miniapp.example.test/app",
    )
    return {item.callback.__name__: item.callback for item in router.message.handlers}


class SearchHelpersTests(unittest.TestCase):
    def test_find_notes_and_latest_notes_cover_matches_and_read_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            alpha = vault / "alpha.md"
            beta = vault / "beta.md"
            alpha.write_text("# Alpha\nNeedle appears twice. Needle is here.", encoding="utf-8")
            beta.write_text("# Beta\nAnother note", encoding="utf-8")

            matches = find_notes(vault, "needle", limit=5)
            self.assertEqual(matches[0]["file_name"], "alpha.md")
            self.assertEqual(matches[0]["score"], "2")

            latest = latest_notes(vault, limit=2)
            self.assertEqual(len(latest), 2)

            original = Path.read_text

            def flaky_read_text(path_obj: Path, *args, **kwargs):
                if path_obj.name == "beta.md":
                    raise OSError("denied")
                return original(path_obj, *args, **kwargs)

            with patch("pathlib.Path.read_text", autospec=True, side_effect=flaky_read_text):
                self.assertTrue(find_notes(vault, "needle"))
                self.assertEqual(len(latest_notes(vault, limit=2)), 1)


class TelegramRouterRuntimeTests(unittest.TestCase):
    def test_text_intake_handler_covers_auth_empty_new_and_duplicate(self) -> None:
        results = [
            SimpleNamespace(is_new=True, job_id="job-1", actions={"save"}),
            SimpleNamespace(is_new=False, job_id="job-2", actions={"save"}),
        ]
        job_service = _FakeJobService(results)
        ai_service = _FakeAIService("ready")
        handlers = _router_handlers(job_service, {1}, ai_service=ai_service)

        unauthorized = _FakeMessage(text="hello", user_id=2)
        asyncio.run(handlers["intake_handler"](unauthorized))
        self.assertIn("Доступ закрыт", unauthorized.answers[0])

        missing_user = _FakeMessage(text="hello", user_id=None)
        asyncio.run(handlers["intake_handler"](missing_user))
        self.assertIn("Доступ закрыт", missing_user.answers[0])

        empty = _FakeMessage(text="   ")
        asyncio.run(handlers["intake_handler"](empty))
        self.assertIn("Пришли текст", empty.answers[0])

        created = _FakeMessage(text="hello #save")
        asyncio.run(handlers["intake_handler"](created))
        self.assertTrue(created.answers[0].startswith("ready"))
        self.assertEqual(ai_service.calls[0][0], "hello #save")
        self.assertIn("папкой", created.answers[0])

        duplicate = _FakeMessage(text="hello again")
        asyncio.run(handlers["intake_handler"](duplicate))
        self.assertIn("Дубликат пропущен", duplicate.answers[0])

    def test_router_keeps_only_ingest_specific_handlers(self) -> None:
        handlers = _router_handlers(_FakeJobService([]), {1}, store=MagicMock(), ai_service=_FakeAIService())
        self.assertIn("intake_handler", handlers)
        self.assertIn("media_intake_handler", handlers)
        self.assertNotIn("quick_status_button_handler", handlers)
        self.assertNotIn("quick_latest_button_handler", handlers)
        self.assertNotIn("quick_search_button_handler", handlers)
        self.assertNotIn("quick_delete_button_handler", handlers)

    def test_media_handlers_cover_failures_new_duplicate_and_ignore(self) -> None:
        results = [
            SimpleNamespace(is_new=True, job_id="job-1", actions={"save"}),
            SimpleNamespace(is_new=False, job_id="job-2", actions={"save"}),
        ]
        job_service = _FakeJobService(results)
        handlers = _router_handlers(job_service, {1})

        fail_message = _FakeMessage(voice=SimpleNamespace(file_id="f1"), bot=_FakeBot(fail_get=True))
        asyncio.run(handlers["intake_handler"](fail_message))
        self.assertIn("Ошибка чтения аудио", fail_message.answers[0])

        with patch("src.bot.telegram_router.asyncio.create_task") as create_task:
            success = _FakeMessage(
                voice=SimpleNamespace(file_id="f1"),
                caption="caption",
                bot=_FakeBot(file_path="voice/file.ogg"),
            )
            asyncio.run(handlers["intake_handler"](success))
            self.assertIn("Начинаю его транскрипцию", success.answers[0])
            self.assertIsInstance(success.reply_markups[0], ReplyKeyboardMarkup)
            create_task.assert_called_once()
            create_task.call_args[0][0].close()

        duplicate = _FakeMessage(
            voice=SimpleNamespace(file_id="f1"),
            bot=_FakeBot(file_path="voice/file.ogg"),
        )
        asyncio.run(handlers["media_intake_handler"](duplicate))
        self.assertIn("Дубликат пропущен", duplicate.answers[0])

        unauthorized = _FakeMessage(document=SimpleNamespace(mime_type="audio/mpeg", file_id="f1"), user_id=3)
        asyncio.run(handlers["media_intake_handler"](unauthorized))
        self.assertIn("Доступ закрыт", unauthorized.answers[0])

        missing_user = _FakeMessage(document=SimpleNamespace(mime_type="audio/mpeg", file_id="f1"), user_id=None)
        asyncio.run(handlers["media_intake_handler"](missing_user))
        self.assertIn("Доступ закрыт", missing_user.answers[0])

        ignored = _FakeMessage(document=SimpleNamespace(mime_type="text/plain", file_id="f1"))
        asyncio.run(handlers["media_intake_handler"](ignored))
        self.assertEqual(ignored.answers, [])

    def test_media_helpers_and_watch_job_cover_branches(self) -> None:
        bot = _FakeBot(file_path="")
        no_bot = _FakeMessage(voice=SimpleNamespace(file_id="f1"), bot=None)
        self.assertEqual(asyncio.run(_extract_telegram_media_url(no_bot)), "")

        empty_path = _FakeMessage(voice=SimpleNamespace(file_id="f1"), bot=bot)
        self.assertEqual(asyncio.run(_extract_telegram_media_url(empty_path)), "")

        url_message = _FakeMessage(
            audio=SimpleNamespace(file_id="f1", mime_type="audio/mpeg"),
            bot=_FakeBot(file_path="voice/file.ogg"),
        )
        media_url = asyncio.run(_extract_telegram_media_url(url_message))
        self.assertIn("#tgmime=audio%2Fmpeg", media_url)
        self.assertTrue(_is_transcribable_media_message(url_message))

        video_message = _FakeMessage(video=SimpleNamespace(file_id="f2", mime_type=""))
        self.assertTrue(_is_transcribable_media_message(video_message))

        class _Store:
            def __init__(self, rows):
                self.rows = list(rows)

            def get_job_status(self, job_id: str, tenant_id: str):
                _ = (job_id, tenant_id)
                return self.rows.pop(0)

        async def no_wait(delay: float) -> None:
            _ = delay

        with patch("src.bot.telegram_router.asyncio.sleep", side_effect=no_wait):
            status_missing_bot = _FakeBot()
            asyncio.run(_watch_job_and_notify(bot=status_missing_bot, store=_Store([None]), tenant_id="t", job_id="j", chat_id=1))
            self.assertIn("Статус недоступен", status_missing_bot.sent_messages[0])

            done_bot = _FakeBot()
            asyncio.run(
                _watch_job_and_notify(
                    bot=done_bot,
                    store=_Store([{"status": "done", "note_path": "C:/vault/20260305-1200 - Done (ABC12345).md"}]),
                    tenant_id="t",
                    job_id="j",
                    chat_id=1,
                    base_vault_path=Path("C:/vault"),
                )
            )
            self.assertIn("Done", done_bot.sent_messages[0])
            self.assertIn("Папка", done_bot.sent_messages[0])

            failed_bot = _FakeBot()
            asyncio.run(
                _watch_job_and_notify(
                    bot=failed_bot,
                    store=_Store([{"status": "failed", "error": "boom"}]),
                    tenant_id="t",
                    job_id="j",
                    chat_id=1,
                )
            )
            self.assertIn("boom", failed_bot.sent_messages[0])

            timeout_bot = _FakeBot()
            with patch.object(timeout_bot, "send_chat_action", side_effect=RuntimeError("typing failed")):
                asyncio.run(
                    _watch_job_and_notify(
                        bot=timeout_bot,
                        store=_Store([{"status": "processing"}, {"status": "processing"}]),
                        tenant_id="t",
                        job_id="j",
                        chat_id=1,
                        timeout_seconds=0,
                    )
                )
            self.assertIn("Материал всё ещё обрабатывается", timeout_bot.sent_messages[0])

        self.assertEqual(_display_note_name("20260305-1200 - Hello World (ABC12345).md"), "Hello World")
        self.assertEqual(_display_note_name("plain.md"), "plain")
        self.assertEqual(
            _humanize_note_destination(note_path=Path("C:/vault/tg_1/note.md"), base_vault_path=Path("C:/vault")),
            ("tg_1", "tg_1/note.md"),
        )
        self.assertEqual(_extract_forward_source(_FakeMessage(text="x")), None)
        self.assertEqual(
            _extract_forward_source(_FakeMessage(text="x", forward_origin=SimpleNamespace(chat=SimpleNamespace(title="T", username=None, id=1)))),
            "T",
        )
        self.assertEqual(
            _extract_forward_source(_FakeMessage(text="x", forward_origin=SimpleNamespace(chat=None, sender_user_name="user"))),
            "user",
        )
        self.assertEqual(
            _extract_forward_source(
                _FakeMessage(
                    text="x",
                    forward_origin=SimpleNamespace(chat=None, sender_user_name=None, sender_user=SimpleNamespace(full_name="Name", username="u")),
                )
            ),
            "Name",
        )
        self.assertEqual(
            _extract_forward_source(_FakeMessage(text="x", forward_origin=SimpleNamespace(chat=None, sender_user_name=None, sender_user=None))),
            "Unknown Forward",
        )


class WatcherRuntimeTests(unittest.TestCase):
    def test_event_path_and_scan_markdown_files(self) -> None:
        self.assertIsNone(_event_path(b"bytes"))
        self.assertEqual(_event_path("C:/note.md"), Path("C:/note.md"))

        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp)
            note = vault / "a.md"
            note.write_text("x", encoding="utf-8")
            snapshot = _scan_markdown_files(vault)
            self.assertIn(note.resolve(), snapshot)

            original_stat = Path.stat

            def flaky_stat(path_obj: Path):
                if path_obj.name == "a.md":
                    raise OSError("gone")
                return original_stat(path_obj)

            with patch("pathlib.Path.stat", autospec=True, side_effect=flaky_stat):
                self.assertEqual(_scan_markdown_files(vault), {})

    def test_run_polling_loop_detects_updates_and_deletes(self) -> None:
        processor = SimpleNamespace(handle_upsert=MagicMock(), handle_delete=MagicMock())
        config = SimpleNamespace(vault_path=Path("."), watcher_poll_seconds=0)
        first = {Path("gone.md"): 1.0, Path("same.md"): 1.0}
        second = {Path("same.md"): 2.0, Path("new.md"): 1.0}

        sleep_calls = {"count": 0}

        async def cancel_sleep(delay: float) -> None:
            _ = delay
            sleep_calls["count"] += 1
            if sleep_calls["count"] > 1:
                raise asyncio.CancelledError

        async def run_case() -> None:
            with patch("src.watcher._scan_markdown_files", side_effect=[first, second]), patch(
                "src.watcher.asyncio.sleep",
                side_effect=cancel_sleep,
            ):
                with self.assertRaises(asyncio.CancelledError):
                    await _run_polling_loop(config, processor)

        asyncio.run(run_case())
        processor.handle_delete.assert_called_once_with(Path("gone.md"))
        self.assertEqual(processor.handle_upsert.call_count, 2)

    def test_run_watcher_falls_back_to_polling_and_watchdog_handler_paths(self) -> None:
        config = SimpleNamespace(vault_path=Path("."), multi_tenant_mode=False)
        rag_manager = MagicMock()

        async def raise_import(config_obj, processor):
            _ = (config_obj, processor)
            raise ImportError("missing watchdog")

        async def stop_polling(config_obj, processor):
            _ = (config_obj, processor)
            raise asyncio.CancelledError

        async def run_case() -> None:
            with patch("src.watcher._run_watchdog_loop", side_effect=raise_import), patch(
                "src.watcher._run_polling_loop",
                side_effect=stop_polling,
            ):
                with self.assertRaises(asyncio.CancelledError):
                    await run_watcher(config, rag_manager)

        asyncio.run(run_case())

        event_module = types.ModuleType("watchdog.events")
        observer_module = types.ModuleType("watchdog.observers")
        observed_paths: list[Path] = []

        class FileSystemEvent:
            def __init__(self, src_path: str | bytes, *, is_directory: bool = False, dest_path: str | bytes = "") -> None:
                self.src_path = src_path
                self.dest_path = dest_path
                self.is_directory = is_directory

        class FileSystemEventHandler:
            pass

        class Observer:
            def schedule(self, handler, path: str, recursive: bool) -> None:
                _ = (path, recursive)
                self.handler = handler

            def start(self) -> None:
                self.handler.on_created(FileSystemEvent("created.md"))
                self.handler.on_modified(FileSystemEvent("modified.md"))
                self.handler.on_deleted(FileSystemEvent("deleted.md"))
                self.handler.on_moved(FileSystemEvent("old.md", dest_path="new.md"))
                self.handler.on_moved(FileSystemEvent(b"bytes.md", dest_path=b"bytes2.md"))

            def stop(self) -> None:
                return None

            def join(self, timeout: int) -> None:
                _ = timeout

        event_module.FileSystemEvent = FileSystemEvent
        event_module.FileSystemEventHandler = FileSystemEventHandler
        observer_module.Observer = Observer
        processor = SimpleNamespace(
            handle_upsert=lambda path: observed_paths.append(path),
            handle_delete=lambda path: observed_paths.append(path),
        )

        async def cancel_after_tick(delay: float) -> None:
            _ = delay
            raise asyncio.CancelledError

        async def run_watchdog_case() -> None:
            with patch.dict(sys.modules, {"watchdog.events": event_module, "watchdog.observers": observer_module}), patch(
                "src.watcher.asyncio.sleep",
                side_effect=cancel_after_tick,
            ):
                from src.watcher import _run_watchdog_loop

                with self.assertRaises(asyncio.CancelledError):
                    await _run_watchdog_loop(SimpleNamespace(vault_path=Path(".")), processor)

        asyncio.run(run_watchdog_case())
        self.assertIn(Path("created.md"), observed_paths)
        self.assertIn(Path("new.md"), observed_paths)


if __name__ == "__main__":
    unittest.main()
