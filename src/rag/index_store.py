"""Persistent vector index store."""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_log = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    note_path: str
    chunk_id: str
    chunk_text: str
    score: float

    @property
    def file_name(self) -> str:
        return Path(self.note_path).name


class IndexStore:
    def __init__(self, index_db_path: Path) -> None:
        self._db_path = index_db_path

    def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    note_path TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    note_path TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    chunk_text TEXT NOT NULL,
                    embedding_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_chunks_note_path
                ON chunks(note_path)
                """
            )

    def is_document_current(self, note_path: str, content_hash: str) -> bool:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT content_hash FROM documents WHERE note_path = ?",
                (note_path,),
            ).fetchone()
        return bool(row and row["content_hash"] == content_hash)

    def upsert_document_chunks(
        self,
        *,
        note_path: str,
        content_hash: str,
        chunks: list[str],
        embeddings: list[list[float]],
    ) -> None:
        if len(chunks) != len(embeddings):
            raise RuntimeError("chunks and embeddings must have equal length.")

        now = _utc_now_iso()
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("DELETE FROM chunks WHERE note_path = ?", (note_path,))
                for idx, (chunk, vector) in enumerate(zip(chunks, embeddings, strict=False)):
                    chunk_id = f"{note_path}::{idx}"
                    conn.execute(
                        """
                        INSERT INTO chunks (chunk_id, note_path, ordinal, chunk_text, embedding_json, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            chunk_id,
                            note_path,
                            idx,
                            chunk,
                            json.dumps(vector, separators=(",", ":")),
                            now,
                        ),
                    )
                conn.execute(
                    """
                    INSERT INTO documents (note_path, content_hash, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(note_path) DO UPDATE SET
                        content_hash = excluded.content_hash,
                        updated_at = excluded.updated_at
                    """,
                    (note_path, content_hash, now),
                )
                conn.execute("COMMIT")
            except Exception:  # pragma: no cover
                conn.execute("ROLLBACK")
                raise

    def search(self, query_embedding: list[float], top_k: int = 5) -> list[RetrievedChunk]:
        rows: list[dict] = []
        with self._connection() as conn:
            db_rows = conn.execute(
                """
                SELECT note_path, chunk_id, chunk_text, embedding_json
                FROM chunks
                ORDER BY updated_at DESC
                """
            ).fetchall()
            rows = [dict(row) for row in db_rows]

        scored: list[RetrievedChunk] = []
        for row in rows:
            embedding = json.loads(row["embedding_json"])
            score = _cosine_similarity(query_embedding, embedding)
            scored.append(
                RetrievedChunk(
                    note_path=row["note_path"],
                    chunk_id=row["chunk_id"],
                    chunk_text=row["chunk_text"],
                    score=score,
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:top_k]

    def stats(self) -> dict[str, int]:
        with self._connection() as conn:
            docs = conn.execute("SELECT COUNT(*) AS count FROM documents").fetchone()
            chunks = conn.execute("SELECT COUNT(*) AS count FROM chunks").fetchone()
        return {
            "documents": int(docs["count"]) if docs else 0,
            "chunks": int(chunks["count"]) if chunks else 0,
        }

    def delete_document(self, note_path: str) -> bool:
        with self._connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                conn.execute("DELETE FROM chunks WHERE note_path = ?", (note_path,))
                deleted_doc = conn.execute(
                    "DELETE FROM documents WHERE note_path = ?",
                    (note_path,),
                )
                conn.execute("COMMIT")
                return int(deleted_doc.rowcount or 0) > 0
            except Exception:  # pragma: no cover
                conn.execute("ROLLBACK")
                raise

    @contextmanager
    def _connection(self):
        with self._connect() as conn:
            yield conn

    def _connect(self) -> _ManagedConnection:
        conn = sqlite3.connect(str(self._db_path), timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return _ManagedConnection(conn)

    def close(self) -> None:
        return None


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) != len(b):
        _log.warning("Embedding dimension mismatch: %d vs %d", len(a), len(b))
        return 0.0
    return float(sum(a[i] * b[i] for i in range(len(a))))


class _ManagedConnection:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __getattr__(self, name: str):
        return getattr(self._conn, name)

    def __enter__(self) -> sqlite3.Connection:
        self._conn.__enter__()
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> bool | None:
        try:
            return self._conn.__exit__(exc_type, exc, tb)
        finally:
            self._conn.close()
