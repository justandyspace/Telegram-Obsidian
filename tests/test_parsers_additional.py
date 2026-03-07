from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.parsers.article_parser import parse_article
from src.parsers.pdf_parser import parse_pdf
from src.parsers.twitter_fallback_parser import parse_twitter_fallback
from src.parsers.youtube_parser import _extract_video_id, parse_youtube


class _FakeHttpResponse:
    def __init__(
        self,
        *,
        text: str = "",
        content: bytes = b"",
        url: str = "",
        ok: bool = True,
        json_payload: dict[str, str] | None = None,
    ) -> None:
        self.text = text
        self.content = content
        self.url = url
        self.ok = ok
        self._json_payload = json_payload or {}
        self.closed = False

    def raise_for_status(self) -> None:
        if not self.ok:
            raise RuntimeError("http error")

    def json(self) -> dict[str, str]:
        return self._json_payload

    def close(self) -> None:
        self.closed = True


class ArticleParserTests(unittest.TestCase):
    def test_parse_article_extracts_title_and_body(self) -> None:
        response = _FakeHttpResponse(
            text=(
                "<html><head><title>Ignored</title><meta property='og:title' content='Article Title'></head>"
                "<body><article><p>This is the main article paragraph with enough length to be included.</p></article>"
                "</body></html>"
            ),
            url="https://example.test/final",
        )
        with patch("src.parsers.article_parser.safe_http_get", return_value=response):
            result = parse_article("https://example.test/post")

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.title, "Article Title")
        self.assertIn("main article paragraph", result.text)
        self.assertEqual(result.links, ["https://example.test/post", "https://example.test/final"])
        self.assertTrue(response.closed)

    def test_parse_article_returns_error_on_fetch_failure(self) -> None:
        with patch("src.parsers.article_parser.safe_http_get", side_effect=RuntimeError("blocked")):
            result = parse_article("https://example.test/post")

        self.assertEqual(result.status, "error")
        self.assertIn("blocked", result.error or "")


class PdfParserTests(unittest.TestCase):
    def test_parse_pdf_extracts_metadata_and_text(self) -> None:
        response = _FakeHttpResponse(content=b"%PDF", url="https://example.test/doc.pdf")
        fake_pages = [
            SimpleNamespace(extract_text=lambda: "Page one text"),
            SimpleNamespace(extract_text=lambda: "Page two text"),
        ]
        fake_reader = SimpleNamespace(pages=fake_pages, metadata=SimpleNamespace(title="My PDF"))
        with patch("src.parsers.pdf_parser.safe_http_get", return_value=response), patch(
            "src.parsers.pdf_parser.PdfReader",
            return_value=fake_reader,
        ):
            result = parse_pdf("https://example.test/doc.pdf")

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.title, "My PDF")
        self.assertIn("Page one text", result.text)
        self.assertTrue(response.closed)

    def test_parse_pdf_returns_fallback_when_pages_are_empty(self) -> None:
        response = _FakeHttpResponse(content=b"%PDF", url="https://example.test/doc.pdf")
        fake_reader = SimpleNamespace(
            pages=[SimpleNamespace(extract_text=lambda: "")],
            metadata=SimpleNamespace(title=""),
        )
        with patch("src.parsers.pdf_parser.safe_http_get", return_value=response), patch(
            "src.parsers.pdf_parser.PdfReader",
            return_value=fake_reader,
        ):
            result = parse_pdf("https://example.test/doc.pdf")

        self.assertEqual(result.status, "fallback")
        self.assertIn("text extraction returned empty", result.text)


class TwitterFallbackParserTests(unittest.TestCase):
    def test_parse_twitter_fallback_reads_og_meta(self) -> None:
        response = _FakeHttpResponse(
            text=(
                "<html><head>"
                "<meta property='og:title' content='Thread Title'>"
                "<meta property='og:description' content='Expanded thread body'>"
                "</head></html>"
            )
        )
        with patch("src.parsers.twitter_fallback_parser.safe_http_get", return_value=response):
            result = parse_twitter_fallback("https://x.com/user/status/1")

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.title, "Thread Title")
        self.assertIn("Expanded thread body", result.text)
        self.assertTrue(response.closed)

    def test_parse_twitter_fallback_returns_fallback_on_error(self) -> None:
        with patch("src.parsers.twitter_fallback_parser.safe_http_get", side_effect=RuntimeError("offline")):
            result = parse_twitter_fallback("https://x.com/user/status/1")

        self.assertEqual(result.status, "fallback")
        self.assertIn("Metadata fetch", result.text)
        self.assertIn("offline", result.error or "")


class YoutubeParserTests(unittest.TestCase):
    def test_extract_video_id_supports_multiple_formats(self) -> None:
        self.assertEqual(_extract_video_id("https://youtu.be/abc123"), "abc123")
        self.assertEqual(_extract_video_id("https://www.youtube.com/watch?v=abc123"), "abc123")
        self.assertEqual(_extract_video_id("https://www.youtube.com/shorts/abc123"), "abc123")

    def test_parse_youtube_uses_transcript_when_available(self) -> None:
        with patch("src.parsers.youtube_parser._fetch_title", return_value="Demo title"), patch(
            "src.parsers.youtube_parser.YouTubeTranscriptApi.get_transcript",
            return_value=[{"text": "hello"}, {"text": "world"}],
        ):
            result = parse_youtube("https://youtu.be/abc123")

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.title, "Demo title")
        self.assertIn("hello world", result.text)
        self.assertIn("api/timedtext", result.links[2])

    def test_parse_youtube_falls_back_without_transcript(self) -> None:
        with patch("src.parsers.youtube_parser._fetch_title", return_value="Demo title"), patch(
            "src.parsers.youtube_parser.YouTubeTranscriptApi.get_transcript",
            side_effect=RuntimeError("disabled"),
        ):
            result = parse_youtube("https://youtu.be/abc123")

        self.assertEqual(result.status, "fallback")
        self.assertIn("Transcript unavailable", result.text)
        self.assertIn("disabled", result.error or "")


if __name__ == "__main__":
    unittest.main()
