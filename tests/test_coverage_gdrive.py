"""Tests to cover missing branches in src/infra/gdrive.py."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.infra.gdrive import (
    DriveFile,
    GoogleDriveClient,
    _drive_file_from_payload,
    _escape_drive_query,
    _guess_file_name,
    _guess_mime_type,
    _is_telegram_file_url,
    _load_manifest,
    _merge_unique_links,
    _path_signature,
    _redact_all_telegram_urls,
    _sanitize_payload_links,
    _sqlite_backup,
    _update_manifest,
    _write_manifest,
    build_gdrive_client,
    mirror_note_to_drive,
    mirror_vault_once,
    redact_telegram_file_url,
    run_gdrive_maintenance_forever,
    snapshot_state_db_once,
)


class _FakeSession:
    def __init__(self, responses=None):
        self._responses = list(responses or [])
        self._idx = 0

    def post(self, url, **kwargs):
        return self._next()

    def request(self, method, url, **kwargs):
        return self._next()

    def _next(self):
        if self._idx >= len(self._responses):
            raise RuntimeError(f"No more mock responses (used {self._idx})")
        resp = self._responses[self._idx]
        self._idx += 1
        return resp


def _json_response(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.close = MagicMock()
    resp.raise_for_status = MagicMock()
    return resp


class GoogleDriveClientTests(unittest.TestCase):
    def _client(self, responses):
        session = _FakeSession(responses)
        return GoogleDriveClient(
            client_id="cid",
            client_secret="csec",
            refresh_token="rtok",
            root_folder_id="root-id",
            share_public_links=False,
            session=session,
        )

    def _token_resp(self):
        return _json_response({"access_token": "at", "expires_in": 3600})

    def test_upload_bytes_creates_and_uploads(self):
        token = self._token_resp()
        create_resp = _json_response({"id": "new-file"}, 201)
        upload_resp = _json_response({
            "id": "new-file", "name": "test.txt",
            "webViewLink": "https://drive/view", "webContentLink": "https://drive/dl",
        })
        # token + create + upload
        client = self._client([token, create_resp, upload_resp])
        result = client.upload_bytes(
            content=b"hello", name="test.txt", mime_type="text/plain",
            folder_path=(), app_properties={"k": "v"},
        )
        self.assertEqual(result.file_id, "new-file")

    def test_upload_bytes_updates_existing(self):
        token = self._token_resp()
        find_resp = _json_response({"files": [{"id": "exist-1", "name": "old.txt"}]})
        patch_resp = _json_response({"id": "exist-1"})
        upload_resp = _json_response({
            "id": "exist-1", "name": "new.txt",
            "webViewLink": "https://drive/view", "webContentLink": "https://drive/dl",
        })
        # token + find + patch + upload
        client = self._client([token, find_resp, patch_resp, upload_resp])
        result = client.upload_bytes(
            content=b"hello", name="new.txt", mime_type="text/plain",
            folder_path=(), existing_key=("key", "val"),
        )
        self.assertEqual(result.file_id, "exist-1")

    def test_upload_bytes_with_public_sharing(self):
        token = self._token_resp()
        create_resp = _json_response({"id": "pub-1"}, 201)
        upload_resp = _json_response({
            "id": "pub-1", "name": "f.txt",
            "webViewLink": "https://drive/view", "webContentLink": "https://drive/dl",
        })
        perm_resp = _json_response({}, 200)
        get_resp = _json_response({
            "id": "pub-1", "name": "f.txt",
            "webViewLink": "https://drive/view2", "webContentLink": "https://drive/dl2",
        })
        # token + create + upload + perm + get
        session = _FakeSession([token, create_resp, upload_resp, perm_resp, get_resp])
        client = GoogleDriveClient(
            client_id="cid", client_secret="csec", refresh_token="rtok",
            root_folder_id="root-id", share_public_links=True, session=session,
        )
        result = client.upload_bytes(
            content=b"x", name="f.txt", mime_type="text/plain", folder_path=(),
        )
        self.assertEqual(result.file_id, "pub-1")

    def test_upload_text_delegates(self):
        token = self._token_resp()
        create_resp = _json_response({"id": "txt-1"}, 201)
        upload_resp = _json_response({
            "id": "txt-1", "name": "n.md",
            "webViewLink": "https://d/v", "webContentLink": "https://d/d",
        })
        client = self._client([token, create_resp, upload_resp])
        result = client.upload_text(text="# hi", name="n.md", folder_path=())
        self.assertEqual(result.file_id, "txt-1")

    def test_upload_file_delegates(self):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(b"# note")
            fpath = Path(f.name)
        try:
            token = self._token_resp()
            create_resp = _json_response({"id": "f-1"}, 201)
            upload_resp = _json_response({
                "id": "f-1", "name": fpath.name,
                "webViewLink": "https://d/v", "webContentLink": "https://d/d",
            })
            client = self._client([token, create_resp, upload_resp])
            result = client.upload_file(file_path=fpath, folder_path=())
            self.assertEqual(result.file_id, "f-1")
        finally:
            fpath.unlink(missing_ok=True)

    def test_ensure_folder_path_creates_and_caches(self):
        token = self._token_resp()
        not_found_a = _json_response({"files": []})
        created_a = _json_response({"id": "folder-1"}, 201)
        not_found_b = _json_response({"files": []})
        created_b = _json_response({"id": "folder-2"}, 201)
        # token refresh (POST) + find_a (GET) + create_a (POST) + find_b (GET) + create_b (POST)
        client = self._client([token, not_found_a, created_a, not_found_b, created_b])
        fid = client.ensure_folder_path(("a", "b"))
        self.assertEqual(fid, "folder-2")
        # second call should use cache
        fid2 = client.ensure_folder_path(("a", "b"))
        self.assertEqual(fid2, "folder-2")

    def test_ensure_folder_path_finds_existing(self):
        token = self._token_resp()
        found = _json_response({"files": [{"id": "existing-f"}]})
        # token + find
        client = self._client([token, found])
        fid = client.ensure_folder_path(("docs",))
        self.assertEqual(fid, "existing-f")

    def test_request_retries_on_401(self):
        token1 = self._token_resp()
        unauth = _json_response({"error": "unauth"}, 401)
        unauth.close = MagicMock()
        token2 = self._token_resp()
        not_found = _json_response({"files": []}, 200)
        created = _json_response({"id": "retry-f"}, 201)
        # token1 + unauth(401) + token2_refresh + retry_success + create
        client = self._client([token1, unauth, token2, not_found, created])
        fid = client.ensure_folder_path(("test",))
        self.assertEqual(fid, "retry-f")

    def test_request_raises_on_unexpected_status(self):
        token = self._token_resp()
        bad = MagicMock()
        bad.status_code = 500
        bad.raise_for_status = MagicMock(side_effect=RuntimeError("500"))
        client = self._client([token, bad])
        with self.assertRaises(RuntimeError):
            client.ensure_folder_path(("fail",))


class GDriveHelpersTests(unittest.TestCase):
    def test_build_gdrive_client_disabled(self):
        config = SimpleNamespace(gdrive_enabled=False)
        self.assertIsNone(build_gdrive_client(config))

    def test_build_gdrive_client_missing_fields(self):
        config = SimpleNamespace(
            gdrive_enabled=True,
            gdrive_client_id="a", gdrive_client_secret="",
            gdrive_refresh_token="c", gdrive_root_folder_id="d",
            gdrive_share_public_links=False,
        )
        with self.assertRaises(RuntimeError):
            build_gdrive_client(config)

    def test_build_gdrive_client_success(self):
        config = SimpleNamespace(
            gdrive_enabled=True,
            gdrive_client_id="a", gdrive_client_secret="b",
            gdrive_refresh_token="c", gdrive_root_folder_id="d",
            gdrive_share_public_links=False,
        )
        client = build_gdrive_client(config)
        self.assertIsNotNone(client)

    def test_sqlite_backup(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "src.db"
            dst = Path(d) / "dst.db"
            conn = sqlite3.connect(str(src))
            conn.execute("CREATE TABLE t (x TEXT)")
            conn.execute("INSERT INTO t VALUES ('hello')")
            conn.commit()
            conn.close()
            _sqlite_backup(src, dst)
            conn2 = sqlite3.connect(str(dst))
            row = conn2.execute("SELECT x FROM t").fetchone()
            conn2.close()
            self.assertEqual(row[0], "hello")

    def test_manifest_operations(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "manifest.json"
            self.assertEqual(_load_manifest(p), {})
            _write_manifest(p, {"a": {"sig": "1"}})
            loaded = _load_manifest(p)
            self.assertEqual(loaded["a"]["sig"], "1")
            _update_manifest(
                p, relative_path="b",
                signature="s2",
                drive_file=DriveFile(file_id="f1", name="b", web_view_link="l", web_content_link="l"),
            )
            loaded2 = _load_manifest(p)
            self.assertIn("b", loaded2)

    def test_load_manifest_bad_json(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "manifest.json"
            p.write_text("not json!!!", encoding="utf-8")
            self.assertEqual(_load_manifest(p), {})

    def test_load_manifest_non_dict(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "manifest.json"
            p.write_text("[1,2,3]", encoding="utf-8")
            self.assertEqual(_load_manifest(p), {})

    def test_path_signature(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x")
            fpath = Path(f.name)
        try:
            sig = _path_signature(fpath)
            self.assertIn(":", sig)
        finally:
            fpath.unlink()

    def test_drive_file_from_payload(self):
        df = _drive_file_from_payload({"id": "x"})
        self.assertEqual(df.file_id, "x")
        self.assertIn("drive.google.com", df.web_view_link)

    def test_guess_file_name(self):
        self.assertEqual(_guess_file_name("https://example.com/audio.ogg", "audio/ogg"), "audio.ogg")
        name = _guess_file_name("https://example.com/", "audio/mpeg")
        self.assertTrue(name.startswith("telegram-media"))

    def test_guess_mime_type(self):
        self.assertEqual(_guess_mime_type("https://x.com/f.ogg", "audio/ogg"), "audio/ogg")
        self.assertEqual(_guess_mime_type("https://x.com/f.ogg", ""), "audio/ogg")
        m = _guess_mime_type("https://x.com/f.bin#tgmime=video%2Fmp4", "")
        # fragment parsing for mime
        self.assertIn("/", m)

    def test_escape_drive_query(self):
        self.assertEqual(_escape_drive_query("it's"), "it\\'s")
        self.assertEqual(_escape_drive_query("a\\b"), "a\\\\b")

    def test_is_telegram_file_url(self):
        self.assertTrue(_is_telegram_file_url("https://api.telegram.org/file/bot123/f"))
        self.assertFalse(_is_telegram_file_url("https://example.com/file"))

    def test_merge_unique_links(self):
        self.assertEqual(_merge_unique_links(["a", "b", "a", "", "  "]), ["a", "b"])

    def test_redact_telegram_file_url(self):
        url = "https://api.telegram.org/file/bot123:abc/voice/f.ogg#tgmime=audio%2Fogg"
        r = redact_telegram_file_url(url)
        self.assertIn("telegram://redacted", r)
        self.assertIn("audio/ogg", r)
        # non-telegram url passthrough
        self.assertEqual(redact_telegram_file_url("https://example.com"), "https://example.com")

    def test_redact_telegram_without_mime(self):
        url = "https://api.telegram.org/file/bot123:abc/voice/f.ogg"
        r = redact_telegram_file_url(url)
        self.assertIn("telegram://redacted/f.ogg", r)
        self.assertNotIn("#", r)

    def test_redact_all_telegram_urls(self):
        text = "see https://api.telegram.org/file/bot123/voice/f.ogg for audio"
        result = _redact_all_telegram_urls(text)
        self.assertIn("telegram://redacted", result)
        self.assertNotIn("api.telegram.org/file/bot", result)

    def test_sanitize_payload_links(self):
        payload = {
            "content": "telegram-file:///voice/f.ogg",
            "enriched_text": "telegram-file:///voice/f.ogg",
            "translation": "",
        }
        result = _sanitize_payload_links(payload, replacements={"telegram-file:///voice/f.ogg": "https://drive/f"})
        self.assertIn("https://drive/f", result["content"])


class MirrorAndSnapshotTests(unittest.TestCase):
    def test_mirror_note_to_drive_none(self):
        self.assertIsNone(mirror_note_to_drive(MagicMock(), None, Path("x.md")))

    def test_mirror_vault_once_none(self):
        self.assertEqual(mirror_vault_once(MagicMock(), None), {"uploaded": 0, "skipped": 0})

    def test_snapshot_state_db_once_none(self):
        self.assertIsNone(snapshot_state_db_once(MagicMock(), None))


class MaintenanceLoopTests(unittest.TestCase):
    def test_run_gdrive_maintenance_forever_none_returns(self):
        asyncio.run(run_gdrive_maintenance_forever(MagicMock(), None))

    def test_run_gdrive_maintenance_forever_runs_once(self):
        config = SimpleNamespace(
            gdrive_vault_mirror_interval_seconds=60,
            gdrive_db_snapshot_interval_seconds=3600,
        )
        call_count = 0

        async def _run():
            nonlocal call_count
            with patch("src.infra.gdrive.mirror_vault_once") as m_mirror, \
                 patch("src.infra.gdrive.snapshot_state_db_once") as m_snap:
                m_mirror.return_value = {"uploaded": 0, "skipped": 0}
                m_snap.return_value = None

                async def _cancel_after():
                    await asyncio.sleep(0.05)
                    raise asyncio.CancelledError()

                task = asyncio.create_task(run_gdrive_maintenance_forever(config, MagicMock()))
                cancel_task = asyncio.create_task(_cancel_after())
                try:
                    await asyncio.gather(task, cancel_task)
                except asyncio.CancelledError:
                    pass
                call_count = m_mirror.call_count

        asyncio.run(_run())
        self.assertGreaterEqual(call_count, 1)

    def test_run_gdrive_maintenance_forever_handles_errors(self):
        config = SimpleNamespace(
            gdrive_vault_mirror_interval_seconds=60,
            gdrive_db_snapshot_interval_seconds=3600,
        )

        async def _run():
            with patch("src.infra.gdrive.mirror_vault_once", side_effect=RuntimeError("boom")), \
                 patch("src.infra.gdrive.snapshot_state_db_once", side_effect=RuntimeError("snap")):
                task = asyncio.create_task(run_gdrive_maintenance_forever(config, MagicMock()))
                await asyncio.sleep(0.05)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
