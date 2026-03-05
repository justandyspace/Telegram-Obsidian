from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.parsers.models import ParseResult
from src.parsers.router import classify_source, parse_url


class VoiceRoutingTests(unittest.TestCase):
    def test_classify_source_detects_local_audio_file_path(self) -> None:
        self.assertEqual(classify_source(r"C:\temp\voice_note.m4a"), "voice")

    def test_classify_source_detects_video_media_url(self) -> None:
        self.assertEqual(classify_source("https://example.com/media/clip.mp4"), "voice")

    def test_classify_source_detects_fragment_mime_hint_for_telegram_document(self) -> None:
        self.assertEqual(
            classify_source("https://api.telegram.org/file/bot123/documents/file_11#tgmime=audio%2Fogg"),
            "voice",
        )

    @patch("src.parsers.router.parse_voice")
    def test_parse_url_routes_audio_link_to_voice_parser(self, mock_parse_voice) -> None:
        expected = ParseResult(
            parser="voice",
            source_url="https://example.com/clip.mp3",
            status="fallback",
            title="Voice transcription",
            text="",
            links=["https://example.com/clip.mp3"],
            error="test fallback",
        )
        mock_parse_voice.return_value = expected

        result = parse_url("https://example.com/clip.mp3")
        self.assertEqual(result, expected)
        mock_parse_voice.assert_called_once_with("https://example.com/clip.mp3")

    @patch("src.parsers.router.parse_voice")
    def test_parse_url_routes_local_audio_file_to_voice_parser(self, mock_parse_voice) -> None:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(b"dummy")
            local_path = tmp.name
        try:
            expected = ParseResult(
                parser="voice",
                source_url=local_path,
                status="error",
                title="Voice transcription failed",
                text="",
                links=[local_path],
                error="simulated error",
            )
            mock_parse_voice.return_value = expected

            result = parse_url(local_path)
            self.assertEqual(result, expected)
            mock_parse_voice.assert_called_once_with(local_path)
        finally:
            Path(local_path).unlink(missing_ok=True)

    @patch("src.parsers.router.parse_voice")
    def test_parse_url_routes_fragment_mime_hint_to_voice_parser(self, mock_parse_voice) -> None:
        url = "https://api.telegram.org/file/bot123/documents/file_11#tgmime=video%2Fmp4"
        expected = ParseResult(
            parser="voice",
            source_url=url,
            status="ok",
            title="Voice transcription",
            text="text",
            links=[url],
            error=None,
        )
        mock_parse_voice.return_value = expected

        result = parse_url(url)
        self.assertEqual(result, expected)
        mock_parse_voice.assert_called_once_with(url)
