from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.infra.gdrive import (
    DriveFile,
    enrich_payload_with_drive_attachments,
    mirror_vault_once,
    snapshot_state_db_once,
)
from src.infra.storage import StateStore
from src.obsidian.note_writer import ObsidianNoteWriter


class _FakeResponse:
    def __init__(self, content: bytes, *, content_type: str = "audio/ogg") -> None:
        self.content = content
        self.headers = {"Content-Type": content_type}

    def close(self) -> None:
        return None


class _FakeDrive:
    def __init__(self) -> None:
        self.upload_bytes_calls: list[dict[str, object]] = []
        self.upload_file_calls: list[dict[str, object]] = []

    def upload_bytes(
        self,
        *,
        content: bytes,
        name: str,
        mime_type: str,
        folder_path: tuple[str, ...],
        app_properties: dict[str, str] | None = None,
        existing_key: tuple[str, str] | None = None,
    ) -> DriveFile:
        self.upload_bytes_calls.append(
            {
                "content": content,
                "name": name,
                "mime_type": mime_type,
                "folder_path": folder_path,
                "app_properties": app_properties,
                "existing_key": existing_key,
            }
        )
        return DriveFile(
            file_id="drive-file-1",
            name=name,
            web_view_link="https://drive.google.com/file/d/drive-file-1/view",
            web_content_link="https://drive.google.com/uc?id=drive-file-1",
        )

    def upload_file(
        self,
        *,
        file_path: Path,
        folder_path: tuple[str, ...],
        app_properties: dict[str, str] | None = None,
        existing_key: tuple[str, str] | None = None,
    ) -> DriveFile:
        self.upload_file_calls.append(
            {
                "file_path": file_path,
                "folder_path": folder_path,
                "app_properties": app_properties,
                "existing_key": existing_key,
            }
        )
        return DriveFile(
            file_id=f"file-{len(self.upload_file_calls)}",
            name=file_path.name,
            web_view_link=f"https://drive.google.com/file/d/file-{len(self.upload_file_calls)}/view",
            web_content_link=f"https://drive.google.com/uc?id=file-{len(self.upload_file_calls)}",
        )


class GoogleDriveIntegrationTests(unittest.TestCase):
    def test_enrich_payload_uploads_attachment_and_redacts_telegram_url(self) -> None:
        source_url = "https://api.telegram.org/file/bot123456:abc/voice/file_1.ogg#tgmime=audio%2Fogg"
        payload = {
            "tenant_id": "tg_1",
            "content": f"Voice message\nMedia URL: {source_url}",
            "enriched_text": f"Media URL: {source_url}",
            "parsed_items": [
                {
                    "parser": "voice",
                    "source_url": source_url,
                    "status": "ok",
                    "title": "Voice transcription",
                    "text": "hello",
                    "links": [source_url],
                    "error": None,
                }
            ],
            "source": {"chat_id": 77, "message_id": 88},
        }

        drive = _FakeDrive()
        with patch("src.infra.gdrive.safe_http_get", return_value=_FakeResponse(b"audio-bytes")):
            enriched = enrich_payload_with_drive_attachments(payload, drive)

        self.assertIn("cloud_attachments", enriched)
        self.assertIn("drive.google.com", enriched["content"])
        self.assertNotIn("api.telegram.org/file/bot", enriched["content"])
        self.assertEqual(enriched["parsed_items"][0]["source_url"], "telegram://redacted/file_1.ogg#audio/ogg")
        self.assertIn("https://drive.google.com/file/d/drive-file-1/view", enriched["parsed_items"][0]["links"])
        self.assertEqual(drive.upload_bytes_calls[0]["folder_path"], ("telegram_media", "tg_1"))

    def test_note_writer_renders_drive_link_without_leaking_telegram_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = StateStore(root / "state.sqlite3")
            store.initialize()
            try:
                writer = ObsidianNoteWriter(root / "vault", store, multi_tenant=False)
                payload = {
                    "tenant_id": "tg_1",
                    "content": "Voice message transcript",
                    "title": "Voice note",
                    "hashtags": ["voice"],
                    "actions": ["save"],
                    "content_fingerprint": "a" * 64,
                    "cloud_attachments": [
                        {
                            "name": "file_1.ogg",
                            "web_view_link": "https://drive.google.com/file/d/drive-file-1/view",
                        }
                    ],
                    "parsed_items": [
                        {
                            "parser": "voice",
                            "source_url": "https://api.telegram.org/file/bot123/voice/file_1.ogg",
                            "status": "ok",
                            "title": "Voice transcription",
                            "text": "hello",
                            "links": ["https://drive.google.com/file/d/drive-file-1/view"],
                            "error": None,
                        }
                    ],
                    "source": {
                        "chat_id": 1,
                        "message_id": 2,
                        "message_datetime": datetime.now(UTC).isoformat(),
                        "user_id": 3,
                    },
                }
                note_path = Path(writer.write(job_id="job-1", payload=payload))
                text = note_path.read_text(encoding="utf-8")
            finally:
                store.close()

        self.assertIn("drive.google.com/file/d/drive-file-1/view", text)
        self.assertIn("telegram://redacted/file_1.ogg", text)
        self.assertNotIn("api.telegram.org/file/bot123", text)

    def test_vault_mirror_uses_manifest_and_db_snapshot_uploads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "vault"
            state = root / "state"
            cache = root / "cache"
            vault.mkdir()
            state.mkdir()
            cache.mkdir()
            note_path = vault / "note.md"
            note_path.write_text("# note\n", encoding="utf-8")

            db_path = state / "bot_state.sqlite3"
            store = StateStore(db_path)
            store.initialize()
            store.close()

            config = SimpleNamespace(
                vault_path=vault,
                state_dir=state,
                cache_dir=cache,
                state_db_path=db_path,
            )
            drive = _FakeDrive()

            first = mirror_vault_once(config, drive)
            second = mirror_vault_once(config, drive)
            snapshot = snapshot_state_db_once(config, drive)

        self.assertEqual(first["uploaded"], 1)
        self.assertEqual(second["uploaded"], 0)
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(len(drive.upload_file_calls), 2)
        self.assertTrue(snapshot)


if __name__ == "__main__":
    unittest.main()
