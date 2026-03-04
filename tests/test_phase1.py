from __future__ import annotations

import shutil
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.infra.storage import StateStore
from src.obsidian.note_writer import ObsidianNoteWriter
from src.obsidian.vault_router import deterministic_file_name


class Phase1FoundationTests(unittest.TestCase):
    def test_deterministic_filename_format(self) -> None:
        name = deterministic_file_name(
            created_at=datetime(2026, 3, 4, 21, 15, tzinfo=timezone.utc),
            title="My Test Title",
            note_id="ABCD1234",
        )
        self.assertEqual(name, "20260304-2115 - My Test Title (ABCD1234).md")

    def test_managed_block_update_keeps_user_content(self) -> None:
        tmpdir = Path(".data") / "test_phase1"
        if tmpdir.exists():
            shutil.rmtree(tmpdir, ignore_errors=True)
        tmpdir.mkdir(parents=True, exist_ok=True)

        store = StateStore(tmpdir / "state.sqlite3")
        store.initialize()
        writer = ObsidianNoteWriter(tmpdir / "vault", store)

        payload = {
            "content": "Initial user text",
            "title": "Sample",
            "hashtags": ["save"],
            "actions": ["save"],
            "content_fingerprint": "f" * 64,
            "source": {
                "chat_id": 1,
                "message_id": 10,
                "message_datetime": datetime.now(timezone.utc).isoformat(),
                "user_id": 999,
            },
        }

        note_path = Path(writer.write(job_id="job1", payload=payload))
        original = note_path.read_text(encoding="utf-8")
        note_path.write_text(original + "\nUser manual line\n", encoding="utf-8")

        payload["actions"] = ["resummarize"]
        writer.write(job_id="job2", payload=payload)

        updated = note_path.read_text(encoding="utf-8")
        self.assertIn("User manual line", updated)
        self.assertIn("<!-- BOT_META:START -->", updated)
        self.assertIn("<!-- BOT_SUMMARY:START -->", updated)

        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
