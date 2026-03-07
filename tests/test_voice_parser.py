from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.infra.ai_fallback import reset_remote_ai
from src.parsers.voice_parser import parse_voice


class VoiceParserTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_remote_ai("voice_transcription")

    def test_parse_voice_returns_fallback_when_api_key_missing(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            result = parse_voice("https://example.com/note.mp3")
        self.assertEqual(result.parser, "voice")
        self.assertEqual(result.status, "fallback")
        self.assertIn("missing", (result.error or "").lower())

    @patch("src.parsers.voice_parser._load_audio_bytes", return_value=(b"voice", "audio/mpeg"))
    @patch("src.parsers.voice_parser.genai.Client")
    def test_parse_voice_returns_error_when_upload_fails(
        self,
        mock_client_cls,
        _mock_load,
    ) -> None:
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("upload broken")
        mock_client_cls.return_value = mock_client

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}, clear=True):
            result = parse_voice("https://example.com/voice.mp3")

        self.assertEqual(result.parser, "voice")
        self.assertEqual(result.status, "error")
        self.assertIn("upload broken", (result.error or "").lower())

    @patch("src.parsers.voice_parser._load_audio_bytes", return_value=(b"voice", "audio/mpeg"))
    @patch("src.parsers.voice_parser.genai.Client")
    def test_parse_voice_returns_fallback_when_quota_is_exhausted(
        self,
        mock_client_cls,
        _mock_load,
    ) -> None:
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = RuntimeError("429 RESOURCE_EXHAUSTED")
        mock_client_cls.return_value = mock_client

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}, clear=True):
            first = parse_voice("https://example.com/voice.mp3")
            second = parse_voice("https://example.com/voice.mp3")

        self.assertEqual(first.status, "fallback")
        self.assertEqual(second.status, "fallback")
        self.assertIn("cooldown", (second.error or "").lower())
