from __future__ import annotations

import shutil
import unittest
import uuid
from pathlib import Path

from src.rag.chunker import chunk_text
from src.rag.retriever import RagService


class Phase3RagTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(".data") / f"test_phase3_{uuid.uuid4().hex[:8]}"
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)
        (self.root / "vault").mkdir(parents=True, exist_ok=True)
        (self.root / "index").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_chunker_multilingual(self) -> None:
        text = (
            "RU блок про заметки и дедуп.\n\n"
            "EN block about semantic retrieval and indexing.\n\n"
            "UK блок про індексацію та відповіді з посиланнями."
        )
        chunks = chunk_text(text, max_chars=80, overlap_chars=20)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(any("semantic retrieval" in chunk for chunk in chunks))

    def test_rag_find_and_grounded_answer(self) -> None:
        note_a = self.root / "vault" / "20260304-1200 - Project Alpha (A1).md"
        note_b = self.root / "vault" / "20260304-1300 - Finance Plan (B1).md"
        note_a.write_text(
            "# Project Alpha\n\nMilestone review is planned on Friday.\n",
            encoding="utf-8",
        )
        note_b.write_text(
            "# Finance Plan\n\nPayment deadline is March 20 and budget owner is Anna.\n",
            encoding="utf-8",
        )

        rag = RagService(
            self.root / "vault",
            self.root / "index",
            gemini_api_key="",
        )
        indexed = rag.reindex_vault_incremental(limit=20)
        self.assertGreaterEqual(indexed, 2)

        hits = rag.find("payment deadline", top_k=3)
        self.assertTrue(hits)
        self.assertIn(note_b.name, [item.file_name for item in hits])

        answer = rag.answer("When is the payment deadline?", top_k=3)
        self.assertTrue(answer.sources)
        self.assertIn(note_b.name, [item.file_name for item in answer.sources])
        self.assertIn("Grounded findings", answer.answer)

    def test_incremental_note_reindex(self) -> None:
        note = self.root / "vault" / "20260304-1500 - Ops Note (C1).md"
        note.write_text("# Ops\n\nInitial text", encoding="utf-8")
        rag = RagService(self.root / "vault", self.root / "index", gemini_api_key="")

        first = rag.index_note(note)
        second = rag.index_note(note)
        note.write_text("# Ops\n\nInitial text updated with retry policy", encoding="utf-8")
        third = rag.index_note(note)

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertTrue(third)


if __name__ == "__main__":
    unittest.main()
