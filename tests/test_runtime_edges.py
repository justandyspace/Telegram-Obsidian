from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import requests

from src.bot.auth import build_tenant_context, is_authorized_user
from src.config import _required, _validate_webhook_secret, load_config
from src.infra.ai_fallback import mark_remote_ai_failure, reset_remote_ai
from src.infra.logging import configure_logging, get_logger
from src.infra.resilience import (
    CircuitBreakerOpenError,
    CircuitBreakerRegistry,
    RetryPolicy,
    async_with_retry,
    with_retry,
)
from src.infra.runtime_state import last_error, record_error, started_at_iso, uptime_human, uptime_seconds
from src.infra.storage import StateStore
from src.obsidian.note_writer import ObsidianNoteWriter
from src.parsers.url_safety import (
    HttpFetchError,
    UnsafeUrlError,
    _ensure_public_ip,
    _request_with_resilience,
    _resolve_host_ips,
    safe_http_get,
    validate_public_http_url,
)
from src.parsers.voice_parser import (
    _download_to_temp,
    _guess_mime_type,
    _is_temp_path,
    _resolve_local_audio_path,
    _suffix_from_source,
    parse_voice,
)
from src.rag.chunker import _slice_large_text, chunk_text
from src.rag.embedder import (
    BaseEmbedder,
    EmbedderError,
    GeminiEmbedder,
    HashEmbedder,
    ResilientEmbedder,
    _hash_to_vector,
    _is_model_not_supported_error,
    _normalize_vector,
    _unique_models,
    build_embedder,
)
from src.rag.index_store import RetrievedChunk
from src.rag.retriever import (
    RagManager,
    RagService,
    _build_extractive_answer,
    _hash_text,
    _humanize_chunk_text,
)


class _Response:
    def __init__(
        self,
        *,
        status_code: int = 200,
        url: str = "https://example.test",
        headers: dict[str, str] | None = None,
        content: bytes = b"",
        chunks: list[bytes] | None = None,
    ) -> None:
        self.status_code = status_code
        self.url = url
        self.headers = headers or {}
        self.content = content
        self._chunks = chunks or []
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def iter_content(self, chunk_size: int):
        _ = chunk_size
        yield from self._chunks

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("http error")


class _SessionCM:
    def __init__(self, responses: list[_Response] | None = None, errors: list[Exception] | None = None) -> None:
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


class _FakePrimary(BaseEmbedder):
    provider_name = "primary"

    def __init__(self, values=None, error: Exception | None = None) -> None:
        self.values = values or [[1.0, 0.0]]
        self.error = error

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        _ = texts
        if self.error:
            raise self.error
        return self.values

    def embed_query(self, text: str) -> list[float]:
        _ = text
        if self.error:
            raise self.error
        return self.values[0]


class _FakeFallback(BaseEmbedder):
    provider_name = "fallback"

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[0.0, 1.0] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        _ = text
        return [0.0, 1.0]


class _FakeGenClient:
    def __init__(self, embeddings=None, embed_error: Exception | None = None, gen_text: str = "") -> None:
        self._embeddings = embeddings
        self._embed_error = embed_error
        self._gen_text = gen_text
        self.models = SimpleNamespace(
            embed_content=self._embed_content,
            generate_content=self._generate_content,
        )
        self.files = SimpleNamespace(upload=self._upload, delete=self._delete)
        self.deleted: list[str] = []

    def _embed_content(self, **kwargs):
        _ = kwargs
        if self._embed_error:
            raise self._embed_error
        return SimpleNamespace(embeddings=self._embeddings)

    def _generate_content(self, **kwargs):
        _ = kwargs
        return SimpleNamespace(text=self._gen_text)

    def _upload(self, **kwargs):
        _ = kwargs
        return SimpleNamespace(name="upload-1", uri="gs://upload-1")

    def _delete(self, **kwargs):
        self.deleted.append(kwargs["name"])


class RuntimeEdgeTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_remote_ai("grounded_answer")

    def test_auth_logging_runtime_state_and_required_helpers(self) -> None:
        self.assertFalse(is_authorized_user(incoming_user_id=None, allowed_user_ids={1}))
        self.assertTrue(is_authorized_user(incoming_user_id=1, allowed_user_ids={1}))
        self.assertEqual(build_tenant_context(5).tenant_id, "tg_5")

        with patch("logging.basicConfig") as basic_config:
            configure_logging("DEBUG")
            basic_config.assert_called_once()
        self.assertEqual(get_logger("demo").name, "demo")

        record_error("   ")
        record_error("fatal error")
        self.assertEqual(last_error()[0], "fatal error")
        self.assertTrue(started_at_iso())
        self.assertGreaterEqual(uptime_seconds(), 0)
        self.assertEqual(len(uptime_human().split(":")), 3)

        self.assertEqual(_required("X", " value "), "value")
        with self.assertRaises(RuntimeError):
            _required("X", " ")
        with self.assertRaises(RuntimeError):
            _validate_webhook_secret("short")
        _validate_webhook_secret("very-strong-secret")

    def test_load_config_covers_invalid_and_valid_variants(self) -> None:
        with patch.dict(os.environ, {"APP_ROLE": "bad"}, clear=True):
            with self.assertRaises(RuntimeError):
                load_config()

        with patch.dict(os.environ, {"APP_ROLE": "worker"}, clear=True):
            config = load_config()
            self.assertEqual(config.telegram_allowed_user_id, 0)

        valid_env = {
            "APP_ROLE": "bot",
            "TELEGRAM_TOKEN": "token",
            "TELEGRAM_ALLOWED_USER_ID": "11",
            "TELEGRAM_ALLOWED_USER_IDS": "11,12",
            "TENANT_MODE": "multi",
            "TELEGRAM_MODE": "auto",
            "WEBHOOK_BASE_URL": "https://example.test",
            "WEBHOOK_SECRET_TOKEN": "super-secret-token",
            "WEBHOOK_PATH": "hook",
            "WORKER_POLL_SECONDS": "3",
            "WORKER_RECOVERY_INTERVAL_SECONDS": "4",
            "WORKER_STUCK_TIMEOUT_SECONDS": "5",
            "WATCHER_POLL_SECONDS": "6",
            "JOB_MAX_RETRIES": "7",
        }
        with patch.dict(os.environ, valid_env, clear=True):
            config = load_config()
            self.assertEqual(config.telegram_allowed_user_ids, (11, 12))
            self.assertTrue(config.multi_tenant_mode)
            self.assertEqual(config.webhook_path, "/hook")
            self.assertEqual(config.state_db_path.name, "bot_state.sqlite3")

        with patch.dict(
            os.environ,
            {"APP_ROLE": "bot", "TELEGRAM_TOKEN": "token", "TELEGRAM_ALLOWED_USER_IDS": "x"},
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                load_config()

        with patch.dict(
            os.environ,
            {"APP_ROLE": "bot", "TELEGRAM_TOKEN": "token", "TELEGRAM_ALLOWED_USER_ID": "bad"},
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                load_config()

        with patch.dict(os.environ, {"APP_ROLE": "bot", "TELEGRAM_TOKEN": "token"}, clear=True):
            with self.assertRaises(RuntimeError):
                load_config()

        with patch.dict(
            os.environ,
            {"APP_ROLE": "bot", "TELEGRAM_TOKEN": "token", "TELEGRAM_ALLOWED_USER_ID": "1", "TELEGRAM_MODE": "oops"},
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                load_config()

        with patch.dict(
            os.environ,
            {"APP_ROLE": "bot", "TELEGRAM_TOKEN": "token", "TELEGRAM_ALLOWED_USER_ID": "1", "TELEGRAM_MODE": "webhook"},
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                load_config()

        with patch.dict(
            os.environ,
            {
                "APP_ROLE": "bot",
                "TELEGRAM_TOKEN": "token",
                "TELEGRAM_ALLOWED_USER_ID": "1",
                "TELEGRAM_MODE": "auto",
                "WEBHOOK_BASE_URL": "https://example.test",
            },
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                load_config()

    def test_retry_and_circuit_helpers_cover_remaining_branches(self) -> None:
        policy = RetryPolicy(max_attempts=0, base_delay_seconds=0.1, max_delay_seconds=0.1, jitter_ratio=0.0)
        self.assertEqual(policy.clamp_attempts(), 1)
        self.assertEqual(policy.backoff_delay(2), 0.1)
        retrying = RetryPolicy(max_attempts=2, base_delay_seconds=0.1, max_delay_seconds=0.1, jitter_ratio=0.0)

        attempts = {"count": 0}

        def flaky() -> str:
            attempts["count"] += 1
            if attempts["count"] < 2:
                raise ValueError("boom")
            return "ok"

        with patch("time.sleep", return_value=None):
            self.assertEqual(with_retry(retrying, flaky, exc_types=(ValueError,)), "ok")

        async def flaky_async() -> str:
            attempts["count"] += 1
            if attempts["count"] < 4:
                raise ValueError("boom")
            return "ok"

        attempts["count"] = 2
        with patch("asyncio.sleep", return_value=None):
            self.assertEqual(asyncio.run(async_with_retry(retrying, flaky_async, exc_types=(ValueError,))), "ok")

        breaker = CircuitBreakerRegistry(failure_threshold=1, cooldown_seconds=10.0, time_fn=lambda: 0.0)
        breaker.record_failure("x")
        with self.assertRaises(CircuitBreakerOpenError):
            breaker.before_call("x")
        current_time = {"value": 5.0}
        breaker = CircuitBreakerRegistry(
            failure_threshold=1,
            cooldown_seconds=1.0,
            time_fn=lambda: current_time["value"],
        )
        breaker.record_failure("x")
        current_time["value"] = 6.0
        breaker.before_call("x")
        breaker.record_success("x")

    def test_url_safety_and_http_fetch_cover_errors_redirects_and_streaming(self) -> None:
        with self.assertRaises(UnsafeUrlError):
            validate_public_http_url("http://user:pass@example.com")
        with self.assertRaises(UnsafeUrlError):
            validate_public_http_url("http://")
        with self.assertRaises(ValueError):
            validate_public_http_url("http://example.com:99999")
        with patch("src.parsers.url_safety._resolve_host_ips", return_value=set()):
            with self.assertRaises(UnsafeUrlError):
                validate_public_http_url("http://example.com")
        with patch("src.parsers.url_safety.socket.getaddrinfo", side_effect=__import__("socket").gaierror("dns")):
            with self.assertRaises(UnsafeUrlError):
                _resolve_host_ips("example.com")

        with self.assertRaises(UnsafeUrlError):
            _ensure_public_ip(__import__("ipaddress").ip_address("127.0.0.1"))

        session = _SessionCM(
            responses=[
                _Response(status_code=302, url="https://example.test", headers={"Location": "/next"}),
                _Response(status_code=200, url="https://example.test/next", content=b"ok"),
            ]
        )
        with patch("src.parsers.url_safety.requests.Session", return_value=session), patch(
            "src.parsers.url_safety.validate_public_http_url",
            return_value=None,
        ):
            response = safe_http_get("https://example.test", timeout_seconds=1)
            self.assertEqual(response.url, "https://example.test/next")

        session = _SessionCM(responses=[_Response(status_code=302, url="https://example.test", headers={"Location": "/next"})] * 5)
        with patch("src.parsers.url_safety.requests.Session", return_value=session), patch(
            "src.parsers.url_safety.validate_public_http_url",
            return_value=None,
        ):
            with self.assertRaises(HttpFetchError):
                safe_http_get("https://example.test", timeout_seconds=1, max_redirects=1)

        session = _SessionCM(responses=[_Response(status_code=200, headers={"Content-Length": "20"})])
        with patch("src.parsers.url_safety.requests.Session", return_value=session), patch(
            "src.parsers.url_safety.validate_public_http_url",
            return_value=None,
        ):
            with self.assertRaises(HttpFetchError):
                safe_http_get("https://example.test", timeout_seconds=1, max_body_bytes=10)

        session = _SessionCM(
            responses=[_Response(status_code=200, chunks=[b"12345", b"67890", b"11"], content=b"")],
        )
        with patch("src.parsers.url_safety.requests.Session", return_value=session), patch(
            "src.parsers.url_safety.validate_public_http_url",
            return_value=None,
        ):
            with self.assertRaises(HttpFetchError):
                safe_http_get("https://example.test", timeout_seconds=1, stream=True, max_body_bytes=10)

        retry_policy = RetryPolicy(max_attempts=2, base_delay_seconds=0, max_delay_seconds=0, jitter_ratio=0)
        breaker = CircuitBreakerRegistry(failure_threshold=3, cooldown_seconds=1.0)
        fail_session = _SessionCM(errors=[requests.Timeout("t1"), requests.ConnectionError("t2")])
        with patch("time.sleep", return_value=None):
            with self.assertRaises(HttpFetchError):
                _request_with_resilience(
                    fail_session,
                    "https://example.test",
                    timeout_seconds=1,
                    headers=None,
                    stream=False,
                    retry_policy=retry_policy,
                    breaker=breaker,
                    breaker_key="example.test",
                )

    def test_voice_parser_chunker_and_note_writer_cover_remaining_branches(self) -> None:
        self.assertEqual(chunk_text(""), [])
        big = "A" * 50 + "\n\n" + "B" * 50
        self.assertTrue(chunk_text(big, max_chars=40, overlap_chars=10))
        self.assertTrue(_slice_large_text("word " * 50, 20, 5))

        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / "audio.mp3"
            audio.write_bytes(b"audio")
            self.assertEqual(_resolve_local_audio_path(str(audio), timeout_seconds=1), str(audio))
            self.assertEqual(_suffix_from_source("https://example.test/file.mp3"), ".mp3")
            self.assertEqual(_suffix_from_source("https://example.test/file"), ".audio")
            self.assertEqual(_guess_mime_type(str(audio)), "audio/mpeg")
            self.assertEqual(_guess_mime_type(str(Path(tmp) / "file.bin")), "audio/mpeg")
            self.assertFalse(_is_temp_path(""))

            response = _Response(content=b"binary")
            with patch("src.parsers.voice_parser.safe_http_get", return_value=response):
                temp_path = _download_to_temp("https://example.test/audio.ogg", timeout_seconds=1)
            self.assertTrue(Path(temp_path).exists())
            Path(temp_path).unlink(missing_ok=True)

            fake_client = _FakeGenClient(gen_text="transcript")
            with patch.dict(os.environ, {"GEMINI_API_KEY": "token", "GEMINI_GENERATION_MODEL": "gen"}, clear=False), patch(
                "src.parsers.voice_parser.genai.Client",
                return_value=fake_client,
            ):
                result = parse_voice(str(audio))
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.links, [str(audio)])

            with patch.dict(os.environ, {"GEMINI_API_KEY": "token"}, clear=False), patch(
                "src.parsers.voice_parser.genai.Client",
                side_effect=RuntimeError("client fail"),
            ):
                with self.assertRaises(RuntimeError):
                    parse_voice(str(audio))

            store = StateStore(Path(tmp) / "state.sqlite3")
            store.initialize()
            payload = {
                "tenant_id": "legacy",
                "content_fingerprint": "abcdef1234567890",
                "title": "Project Alpha",
                "content": "- [ ] task one\nbody text",
                "hashtags": ["save"],
                "actions": ["save", "translate"],
                "translation": "перевод",
                "ai_summary": "summary",
                "semantic_hashtags": ["alpha"],
                "parsed_items": [
                    {
                        "parser": "article",
                        "status": "ok",
                        "title": "Article",
                        "source_url": "https://example.test",
                        "links": ["https://example.test", "https://mirror.test"],
                        "error": "oops",
                    }
                ],
                "source": {
                    "chat_id": 1,
                    "message_id": 2,
                    "user_id": 3,
                    "message_datetime": datetime(2026, 3, 5, 12, 0, tzinfo=UTC).isoformat(),
                    "forward_source": "Channel",
                },
            }
            related = Path(tmp) / "vault" / "20260305-1200 - Alpha note (ABC12345).md"
            related.parent.mkdir(parents=True, exist_ok=True)
            related.write_text("alpha related", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "COUCHDB_USER": "user",
                    "COUCHDB_PASSWORD": "pass",
                    "COUCHDB_DATABASE": "notes",
                    "COUCHDB_URL": "http://db.test",
                },
                clear=False,
            ), patch("src.obsidian.note_writer.CouchDBBridge") as bridge_cls:
                bridge = MagicMock()
                bridge_cls.return_value = bridge
                writer = ObsidianNoteWriter(Path(tmp) / "vault", store, multi_tenant=False)
                note_path = writer.write(job_id="job-1", payload=payload)
                self.assertTrue(Path(note_path).exists())
                bridge.push_note.assert_called_once()
                self.assertIn("Article", writer._render_links(payload, Path(tmp) / "vault", Path(note_path).name))
                self.assertIn("summary", writer._render_summary(payload, {"save"}))
                self.assertIn("task one", writer._render_tasks(payload))
                self.assertEqual(writer._extract_link_tokens(""), set())
                self.assertEqual(writer._humanize_note_stem("20260305-1200 - Name (ABC12345)"), "Name")
            store.close()

    def test_embedder_and_retriever_cover_remaining_branches(self) -> None:
        with self.assertRaises(NotImplementedError):
            BaseEmbedder().embed_query("x")
        with self.assertRaises(NotImplementedError):
            BaseEmbedder().embed_texts(["x"])

        self.assertEqual(_hash_to_vector("", 3), [0.0, 0.0, 0.0])
        self.assertEqual(_normalize_vector([0.0, 0.0]), [0.0, 0.0])
        self.assertTrue(_is_model_not_supported_error(RuntimeError("not supported for embedContent")))
        self.assertEqual(_unique_models(["a", "a", "", "b"]), ["a", "b"])
        self.assertIsInstance(build_embedder(), HashEmbedder)

        primary = _FakePrimary(error=RuntimeError("down"))
        resilient = ResilientEmbedder(primary=primary, fallback=_FakeFallback(), cooldown_seconds=1.0, time_fn=lambda: 0.0)
        self.assertEqual(resilient.embed_query("x"), [0.0, 1.0])
        self.assertTrue(resilient.fallback_active)
        self.assertIn("fallback", resilient.provider_name)

        with patch("src.rag.embedder.genai.Client", return_value=_FakeGenClient(embeddings=[SimpleNamespace(values=[1.0, 2.0])])):
            embedder = GeminiEmbedder(api_key="token")
            self.assertEqual(len(embedder.embed_query("x")), 2)

        with patch("src.rag.embedder.genai.Client", return_value=_FakeGenClient(embeddings=[])):
            with self.assertRaises(EmbedderError):
                GeminiEmbedder(api_key="token").embed_query("x")

        with patch(
            "src.rag.embedder.genai.Client",
            return_value=_FakeGenClient(embeddings=[SimpleNamespace(values=[1.0])]),
        ):
            fallback_embedder = GeminiEmbedder(api_key="token", fallback_models=("text-embedding-004",))
            fallback_embedder._client.models.embed_content = MagicMock(
                side_effect=[
                    RuntimeError("model not supported for embedContent"),
                    SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0])]),
                ]
            )
            self.assertTrue(fallback_embedder.embed_query("x"))

        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            index = Path(tmp) / "index"
            vault.mkdir()
            index.mkdir()
            note = vault / "note.md"
            note.write_text("alpha beta gamma", encoding="utf-8")

            service = RagService(vault, index, gemini_api_key="")
            self.assertFalse(service.find("", top_k=1))
            self.assertFalse(service.index_note(vault / "missing.md"))
            self.assertFalse(service.index_note(vault / "file.txt"))

            with patch("src.rag.retriever.chunk_text", return_value=[]):
                self.assertFalse(service.index_note(note))

            hit = RetrievedChunk(str(note.resolve()), "c1", "alpha", 0.2)
            service.close()
            fake_index_store = SimpleNamespace(search=lambda vector, top_k: [hit], close=lambda: None)
            service._embedder = SimpleNamespace(provider_name="gemini", embed_query=lambda query: [1.0])  # type: ignore[assignment]
            service._index_store = fake_index_store  # type: ignore[assignment]
            self.assertEqual(service.find("alpha"), [])

            service._embedder = SimpleNamespace(provider_name="hash-fallback", embed_query=lambda query: [1.0])  # type: ignore[assignment]
            self.assertEqual(service.find("alpha"), [hit])

            with patch.object(service, "find", return_value=[]):
                answer = service.answer("question")
                self.assertEqual(answer.mode, "empty")

            hits = [RetrievedChunk(str(note.resolve()), "c1", "alpha beta", 0.9)]
            with patch.object(service, "find", return_value=hits), patch.object(service, "_answer_with_gemini", return_value="grounded"):
                service._generation_client = object()
                answer = service.answer("question")
                self.assertEqual(answer.mode, "gemini-grounded")

            with patch.object(service, "find", return_value=hits), patch.object(service, "_answer_with_gemini", return_value=""):
                service._generation_client = object()
                answer = service.answer("question")
                self.assertEqual(answer.mode, "extractive")

            service._generation_client = None
            self.assertEqual(service._answer_with_gemini("q", hits), "")
            mark_remote_ai_failure("grounded_answer", RuntimeError("429 RESOURCE_EXHAUSTED"))
            service._generation_client = _FakeGenClient(gen_text="should not be used")
            self.assertEqual(service._answer_with_gemini("q", hits), "")
            reset_remote_ai("grounded_answer")
            service._generation_client = _FakeGenClient(gen_text="generated")
            self.assertEqual(service._answer_with_gemini("q", hits), "generated")
            service._generation_client = SimpleNamespace(models=SimpleNamespace(generate_content=MagicMock(side_effect=RuntimeError("boom"))))
            self.assertEqual(service._answer_with_gemini("q", hits), "")
            service.close()

            manager = RagManager(
                base_vault_path=vault,
                base_index_dir=index,
                multi_tenant=True,
                gemini_api_key="",
                gemini_embed_model="embed",
                gemini_generation_model="gen",
            )
            service_a = manager.for_tenant("tg_1")
            self.assertIs(service_a, manager.for_tenant("tg_1"))
            self.assertIsNot(service_a, manager.for_tenant("tg_2"))
            manager.close()

        answer = _build_extractive_answer("q", [RetrievedChunk("note.md", "c1", "hello world", 0.7)])
        self.assertIn("Вот что удалось найти", answer)
        self.assertIn("hello world", answer)

        noisy = (
            "# Title\n"
            "<!-- BOT_META:START -->\n"
            "note_id: ABCD1234\n"
            "source_chat_id: 1\n"
            "<!-- BOT_META:END -->\n"
            "## 📝 User Content\n"
            "Normal text here\n"
            "[Processed in 12ms | Tokens: 7]\n"
            "### Related notes (auto)\n"
            "- [[Other Note]]\n"
        )
        cleaned = _humanize_chunk_text(noisy)
        self.assertIn("Title", cleaned)
        self.assertIn("Normal text here", cleaned)
        self.assertNotIn("note_id", cleaned)
        self.assertNotIn("Related notes", cleaned)
        self.assertEqual(len(_hash_text("x")), 64)


if __name__ == "__main__":
    unittest.main()
