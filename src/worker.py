"""Async worker loop."""

from __future__ import annotations

import asyncio

from src.config import AppConfig
from src.infra.logging import get_logger
from src.infra.storage import StateStore
from src.obsidian.note_writer import ObsidianNoteWriter

LOGGER = get_logger(__name__)


async def run_worker(config: AppConfig, store: StateStore) -> None:
    writer = ObsidianNoteWriter(config.vault_path, store)

    while True:
        job = store.acquire_next_job()
        if job is None:
            await asyncio.sleep(config.worker_poll_seconds)
            continue

        LOGGER.info("Processing job_id=%s", job.job_id)
        try:
            note_path = writer.write(job_id=job.job_id, payload=job.payload)
            store.mark_done(job.job_id, note_path)
            LOGGER.info("Job done job_id=%s note=%s", job.job_id, note_path)
        except Exception as exc:  # noqa: BLE001
            status, attempts = store.mark_failed_or_retry(job, str(exc))
            LOGGER.exception(
                "Job processing failed job_id=%s status=%s attempts=%s",
                job.job_id,
                status,
                attempts,
            )
