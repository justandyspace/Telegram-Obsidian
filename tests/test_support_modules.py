from __future__ import annotations

import asyncio
import os
import unittest
from datetime import UTC, datetime
from pathlib import Path

from src.infra.ai_fallback import (
    _cooldown_seconds,
    is_quota_error,
    is_remote_ai_available,
    mark_remote_ai_failure,
    reset_remote_ai,
)
from src.infra.health import HealthServer
from src.infra.metrics import record_event
from src.infra.tenancy import resolve_tenant_id, tenant_index_dir, tenant_vault_path
from src.obsidian.block_merge import build_block, merge_managed_blocks, replace_or_append_block
from src.obsidian.couchdb_bridge import CouchDBBridge
from src.obsidian.note_schema import NotePayload, render_meta
from src.pipeline.dedup import build_content_fingerprint, build_idempotency_key


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict[str, str]:
        return self._payload


class _FakeSession:
    def __init__(self, get_responses: list[_FakeResponse], put_statuses: list[int]) -> None:
        self.auth: tuple[str, str] | None = None
        self._get_responses = list(get_responses)
        self._put_statuses = list(put_statuses)
        self.put_payloads: list[str] = []

    def get(self, url: str) -> _FakeResponse:
        _ = url
        return self._get_responses.pop(0)

    def put(self, url: str, *, data: str, headers: dict[str, str]) -> _FakeResponse:
        _ = (url, headers)
        self.put_payloads.append(data)
        return _FakeResponse(self._put_statuses.pop(0))


class HealthServerTests(unittest.TestCase):
    def test_health_server_reports_ready_and_not_ready(self) -> None:
        async def scenario() -> None:
            ready_flag = {"value": True}
            server = HealthServer("127.0.0.1", 0, lambda: ready_flag["value"])
            await server.start()
            try:
                sockets = server._server.sockets if server._server is not None else []
                self.assertTrue(sockets)
                port = int(sockets[0].getsockname()[1])

                async def request() -> str:
                    reader, writer = await asyncio.open_connection("127.0.0.1", port)
                    writer.write(b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n")
                    await writer.drain()
                    body = await reader.read()
                    writer.close()
                    await writer.wait_closed()
                    return body.decode("utf-8")

                ready_response = await request()
                self.assertIn("200 OK", ready_response)
                self.assertTrue(ready_response.endswith("ok"))

                ready_flag["value"] = False
                not_ready_response = await request()
                self.assertIn("503 Service Unavailable", not_ready_response)
                self.assertTrue(not_ready_response.endswith("not ready"))
            finally:
                await server.stop()

        asyncio.run(scenario())


class TenantAndMetricsTests(unittest.TestCase):
    def test_tenant_helpers_route_paths(self) -> None:
        base = Path("C:/vault")
        self.assertEqual(resolve_tenant_id(42), "tg_42")
        self.assertEqual(tenant_vault_path(base, "tg_42", multi_tenant=False), base)
        self.assertEqual(tenant_vault_path(base, "tg_42", multi_tenant=True), base / "tg_42")
        self.assertEqual(tenant_index_dir(base, "tg_42", multi_tenant=False), base)
        self.assertEqual(tenant_index_dir(base, "tg_42", multi_tenant=True), base / "tg_42")

    def test_record_event_is_noop(self) -> None:
        record_event("worker_started")

    def test_ai_fallback_helpers_cover_quota_gate_and_env_parsing(self) -> None:
        scope = "support-test"
        reset_remote_ai(scope)
        self.assertTrue(is_remote_ai_available(scope))
        self.assertTrue(is_quota_error(RuntimeError("429 RESOURCE_EXHAUSTED")))
        self.assertFalse(is_quota_error(RuntimeError("plain failure")))

        mark_remote_ai_failure(scope, RuntimeError("plain failure"))
        self.assertTrue(is_remote_ai_available(scope))

        original = os.environ.get("AI_REMOTE_COOLDOWN_SECONDS")
        try:
            os.environ["AI_REMOTE_COOLDOWN_SECONDS"] = "10"
            self.assertEqual(_cooldown_seconds(), 30.0)
            os.environ["AI_REMOTE_COOLDOWN_SECONDS"] = "invalid"
            self.assertEqual(_cooldown_seconds(), 900.0)

            mark_remote_ai_failure(scope, RuntimeError("quota exceeded"))
            self.assertFalse(is_remote_ai_available(scope))
        finally:
            if original is None:
                os.environ.pop("AI_REMOTE_COOLDOWN_SECONDS", None)
            else:
                os.environ["AI_REMOTE_COOLDOWN_SECONDS"] = original
            reset_remote_ai(scope)


class ObsidianHelpersTests(unittest.TestCase):
    def test_block_merge_replaces_existing_and_appends_missing(self) -> None:
        document = (
            "# Title\n\n"
            "<!-- BOT_META:START -->\nold\n<!-- BOT_META:END -->\n\n"
            "## User Content\nbody\n"
        )
        replaced = replace_or_append_block(document, name="BOT_META", body="new")
        self.assertIn(build_block("BOT_META", "new"), replaced)

        merged = merge_managed_blocks(replaced, {"BOT_LINKS": "- link"})
        self.assertIn(build_block("BOT_LINKS", "- link"), merged)
        self.assertIn("## User Content", merged)

    def test_render_meta_includes_forward_source_and_tags(self) -> None:
        payload = NotePayload(
            note_id="ABCD1234",
            file_name="note.md",
            title="Test",
            content="content",
            hashtags=["tag1", "tag2"],
            actions=["save", "summary"],
            source_chat_id=1,
            source_message_id=2,
            source_user_id=3,
            source_datetime=datetime(2026, 3, 5, 12, 0, tzinfo=UTC),
            forward_source="Channel",
        )
        rendered = render_meta(payload)
        self.assertIn("forward_source: Channel", rendered)
        self.assertIn("actions: #save, #summary", rendered)
        self.assertIn("tags: #tag1, #tag2", rendered)

    def test_dedup_keys_are_stable_and_action_sensitive(self) -> None:
        fingerprint_a = build_content_fingerprint(
            user_id=7,
            normalized_content="same text",
            semantic_hashtags={"alpha", "beta"},
        )
        fingerprint_b = build_content_fingerprint(
            user_id=7,
            normalized_content="same text",
            semantic_hashtags={"beta", "alpha"},
        )
        self.assertEqual(fingerprint_a, fingerprint_b)

        save_key = build_idempotency_key(content_fingerprint=fingerprint_a, actions={"save"})
        summary_key = build_idempotency_key(content_fingerprint=fingerprint_a, actions={"summary"})
        self.assertNotEqual(save_key, summary_key)


class CouchDBBridgeTests(unittest.TestCase):
    def test_push_note_updates_existing_docs(self) -> None:
        bridge = CouchDBBridge("http://example.test", "user", "pass", "notes")
        bridge.session = _FakeSession(
            get_responses=[
                _FakeResponse(200, {"_rev": "1-a"}),
                _FakeResponse(200, {"_rev": "2-b"}),
            ],
            put_statuses=[201, 202],
        )

        ok = bridge.push_note("note.md", "Hello world")
        self.assertTrue(ok)
        self.assertEqual(len(bridge.session.put_payloads), 2)
        self.assertIn('"type": "leaf"', bridge.session.put_payloads[0])
        self.assertIn('"type": "plain"', bridge.session.put_payloads[1])

    def test_push_note_returns_false_on_transport_error(self) -> None:
        bridge = CouchDBBridge("http://example.test", "user", "pass", "notes")

        class _ExplodingSession:
            auth: tuple[str, str] | None = None

            def get(self, url: str) -> _FakeResponse:
                _ = url
                raise RuntimeError("network down")

        bridge.session = _ExplodingSession()
        self.assertFalse(bridge.push_note("note.md", "Hello world"))


if __name__ == "__main__":
    unittest.main()
