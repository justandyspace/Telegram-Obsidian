from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import src.bot.commands as commands_module
from src.bot.commands import _job_status_emoji, _normalize_job_status
from src.infra.storage import StateStore


class JobLookupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self._tmp.name) / "state.sqlite3")
        self.store.initialize()

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def test_resolve_job_ref_by_prefix_returns_single_row(self) -> None:
        _, job_id, _ = self.store.enqueue_job(
            idempotency_key="idem-1",
            content_fingerprint="fp-1",
            tenant_id="tg_111",
            user_id=111,
            chat_id=1,
            message_id=1,
            payload={"tenant_id": "tg_111"},
            max_attempts=1,
        )
        acquired = self.store.acquire_next_job()
        self.assertIsNotNone(acquired)
        self.store.mark_done(job_id, str(Path(self._tmp.name) / "voice-note.md"))

        ok, resolved = self.store.resolve_job_ref(job_id[:10], tenant_id="tg_111")
        self.assertTrue(ok)
        self.assertIsInstance(resolved, dict)
        self.assertEqual(resolved["job_id"], job_id)
        self.assertEqual(resolved["status"], "done")
        self.assertTrue(str(resolved["note_path"]).endswith("voice-note.md"))

    def test_resolve_job_ref_returns_ambiguous_for_short_prefix(self) -> None:
        created_ids: list[str] = []
        for idx in range(20):
            _, job_id, _ = self.store.enqueue_job(
                idempotency_key=f"idem-{idx}",
                content_fingerprint=f"fp-{idx}",
                tenant_id="tg_111",
                user_id=111,
                chat_id=1,
                message_id=idx + 1,
                payload={"tenant_id": "tg_111"},
                max_attempts=1,
            )
            created_ids.append(job_id)

        by_prefix: dict[str, list[str]] = {}
        for job_id in created_ids:
            by_prefix.setdefault(job_id[0], []).append(job_id)
        ambiguous_prefix = next(prefix for prefix, ids in by_prefix.items() if len(ids) > 1)

        ok, resolved = self.store.resolve_job_ref(ambiguous_prefix, tenant_id="tg_111")
        self.assertFalse(ok)
        self.assertIn("ambiguous", str(resolved))

    def test_resolve_job_ref_honors_tenant_filter(self) -> None:
        _, job_id, _ = self.store.enqueue_job(
            idempotency_key="idem-a",
            content_fingerprint="fp-a",
            tenant_id="tg_111",
            user_id=111,
            chat_id=1,
            message_id=1,
            payload={"tenant_id": "tg_111"},
            max_attempts=1,
        )

        ok, resolved = self.store.resolve_job_ref(job_id, tenant_id="tg_222")
        self.assertFalse(ok)
        self.assertEqual(str(resolved), "job not found")


class JobStatusPresentationTests(unittest.TestCase):
    def test_normalize_job_status_maps_pending_to_queued(self) -> None:
        self.assertEqual(_normalize_job_status("pending"), "queued")
        self.assertEqual(_normalize_job_status("retry"), "retry")
        self.assertEqual(_normalize_job_status("processing"), "processing")
        self.assertEqual(_normalize_job_status("done"), "done")
        self.assertEqual(_normalize_job_status("failed"), "failed")

    def test_job_status_emoji_matches_html_style(self) -> None:
        self.assertEqual(_job_status_emoji("queued"), "🕒")
        self.assertEqual(_job_status_emoji("retry"), "♻️")
        self.assertEqual(_job_status_emoji("processing"), "⏳")
        self.assertEqual(_job_status_emoji("done"), "✅")
        self.assertEqual(_job_status_emoji("failed"), "❌")
        self.assertEqual(_job_status_emoji("unknown"), "⚠️")

    def test_command_router_contains_job_command_wiring(self) -> None:
        import inspect

        source = inspect.getsource(commands_module.build_command_router)
        self.assertIn('Command("job")', source)
        self.assertIn("/job &lt;job_id | prefix&gt;", source)


if __name__ == "__main__":
    unittest.main()
