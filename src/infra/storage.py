"""SQLite storage for idempotent jobs, migration safety, and recovery."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 4
LOGGER = logging.getLogger(__name__)


@dataclass
class QueueJob:
    job_id: str
    tenant_id: str
    idempotency_key: str
    content_fingerprint: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int


class StateStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        self._ensure_meta_table(conn)

        current_version = self._detect_schema_version(conn)
        if current_version < 1:
            self._migrate_to_v1(conn)
            current_version = 1
        if current_version < 2:
            self._migrate_to_v2(conn)
            current_version = 2
        if current_version < 3:
            self._migrate_to_v3(conn)
            current_version = 3
        if current_version < 4:
            self._migrate_to_v4(conn)
            current_version = 4

        self._set_schema_version(conn, current_version)
        self._migrate_legacy_tables(conn)

    def schema_version(self) -> int:
        return self._detect_schema_version(self._connect())

    def enqueue_job(
        self,
        *,
        idempotency_key: str,
        content_fingerprint: str,
        tenant_id: str,
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
                    INSERT INTO jobs_mt (
                        job_id, tenant_id, idempotency_key, content_fingerprint, user_id, chat_id, message_id,
                        payload_json, status, attempts, max_attempts, created_at, updated_at, processing_started_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?, NULL)
                    """,
                    (
                        job_id,
                        tenant_id,
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
                    """
                    SELECT job_id, status
                    FROM jobs_mt
                    WHERE tenant_id = ? AND idempotency_key = ?
                    """,
                    (tenant_id, idempotency_key),
                ).fetchone()
                if row is None:
                    raise RuntimeError("Idempotency conflict occurred but row was not found.") from None
                return False, str(row["job_id"]), str(row["status"])

    def acquire_next_job(self) -> QueueJob | None:
        now = _utc_now_iso()
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """
            SELECT * FROM jobs_mt
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
            UPDATE jobs_mt
            SET status = 'processing',
                updated_at = ?,
                processing_started_at = ?,
                next_retry_at = NULL
            WHERE job_id = ?
            """,
            (now, now, row["job_id"]),
        )
        conn.execute("COMMIT")

        return QueueJob(
            job_id=str(row["job_id"]),
            tenant_id=str(row["tenant_id"]),
            idempotency_key=str(row["idempotency_key"]),
            content_fingerprint=str(row["content_fingerprint"]),
            payload=json.loads(str(row["payload_json"])),
            attempts=int(row["attempts"]),
            max_attempts=int(row["max_attempts"]),
        )

    def mark_done(self, job_id: str, note_path: str) -> None:
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE jobs_mt
                SET status = 'done',
                    updated_at = ?,
                    note_path = ?,
                    error = NULL,
                    next_retry_at = NULL,
                    processing_started_at = NULL
                WHERE job_id = ?
                """,
                (now, note_path, job_id),
            )

    def mark_failed_or_retry(self, job: QueueJob, error: str) -> tuple[str, int]:
        attempts = job.attempts + 1
        now_dt = datetime.now(UTC)
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
                UPDATE jobs_mt
                SET status = ?,
                    attempts = ?,
                    updated_at = ?,
                    error = ?,
                    next_retry_at = ?,
                    processing_started_at = NULL
                WHERE job_id = ?
                """,
                (status, attempts, now, error[:1500], next_retry_at, job.job_id),
            )

        return status, attempts

    def recover_stuck_jobs(self, *, max_processing_age_seconds: int, limit: int = 200) -> int:
        max_processing_age_seconds = max(1, int(max_processing_age_seconds))
        cutoff = (datetime.now(UTC) - timedelta(seconds=max_processing_age_seconds)).isoformat()
        now = _utc_now_iso()
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            """
            SELECT job_id FROM jobs_mt
            WHERE status = 'processing'
              AND (
                (processing_started_at IS NOT NULL AND processing_started_at <= ?)
                OR (processing_started_at IS NULL AND updated_at <= ?)
              )
            ORDER BY updated_at ASC
            LIMIT ?
            """,
            (cutoff, cutoff, limit),
        ).fetchall()
        if not rows:
            conn.execute("COMMIT")
            return 0

        for row in rows:
            conn.execute(
                """
                UPDATE jobs_mt
                SET status = 'retry',
                    next_retry_at = ?,
                    updated_at = ?,
                    processing_started_at = NULL,
                    error = CASE
                        WHEN error IS NULL OR error = '' THEN 'Recovered from stuck processing state.'
                        ELSE substr(error || ' | Recovered from stuck processing state.', 1, 1500)
                    END
                WHERE job_id = ?
                """,
                (now, now, row["job_id"]),
            )
        conn.execute("COMMIT")
        return len(rows)

    def get_note(self, content_fingerprint: str, tenant_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM notes_mt
                WHERE tenant_id = ? AND content_fingerprint = ?
                """,
                (tenant_id, content_fingerprint),
            ).fetchone()
        return dict(row) if row else None

    def resolve_note_ref(self, note_ref: str, tenant_id: str) -> tuple[bool, dict[str, Any] | str]:
        ref = note_ref.strip()
        if not ref:
            return False, "note reference is required"

        with self._connect() as conn:
            by_note_id = conn.execute(
                """
                SELECT tenant_id, content_fingerprint, note_id, file_name, last_job_id
                FROM notes_mt
                WHERE tenant_id = ? AND note_id = ?
                LIMIT 5
                """,
                (tenant_id, ref.upper()),
            ).fetchall()
            if len(by_note_id) == 1:
                return True, dict(by_note_id[0])
            if len(by_note_id) > 1:
                return False, "note id is ambiguous"

            by_job = conn.execute(
                """
                SELECT tenant_id, content_fingerprint, note_id, file_name, last_job_id
                FROM notes_mt
                WHERE tenant_id = ? AND (last_job_id = ? OR last_job_id LIKE ?)
                ORDER BY updated_at DESC
                LIMIT 5
                """,
                (tenant_id, ref, f"{ref}%"),
            ).fetchall()
            if len(by_job) == 1:
                return True, dict(by_job[0])
            if len(by_job) > 1:
                choices = ", ".join(str(row["note_id"]) for row in by_job)
                return False, f"job id is ambiguous across notes: {choices}"

            by_file = conn.execute(
                """
                SELECT tenant_id, content_fingerprint, note_id, file_name, last_job_id
                FROM notes_mt
                WHERE tenant_id = ? AND file_name = ?
                LIMIT 5
                """,
                (tenant_id, ref),
            ).fetchall()
            if len(by_file) == 1:
                return True, dict(by_file[0])
            if len(by_file) > 1:
                return False, "file name is ambiguous"

        return False, "note not found"

    def delete_note_record(self, *, tenant_id: str, content_fingerprint: str) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                """
                DELETE FROM notes_mt
                WHERE tenant_id = ? AND content_fingerprint = ?
                """,
                (tenant_id, content_fingerprint),
            )
            return int(result.rowcount or 0) > 0

    def list_notes(self, *, tenant_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT tenant_id, content_fingerprint, note_id, file_name, last_job_id
                FROM notes_mt
                WHERE tenant_id = ?
                ORDER BY updated_at DESC
                """,
                (tenant_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_all_notes(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT tenant_id, content_fingerprint, note_id, file_name, last_job_id
                FROM notes_mt
                ORDER BY tenant_id ASC, updated_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_all_note_records(self, *, tenant_id: str) -> int:
        with self._connect() as conn:
            result = conn.execute(
                """
                DELETE FROM notes_mt
                WHERE tenant_id = ?
                """,
                (tenant_id,),
            )
        return int(result.rowcount or 0)

    def create_delete_all_confirmation(
        self,
        *,
        tenant_id: str,
        user_id: int,
        chat_id: int,
        ttl_seconds: int = 120,
    ) -> dict[str, Any]:
        now_dt = datetime.now(UTC)
        ttl = max(1, int(ttl_seconds))
        now = now_dt.isoformat()
        expires_at = (now_dt + timedelta(seconds=ttl)).isoformat()
        token = uuid.uuid4().hex[:8].upper()

        with self._connect() as conn:
            self._prune_expired_delete_all_confirmations(conn, now=now)
            conn.execute(
                """
                INSERT INTO delete_all_confirmations_mt (
                    tenant_id, user_id, chat_id, token, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, user_id) DO UPDATE SET
                    chat_id = excluded.chat_id,
                    token = excluded.token,
                    created_at = excluded.created_at,
                    expires_at = excluded.expires_at
                """,
                (tenant_id, user_id, chat_id, token, now, expires_at),
            )
        return {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "chat_id": chat_id,
            "token": token,
            "created_at": now,
            "expires_at": expires_at,
        }

    def get_delete_all_confirmation(self, *, tenant_id: str, user_id: int) -> dict[str, Any] | None:
        now = _utc_now_iso()
        with self._connect() as conn:
            self._prune_expired_delete_all_confirmations(conn, now=now)
            row = conn.execute(
                """
                SELECT tenant_id, user_id, chat_id, token, created_at, expires_at
                FROM delete_all_confirmations_mt
                WHERE tenant_id = ? AND user_id = ?
                LIMIT 1
                """,
                (tenant_id, user_id),
            ).fetchone()
        return dict(row) if row else None

    def consume_delete_all_confirmation(
        self,
        *,
        tenant_id: str,
        user_id: int,
        token: str | None = None,
    ) -> tuple[bool, str]:
        now = _utc_now_iso()
        token_value = token.strip().upper() if token else None
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                """
                SELECT token, expires_at
                FROM delete_all_confirmations_mt
                WHERE tenant_id = ? AND user_id = ?
                LIMIT 1
                """,
                (tenant_id, user_id),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return False, "not_found"

            if str(row["expires_at"]) <= now:
                conn.execute(
                    """
                    DELETE FROM delete_all_confirmations_mt
                    WHERE tenant_id = ? AND user_id = ?
                    """,
                    (tenant_id, user_id),
                )
                conn.execute("COMMIT")
                return False, "expired"

            if token_value and str(row["token"]).upper() != token_value:
                conn.execute("COMMIT")
                return False, "token_mismatch"

            conn.execute(
                """
                DELETE FROM delete_all_confirmations_mt
                WHERE tenant_id = ? AND user_id = ?
                """,
                (tenant_id, user_id),
            )
            conn.execute("COMMIT")
            return True, "confirmed"
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def cancel_delete_all_confirmation(self, *, tenant_id: str, user_id: int) -> bool:
        now = _utc_now_iso()
        with self._connect() as conn:
            self._prune_expired_delete_all_confirmations(conn, now=now)
            result = conn.execute(
                """
                DELETE FROM delete_all_confirmations_mt
                WHERE tenant_id = ? AND user_id = ?
                """,
                (tenant_id, user_id),
            )
        return int(result.rowcount or 0) > 0

    def upsert_note(
        self,
        *,
        content_fingerprint: str,
        tenant_id: str,
        note_id: str,
        file_name: str,
        job_id: str,
    ) -> None:
        now = _utc_now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO notes_mt (
                    tenant_id, content_fingerprint, note_id, file_name, created_at, updated_at, last_job_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, content_fingerprint) DO UPDATE SET
                    note_id = excluded.note_id,
                    file_name = excluded.file_name,
                    updated_at = excluded.updated_at,
                    last_job_id = excluded.last_job_id
                """,
                (tenant_id, content_fingerprint, note_id, file_name, now, now, job_id),
            )

    def status_counts(self, tenant_id: str | None = None) -> dict[str, int]:
        with self._connect() as conn:
            if tenant_id:
                rows = conn.execute(
                    """
                    SELECT status, COUNT(*) AS count
                    FROM jobs_mt
                    WHERE tenant_id = ?
                    GROUP BY status
                    """,
                    (tenant_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT status, COUNT(*) AS count FROM jobs_mt GROUP BY status"
                ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def recent_jobs(self, limit: int = 10, tenant_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if tenant_id:
                rows = conn.execute(
                    """
                    SELECT job_id, tenant_id, status, attempts, max_attempts, updated_at, note_path
                    FROM jobs_mt
                    WHERE tenant_id = ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (tenant_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT job_id, tenant_id, status, attempts, max_attempts, updated_at, note_path
                    FROM jobs_mt
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def recent_failures(self, limit: int = 5, tenant_id: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if tenant_id:
                rows = conn.execute(
                    """
                    SELECT job_id, tenant_id, status, attempts, max_attempts, updated_at, error
                    FROM jobs_mt
                    WHERE tenant_id = ? AND status IN ('failed', 'retry')
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (tenant_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT job_id, tenant_id, status, attempts, max_attempts, updated_at, error
                    FROM jobs_mt
                    WHERE status IN ('failed', 'retry')
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def get_job_status(self, job_id: str, *, tenant_id: str | None = None) -> dict[str, Any] | None:
        with self._connect() as conn:
            if tenant_id:
                row = conn.execute(
                    """
                    SELECT job_id, tenant_id, status, error, note_path, updated_at
                    FROM jobs_mt
                    WHERE job_id = ? AND tenant_id = ?
                    LIMIT 1
                    """,
                    (job_id, tenant_id),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT job_id, tenant_id, status, error, note_path, updated_at
                    FROM jobs_mt
                    WHERE job_id = ?
                    LIMIT 1
                    """,
                    (job_id,),
                ).fetchone()
        return dict(row) if row else None

    def resolve_job_ref(self, job_ref: str, *, tenant_id: str | None = None) -> tuple[bool, dict[str, Any] | str]:
        ref = job_ref.strip()
        if not ref:
            return False, "job_id is required"

        with self._connect() as conn:
            if tenant_id:
                rows = conn.execute(
                    """
                    SELECT job_id, tenant_id, status, error, note_path, updated_at
                    FROM jobs_mt
                    WHERE tenant_id = ? AND (job_id = ? OR job_id LIKE ?)
                    ORDER BY updated_at DESC
                    LIMIT 5
                    """,
                    (tenant_id, ref, f"{ref}%"),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT job_id, tenant_id, status, error, note_path, updated_at
                    FROM jobs_mt
                    WHERE job_id = ? OR job_id LIKE ?
                    ORDER BY updated_at DESC
                    LIMIT 5
                    """,
                    (ref, f"{ref}%"),
                ).fetchall()

            if not rows:
                return False, "job not found"
            if len(rows) > 1:
                choices = ", ".join(str(row["job_id"])[:10] for row in rows)
                return False, f"job id is ambiguous: {choices}"

            return True, dict(rows[0])

    def retry_job(self, job_ref: str, tenant_id: str | None = None) -> tuple[bool, str]:
        if not job_ref.strip():
            return False, "job_id is required"

        with self._connect() as conn:
            if tenant_id:
                rows = conn.execute(
                    """
                    SELECT job_id, status
                    FROM jobs_mt
                    WHERE tenant_id = ? AND (job_id = ? OR job_id LIKE ?)
                    ORDER BY updated_at DESC
                    LIMIT 5
                    """,
                    (tenant_id, job_ref, f"{job_ref}%"),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT job_id, status
                    FROM jobs_mt
                    WHERE job_id = ? OR job_id LIKE ?
                    ORDER BY updated_at DESC
                    LIMIT 5
                    """,
                    (job_ref, f"{job_ref}%"),
                ).fetchall()

            if not rows:
                return False, "job not found"
            if len(rows) > 1:
                choices = ", ".join(str(row["job_id"])[:10] for row in rows)
                return False, f"job id is ambiguous: {choices}"

            row = rows[0]
            job_id = str(row["job_id"])
            status = str(row["status"])
            if status in {"pending", "retry", "processing"}:
                return False, f"job is already active with status={status}"
            if status == "done":
                return False, "only failed jobs can be retried"
            if status != "failed":
                return False, f"cannot retry job with status={status}"

            now = _utc_now_iso()
            conn.execute(
                """
                UPDATE jobs_mt
                SET status = 'retry',
                    next_retry_at = ?,
                    updated_at = ?,
                    processing_started_at = NULL
                WHERE job_id = ?
                """,
                (now, now, job_id),
            )
            return True, job_id

    def integrity_check(self) -> tuple[bool, str]:
        conn = self._connect()
        row = conn.execute("PRAGMA integrity_check").fetchone()
        if row is None:
            return False, "integrity_check returned no rows"  # pragma: no cover
        result = str(row[0] if isinstance(row, tuple) else row["integrity_check"])
        if result.strip().lower() != "ok":
            return False, result
        invalid_status = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM jobs_mt
            WHERE status NOT IN ('pending', 'retry', 'processing', 'done', 'failed')
            """
        ).fetchone()
        bad = int(invalid_status["count"]) if invalid_status else 0
        if bad:
            return False, f"Found jobs with invalid statuses: {bad}"
        return True, "ok"

    def close(self) -> None:
        conn = self._conn
        if conn is not None:
            try:
                conn.close()
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Failed to close state DB connection cleanly: %s", exc)
            self._conn = None

    def _ensure_meta_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )

    def _detect_schema_version(self, conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT MAX(version) AS version FROM schema_migrations"
        ).fetchone()
        if row and row["version"] is not None:
            return int(row["version"])

        if _table_exists(conn, "jobs_mt") and _table_exists(conn, "notes_mt"):
            return 1
        return 0

    def _set_schema_version(self, conn: sqlite3.Connection, version: int) -> None:
        now = _utc_now_iso()
        conn.execute(
            "DELETE FROM schema_migrations WHERE version > ?",
            (version,),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO schema_migrations (version, applied_at)
            VALUES (?, ?)
            """,
            (version, now),
        )

    def _migrate_to_v1(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs_mt (
                job_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
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
                next_retry_at TEXT,
                UNIQUE(tenant_id, idempotency_key)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_jobs_mt_status_retry
            ON jobs_mt(tenant_id, status, next_retry_at, created_at)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notes_mt (
                tenant_id TEXT NOT NULL,
                content_fingerprint TEXT NOT NULL,
                note_id TEXT NOT NULL,
                file_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_job_id TEXT NOT NULL,
                PRIMARY KEY (tenant_id, content_fingerprint)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_notes_mt_file_name
            ON notes_mt(tenant_id, file_name)
            """
        )

    def _migrate_to_v2(self, conn: sqlite3.Connection) -> None:
        _ensure_column(conn, "jobs_mt", "processing_started_at", "TEXT")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_jobs_mt_processing
            ON jobs_mt(status, processing_started_at, updated_at)
            """
        )

    def _migrate_to_v3(self, conn: sqlite3.Connection) -> None:
        _ensure_column(conn, "jobs_mt", "tenant_id", "TEXT NOT NULL DEFAULT 'legacy'")
        _ensure_column(conn, "notes_mt", "tenant_id", "TEXT NOT NULL DEFAULT 'legacy'")
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_jobs_mt_tenant_created
            ON jobs_mt(tenant_id, created_at)
            """
        )

    def _migrate_to_v4(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS delete_all_confirmations_mt (
                tenant_id TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                token TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, user_id)
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_delete_all_confirmations_mt_expires
            ON delete_all_confirmations_mt(expires_at)
            """
        )

    def _migrate_legacy_tables(self, conn: sqlite3.Connection) -> None:
        if _table_exists(conn, "jobs"):
            legacy_rows = conn.execute("SELECT * FROM jobs").fetchall()
            for row in legacy_rows:
                tenant_id = str(row["tenant_id"]) if "tenant_id" in row.keys() else "legacy"
                idempotency_key = str(row["idempotency_key"])
                existing = conn.execute(
                    """
                    SELECT 1 FROM jobs_mt
                    WHERE tenant_id = ? AND idempotency_key = ?
                    """,
                    (tenant_id, idempotency_key),
                ).fetchone()
                if existing:
                    continue
                conn.execute(
                    """
                    INSERT INTO jobs_mt (
                        job_id, tenant_id, idempotency_key, content_fingerprint, user_id, chat_id, message_id,
                        payload_json, status, attempts, max_attempts, error, note_path, created_at, updated_at, next_retry_at, processing_started_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        row["job_id"],
                        tenant_id,
                        row["idempotency_key"],
                        row["content_fingerprint"],
                        row["user_id"],
                        row["chat_id"],
                        row["message_id"],
                        row["payload_json"],
                        row["status"],
                        row["attempts"],
                        row["max_attempts"],
                        row["error"],
                        row["note_path"],
                        row["created_at"],
                        row["updated_at"],
                        row["next_retry_at"],
                    ),
                )

        if _table_exists(conn, "notes"):
            legacy_rows = conn.execute("SELECT * FROM notes").fetchall()
            for row in legacy_rows:
                tenant_id = str(row["tenant_id"]) if "tenant_id" in row.keys() else "legacy"
                existing = conn.execute(
                    """
                    SELECT 1 FROM notes_mt
                    WHERE tenant_id = ? AND content_fingerprint = ?
                    """,
                    (tenant_id, row["content_fingerprint"]),
                ).fetchone()
                if existing:
                    continue
                conn.execute(
                    """
                    INSERT INTO notes_mt (
                        tenant_id, content_fingerprint, note_id, file_name, created_at, updated_at, last_job_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tenant_id,
                        row["content_fingerprint"],
                        row["note_id"],
                        row["file_name"],
                        row["created_at"],
                        row["updated_at"],
                        row["last_job_id"],
                    ),
                )

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self._db_path), timeout=30, isolation_level=None)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def _prune_expired_delete_all_confirmations(self, conn: sqlite3.Connection, *, now: str) -> None:
        conn.execute(
            """
            DELETE FROM delete_all_confirmations_mt
            WHERE expires_at <= ?
            """,
            (now,),
        )


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, column_ddl: str) -> None:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    existing = {str(row["name"]) for row in rows}
    if column_name in existing:
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_ddl}")


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
