from __future__ import annotations

import argparse
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import src.main as main_module
from src.config import AppConfig


class _FakeSession:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _FakeBot:
    def __init__(self, token: str) -> None:
        self.token = token
        self.session = _FakeSession()
        self.deleted = 0
        self.webhooks: list[dict[str, object]] = []

    async def delete_webhook(self, **kwargs) -> None:
        self.deleted += 1
        self.webhooks.append({"delete": kwargs})

    async def set_webhook(self, **kwargs) -> None:
        self.webhooks.append(kwargs)


class _FakeDispatcher:
    def __init__(self) -> None:
        self.included: list[object] = []
        self.behavior = None

    def include_router(self, router: object) -> None:
        self.included.append(router)

    async def start_polling(self, bot: object) -> None:
        _ = bot
        if self.behavior is not None:
            await self.behavior()


class _FakeHealthServer:
    def __init__(self, host: str, port: int, is_ready) -> None:
        self.host = host
        self.port = port
        self.is_ready = is_ready
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class _FakeRunner:
    def __init__(self, app: object) -> None:
        self.app = app
        self.cleaned = False

    async def setup(self) -> None:
        return None

    async def cleanup(self) -> None:
        self.cleaned = True


class _FakeSite:
    def __init__(self, runner: object, host: str, port: int) -> None:
        self.runner = runner
        self.host = host
        self.port = port
        self.started = False

    async def start(self) -> None:
        self.started = True


class MainRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.config = AppConfig(
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
            vault_path=self.root / "vault",
            state_dir=self.root / "state",
            cache_dir=self.root / "cache",
            index_dir=self.root / "index",
            log_level="INFO",
            worker_poll_seconds=0.01,
            worker_recovery_interval_seconds=30.0,
            worker_stuck_timeout_seconds=600,
            watcher_poll_seconds=2.0,
            job_max_retries=2,
            bot_health_port=18080,
            worker_health_port=18081,
            gemini_api_key="",
            gemini_embed_model="embed",
            gemini_generation_model="gen",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_build_dispatcher_wires_router(self) -> None:
        fake_dispatcher = _FakeDispatcher()
        with patch("src.main.Dispatcher", return_value=fake_dispatcher), patch(
            "src.main.AIService",
            return_value="ai-service",
        ) as ai_service, patch("src.main.build_router", return_value="router") as build_router:
            dp = main_module._build_dispatcher(self.config, "store", "rag-manager")

        self.assertIs(dp, fake_dispatcher)
        ai_service.assert_called_once()
        build_router.assert_called_once()
        self.assertEqual(fake_dispatcher.included, ["router"])

    def test_migrate_shared_notes_to_tenant_dirs_moves_root_notes(self) -> None:
        config = AppConfig(
            **{**self.config.__dict__, "multi_tenant_mode": True}
        )
        root_note = config.vault_path / "shared.md"
        root_note.parent.mkdir(parents=True, exist_ok=True)
        root_note.write_text("hello", encoding="utf-8")

        store = MagicMock()
        store.list_all_notes.return_value = [
            {"tenant_id": "tg_1", "file_name": "shared.md"},
        ]

        tenant_service = MagicMock()
        rag_manager = MagicMock()
        rag_manager.for_tenant.return_value = tenant_service

        moved = main_module._migrate_shared_notes_to_tenant_dirs(config, store, rag_manager)

        self.assertEqual(moved, 1)
        tenant_note = config.vault_path / "tg_1" / "shared.md"
        self.assertTrue(tenant_note.exists())
        self.assertFalse(root_note.exists())
        tenant_service.index_note.assert_called_once_with(tenant_note.resolve())

    def test_run_polling_forever_handles_retry_and_cleanup(self) -> None:
        readiness: list[bool] = []
        fake_bot = _FakeBot("token")
        dp = _FakeDispatcher()
        attempts = {"count": 0}

        async def polling_behavior() -> None:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RuntimeError("boom")
            raise asyncio.CancelledError

        dp.behavior = polling_behavior

        async def run_case() -> None:
            async def fake_sleep(delay: float) -> None:
                _ = delay
                raise asyncio.CancelledError

            with patch("src.main.Bot", return_value=fake_bot), patch(
                "src.main._build_dispatcher",
                return_value=dp,
            ), patch("src.main.record_error") as record_error, patch(
                "src.main.asyncio.sleep",
                side_effect=fake_sleep,
            ):
                with self.assertRaises(asyncio.CancelledError):
                    await main_module._run_polling_forever(
                        self.config,
                        "store",
                        "rag-manager",
                        readiness.append,
                    )
                record_error.assert_called()

        asyncio.run(run_case())
        self.assertIn(True, readiness)
        self.assertIn(False, readiness)
        self.assertTrue(fake_bot.session.closed)

    def test_run_webhook_forever_validates_and_cleans_up(self) -> None:
        readiness: list[bool] = []
        fake_bot = _FakeBot("token")
        dp = _FakeDispatcher()

        async def wait_forever() -> None:
            raise asyncio.CancelledError

        async def run_case() -> None:
            with patch("src.main.Bot", return_value=fake_bot), patch(
                "src.main._build_dispatcher",
                return_value=dp,
            ), patch("src.main.web.Application", return_value="app"), patch(
                "src.main.SimpleRequestHandler",
            ) as handler_cls, patch("src.main.setup_application"), patch(
                "src.main.web.AppRunner",
                return_value=_FakeRunner("app"),
            ), patch("src.main.web.TCPSite", side_effect=lambda runner, host, port: _FakeSite(runner, host, port)), patch(
                "src.main.asyncio.Event",
                return_value=SimpleNamespace(wait=wait_forever),
            ):
                handler = MagicMock()
                handler_cls.return_value = handler
                with self.assertRaises(asyncio.CancelledError):
                    await main_module._run_webhook_forever(
                        SimpleNamespace(**{**self.config.__dict__, "webhook_base_url": "https://example.test"}),
                        "store",
                        "rag-manager",
                        readiness.append,
                        retry_forever=False,
                    )

        asyncio.run(run_case())
        self.assertIn(True, readiness)
        self.assertTrue(fake_bot.session.closed)

    def test_run_webhook_forever_retries_when_requested(self) -> None:
        fake_bot = _FakeBot("token")

        async def fake_sleep(delay: float) -> None:
            _ = delay
            raise asyncio.CancelledError

        class _BrokenRunner(_FakeRunner):
            async def setup(self) -> None:
                raise RuntimeError("webhook fail")

        async def run_case() -> None:
            with patch("src.main.Bot", return_value=fake_bot), patch(
                "src.main._build_dispatcher",
                return_value=_FakeDispatcher(),
            ), patch("src.main.web.Application", return_value="app"), patch(
                "src.main.SimpleRequestHandler",
            ) as handler_cls, patch(
                "src.main.setup_application",
            ), patch(
                "src.main.web.AppRunner",
                return_value=_BrokenRunner("app"),
            ), patch(
                "src.main.asyncio.sleep",
                side_effect=fake_sleep,
            ), patch("src.main.record_error") as record_error:
                handler_cls.return_value = MagicMock()
                with self.assertRaises(asyncio.CancelledError):
                    await main_module._run_webhook_forever(
                        AppConfig(**{**self.config.__dict__, "webhook_base_url": "https://example.test"}),
                        "store",
                        "rag-manager",
                        lambda value: value,
                        retry_forever=True,
                    )
                record_error.assert_called()

        asyncio.run(run_case())
        self.assertTrue(fake_bot.session.closed)

    def test_run_bot_loop_covers_polling_webhook_and_auto(self) -> None:
        async def run_case() -> None:
            async def cancel_polling(*args, **kwargs) -> None:
                _ = (args, kwargs)
                raise asyncio.CancelledError

            async def fail_then_cancel(*args, **kwargs) -> None:
                _ = (args, kwargs)
                if not hasattr(fail_then_cancel, "called"):
                    fail_then_cancel.called = True
                    raise RuntimeError("webhook down")
                raise asyncio.CancelledError

            with patch("src.main.HealthServer", side_effect=lambda host, port, ready: _FakeHealthServer(host, port, ready)):
                with patch("src.main._run_polling_forever", new=cancel_polling), patch(
                    "src.main._run_webhook_forever",
                    new=fail_then_cancel,
                ):
                    with self.assertRaises(asyncio.CancelledError):
                        await main_module._run_bot_loop(
                            AppConfig(**{**self.config.__dict__, "telegram_mode": "auto", "webhook_base_url": "https://example.test"}),
                            "store",
                            "rag-manager",
                        )

        asyncio.run(run_case())

    def test_run_worker_and_watcher_loops_record_errors(self) -> None:
        async def run_case() -> None:
            with patch("src.main.HealthServer", side_effect=lambda host, port, ready: _FakeHealthServer(host, port, ready)), patch(
                "src.main.run_worker",
                side_effect=RuntimeError("worker exploded"),
            ), patch("src.main.record_error") as record_error:
                with self.assertRaises(RuntimeError):
                    await main_module._run_worker_loop(self.config, "store", "rag-manager")
                record_error.assert_called_once()

            with patch("src.main.run_watcher", side_effect=RuntimeError("watcher exploded")), patch(
                "src.main.record_error"
            ) as record_error:
                with self.assertRaises(RuntimeError):
                    await main_module._run_watcher_loop(self.config, "rag-manager")
                record_error.assert_called_once()

        asyncio.run(run_case())

    def test_async_main_covers_roles_and_main_entrypoint(self) -> None:
        fake_store = MagicMock()
        fake_rag_manager = MagicMock()

        async def run_case() -> None:
            config = AppConfig(**self.config.__dict__)

            async def raise_cancelled(*args, **kwargs) -> None:
                _ = (args, kwargs)
                raise asyncio.CancelledError

            async def gather_cancelled(*args, **kwargs) -> None:
                for coro in args:
                    if hasattr(coro, "close"):
                        coro.close()
                _ = kwargs
                raise asyncio.CancelledError

            with patch("src.main.load_config", return_value=config), patch(
                "src.main.configure_logging",
            ), patch("src.main.StateStore", return_value=fake_store), patch(
                "src.main.RagManager",
                return_value=fake_rag_manager,
            ), patch("src.main._run_bot_loop", new=raise_cancelled), patch(
                "src.main._run_worker_loop",
                new=raise_cancelled,
            ), patch("src.main._run_watcher_loop", new=raise_cancelled):
                for role in ("bot", "worker", "watcher"):
                    fake_store.reset_mock()
                    fake_rag_manager.reset_mock()
                    with self.assertRaises(asyncio.CancelledError):
                        await main_module._async_main(role)

                standalone_config = AppConfig(**{**self.config.__dict__, "role": "standalone"})
                with patch("src.main.load_config", return_value=standalone_config):
                    with patch("src.main.asyncio.gather", new=gather_cancelled):
                        with self.assertRaises(asyncio.CancelledError):
                            await main_module._async_main(None)

                invalid_config = AppConfig(**{**self.config.__dict__, "role": "invalid"})
                with patch("src.main.load_config", return_value=invalid_config):
                    with self.assertRaises(RuntimeError):
                        await main_module._async_main(None)

        asyncio.run(run_case())

        def fake_run(coro):
            coro.close()

        with patch("src.main.argparse.ArgumentParser.parse_args", return_value=argparse.Namespace(role="bot")), patch(
            "src.main.asyncio.run",
            side_effect=fake_run,
        ) as run_async:
            main_module.main()
        run_async.assert_called_once()


if __name__ == "__main__":
    unittest.main()
