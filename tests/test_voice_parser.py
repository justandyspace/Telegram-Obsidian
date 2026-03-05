from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.parsers.voice_parser import parse_voice


class VoiceParserTests(unittest.TestCase):
    def test_parse_voice_returns_fallback_when_api_key_missing(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            result = parse_voice("https://example.com/note.mp3")
        self.assertEqual(result.parser, "voice")
        self.assertEqual(result.status, "fallback")
        self.assertIn("missing", (result.error or "").lower())

    @patch("src.parsers.voice_parser._resolve_local_audio_path", return_value=r"C:\tmp\voice.mp3")
    @patch("src.parsers.voice_parser.genai.Client")
    def test_parse_voice_returns_error_when_upload_fails(
        self,
        mock_client_cls,
        _mock_resolve,
    ) -> None:
        mock_client = MagicMock()
        mock_client.files.upload.side_effect = RuntimeError("upload broken")
        mock_client_cls.return_value = mock_client

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}, clear=True):
            result = parse_voice("https://example.com/voice.mp3")

        self.assertEqual(result.parser, "voice")
        self.assertEqual(result.status, "error")
        self.assertIn("upload broken", (result.error or "").lower())
