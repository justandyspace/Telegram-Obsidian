from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.infra.storage import StateStore, _ensure_column


class StorageCompletionTests(unittest.TestCase):
    def test_storage_covers_ambiguous_refs_retry_integrity_and_legacy_migrations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "state.sqlite3"
            store = StateStore(db_path)
            store.initialize()
            try:
                ok, job_id, status = store.enqueue_job(
                    idempotency_key="dup-1",
                    content_fingerprint="fp-1",
                    tenant_id="t1",
                    user_id=1,
                    chat_id=1,
                    message_id=1,
                    payload={"tenant_id": "t1"},
                    max_attempts=2,
                )
                self.assertTrue(ok)
                self.assertEqual(status, "pending")
                duplicate = store.enqueue_job(
                    idempotency_key="dup-1",
                    content_fingerprint="fp-1",
                    tenant_id="t1",
                    user_id=1,
                    chat_id=1,
                    message_id=1,
                    payload={"tenant_id": "t1"},
                    max_attempts=2,
                )
                self.assertEqual(duplicate, (False, job_id, "pending"))

                store.upsert_note(tenant_id="t1", content_fingerprint="n1", note_id="NOTE1", file_name="one.md", job_id="abc1111111")
                store.upsert_note(tenant_id="t1", content_fingerprint="n2", note_id="NOTE2", file_name="two.md", job_id="abc2222222")
                self.assertEqual(store.resolve_note_ref("", tenant_id="t1"), (False, "note reference is required"))

                with store._connect() as conn:
                    now = datetime.now(UTC).isoformat()
                    conn.execute("UPDATE notes_mt SET note_id='SAME', updated_at=? WHERE content_fingerprint='n1'", (now,))
                    conn.execute("UPDATE notes_mt SET note_id='SAME', updated_at=? WHERE content_fingerprint='n2'", (now,))
                    self.assertEqual(store.resolve_note_ref("same", tenant_id="t1"), (False, "note id is ambiguous"))

                    conn.execute("UPDATE notes_mt SET note_id='NOTE1', last_job_id='same-job-a', updated_at=? WHERE content_fingerprint='n1'", (now,))
                    conn.execute("UPDATE notes_mt SET note_id='NOTE2', last_job_id='same-job-b', updated_at=? WHERE content_fingerprint='n2'", (now,))
                    ok, message = store.resolve_note_ref("same-job", tenant_id="t1")
                    self.assertFalse(ok)
                    self.assertIn("job id is ambiguous across notes", message)

                    conn.execute("UPDATE notes_mt SET file_name='same.md' WHERE content_fingerprint='n1'")
                    conn.execute("UPDATE notes_mt SET file_name='same.md' WHERE content_fingerprint='n2'")
                    self.assertEqual(store.resolve_note_ref("same.md", tenant_id="t1"), (False, "file name is ambiguous"))
                    self.assertEqual(store.resolve_note_ref("missing", tenant_id="t1"), (False, "note not found"))

                    self.assertFalse(store.cancel_delete_all_confirmation(tenant_id="t1", user_id=1))
                    self.assertEqual(store.recent_jobs(limit=5)[0]["job_id"], job_id)
                    self.assertEqual(store.recent_failures(limit=5), [])
                    self.assertIsNone(store.get_job_status("missing"))
                    self.assertEqual(store.resolve_job_ref(""), (False, "job_id is required"))
                    self.assertEqual(store.retry_job(""), (False, "job_id is required"))
                    self.assertEqual(store.resolve_job_ref("missing"), (False, "job not found"))
                    self.assertEqual(store.retry_job("missing"), (False, "job not found"))
                    self.assertEqual(store.recent_jobs(limit=5, tenant_id="t1")[0]["job_id"], job_id)

                    conn.execute("UPDATE jobs_mt SET status='done' WHERE job_id=?", (job_id,))
                    self.assertEqual(store.retry_job(job_id), (False, "only failed jobs can be retried"))
                    conn.execute("UPDATE jobs_mt SET status='weird' WHERE job_id=?", (job_id,))
                    self.assertEqual(store.retry_job(job_id), (False, "cannot retry job with status=weird"))
                    conn.execute("UPDATE jobs_mt SET status='pending' WHERE job_id=?", (job_id,))
                    self.assertEqual(store.retry_job(job_id), (False, "job is already active with status=pending"))
                    conn.execute("UPDATE jobs_mt SET status='failed' WHERE job_id=?", (job_id,))
                    self.assertEqual(store.retry_job(job_id), (True, job_id))
                    ok, msg = store.resolve_job_ref(job_id[:4], tenant_id="t1")
                    self.assertTrue(ok)
                    self.assertEqual(msg["job_id"], job_id)

                    ok, details = store.integrity_check()
                    self.assertTrue(ok)
                    self.assertEqual(details, "ok")
                    self.assertEqual(store.recent_failures(limit=5, tenant_id="t1")[0]["job_id"], job_id)
                    conn.execute("UPDATE jobs_mt SET status='broken' WHERE job_id=?", (job_id,))
                    self.assertEqual(store.integrity_check(), (False, "Found jobs with invalid statuses: 1"))

                    conn.execute("DROP TABLE schema_migrations")
                    store._ensure_meta_table(conn)
                    conn.execute("DELETE FROM schema_migrations")
                    self.assertEqual(store._detect_schema_version(conn), 1)

                    conn.execute(
                        "CREATE TABLE jobs (job_id TEXT, tenant_id TEXT, idempotency_key TEXT, content_fingerprint TEXT, user_id INTEGER, chat_id INTEGER, message_id INTEGER, payload_json TEXT, status TEXT, attempts INTEGER, max_attempts INTEGER, error TEXT, note_path TEXT, created_at TEXT, updated_at TEXT, next_retry_at TEXT)"
                    )
                    conn.execute(
                        "CREATE TABLE notes (tenant_id TEXT, content_fingerprint TEXT, note_id TEXT, file_name TEXT, created_at TEXT, updated_at TEXT, last_job_id TEXT)"
                    )
                    conn.execute(
                        "INSERT INTO jobs VALUES ('legacy-job','legacy','legacy-key','legacy-fp',1,1,1,'{}','failed',1,3,'err',NULL,?,?,NULL)",
                        (now, now),
                    )
                    conn.execute(
                        "INSERT INTO notes VALUES ('legacy','legacy-fp','LEGACY1','legacy.md',?,?, 'legacy-job')",
                        (now, now),
                    )
                    store._migrate_legacy_tables(conn)
                    self.assertTrue(store.get_job_status("legacy-job"))
                    self.assertTrue(store.get_note("legacy-fp", "legacy"))
                    store._migrate_legacy_tables(conn)
            finally:
                store.close()

    def test_storage_internal_error_paths_and_helpers(self) -> None:
        class MissingRowConn:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, sql: str, params=None):
                _ = params
                if "INSERT INTO jobs_mt" in sql:
                    raise sqlite3.IntegrityError
                return self

            def fetchone(self):
                return None

        store = StateStore(Path("dummy.sqlite3"))
        with patch.object(store, "_connect", return_value=MissingRowConn()):
            with self.assertRaises(RuntimeError):
                store.enqueue_job(
                    idempotency_key="x",
                    content_fingerprint="y",
                    tenant_id="t",
                    user_id=1,
                    chat_id=1,
                    message_id=1,
                    payload={},
                    max_attempts=1,
                )

        class RollbackConn:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, sql: str, params=None):
                _ = params
                if sql == "BEGIN IMMEDIATE":
                    return None
                if "SELECT token" in sql:
                    raise RuntimeError("boom")
                return None

        store = StateStore(Path("dummy.sqlite3"))
        with patch.object(store, "_connect", return_value=RollbackConn()):
            with self.assertRaises(RuntimeError):
                store.consume_delete_all_confirmation(tenant_id="t", user_id=1, token="x")

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE sample (id INTEGER)")
        _ensure_column(conn, "sample", "extra", "TEXT")
        _ensure_column(conn, "sample", "extra", "TEXT")
        names = [row["name"] for row in conn.execute("PRAGMA table_info(sample)").fetchall()]
        self.assertIn("extra", names)
        conn.close()

        store = StateStore(Path("dummy.sqlite3"))
        self.assertIsNone(store.close())


if __name__ == "__main__":
    unittest.main()
