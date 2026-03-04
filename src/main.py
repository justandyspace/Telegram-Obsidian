"""Application entrypoint for bot/worker roles."""

from __future__ import annotations

import argparse
import asyncio

from aiogram import Bot, Dispatcher

from src.bot.telegram_router import build_router
from src.config import load_config
from src.infra.health import HealthServer
from src.infra.logging import configure_logging, get_logger
from src.infra.storage import StateStore
from src.pipeline.jobs import JobService
from src.worker import run_worker

LOGGER = get_logger(__name__)


async def _run_bot_loop(config, store: StateStore) -> None:
    ready = False

    def is_ready() -> bool:
        return ready

    health = HealthServer("0.0.0.0", config.bot_health_port, is_ready)
    await health.start()
    LOGGER.info("Bot health server listening on %s", config.bot_health_port)

    backoff = 1
    try:
        while True:
            bot = Bot(token=config.telegram_token)
            dp = Dispatcher()
            dp.include_router(
                build_router(
                    job_service=JobService(store, config.job_max_retries),
                    allowed_user_id=config.telegram_allowed_user_id,
                    store=store,
                )
            )
            try:
                ready = True
                LOGGER.info("Starting Telegram long polling")
                await dp.start_polling(bot)
                backoff = 1
            except Exception as exc:  # noqa: BLE001
                ready = False
                LOGGER.exception("Polling crashed, retrying in %s sec: %s", backoff, exc)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
            finally:
                await bot.session.close()
    finally:
        await health.stop()


async def _run_worker_loop(config, store: StateStore) -> None:
    ready = True

    def is_ready() -> bool:
        return ready

    health = HealthServer("0.0.0.0", config.worker_health_port, is_ready)
    await health.start()
    LOGGER.info("Worker health server listening on %s", config.worker_health_port)
    try:
        await run_worker(config, store)
    finally:
        ready = False
        await health.stop()


async def _async_main(role_override: str | None) -> None:
    config = load_config()
    if role_override:
        config = config.__class__(**{**config.__dict__, "role": role_override})

    configure_logging(config.log_level)

    config.state_dir.mkdir(parents=True, exist_ok=True)
    config.cache_dir.mkdir(parents=True, exist_ok=True)
    config.index_dir.mkdir(parents=True, exist_ok=True)
    config.vault_path.mkdir(parents=True, exist_ok=True)

    store = StateStore(config.state_db_path)
    store.initialize()

    LOGGER.info("Starting role=%s", config.role)
    if config.role == "bot":
        await _run_bot_loop(config, store)
    elif config.role == "worker":
        await _run_worker_loop(config, store)
    else:
        raise RuntimeError(f"Unsupported role: {config.role}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=["bot", "worker"], default=None)
    args = parser.parse_args()
    asyncio.run(_async_main(args.role))


if __name__ == "__main__":
    main()
