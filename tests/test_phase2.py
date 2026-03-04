from __future__ import annotations

import shutil
import unittest
from datetime import UTC, datetime
from pathlib import Path

from src.infra.storage import StateStore
from src.obsidian.note_writer import ObsidianNoteWriter
from src.parsers.router import classify_url


class Phase2ContentUxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(".data") / "test_phase2"
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_parser_url_classification(self) -> None:
        self.assertEqual(classify_url("https://example.com/doc.pdf"), "pdf")
        self.assertEqual(classify_url("https://youtu.be/abc123"), "youtube")
        self.assertEqual(
            classify_url("https://x.com/user/status/1234567890"),
            "twitter_fallback",
        )
        self.assertEqual(classify_url("https://example.com/article"), "article")

    def test_retry_failed_job_by_prefix(self) -> None:
        store = StateStore(self.root / "state.sqlite3")
        store.initialize()
        payload = {
            "tenant_id": "tg_1",
            "content": "text",
            "title": "title",
            "hashtags": [],
            "actions": ["save"],
            "content_fingerprint": "a" * 64,
            "source": {
                "chat_id": 1,
                "message_id": 1,
                "message_datetime": datetime.now(UTC).isoformat(),
                "user_id": 1,
            },
        }
        is_new, job_id, _ = store.enqueue_job(
            idempotency_key="idem-1",
            content_fingerprint=payload["content_fingerprint"],
            tenant_id="tg_1",
            user_id=1,
            chat_id=1,
            message_id=1,
            payload=payload,
            max_attempts=1,
        )
        self.assertTrue(is_new)

        job = store.acquire_next_job()
        self.assertIsNotNone(job)
        status, _ = store.mark_failed_or_retry(job, "forced failure")
        self.assertEqual(status, "failed")

        ok, details = store.retry_job(job_id[:10])
        self.assertTrue(ok)
        self.assertEqual(details, job_id)
        self.assertEqual(store.status_counts().get("retry"), 1)

    def test_summary_updates_only_on_explicit_actions_for_existing_note(self) -> None:
        store = StateStore(self.root / "state.sqlite3")
        store.initialize()
        writer = ObsidianNoteWriter(self.root / "vault", store, multi_tenant=False)

        payload = {
            "tenant_id": "tg_999",
            "content": "alpha original content",
            "title": "Sample",
            "hashtags": ["save"],
            "actions": ["save"],
            "parsed_items": [],
            "content_fingerprint": "f" * 64,
            "source": {
                "chat_id": 1,
                "message_id": 10,
                "message_datetime": datetime.now(UTC).isoformat(),
                "user_id": 999,
            },
        }
        note_path = Path(writer.write(job_id="job1", payload=payload))
        first_text = note_path.read_text(encoding="utf-8")
        first_summary = _extract_block(first_text, "BOT_SUMMARY")
        self.assertIn("alpha original content", first_summary)

        payload["content"] = "beta changed content that should not rewrite summary"
        payload["enriched_text"] = payload["content"]
        payload["actions"] = ["save"]
        writer.write(job_id="job2", payload=payload)
        second_text = note_path.read_text(encoding="utf-8")
        second_summary = _extract_block(second_text, "BOT_SUMMARY")
        self.assertEqual(first_summary, second_summary)

        payload["actions"] = ["resummarize"]
        writer.write(job_id="job3", payload=payload)
        third_text = note_path.read_text(encoding="utf-8")
        third_summary = _extract_block(third_text, "BOT_SUMMARY")
        self.assertIn("beta changed content", third_summary)


def _extract_block(document: str, block_name: str) -> str:
    start_marker = f"<!-- {block_name}:START -->"
    end_marker = f"<!-- {block_name}:END -->"
    start = document.index(start_marker) + len(start_marker)
    end = document.index(end_marker)
    return document[start:end].strip()


if __name__ == "__main__":
    unittest.main()
