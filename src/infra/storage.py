"""SQLite storage for idempotent jobs and note mapping."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


@dataclass
class QueueJob:
    job_id: str
    idempotency_key: str
    content_fingerprint: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int


class StateStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    content_fingerprint TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL,
                    error TEXT,
                    note_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    next_retry_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jobs_status_retry
                ON jobs(status, next_retry_at, created_at)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    content_fingerprint TEXT PRIMARY KEY,
                    note_id TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_job_id TEXT NOT NULL
                )
                """
            )

    def enqueue_job(
        self,
        *,
        idempotency_key: str,
        content_fingerprint: str,
        user_id: int,
        chat_id: int,
        message_id: int,
        payload: dict[str, Any],
        max_attempts: int,
    ) -> tuple[bool, str, str]:
        now = _utc_now_iso()
        job_id = uuid.uuid4().hex
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)

        with self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO jobs (
                        job_id, idempotency_key, content_fingerprint, user_id, chat_id, message_id,
                        payload_json, status, attempts, max_attempts, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?)
                    """,
                    (
                        job_id,
                        idempotency_key,
                        content_fingerprint,
                        user_id,
                        chat_id,
                        message_id,
                        payload_json,
                        max_attempts,
                        now,
                        now,
                    ),
                )
                return True, job_id, "pending"
            except sqlite3.IntegrityError:
                row = conn.execute(
                    "SELECT job_id, status FROM jobs WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
                if row is None:
                    raise RuntimeError("Idempotency conflict occurred but row was not found.")
                return False, row["job_id"], row["status"]

    def acquire_next_job(self) -> QueueJob | None:
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM jobs
                WHERE status IN ('pending', 'retry')
                  AND (next_retry_at IS NULL OR next_retry_at <= ?)
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None

            conn.execute(
                """
                UPDATE jobs
                SET status = 'processing', updated_at = ?
                WHERE job_id = ?
                """,
                (now, row["job_id"]),
            )
            conn.execute("COMMIT")

            return QueueJob(
                job_id=row["job_id"],
                idempotency_key=row["idempotency_key"],
                content_fingerprint=row["content_fingerprint"],
                payload=json.loads(row["payload_json"]),
                attempts=int(row["attempts"]),
                max_attempts=int(row["max_attempts"]),
            )

    def mark_done(self, job_id: str, note_path: str) -> None:
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = 'done', updated_at = ?, note_path = ?, error = NULL
                WHERE job_id = ?
                """,
                (now, note_path, job_id),
            )

    def mark_failed_or_retry(self, job: QueueJob, error: str) -> tuple[str, int]:
        attempts = job.attempts + 1
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        status = "failed"
        next_retry_at = None

        if attempts < job.max_attempts:
            status = "retry"
            delay_seconds = min(2 ** attempts, 300)
            next_retry_at = (now_dt + timedelta(seconds=delay_seconds)).isoformat()

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs
                SET status = ?, attempts = ?, updated_at = ?, error = ?, next_retry_at = ?
                WHERE job_id = ?
                """,
                (status, attempts, now, error[:1500], next_retry_at, job.job_id),
            )

        return status, attempts

    def get_note(self, content_fingerprint: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM notes WHERE content_fingerprint = ?",
                (content_fingerprint,),
            ).fetchone()
        return dict(row) if row else None

    def upsert_note(
        self,
        *,
        content_fingerprint: str,
        note_id: str,
        file_name: str,
        job_id: str,
    ) -> None:
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO notes (content_fingerprint, note_id, file_name, created_at, updated_at, last_job_id)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(content_fingerprint) DO UPDATE SET
                    note_id = excluded.note_id,
                    file_name = excluded.file_name,
                    updated_at = excluded.updated_at,
                    last_job_id = excluded.last_job_id
                """,
                (content_fingerprint, note_id, file_name, now, now, job_id),
            )

    def status_counts(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM jobs GROUP BY status"
            ).fetchall()
        return {row["status"]: int(row["count"]) for row in rows}

    def _connect(self) -> sqlite3.Connection:
        import os

        raw_path = str(self._db_path)
        normalized_raw = raw_path[4:] if raw_path.startswith("\\\\?\\") else raw_path

        candidates = [raw_path]
        if normalized_raw != raw_path:
            candidates.append(normalized_raw)

        cwd = str(Path.cwd())
        normalized_cwd = cwd[4:] if cwd.startswith("\\\\?\\") else cwd
        try:
            rel_path = os.path.relpath(normalized_raw, normalized_cwd)
            if rel_path not in candidates:
                candidates.append(rel_path)
        except ValueError:
            pass

        last_error: Exception | None = None
        for db_path in candidates:
            try:
                conn = sqlite3.connect(db_path, timeout=30, isolation_level=None)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                return conn
            except sqlite3.OperationalError as exc:
                last_error = exc

        raise RuntimeError(f"Unable to open sqlite database at {raw_path}: {last_error}")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()





