from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.pipeline.enrichment import enrich_payload_with_ai


class _FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeModels:
    def __init__(self, response_text: str | None = None, error: Exception | None = None) -> None:
        self._response_text = response_text
        self._error = error

    def generate_content(self, **_: object) -> _FakeResponse:
        if self._error:
            raise self._error
        return _FakeResponse(self._response_text or "")


class _FakeClient:
    def __init__(self, models: _FakeModels) -> None:
        self.models = models


class EnrichmentTests(unittest.TestCase):
    def test_fallback_when_api_key_missing(self) -> None:
        payload = {
            "content": "original text",
            "enriched_text": "parsed text",
            "auto_tags": ["existing"],
        }
        result = enrich_payload_with_ai(
            payload,
            api_key="",
            model_name="gemini-2.5-flash",
        )
        self.assertEqual(result["enriched_text"], "parsed text")
        self.assertEqual(result["auto_tags"], ["existing"])
        self.assertNotIn("ai_summary", result)

    def test_fallback_when_gemini_raises(self) -> None:
        payload = {
            "content": "original text",
            "enriched_text": "parsed text",
            "auto_tags": ["keep_me"],
            "ai_summary": "old summary",
        }
        result = enrich_payload_with_ai(
            payload,
            api_key="test-key",
            model_name="gemini-2.5-flash",
            client=_FakeClient(models=_FakeModels(error=RuntimeError("boom"))),
        )
        self.assertEqual(result["enriched_text"], "parsed text")
        self.assertEqual(result["auto_tags"], ["keep_me"])
        self.assertEqual(result["ai_summary"], "old summary")

    def test_merge_generated_tags_and_summary(self) -> None:
        payload = {
            "content": "Original content",
            "enriched_text": "Parsed content",
            "auto_tags": ["existing_tag"],
        }
        response_text = '{"tags": ["existing_tag", "new_topic"], "summary": "Short AI summary"}'
        result = enrich_payload_with_ai(
            payload,
            api_key="test-key",
            model_name="gemini-2.5-flash",
            client=_FakeClient(models=_FakeModels(response_text=response_text)),
        )
        self.assertEqual(result["auto_tags"], ["existing_tag", "new_topic"])
        self.assertEqual(result["ai_summary"], "Short AI summary")
        self.assertIn("Parsed content", result["enriched_text"])
        self.assertIn("AI summary: Short AI summary", result["enriched_text"])


if __name__ == "__main__":
    unittest.main()
