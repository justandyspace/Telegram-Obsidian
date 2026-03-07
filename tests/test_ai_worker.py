from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.infra.ai_fallback import reset_remote_ai
from src.infra.storage import StateStore
from src.pipeline.ai_service import AIService
from src.pipeline.ingest import IngestRequest
from src.pipeline.jobs import JobService
from src.worker import run_worker


class _FakeAsyncModels:
    def __init__(self, *, text: str = "", error: Exception | None = None) -> None:
        self._text = text
        self._error = error

    async def generate_content(self, **kwargs):
        _ = kwargs
        if self._error is not None:
            raise self._error
        return SimpleNamespace(text=self._text)


class _FakeRagService:
    def __init__(self) -> None:
        self.indexed_paths: list[Path] = []

    def index_note(self, note_path: Path) -> bool:
        self.indexed_paths.append(note_path)
        return True


class _FakeRagManager:
    def __init__(self) -> None:
        self.service = _FakeRagService()
        self.tenants: list[str] = []

    def for_tenant(self, tenant_id: str) -> _FakeRagService:
        self.tenants.append(tenant_id)
        return self.service


class AIServiceTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_remote_ai("assistant_reply")

    def test_generate_reply_returns_disabled_message_without_api_key(self) -> None:
        service = AIService(api_key="", model_name="gemini")
        reply = asyncio.run(service.generate_reply("hello"))
        self.assertIn("не настроен", reply)

    def test_generate_reply_uses_async_client(self) -> None:
        service = AIService(api_key="token", model_name="gemini")
        service.client = SimpleNamespace(aio=SimpleNamespace(models=_FakeAsyncModels(text="  hello back  ")))
        reply = asyncio.run(service.generate_reply("hello"))
        self.assertEqual(reply, "hello back")

    def test_generate_reply_falls_back_on_error(self) -> None:
        service = AIService(api_key="token", model_name="gemini")
        service.client = SimpleNamespace(
            aio=SimpleNamespace(models=_FakeAsyncModels(error=RuntimeError("boom")))
        )
        reply = asyncio.run(service.generate_reply("hello"))
        self.assertEqual(reply, "Принято. Сохраняю в Obsidian...")

    def test_generate_reply_enters_quota_cooldown(self) -> None:
        service = AIService(api_key="token", model_name="gemini")
        service.client = SimpleNamespace(
            aio=SimpleNamespace(models=_FakeAsyncModels(error=RuntimeError("429 RESOURCE_EXHAUSTED")))
        )
        first = asyncio.run(service.generate_reply("hello"))
        self.assertEqual(first, "Принято. Сохраняю в Obsidian...")
        service.client = SimpleNamespace(
            aio=SimpleNamespace(models=_FakeAsyncModels(text="should not be called"))
        )
        second = asyncio.run(service.generate_reply("hello"))
        self.assertEqual(second, "Принято. Сохраняю в Obsidian...")


class WorkerFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.store = StateStore(self.root / "state.sqlite3")
        self.store.initialize()
        self.job_service = JobService(self.store, max_retries=2)
        self.config = SimpleNamespace(
            vault_path=self.root / "vault",
            multi_tenant_mode=False,
            worker_recovery_interval_seconds=3600.0,
            worker_stuck_timeout_seconds=600,
            worker_poll_seconds=0.01,
            gemini_api_key="",
            gemini_generation_model="gemini-2.5-flash",
        )

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def _submit_job(self, raw_text: str = "Test note #save") -> str:
        result = self.job_service.submit(
            IngestRequest(
                tenant_id="single",
                user_id=1,
                chat_id=10,
                message_id=20,
                message_datetime=datetime(2026, 3, 5, 12, 0, tzinfo=UTC),
                raw_text=raw_text,
            )
        )
        return result.job_id

    def test_worker_processes_job_and_indexes_note(self) -> None:
        job_id = self._submit_job()
        rag_manager = _FakeRagManager()

        async def stop_when_idle(delay: float) -> None:
            _ = delay
            raise asyncio.CancelledError

        async def scenario() -> None:
            with patch("src.worker.asyncio.sleep", side_effect=stop_when_idle):
                with self.assertRaises(asyncio.CancelledError):
                    await run_worker(self.config, self.store, rag_manager)

        asyncio.run(scenario())

        row = self.store.get_job_status(job_id, tenant_id="single")
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "done")
        self.assertEqual(rag_manager.tenants, ["single"])
        self.assertEqual(len(rag_manager.service.indexed_paths), 1)
        self.assertTrue(Path(row["note_path"]).exists())

    def test_worker_retries_when_processed_payload_tenant_mismatches(self) -> None:
        job_id = self._submit_job()
        rag_manager = _FakeRagManager()

        async def stop_on_retry(delay: float) -> None:
            _ = delay
            raise asyncio.CancelledError

        def force_tenant_mismatch(payload: dict) -> dict:
            broken = dict(payload)
            broken["tenant_id"] = "wrong-tenant"
            return broken

        async def scenario() -> None:
            with patch("src.worker.enrich_payload", side_effect=force_tenant_mismatch):
                with patch("src.worker.asyncio.sleep", side_effect=stop_on_retry):
                    with self.assertRaises(asyncio.CancelledError):
                        await run_worker(self.config, self.store, rag_manager)

        asyncio.run(scenario())

        row = self.store.get_job_status(job_id, tenant_id="single")
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "retry")
        self.assertIn("Tenant mismatch", row["error"])


if __name__ == "__main__":
    unittest.main()
