from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.rag.index_store import IndexStore
from src.rag.retriever import RagService


class IndexStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = IndexStore(Path(self._tmp.name) / "index" / "rag.sqlite3")
        self.store.initialize()

    def tearDown(self) -> None:
        self.store.close()
        self._tmp.cleanup()

    def test_upsert_search_stats_and_delete(self) -> None:
        note_a = str((Path(self._tmp.name) / "a.md").resolve())
        note_b = str((Path(self._tmp.name) / "b.md").resolve())

        self.store.upsert_document_chunks(
            note_path=note_a,
            content_hash="hash-a",
            chunks=["alpha text", "beta text"],
            embeddings=[[1.0, 0.0], [0.8, 0.2]],
        )
        self.store.upsert_document_chunks(
            note_path=note_b,
            content_hash="hash-b",
            chunks=["gamma text"],
            embeddings=[[0.0, 1.0]],
        )

        self.assertTrue(self.store.is_document_current(note_a, "hash-a"))
        self.assertFalse(self.store.is_document_current(note_a, "hash-x"))

        hits = self.store.search([1.0, 0.0], top_k=2)
        self.assertEqual(len(hits), 2)
        self.assertTrue(all(hit.note_path == note_a for hit in hits))
        self.assertGreaterEqual(hits[0].score, hits[1].score)

        stats = self.store.stats()
        self.assertEqual(stats["documents"], 2)
        self.assertEqual(stats["chunks"], 3)

        self.assertTrue(self.store.delete_document(note_a))
        self.assertFalse(self.store.is_document_current(note_a, "hash-a"))
        updated = self.store.stats()
        self.assertEqual(updated["documents"], 1)
        self.assertEqual(updated["chunks"], 1)

    def test_search_handles_dimension_mismatch(self) -> None:
        note = str((Path(self._tmp.name) / "note.md").resolve())
        self.store.upsert_document_chunks(
            note_path=note,
            content_hash="hash-note",
            chunks=["mismatch"],
            embeddings=[[0.5, 0.5, 0.5]],
        )

        hits = self.store.search([1.0, 0.0], top_k=1)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].note_path, note)

    def test_rag_service_prunes_stale_deleted_hits(self) -> None:
        vault = Path(self._tmp.name) / "vault"
        index_dir = Path(self._tmp.name) / "index-prune"
        vault.mkdir(parents=True, exist_ok=True)
        note = vault / "stale.md"
        note.write_text("alpha stale text", encoding="utf-8")

        service = RagService(vault, index_dir)
        try:
            service._index_store.upsert_document_chunks(
                note_path=str(note.resolve()),
                content_hash="hash-stale",
                chunks=["alpha stale text"],
                embeddings=[[1.0, 0.0]],
            )
            note.unlink()

            hits = service.find("alpha", top_k=5)
            self.assertEqual(hits, [])
            stats = service.stats()
            self.assertEqual(stats["documents"], 0)
            self.assertEqual(stats["chunks"], 0)
        finally:
            service.close()


if __name__ == "__main__":
    unittest.main()
