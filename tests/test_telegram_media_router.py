from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace

from src.bot.telegram_router import (
    _build_voice_ingest_text,
    _extract_telegram_media_url,
    _is_transcribable_media_message,
)
from src.parsers.router import extract_urls
from src.pipeline.normalize import ascii_safe_title, derive_title, normalize_text, strip_hashtags


class _Bot:
    token = "abc123"

    def __init__(self, file_path: str = "voice/file_1.ogg", should_fail: bool = False) -> None:
        self._file_path = file_path
        self._should_fail = should_fail
        self.last_file_id = ""

    async def get_file(self, file_id: str):
        self.last_file_id = file_id
        if self._should_fail:
            raise RuntimeError("boom")
        return SimpleNamespace(file_path=self._file_path)


def _message_with_media(
    *,
    bot: _Bot | None = None,
    voice=None,
    audio=None,
    video_note=None,
    video=None,
    document=None,
):
    return SimpleNamespace(
        voice=voice,
        audio=audio,
        video_note=video_note,
        video=video,
        document=document,
        bot=bot,
    )


class TelegramMediaRouterTests(unittest.TestCase):
    def test_extract_media_url_for_voice(self) -> None:
        bot = _Bot(file_path="voice/file_1.ogg")
        message = _message_with_media(
            bot=bot,
            voice=SimpleNamespace(file_id="voice_id"),
        )
        url = asyncio.run(_extract_telegram_media_url(message))
        self.assertEqual(url, "https://api.telegram.org/file/botabc123/voice/file_1.ogg")
        self.assertEqual(bot.last_file_id, "voice_id")

    def test_extract_media_url_returns_empty_on_failure(self) -> None:
        message = _message_with_media(
            bot=_Bot(file_path="voice/file_1.ogg", should_fail=True),
            voice=SimpleNamespace(file_id="voice_id"),
        )
        url = asyncio.run(_extract_telegram_media_url(message))
        self.assertEqual(url, "")

    def test_extract_media_url_for_video_note(self) -> None:
        bot = _Bot(file_path="video_notes/file_2.mp4")
        message = _message_with_media(
            bot=bot,
            video_note=SimpleNamespace(file_id="video_note_id"),
        )
        url = asyncio.run(_extract_telegram_media_url(message))
        self.assertEqual(
            url,
            "https://api.telegram.org/file/botabc123/video_notes/file_2.mp4#tgmime=video%2Fmp4",
        )
        self.assertEqual(bot.last_file_id, "video_note_id")

    def test_extract_media_url_for_video(self) -> None:
        bot = _Bot(file_path="video/file_3.mp4")
        message = _message_with_media(
            bot=bot,
            video=SimpleNamespace(file_id="video_id", mime_type="video/mp4"),
        )
        url = asyncio.run(_extract_telegram_media_url(message))
        self.assertEqual(
            url,
            "https://api.telegram.org/file/botabc123/video/file_3.mp4#tgmime=video%2Fmp4",
        )
        self.assertEqual(bot.last_file_id, "video_id")

    def test_extract_media_url_for_audio_document_with_mime_hint(self) -> None:
        bot = _Bot(file_path="documents/file_4")
        message = _message_with_media(
            bot=bot,
            document=SimpleNamespace(file_id="doc_audio_id", mime_type="audio/ogg"),
        )
        url = asyncio.run(_extract_telegram_media_url(message))
        self.assertEqual(
            url,
            "https://api.telegram.org/file/botabc123/documents/file_4#tgmime=audio%2Fogg",
        )
        self.assertEqual(bot.last_file_id, "doc_audio_id")

    def test_extract_media_url_for_video_document_with_mime_hint(self) -> None:
        bot = _Bot(file_path="documents/file_5")
        message = _message_with_media(
            bot=bot,
            document=SimpleNamespace(file_id="doc_video_id", mime_type="video/quicktime"),
        )
        url = asyncio.run(_extract_telegram_media_url(message))
        self.assertEqual(
            url,
            "https://api.telegram.org/file/botabc123/documents/file_5#tgmime=video%2Fquicktime",
        )
        self.assertEqual(bot.last_file_id, "doc_video_id")

    def test_non_media_document_is_not_transcribable_and_has_no_media_url(self) -> None:
        message = _message_with_media(
            bot=_Bot(file_path="documents/file_6"),
            document=SimpleNamespace(file_id="doc_text_id", mime_type="application/pdf"),
        )
        self.assertFalse(_is_transcribable_media_message(message))
        url = asyncio.run(_extract_telegram_media_url(message))
        self.assertEqual(url, "")

    def test_build_voice_ingest_text_keeps_media_url_extractable(self) -> None:
        media_url = "https://api.telegram.org/file/botabc123/voice/file_1.ogg"
        text = _build_voice_ingest_text(caption="Короткий комментарий", media_url=media_url)

        self.assertIn(media_url, text)
        self.assertEqual(extract_urls(text), [media_url])

    def test_build_voice_ingest_text_keeps_fragment_hint_url_extractable(self) -> None:
        media_url = (
            "https://api.telegram.org/file/botabc123/documents/file_7#tgmime=audio%2Fogg"
        )
        text = _build_voice_ingest_text(caption="", media_url=media_url)

        self.assertIn(media_url, text)
        self.assertEqual(extract_urls(text), [media_url])

    def test_build_voice_ingest_text_keeps_url_out_of_generated_title_prefix(self) -> None:
        media_url = "https://api.telegram.org/file/botabc123/voice/file_1.ogg"
        raw_text = _build_voice_ingest_text(caption="", media_url=media_url)
        content = normalize_text(strip_hashtags(raw_text))
        title = ascii_safe_title(derive_title(content))

        self.assertNotIn("http", title.lower())
        self.assertTrue(title.startswith("Voice message transcript"))


if __name__ == "__main__":
    unittest.main()
