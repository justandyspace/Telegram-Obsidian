from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import src.main as main_module
from src.bot.commands import build_command_router
from src.bot.telegram_router import _watch_job_and_notify, build_router
from src.config import AppConfig
from src.obsidian.note_writer import ObsidianNoteWriter
from src.watcher import NoteEventProcessor
from src.worker import run_worker


class CmdMessage:
    def __init__(self, text: str, *, user_id: int | None = 1, chat_type: str = "private") -> None:
        self.text = text
        self.caption = None
        self.date = datetime(2026, 3, 5, 12, 0, tzinfo=UTC)
        self.chat = SimpleNamespace(id=1, type=chat_type)
        self.from_user = SimpleNamespace(id=user_id) if user_id is not None else None
        self.answers: list[str] = []

    async def answer(self, text: str, parse_mode: str | None = None, **kwargs) -> None:
        _ = kwargs
        _ = parse_mode
        self.answers.append(text)


class RouteMessage:
    def __init__(
        self,
        *,
        text: str | None = None,
        user_id: int | None = 1,
        date: datetime | None = None,
        voice=None,
        bot=None,
        chat_type: str = "private",
    ) -> None:
        self.text = text
        self.caption = None
        self.voice = voice
        self.audio = None
        self.video = None
        self.video_note = None
        self.document = None
        self.bot = bot
        self.chat = SimpleNamespace(id=1, type=chat_type)
        self.from_user = SimpleNamespace(id=user_id) if user_id is not None else None
        self.date = date or datetime(2026, 3, 5, 12, 0, tzinfo=UTC)
        self.message_id = 10
        self.answers: list[str] = []

    async def answer(self, text: str, parse_mode: str | None = None, **kwargs) -> None:
        _ = kwargs
        _ = parse_mode
        self.answers.append(text)


class RouterBot:
    def __init__(self) -> None:
        self.token = "token"
        self.messages: list[str] = []

    async def get_file(self, file_id: str):
        _ = file_id
        return SimpleNamespace(file_path="voice/file.ogg")

    async def send_chat_action(self, *, chat_id: int, action: str) -> None:
        _ = (chat_id, action)
        raise RuntimeError("typing fail")

    async def send_message(self, *, chat_id: int, text: str, parse_mode: str, reply_markup=None) -> None:
        _ = (chat_id, parse_mode, reply_markup)
        self.messages.append(text)


class JobService:
    def __init__(self, results: list[object]) -> None:
        self._results = list(results)

    def submit(self, request) -> object:
        self.last_request = request
        return self._results.pop(0)


class AIService:
    async def generate_reply(self, raw_text: str, *, context_info: str = "") -> str:
        return f"{raw_text}|{context_info}"


class StoreRows:
    def __init__(self, rows: list[dict[str, object] | None]) -> None:
        self.rows = list(rows)

    def get_job_status(self, job_id: str, tenant_id: str):
        _ = (job_id, tenant_id)
        return self.rows.pop(0)


def command_handlers(store, rag_manager, vault_path: Path, allowed: set[int] | None = None):
    router = build_command_router(
        store,
        allowed or {1},
        rag_manager,
        mini_app_base_url="https://miniapp.example.test/app",
    )
    return {item.callback.__name__: item.callback for item in router.message.handlers}


def telegram_handlers(job_service, *, allowed_user_ids: set[int], store=None, ai_service=None):
    router = build_router(
        job_service=job_service,
        allowed_user_ids=allowed_user_ids,
        store=store or MagicMock(),
        vault_path=Path("."),
        rag_manager=MagicMock(),
        ai_service=ai_service or AIService(),
        mini_app_base_url="https://miniapp.example.test/app",
    )
    return {item.callback.__name__: item.callback for item in router.message.handlers}


class MainSession:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class MainBot:
    def __init__(self, token: str) -> None:
        self.token = token
        self.session = MainSession()

    async def delete_webhook(self, **kwargs) -> None:
        _ = kwargs

    async def set_webhook(self, **kwargs) -> None:
        _ = kwargs


class MainDispatcher:
    def __init__(self, behavior=None) -> None:
        self.behavior = behavior
        self.included: list[object] = []

    def include_router(self, router: object) -> None:
        self.included.append(router)

    async def start_polling(self, bot: object) -> None:
        _ = bot
        if self.behavior is not None:
            await self.behavior()


class MainHealthServer:
    instances: list[MainHealthServer] = []

    def __init__(self, host: str, port: int, is_ready) -> None:
        self.is_ready = is_ready
        MainHealthServer.instances.append(self)

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


class RuntimeCompletionTests(unittest.TestCase):
    def test_command_router_covers_remaining_status_and_delete_branches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            vault.mkdir()
            rag = SimpleNamespace(vault_path=vault, stats=lambda: {"documents": 0, "chunks": 0}, remove_note=lambda note: True)
            rag_manager = SimpleNamespace(for_tenant=lambda tenant_id: rag)
            store = MagicMock()
            store.status_counts.return_value = {}
            store.recent_failures.return_value = []
            store.recent_jobs.return_value = []
            store.integrity_check.return_value = (True, "ok")
            handlers = command_handlers(store, rag_manager, vault)

            with patch("src.bot.commands.last_error", return_value=("", "")), patch(
                "src.bot.commands.uptime_human",
                return_value="00:00:01",
            ):
                status = CmdMessage("/status")
                asyncio.run(handlers["status_handler"](status))
            status_text = status.answers[0]
            self.assertIn("Короткая сводка", status_text)
            self.assertIn("Очередь пуста", status_text)
            self.assertIn("Ошибок в последних задачах не вижу", status_text)
            self.assertIn("Runtime: <b>без ошибок</b>", status_text)

            self.assertEqual(asyncio.run(_denied_answer(command_handlers(store, rag_manager, vault, allowed={1})["find_handler"], CmdMessage("/find", user_id=9))), [])
            self.assertEqual(asyncio.run(_denied_answer(command_handlers(store, rag_manager, vault, allowed={1})["summary_handler"], CmdMessage("/summary", user_id=9))), [])
            self.assertEqual(asyncio.run(_denied_answer(command_handlers(store, rag_manager, vault, allowed={1})["retry_handler"], CmdMessage("/retry", user_id=9))), [])
            self.assertEqual(asyncio.run(_denied_answer(command_handlers(store, rag_manager, vault, allowed={1})["job_handler"], CmdMessage("/job", user_id=9))), [])
            self.assertEqual(asyncio.run(_denied_answer(command_handlers(store, rag_manager, vault, allowed={1})["delete_handler"], CmdMessage("/delete x", user_id=9))), [])

            from src.infra.storage import StateStore

            real_store = StateStore(Path(tmp) / "state.sqlite3")
            real_store.initialize()
            try:
                handlers = command_handlers(real_store, rag_manager, vault)
                request = CmdMessage("/delete all")
                asyncio.run(handlers["delete_handler"](request))
                cancel = CmdMessage("/delete cancel")
                asyncio.run(handlers["delete_handler"](cancel))
                self.assertIn("Ожидающее подтверждение удалено", cancel.answers[0])
            finally:
                real_store.close()

            fake_store = MagicMock()
            fake_store.consume_delete_all_confirmation.return_value = (True, "confirmed")
            fake_store.list_notes.return_value = [{"file_name": "../outside.md"}]
            fake_store.delete_all_note_records.return_value = 0
            handlers = command_handlers(fake_store, rag_manager, vault)
            confirm = CmdMessage("/delete confirm ABC12345")
            asyncio.run(handlers["delete_handler"](confirm))
            self.assertIn("Файлов удалено: <b>0</b>", confirm.answers[0])

            legacy_message = CmdMessage("/status", user_id=None)
            with patch("src.bot.commands.is_authorized_user", return_value=True), patch(
                "src.bot.commands.last_error",
                return_value=("", ""),
            ), patch(
                "src.bot.commands.uptime_human",
                return_value="00:00:01",
            ):
                asyncio.run(command_handlers(store, rag_manager, vault)["status_handler"](legacy_message))
            store.status_counts.assert_any_call(tenant_id="legacy")

    def test_telegram_router_covers_unsupported_naive_dates_and_notify_paths(self) -> None:
        handlers = telegram_handlers(
            JobService(
                [
                    SimpleNamespace(is_new=True, job_id="job-1", actions={"save"}),
                    SimpleNamespace(is_new=True, job_id="job-2", actions={"save"}),
                ]
            ),
            allowed_user_ids={1},
            store=MagicMock(),
        )

        unsupported = RouteMessage(text="hello", user_id=None)
        with patch("src.bot.telegram_router.is_authorized_user", return_value=True):
            asyncio.run(handlers["intake_handler"](unsupported))
        self.assertIn("Не удалось определить источник", unsupported.answers[0])

        naive = RouteMessage(text="hello", date=datetime(2026, 3, 5, 12, 0))
        with patch("src.bot.telegram_router.is_authorized_user", return_value=True):
            asyncio.run(handlers["intake_handler"](naive))
        self.assertIn("hello|Действия: save", naive.answers[0])
        self.assertIn("папкой", naive.answers[0])

        media_unsupported = RouteMessage(voice=SimpleNamespace(file_id="f1"), user_id=None, bot=RouterBot())
        with patch("src.bot.telegram_router.is_authorized_user", return_value=True):
            asyncio.run(handlers["media_intake_handler"](media_unsupported))
        self.assertIn("Не удалось определить источник", media_unsupported.answers[0])

        media_naive = RouteMessage(voice=SimpleNamespace(file_id="f2"), bot=RouterBot(), date=datetime(2026, 3, 5, 12, 0))
        with patch("src.bot.telegram_router.is_authorized_user", return_value=True), patch(
            "src.bot.telegram_router.asyncio.create_task"
        ) as create_task:
            asyncio.run(handlers["media_intake_handler"](media_naive))
            create_task.call_args[0][0].close()
        self.assertIn("Начинаю его транскрипцию", media_naive.answers[0])

        bot = RouterBot()

        async def fast_sleep(delay: float) -> None:
            _ = delay

        with patch("src.bot.telegram_router.asyncio.sleep", side_effect=fast_sleep):
            asyncio.run(
                _watch_job_and_notify(
                    bot=bot,
                    store=StoreRows([{"status": "processing"}, {"status": "done", "note_path": ""}]),
                    tenant_id="t1",
                    job_id="j1",
                    chat_id=1,
                    timeout_seconds=10,
                    poll_seconds=1,
                )
            )
        self.assertIn("Материал обработан и сохранён", bot.messages[0])

    def test_main_runtime_and_worker_cover_remaining_lines(self) -> None:
        config = AppConfig(
            role="bot",
            telegram_token="token",
            telegram_allowed_user_id=1,
            telegram_allowed_user_ids=(1,),
            multi_tenant_mode=False,
            telegram_mode="polling",
            webhook_base_url="",
            webhook_bind_host="127.0.0.1",
            webhook_bind_port=8082,
            webhook_path="/telegram/webhook",
            webhook_secret_token="super-secret-token",
            mini_app_base_url="https://miniapp.example.test/app",
            vault_path=Path("."),
            state_dir=Path("."),
            cache_dir=Path("."),
            index_dir=Path("."),
            log_level="INFO",
            worker_poll_seconds=0.0,
            worker_recovery_interval_seconds=0.0,
            worker_stuck_timeout_seconds=600,
            watcher_poll_seconds=0.0,
            job_max_retries=2,
            bot_health_port=18080,
            worker_health_port=18081,
            gemini_api_key="",
            gemini_embed_model="embed",
            gemini_generation_model="gen",
        )

        bot1 = MainBot("token")
        bot2 = MainBot("token")
        calls = {"count": 0}

        async def polling_behavior() -> None:
            calls["count"] += 1
            if calls["count"] == 1:
                return
            raise asyncio.CancelledError

        async def run_polling_case() -> None:
            with patch("src.main.Bot", side_effect=[bot1, bot2]), patch(
                "src.main._build_dispatcher",
                side_effect=[MainDispatcher(polling_behavior), MainDispatcher(polling_behavior)],
            ):
                with self.assertRaises(asyncio.CancelledError):
                    await main_module._run_polling_forever(config, "store", "rag", lambda value: value)

        asyncio.run(run_polling_case())
        self.assertTrue(bot1.session.closed)
        self.assertTrue(bot2.session.closed)

        async def run_webhook_no_base() -> None:
            with self.assertRaises(RuntimeError):
                await main_module._run_webhook_forever(config, "store", "rag", lambda value: value, retry_forever=False)

        asyncio.run(run_webhook_no_base())

        class BrokenBot(MainBot):
            async def delete_webhook(self, **kwargs) -> None:
                _ = kwargs
                raise RuntimeError("cleanup fail")

        class BrokenRunner:
            async def setup(self) -> None:
                raise RuntimeError("webhook fail")

            async def cleanup(self) -> None:
                return None

        async def run_webhook_raise_case() -> None:
            with patch("src.main.Bot", return_value=BrokenBot("token")), patch(
                "src.main._build_dispatcher",
                return_value=MainDispatcher(),
            ), patch("src.main.web.Application", return_value="app"), patch(
                "src.main.SimpleRequestHandler",
                return_value=SimpleNamespace(register=lambda app, path: None),
            ), patch("src.main.setup_application"), patch(
                "src.main.web.AppRunner",
                return_value=BrokenRunner(),
            ), patch("src.main.web.TCPSite"), patch("src.main.LOGGER.warning") as warning:
                with self.assertRaises(RuntimeError):
                    await main_module._run_webhook_forever(
                        AppConfig(**{**config.__dict__, "webhook_base_url": "https://example.test"}),
                        "store",
                        "rag",
                        lambda value: value,
                        retry_forever=False,
                    )
                warning.assert_called()

        asyncio.run(run_webhook_raise_case())

        MainHealthServer.instances.clear()

        async def cancel_polling(cfg, store, rag, set_ready) -> None:
            _ = (cfg, store, rag)
            set_ready(True)
            raise asyncio.CancelledError

        async def cancel_webhook(cfg, store, rag, set_ready, *, retry_forever) -> None:
            _ = (cfg, store, rag, retry_forever)
            set_ready(True)
            raise asyncio.CancelledError

        async def run_bot_modes() -> None:
            with patch("src.main.HealthServer", side_effect=lambda host, port, ready: MainHealthServer(host, port, ready)), patch(
                "src.main._run_polling_forever",
                side_effect=cancel_polling,
            ), patch("src.main._run_webhook_forever", side_effect=cancel_webhook):
                with self.assertRaises(asyncio.CancelledError):
                    await main_module._run_bot_loop(AppConfig(**{**config.__dict__, "telegram_mode": "polling"}), "store", "rag")
                self.assertTrue(MainHealthServer.instances[-1].is_ready())
                with self.assertRaises(asyncio.CancelledError):
                    await main_module._run_bot_loop(AppConfig(**{**config.__dict__, "telegram_mode": "webhook", "webhook_base_url": "https://example.test"}), "store", "rag")
                self.assertTrue(MainHealthServer.instances[-1].is_ready())
                with self.assertRaises(asyncio.CancelledError):
                    await main_module._run_bot_loop(AppConfig(**{**config.__dict__, "telegram_mode": "auto", "webhook_base_url": "https://example.test"}), "store", "rag")

        asyncio.run(run_bot_modes())

        async def run_worker_loop_case() -> None:
            with patch("src.main.HealthServer", side_effect=lambda host, port, ready: MainHealthServer(host, port, ready)), patch(
                "src.main.run_worker",
                side_effect=asyncio.CancelledError,
            ):
                with self.assertRaises(asyncio.CancelledError):
                    await main_module._run_worker_loop(config, "store", "rag")
                self.assertFalse(MainHealthServer.instances[-1].is_ready())

        asyncio.run(run_worker_loop_case())

        async def no_sleep(delay: float) -> None:
            raise asyncio.CancelledError

        bad_store = MagicMock()
        bad_store.integrity_check.return_value = (False, "bad")
        with self.assertRaises(RuntimeError):
            asyncio.run(run_worker(config, bad_store, MagicMock()))

        good_store = MagicMock()
        good_store.integrity_check.return_value = (True, "ok")
        good_store.recover_stuck_jobs.return_value = 1
        good_store.acquire_next_job.return_value = None
        with patch("src.worker.asyncio.sleep", side_effect=no_sleep), patch("src.worker.LOGGER.warning") as warning:
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(run_worker(config, good_store, MagicMock()))
            warning.assert_called_once()

    def test_misc_helpers_cover_writer_and_processor_branches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            from src.infra.storage import StateStore

            root = Path(tmp)
            vault = root / "vault"
            vault.mkdir()
            store = StateStore(root / "state.sqlite3")
            store.initialize()
            try:
                writer = ObsidianNoteWriter(vault, store, multi_tenant=False)
                self.assertIn("body", writer._render_summary({"content": "body", "ai_summary": ""}, {"save"}))
                self.assertIn("Review:", writer._render_tasks({"title": "T", "content": "body"}))
            finally:
                store.close()

            processor = NoteEventProcessor(base_vault_path=vault, rag_manager=SimpleNamespace(for_tenant=lambda tenant_id: SimpleNamespace(index_note=lambda path: True, remove_note=lambda path: True)), multi_tenant=False)
            self.assertFalse(processor.handle_upsert(root / "missing.md"))
            self.assertFalse(processor.handle_delete(root / "outside.md"))


async def _denied_answer(handler, message: CmdMessage) -> list[str]:
    await handler(message)
    return message.answers


if __name__ == "__main__":
    unittest.main()
