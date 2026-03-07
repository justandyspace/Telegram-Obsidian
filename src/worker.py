"""Async worker loop."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from src.config import AppConfig
from src.infra.gdrive import GoogleDriveClient, enrich_payload_with_drive_attachments, mirror_note_to_drive
from src.infra.logging import get_logger
from src.infra.storage import StateStore
from src.obsidian.note_writer import ObsidianNoteWriter
from src.parsers.router import enrich_payload
from src.pipeline.enrichment import enrich_payload_with_ai
from src.rag.embedder import EmbedderError
from src.rag.retriever import RagManager

LOGGER = get_logger(__name__)


async def run_worker(
    config: AppConfig,
    store: StateStore,
    rag_manager: RagManager,
    drive_client: GoogleDriveClient | None = None,
) -> None:
    ok, details = store.integrity_check()
    if not ok:
        raise RuntimeError(f"SQLite integrity check failed: {details}")

    writer = ObsidianNoteWriter(
        config.vault_path,
        store,
        multi_tenant=config.multi_tenant_mode,
    )
    last_recovery_at = -1.0

    while True:
        now = time.monotonic()
        if now - last_recovery_at >= config.worker_recovery_interval_seconds:
            recovered = store.recover_stuck_jobs(
                max_processing_age_seconds=config.worker_stuck_timeout_seconds,
            )
            if recovered:
                LOGGER.warning("Recovered stuck jobs count=%s", recovered)
            last_recovery_at = now

        job = store.acquire_next_job()
        if job is None:
            await asyncio.sleep(config.worker_poll_seconds)
            continue

        LOGGER.info("Processing job_id=%s", job.job_id)
        try:
            parsed_payload = enrich_payload(job.payload)
            parsed_payload = enrich_payload_with_drive_attachments(parsed_payload, drive_client)
            processed_payload = enrich_payload_with_ai(
                parsed_payload,
                api_key=config.gemini_api_key,
                model_name=config.gemini_generation_model,
            )
            payload_tenant = str(processed_payload.get("tenant_id") or "legacy")
            if payload_tenant != job.tenant_id:
                raise RuntimeError(
                    f"Tenant mismatch for job {job.job_id}: queue={job.tenant_id} payload={payload_tenant}"
                )

            note_path = writer.write(job_id=job.job_id, payload=processed_payload)
            if drive_client is not None:
                try:
                    mirror_note_to_drive(config, drive_client, Path(note_path))
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning("Immediate note mirror skipped for %s: %s", note_path, exc)
            rag = rag_manager.for_tenant(payload_tenant)
            try:
                rag.index_note(Path(note_path))
            except EmbedderError as exc:
                # Note is already written. Keep queue healthy even if remote embeddings are unavailable.
                LOGGER.warning(
                    "RAG indexing skipped for job_id=%s note=%s reason=%s",
                    job.job_id,
                    note_path,
                    exc,
                )
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
            # Prevent tight CPU loop on poison jobs.
            await asyncio.sleep(1)
