"""Application entrypoint for bot/worker roles."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from src.bot.telegram_router import build_router
from src.config import AppConfig, load_config
from src.infra.gdrive import build_gdrive_client, run_gdrive_maintenance_forever
from src.infra.health import HealthServer
from src.infra.logging import configure_logging, get_logger
from src.infra.runtime_state import record_error
from src.infra.storage import StateStore
from src.pipeline.ai_service import AIService
from src.pipeline.jobs import JobService
from src.rag.retriever import RagManager
from src.watcher import run_watcher
from src.worker import run_worker

LOGGER = get_logger(__name__)


def _build_dispatcher(config: AppConfig, store: StateStore, rag_manager: RagManager) -> Dispatcher:
    dp = Dispatcher()
    ai_service = AIService(
        api_key=config.gemini_api_key,
        model_name=config.gemini_generation_model,
    )
    dp.include_router(
        build_router(
            job_service=JobService(store, config.job_max_retries),
            allowed_user_ids=set(config.telegram_allowed_user_ids),
            store=store,
            vault_path=config.vault_path,
            rag_manager=rag_manager,
            ai_service=ai_service,
            mini_app_base_url=config.mini_app_base_url,
        )
    )
    return dp


async def _run_polling_forever(
    config: AppConfig,
    store: StateStore,
    rag_manager: RagManager,
    set_ready: Callable[[bool], None],
) -> None:
    backoff = 1
    while True:
        bot = Bot(token=config.telegram_token)
        dp = _build_dispatcher(config, store, rag_manager)
        try:
            await bot.delete_webhook(drop_pending_updates=False)
            set_ready(True)
            LOGGER.info("Starting Telegram long polling")
            await dp.start_polling(bot)
            backoff = 1
        except Exception as exc:  # noqa: BLE001
            set_ready(False)
            record_error(f"polling crash: {exc}")
            LOGGER.exception("Polling crashed, retrying in %s sec: %s", backoff, exc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)  # pragma: no cover
        finally:
            await bot.session.close()


async def _run_webhook_forever(
    config: AppConfig,
    store: StateStore,
    rag_manager: RagManager,
    set_ready: Callable[[bool], None],
    *,
    retry_forever: bool,
) -> None:
    if not config.webhook_base_url:
        raise RuntimeError("WEBHOOK_BASE_URL is required for webhook mode.")

    backoff = 1
    while True:
        bot = Bot(token=config.telegram_token)
        dp = _build_dispatcher(config, store, rag_manager)
        app = web.Application()
        secret = config.webhook_secret_token or None
        handler = SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=secret)
        handler.register(app, path=config.webhook_path)
        setup_application(app, dp, bot=bot)

        runner = web.AppRunner(app)
        site: web.TCPSite | None = None
        webhook_url = config.webhook_base_url.rstrip("/") + config.webhook_path

        try:
            await runner.setup()
            site = web.TCPSite(runner, host=config.webhook_bind_host, port=config.webhook_bind_port)
            await site.start()
            await bot.set_webhook(
                url=webhook_url,
                secret_token=secret,
                drop_pending_updates=False,
            )
            set_ready(True)
            LOGGER.info(
                "Webhook mode started url=%s bind=%s:%s",
                webhook_url,
                config.webhook_bind_host,
                config.webhook_bind_port,
            )
            backoff = 1
            await asyncio.Event().wait()
        except Exception as exc:  # noqa: BLE001
            set_ready(False)
            record_error(f"webhook crash: {exc}")
            if not retry_forever:
                raise
            LOGGER.exception("Webhook crashed, retrying in %s sec: %s", backoff, exc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)  # pragma: no cover
        finally:
            try:
                await bot.delete_webhook(drop_pending_updates=False)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Failed to delete webhook during shutdown: %s", exc)
            try:
                if site is not None:
                    await runner.cleanup()
            finally:
                await bot.session.close()


async def _run_bot_loop(config: AppConfig, store: StateStore, rag_manager: RagManager) -> None:
    ready = False

    def set_ready(value: bool) -> None:
        nonlocal ready
        ready = value

    def is_ready() -> bool:
        return ready

    health = HealthServer("0.0.0.0", config.bot_health_port, is_ready)
    await health.start()
    LOGGER.info("Bot health server listening on %s", config.bot_health_port)

    try:
        mode = config.telegram_mode
        if mode == "polling":
            await _run_polling_forever(config, store, rag_manager, set_ready)
            return  # pragma: no cover
        if mode == "webhook":
            await _run_webhook_forever(
                config,
                store,
                rag_manager,
                set_ready,
                retry_forever=True,
            )
            return  # pragma: no cover

        # auto mode
        if config.webhook_base_url:
            try:
                await _run_webhook_forever(
                    config,
                    store,
                    rag_manager,
                    set_ready,
                    retry_forever=False,
                )
                return  # pragma: no cover
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Webhook mode unavailable in auto mode, switching to polling: %s", exc)

        await _run_polling_forever(config, store, rag_manager, set_ready)
    finally:
        await health.stop()


async def _run_worker_loop(config: AppConfig, store: StateStore, rag_manager: RagManager) -> None:
    ready = True
    drive_client = build_gdrive_client(config)

    def is_ready() -> bool:
        return ready

    health = HealthServer("0.0.0.0", config.worker_health_port, is_ready)
    await health.start()
    LOGGER.info("Worker health server listening on %s", config.worker_health_port)
    maintenance_task = None
    if drive_client is not None:
        maintenance_task = asyncio.create_task(run_gdrive_maintenance_forever(config, drive_client))
    try:
        try:
            await run_worker(config, store, rag_manager, drive_client=drive_client)
        except Exception as exc:  # noqa: BLE001
            record_error(f"worker crash: {exc}")
            raise
    finally:
        if maintenance_task is not None:
            maintenance_task.cancel()
            with suppress(asyncio.CancelledError):
                await maintenance_task
        ready = False
        await health.stop()


async def _run_watcher_loop(config: AppConfig, rag_manager: RagManager) -> None:
    try:
        await run_watcher(config, rag_manager)
    except Exception as exc:  # noqa: BLE001
        record_error(f"watcher crash: {exc}")
        raise


async def _async_main(role_override: str | None) -> None:
    config = load_config()
    if role_override:
        from dataclasses import replace
        config = replace(config, role=role_override)

    configure_logging(config.log_level)

    config.state_dir.mkdir(parents=True, exist_ok=True)
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    config.index_dir.mkdir(parents=True, exist_ok=True)
    config.vault_path.mkdir(parents=True, exist_ok=True)

    store = StateStore(config.state_db_path)
    store.initialize()
    rag_manager = RagManager(
        base_vault_path=config.vault_path,
        base_index_dir=config.index_dir,
        multi_tenant=config.multi_tenant_mode,
        gemini_api_key=config.gemini_api_key,
        gemini_embed_model=config.gemini_embed_model,
        gemini_generation_model=config.gemini_generation_model,
    )
    try:
        LOGGER.info("Starting role=%s", config.role)
        if config.role == "bot":
            await _run_bot_loop(config, store, rag_manager)
        elif config.role == "worker":
            await _run_worker_loop(config, store, rag_manager)
        elif config.role == "watcher":
            await _run_watcher_loop(config, rag_manager)
        elif config.role == "standalone":
            await asyncio.gather(
                _run_bot_loop(config, store, rag_manager),
                _run_worker_loop(config, store, rag_manager),
            )
        else:
            raise RuntimeError(f"Unsupported role: {config.role}")
    finally:
        rag_manager.close()
        store.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["bot", "worker", "watcher", "standalone"], default=None)
    args = parser.parse_args()
    asyncio.run(_async_main(args.role))


if __name__ == "__main__":  # pragma: no cover
    main()
