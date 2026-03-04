from __future__ import annotations

import shutil
import unittest
from datetime import UTC, datetime
from pathlib import Path

from src.bot.auth import build_tenant_context, is_authorized_user
from src.infra.storage import StateStore
from src.obsidian.note_writer import ObsidianNoteWriter


class Phase4MultiTenantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(".data") / "test_phase4"
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_allowlist_auth(self) -> None:
        allowed = {111, 222}
        self.assertTrue(is_authorized_user(incoming_user_id=111, allowed_user_ids=allowed))
        self.assertFalse(is_authorized_user(incoming_user_id=333, allowed_user_ids=allowed))
        self.assertEqual(build_tenant_context(222).tenant_id, "tg_222")

    def test_storage_tenant_filters_retry_and_status(self) -> None:
        store = StateStore(self.root / "state.sqlite3")
        store.initialize()

        payload_a = _sample_payload("tg_111", "a" * 64)
        payload_b = _sample_payload("tg_222", "b" * 64)

        _, job_a, _ = store.enqueue_job(
            idempotency_key="idem-a",
            content_fingerprint=payload_a["content_fingerprint"],
            tenant_id="tg_111",
            user_id=111,
            chat_id=1,
            message_id=1,
            payload=payload_a,
            max_attempts=1,
        )
        store.enqueue_job(
            idempotency_key="idem-b",
            content_fingerprint=payload_b["content_fingerprint"],
            tenant_id="tg_222",
            user_id=222,
            chat_id=2,
            message_id=2,
            payload=payload_b,
            max_attempts=1,
        )

        first = store.acquire_next_job()
        second = store.acquire_next_job()
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        store.mark_failed_or_retry(first, "forced")
        store.mark_failed_or_retry(second, "forced")

        counts_a = store.status_counts(tenant_id="tg_111")
        counts_b = store.status_counts(tenant_id="tg_222")
        self.assertEqual(counts_a.get("failed"), 1)
        self.assertEqual(counts_b.get("failed"), 1)

        ok_wrong, _ = store.retry_job(job_a[:10], tenant_id="tg_222")
        self.assertFalse(ok_wrong)
        ok_right, retried_id = store.retry_job(job_a[:10], tenant_id="tg_111")
        self.assertTrue(ok_right)
        self.assertEqual(retried_id, job_a)

    def test_notes_primary_key_is_tenant_scoped(self) -> None:
        store = StateStore(self.root / "state.sqlite3")
        store.initialize()
        store.upsert_note(
            content_fingerprint="same",
            tenant_id="tg_111",
            note_id="N1",
            file_name="a.md",
            job_id="job-a",
        )
        store.upsert_note(
            content_fingerprint="same",
            tenant_id="tg_222",
            note_id="N2",
            file_name="b.md",
            job_id="job-b",
        )

        note_a = store.get_note("same", "tg_111")
        note_b = store.get_note("same", "tg_222")
        self.assertIsNotNone(note_a)
        self.assertIsNotNone(note_b)
        self.assertNotEqual(note_a["file_name"], note_b["file_name"])

    def test_writer_isolates_tenant_vault_paths(self) -> None:
        store = StateStore(self.root / "state.sqlite3")
        store.initialize()
        writer = ObsidianNoteWriter(self.root / "vault", store, multi_tenant=True)

        payload_a = _sample_payload("tg_111", "c" * 64)
        payload_b = _sample_payload("tg_222", "d" * 64)

        path_a = Path(writer.write(job_id="job-a", payload=payload_a))
        path_b = Path(writer.write(job_id="job-b", payload=payload_b))

        self.assertIn("tg_111", str(path_a))
        self.assertIn("tg_222", str(path_b))
        self.assertNotEqual(path_a.parent, path_b.parent)


def _sample_payload(tenant_id: str, fingerprint: str) -> dict:
    return {
        "tenant_id": tenant_id,
        "content": f"content for {tenant_id}",
        "title": f"title {tenant_id}",
        "hashtags": [],
        "actions": ["save"],
        "content_fingerprint": fingerprint,
        "source": {
            "chat_id": 1,
            "message_id": 1,
            "message_datetime": datetime.now(UTC).isoformat(),
            "user_id": int(tenant_id.replace("tg_", "")),
        },
    }


if __name__ == "__main__":
    unittest.main()
