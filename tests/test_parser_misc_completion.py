from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests

from src.config import load_config
from src.infra.resilience import RetryPolicy, async_with_retry, with_retry
from src.obsidian.couchdb_bridge import CouchDBBridge
from src.obsidian.note_writer import ObsidianNoteWriter
from src.obsidian.search import find_notes
from src.parsers.article_parser import _extract_title, parse_article
from src.parsers.models import ParseResult
from src.parsers.pdf_parser import _guess_title, parse_pdf
from src.parsers.router import (
    _has_voice_mime_fragment,
    _host_matches,
    _is_audio_path,
    classify_source,
    classify_url,
    enrich_payload,
    parse_url,
)
from src.parsers.twitter_fallback_parser import _convert_urls, _read_meta, parse_twitter_fallback
from src.parsers.url_safety import (
    HttpFetchError,
    _enforce_max_body_size,
    _request_with_resilience,
    safe_http_get,
    validate_public_http_url,
)
from src.parsers.voice_parser import (
    _guess_mime_type,
    _guess_mime_type_from_source,
    _is_temp_path,
    _load_audio_bytes,
    _resolve_local_audio_path,
    parse_voice,
)
from src.parsers.youtube_parser import _fetch_title, parse_youtube
from src.pipeline.enrichment import (
    _append_summary,
    _merge_tags,
    _normalize_tags,
    _parse_ai_response,
    enrich_payload_with_ai,
)
from src.pipeline.normalize import (
    ascii_safe_title,
    derive_title,
    normalize_text,
    short_summary,
    strip_hashtags,
)
from src.rag.chunker import _slice_large_text, chunk_text
from src.rag.embedder import EmbedderError, GeminiEmbedder, build_embedder
from src.rag.index_store import IndexStore, _cosine_similarity
from src.rag.retriever import RagService
from src.watcher import NoteEventProcessor, run_watcher
from src.worker import run_worker


class FakeHttpResponse:
    def __init__(
        self,
        *,
        text: str = "",
        content: bytes = b"",
        url: str = "https://example.test",
        ok: bool = True,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        json_payload: dict[str, str] | None = None,
        chunks: list[bytes] | None = None,
    ) -> None:
        self.text = text
        self.content = content
        self.url = url
        self.ok = ok
        self.status_code = status_code
        self.headers = headers or {}
        self._json_payload = json_payload or {}
        self._chunks = chunks or []
        self.closed = False

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self) -> dict[str, str]:
        return self._json_payload

    def close(self) -> None:
        self.closed = True

    def iter_content(self, chunk_size: int):
        _ = chunk_size
        yield from self._chunks


class SessionCM:
    def __init__(self, responses: list[FakeHttpResponse] | None = None, errors: list[Exception] | None = None) -> None:
        self.responses = list(responses or [])
        self.errors = list(errors or [])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, *args, **kwargs):
        _ = (args, kwargs)
        if self.errors:
            raise self.errors.pop(0)
        return self.responses.pop(0)


class ParserMiscCompletionTests(unittest.TestCase):
    def test_parsers_and_enrichment_cover_remaining_branches(self) -> None:
        self.assertEqual(_extract_title(SimpleNamespace(title=SimpleNamespace(text="Page Title"), select_one=lambda selector: None)), "Page Title")
        soup = SimpleNamespace(title=None, select_one=lambda selector: SimpleNamespace(text="Header") if selector == "h1" else None)
        self.assertEqual(_extract_title(soup), "Header")

        fallback_html = FakeHttpResponse(
            text="<html><body>fallback text repeated enough to count as body fallback content for parser coverage</body></html>",
            url="https://example.test/final",
        )
        with patch("src.parsers.article_parser.safe_http_get", return_value=fallback_html):
            article = parse_article("https://example.test/post")
        self.assertEqual(article.status, "fallback")
        self.assertIn("fallback text repeated", article.text)

        with patch("src.parsers.pdf_parser.safe_http_get", side_effect=RuntimeError("fetch fail")):
            pdf = parse_pdf("https://example.test/doc.pdf")
        self.assertEqual(pdf.status, "error")

        response = FakeHttpResponse(content=b"%PDF")
        with patch("src.parsers.pdf_parser.safe_http_get", return_value=response), patch(
            "src.parsers.pdf_parser.PdfReader",
            side_effect=RuntimeError("parse fail"),
        ):
            pdf = parse_pdf("https://example.test/doc.pdf")
        self.assertEqual(pdf.status, "error")
        self.assertEqual(_guess_title(""), "PDF Document")

        self.assertEqual(parse_youtube("https://example.test").status, "error")
        self.assertEqual(_fetch_title("https://youtu.be/x", 1), "")
        with patch("src.parsers.youtube_parser.safe_http_get", return_value=FakeHttpResponse(ok=True, json_payload={"title": "YT Title"})):
            self.assertEqual(_fetch_title("https://youtu.be/x", 1), "YT Title")
        with patch("src.parsers.youtube_parser.safe_http_get", side_effect=RuntimeError("no title")):
            self.assertEqual(_fetch_title("https://youtu.be/x", 1), "")

        self.assertEqual(classify_url("https://example.test/file.mp3"), "voice")
        self.assertEqual(classify_url("https://example.test/file.pdf"), "pdf")
        self.assertEqual(classify_url("https://youtu.be/x"), "youtube")
        self.assertEqual(classify_url("https://x.com/a/status/1"), "twitter_fallback")
        self.assertEqual(classify_url("https://example.test#tgmime=audio%2Fmpeg"), "voice")
        self.assertEqual(classify_source("C:/audio.mp3"), "voice")
        self.assertEqual(classify_source("C:/note.txt"), "article")
        self.assertTrue(_host_matches("sub.youtube.com:443", "youtube.com"))
        self.assertTrue(_is_audio_path("https://example.test/file.ogg"))
        self.assertFalse(_has_voice_mime_fragment("x=y"))

        fake_result = ParseResult(parser="article", source_url="u", status="ok", title="T", text="Body", links=["u"])
        with patch("src.parsers.router.parse_url", return_value=fake_result):
            enriched = enrich_payload({"content": "https://example.test"})
        self.assertEqual(enriched["parsed_items"][0]["title"], "T")
        self.assertIn("Body", enriched["enriched_text"])

        with patch("src.parsers.router.parse_voice", return_value=fake_result):
            self.assertEqual(parse_url("C:/audio.mp3"), fake_result)
        with patch("src.parsers.router.parse_pdf", return_value=fake_result):
            self.assertEqual(parse_url("https://example.test/a.pdf"), fake_result)
        with patch("src.parsers.router.parse_youtube", return_value=fake_result):
            self.assertEqual(parse_url("https://youtu.be/x"), fake_result)
        with patch("src.parsers.router.parse_twitter_fallback", return_value=fake_result):
            self.assertEqual(parse_url("https://x.com/a/status/1"), fake_result)
        self.assertEqual(_convert_urls("https://x.com/a/status/1?x=1")[0], "https://fxtwitter.com/a/status/1?x=1")
        self.assertEqual(_read_meta(SimpleNamespace(select_one=lambda selector: None), "og:title"), "")
        with patch("src.parsers.twitter_fallback_parser.safe_http_get", return_value=FakeHttpResponse(text="<html></html>")):
            twitter = parse_twitter_fallback("https://x.com/a/status/1")
        self.assertEqual(twitter.status, "fallback")

        self.assertEqual(_parse_ai_response(None), ([], "", ""))
        self.assertEqual(_parse_ai_response("bad-json"), ([], "", ""))
        self.assertEqual(_normalize_tags("bad"), [])
        self.assertEqual(_normalize_tags(["A", "#A", "b c"]), ["a", "b_c"])
        self.assertEqual(_merge_tags(["a"], ["a", "b"]), ["a", "b"])
        self.assertEqual(_append_summary("", "summary"), "AI summary: summary")
        self.assertEqual(_append_summary("base", ""), "base")
        self.assertEqual(_append_summary("AI summary: summary", "summary"), "AI summary: summary")

        payload = {"content": "text", "actions": [], "auto_tags": ["seed"], "ai_summary": "existing"}
        self.assertEqual(enrich_payload_with_ai(payload, api_key="", model_name="x")["ai_summary"], "existing")
        no_summary = enrich_payload_with_ai({"content": "text"}, api_key="k", model_name="x", client=SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs: SimpleNamespace(text=""))))
        self.assertEqual(no_summary["auto_tags"], [])
        with patch(
            "src.pipeline.enrichment.with_retry",
            return_value=SimpleNamespace(text='{"tags":["new"],"summary":"brief","translation":"ru"}'),
        ):
            rich = enrich_payload_with_ai({"content": "text", "actions": ["translate"]}, api_key="k", model_name="m", client=SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs: None)))
        self.assertEqual(rich["translation"], "ru")

    def test_config_resilience_normalize_and_url_safety_helpers(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "APP_ROLE": "standalone",
                "TELEGRAM_TOKEN": "token",
                "TELEGRAM_ALLOWED_USER_ID": "1",
            },
            clear=True,
        ):
            self.assertEqual(load_config().role, "standalone")

        with patch.dict(
            "os.environ",
            {
                "APP_ROLE": "bot",
                "TELEGRAM_TOKEN": "token",
                "TELEGRAM_ALLOWED_USER_ID": "1",
                "WEBHOOK_SECRET_TOKEN": "not-weak-but-valid",
            },
            clear=True,
        ):
            self.assertEqual(load_config().webhook_secret_token, "not-weak-but-valid")
        with patch.dict(
            "os.environ",
            {
                "APP_ROLE": "bot",
                "TELEGRAM_TOKEN": "token",
                "TELEGRAM_ALLOWED_USER_IDS": "1, ,2",
                "WEBHOOK_SECRET_TOKEN": "secret",
            },
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                load_config()
        with patch.dict(
            "os.environ",
            {
                "APP_ROLE": "bot",
                "TELEGRAM_TOKEN": "token",
                "TELEGRAM_ALLOWED_USER_ID": "1",
                "WEBHOOK_SECRET_TOKEN": "change_me",
            },
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                load_config()
        with patch.dict(
            "os.environ",
            {
                "APP_ROLE": "bot",
                "TELEGRAM_TOKEN": "token",
                "TELEGRAM_ALLOWED_USER_IDS": " ",
            },
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                load_config()
        with patch.dict(
            "os.environ",
            {
                "APP_ROLE": "bot",
                "TELEGRAM_TOKEN": "token",
                "TELEGRAM_ALLOWED_USER_IDS": ",,",
            },
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                load_config()

        with self.assertRaises(ValueError):
            validate_public_http_url("http://example.com:99999")

        with self.assertRaises(ValueError):
            with_retry(RetryPolicy(max_attempts=1, base_delay_seconds=0, max_delay_seconds=0, jitter_ratio=0), lambda: (_ for _ in ()).throw(ValueError("x")), exc_types=(ValueError,))
        with self.assertRaises(ValueError):
            asyncio.run(async_with_retry(RetryPolicy(max_attempts=1, base_delay_seconds=0, max_delay_seconds=0, jitter_ratio=0), _async_raise, exc_types=(ValueError,)))

        self.assertEqual(strip_hashtags("#one text #two"), " text ")
        self.assertEqual(normalize_text(" a \u00a0 b "), "a b")
        self.assertEqual(derive_title("!!!"), "Untitled")
        self.assertEqual(ascii_safe_title("Привет"), "Note")
        self.assertEqual(short_summary("a" * 10, 5), "aa...")
        self.assertEqual(chunk_text("same", max_chars=100), ["same"])
        self.assertEqual(_slice_large_text("tiny", 10, 2), ["tiny"])
        self.assertEqual(_cosine_similarity([], [1.0]), 0.0)
        self.assertEqual(_cosine_similarity([1.0], [1.0, 2.0]), 0.0)
        self.assertTrue(_is_temp_path(str(Path(tempfile.gettempdir()) / "x.tmp")))
        self.assertEqual(ParseResult(parser="x", source_url="u", status="ok", title="t", text="body").to_payload()["text"], "body")

    def test_http_helpers_and_couchdb_remaining_paths(self) -> None:
        session = SessionCM(
            responses=[
                FakeHttpResponse(status_code=302, headers={"Location": "/next"}),
                FakeHttpResponse(status_code=200, content=b"ok", url="https://example.test/next"),
            ]
        )
        with patch("src.parsers.url_safety.requests.Session", return_value=session), patch(
            "src.parsers.url_safety.validate_public_http_url",
            return_value=None,
        ):
            response = safe_http_get("https://example.test", timeout_seconds=1)
        self.assertEqual(response.url, "https://example.test/next")
        session = SessionCM(responses=[FakeHttpResponse(status_code=302, headers={})])
        with patch("src.parsers.url_safety.requests.Session", return_value=session), patch(
            "src.parsers.url_safety.validate_public_http_url",
            return_value=None,
        ):
            response = safe_http_get("https://example.test", timeout_seconds=1)
        self.assertEqual(response.status_code, 302)

        retry_policy = RetryPolicy(max_attempts=1, base_delay_seconds=0, max_delay_seconds=0, jitter_ratio=0)
        with self.assertRaises(HttpFetchError):
            _request_with_resilience(
                SessionCM(errors=[requests.Timeout("t")]),
                "https://example.test",
                timeout_seconds=1,
                headers=None,
                stream=False,
                retry_policy=retry_policy,
                breaker=SimpleNamespace(before_call=lambda key: None, record_failure=lambda key: None, record_success=lambda key: None),
                breaker_key="example.test",
            )
        response = _request_with_resilience(
            SessionCM(responses=[FakeHttpResponse(status_code=500)]),
            "https://example.test",
            timeout_seconds=1,
            headers=None,
            stream=False,
            retry_policy=retry_policy,
            breaker=SimpleNamespace(before_call=lambda key: None, record_failure=lambda key: None, record_success=lambda key: None),
            breaker_key="example.test",
        )
        self.assertEqual(response.status_code, 500)

        response = FakeHttpResponse(content=b"123456")
        with self.assertRaises(HttpFetchError):
            _enforce_max_body_size(response, max_body_bytes=3, stream=False)
        stream_response = FakeHttpResponse(chunks=[b"", b"12"])
        _enforce_max_body_size(stream_response, max_body_bytes=3, stream=True)
        self.assertEqual(stream_response._content, b"12")
        with patch("src.parsers.url_safety.socket.getaddrinfo", return_value=[(None, None, None, None, ("bad-ip", 443))]):
            from src.parsers.url_safety import _resolve_host_ips

            self.assertEqual(_resolve_host_ips("example.test"), set())

        bridge = CouchDBBridge("http://example.test", "u", "p", "db")
        bridge.session = SimpleNamespace(
            get=lambda url: SimpleNamespace(status_code=404, json=lambda: {}),
            put=lambda url, **kwargs: SimpleNamespace(status_code=201 if "h%3A" in url else 500),
        )
        self.assertFalse(bridge.push_note("note.md", "text"))
        bridge = CouchDBBridge("http://example.test", "u", "p", "db")
        bridge.session = SimpleNamespace(
            get=lambda url: SimpleNamespace(status_code=404, json=lambda: {}),
            put=lambda url, **kwargs: SimpleNamespace(status_code=500 if "h%3A" in url else 202),
        )
        self.assertFalse(bridge.push_note("note.md", "text"))
        bridge = CouchDBBridge("http://example.test", "u", "p", "db")
        bridge.session = SimpleNamespace(
            get=lambda url: SimpleNamespace(status_code=200 if "note.md" in url else 404, json=lambda: {"_rev": "1-a"}),
            put=lambda url, **kwargs: SimpleNamespace(status_code=202),
        )
        self.assertTrue(bridge.push_note("note.md", "text"))

    def test_voice_embedder_retriever_chunker_and_watcher_completion(self) -> None:
        with patch("src.parsers.voice_parser._download_to_temp", return_value="temp.audio"):
            self.assertEqual(_resolve_local_audio_path("https://example.test/audio.mp3", timeout_seconds=1), "temp.audio")
        with self.assertRaises(FileNotFoundError):
            _resolve_local_audio_path("missing.audio", timeout_seconds=1)
        with patch("mimetypes.guess_type", return_value=("audio/custom", None)):
            self.assertEqual(_guess_mime_type("file.custom"), "audio/custom")

        self.assertEqual(
            _guess_mime_type_from_source(
                "https://example.test/audio#tgmime=audio%2Fogg",
                "",
            ),
            "audio/ogg",
        )
        self.assertEqual(_load_audio_bytes.__name__, "_load_audio_bytes")

        fake_client = SimpleNamespace(
            models=SimpleNamespace(generate_content=lambda **kwargs: SimpleNamespace(text="")),
        )
        with patch.dict("os.environ", {"GEMINI_API_KEY": "token"}, clear=False), patch(
            "src.parsers.voice_parser.genai.Client",
            return_value=fake_client,
        ), patch(
            "src.parsers.voice_parser._load_audio_bytes",
            return_value=(b"voice", "audio/mpeg"),
        ):
            result = parse_voice("https://example.test/audio.mp3")
        self.assertEqual(result.status, "fallback")
        self.assertEqual(result.links, ["https://example.test/audio.mp3"])

        with patch("src.rag.embedder.genai.Client", return_value=SimpleNamespace(models=SimpleNamespace(embed_content=lambda **kwargs: SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0])])))):
            embedder = GeminiEmbedder(api_key="token")
            self.assertEqual(len(embedder.embed_texts(["a", "b"])), 2)
        with patch("src.rag.embedder.genai.Client", return_value=SimpleNamespace(models=SimpleNamespace(embed_content=lambda **kwargs: SimpleNamespace(embeddings=[SimpleNamespace(values=[])])))):
            with self.assertRaises(EmbedderError):
                GeminiEmbedder(api_key="token").embed_query("x")
        with patch("src.rag.embedder.genai.Client", return_value=SimpleNamespace(models=SimpleNamespace(embed_content=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("not supported for embedContent"))))):
            with self.assertRaises(EmbedderError):
                GeminiEmbedder(api_key="token", fallback_models=("bad-model",)).embed_query("x")
        self.assertEqual(build_embedder(api_key="token").__class__.__name__, "ResilientEmbedder")

        with patch("src.rag.chunker._slice_large_text", return_value=["", "dup", "dup"]):
            self.assertEqual(chunk_text("A\n\n" + ("B" * 2000), max_chars=10, overlap_chars=2), ["A", "dup"])

        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            index = Path(tmp) / "index"
            vault.mkdir()
            index.mkdir()
            (vault / "a.md").write_text("alpha", encoding="utf-8")
            (vault / "b.md").write_text("beta", encoding="utf-8")
            service = RagService(vault, index, gemini_api_key="")
            with patch.object(service, "index_note", side_effect=[True, False]):
                self.assertEqual(service.reindex_vault_incremental(limit=1), 1)
            self.assertIn("provider", service.stats())
            self.assertFalse(service.remove_note(vault / "missing.md"))
            service.close()

            index_store = IndexStore(index / "rag.sqlite3")
            index_store.initialize()
            with self.assertRaises(RuntimeError):
                index_store.upsert_document_chunks(note_path="a", content_hash="b", chunks=["x"], embeddings=[])
            self.assertIsNone(index_store.close())

            processor = NoteEventProcessor(
                base_vault_path=vault,
                rag_manager=SimpleNamespace(for_tenant=lambda tenant_id: SimpleNamespace(index_note=lambda path: False, remove_note=lambda path: False)),
                multi_tenant=False,
            )
            self.assertFalse(processor.handle_upsert(vault / "missing.md"))
            self.assertFalse(processor.handle_delete(vault / "a.md"))
            with patch("pathlib.Path.resolve", side_effect=OSError("bad")):
                self.assertIsNone(processor._resolve_markdown_path(vault / "a.md"))

            async def raise_runtime(config, processor):
                _ = (config, processor)
                raise RuntimeError("watchdog fail")

            async def stop_polling(config, processor):
                _ = (config, processor)
                raise asyncio.CancelledError

            with patch("src.watcher._run_watchdog_loop", side_effect=raise_runtime), patch(
                "src.watcher._run_polling_loop",
                side_effect=stop_polling,
            ):
                with self.assertRaises(asyncio.CancelledError):
                    asyncio.run(run_watcher(SimpleNamespace(vault_path=vault, multi_tenant_mode=False), MagicMock()))

            store = __import__("src.infra.storage", fromlist=["StateStore"]).StateStore(Path(tmp) / "state.sqlite3")
            store.initialize()
            try:
                writer = ObsidianNoteWriter(vault, store, multi_tenant=False)
                self.assertEqual(writer._discover_related_notes(resolved_vault=vault, current_file_name="a.md", payload={"title": "!!!", "content": "", "semantic_hashtags": [], "parsed_items": []}), [])
                (vault / "123.md").write_text("x", encoding="utf-8")
                self.assertEqual(writer._discover_related_notes(resolved_vault=vault, current_file_name="a.md", payload={"title": "alpha", "content": "", "semantic_hashtags": [], "parsed_items": []}), [])
            finally:
                store.close()

            self.assertEqual(find_notes(vault, ""), [])

    def test_enrichment_storage_and_worker_remaining_branches(self) -> None:
        merged = enrich_payload_with_ai(
            {"content": "text", "actions": [], "ai_summary": "existing"},
            api_key="k",
            model_name="m",
            client=SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs: SimpleNamespace(text='{"tags":[],"summary":""}'))),
        )
        self.assertEqual(merged["ai_summary"], "existing")

        with tempfile.TemporaryDirectory() as tmp:
            from src.infra.storage import StateStore

            store = StateStore(Path(tmp) / "state.sqlite3")
            store.initialize()
            try:
                store.upsert_note(tenant_id="t1", content_fingerprint="fp", note_id="N1", file_name="file.md", job_id="job-file")
                self.assertTrue(store.resolve_note_ref("file.md", tenant_id="t1")[0])
                _, first_job_id, _ = store.enqueue_job(
                    idempotency_key="job-a",
                    content_fingerprint="cf-a",
                    tenant_id="t1",
                    user_id=1,
                    chat_id=1,
                    message_id=1,
                    payload={"tenant_id": "t1"},
                    max_attempts=2,
                )
                _, second_job_id, _ = store.enqueue_job(
                    idempotency_key="job-b",
                    content_fingerprint="cf-b",
                    tenant_id="t1",
                    user_id=1,
                    chat_id=1,
                    message_id=2,
                    payload={"tenant_id": "t1"},
                    max_attempts=2,
                )
                with store._connect() as conn:
                    conn.execute("UPDATE jobs_mt SET job_id='job-aaa' WHERE job_id=?", (first_job_id,))
                    conn.execute("UPDATE jobs_mt SET job_id='job-bbb' WHERE job_id=?", (second_job_id,))
                    conn.execute("UPDATE jobs_mt SET status='failed' WHERE idempotency_key='job-a'")
                    conn.execute("UPDATE jobs_mt SET status='failed' WHERE idempotency_key='job-b'")
                    ambiguous = store.retry_job("job", tenant_id="t1")
                    self.assertFalse(ambiguous[0])
                    self.assertIn("ambiguous", ambiguous[1])

                class IntegrityConn:
                    def __enter__(self):
                        return self

                    def __exit__(self, exc_type, exc, tb):
                        return False

                    def execute(self, sql: str):
                        _ = sql
                        return SimpleNamespace(fetchone=lambda: ("corrupt",))

                with patch.object(store, "_connect", return_value=IntegrityConn()):
                    self.assertEqual(store.integrity_check(), (False, "corrupt"))
            finally:
                store.close()

            config = SimpleNamespace(
                worker_recovery_interval_seconds=0.0,
                worker_stuck_timeout_seconds=600,
                worker_poll_seconds=0.0,
                vault_path=Path(tmp),
                multi_tenant_mode=False,
                gemini_api_key="",
                gemini_generation_model="gen",
            )

            class FakeStore:
                def __init__(self) -> None:
                    self.calls = 0

                def integrity_check(self):
                    return True, "ok"

                def recover_stuck_jobs(self, **kwargs):
                    _ = kwargs
                    return 0

                def acquire_next_job(self):
                    self.calls += 1
                    if self.calls == 1:
                        return None
                    if self.calls == 2:
                        return SimpleNamespace(job_id="j1", tenant_id="t1", payload={"tenant_id": "t1"}, attempts=0, max_attempts=2)
                    return None

                def mark_done(self, job_id: str, note_path: str) -> None:
                    self.done = (job_id, note_path)

                def mark_failed_or_retry(self, job, error: str):
                    raise AssertionError(error)

            fake_store = FakeStore()
            rag_service = SimpleNamespace(index_note=lambda path: (_ for _ in ()).throw(EmbedderError("embed down")))
            rag_manager = SimpleNamespace(for_tenant=lambda tenant_id: rag_service)

            sleep_calls = {"count": 0}

            async def stop_after_second_sleep(delay: float) -> None:
                _ = delay
                sleep_calls["count"] += 1
                if sleep_calls["count"] >= 2:
                    raise asyncio.CancelledError

            with patch("src.worker.asyncio.sleep", side_effect=stop_after_second_sleep), patch(
                "src.worker.ObsidianNoteWriter",
                return_value=SimpleNamespace(write=lambda **kwargs: str(Path(tmp) / "note.md")),
            ), patch("src.worker.enrich_payload", side_effect=lambda payload: payload), patch(
                "src.worker.enrich_payload_with_ai",
                side_effect=lambda payload, **kwargs: payload,
            ), patch("src.worker.LOGGER.warning") as warning:
                with self.assertRaises(asyncio.CancelledError):
                    asyncio.run(run_worker(config, fake_store, rag_manager))
            self.assertTrue(hasattr(fake_store, "done"))
            warning.assert_called()


async def _async_raise() -> str:
    raise ValueError("x")


if __name__ == "__main__":
    unittest.main()
