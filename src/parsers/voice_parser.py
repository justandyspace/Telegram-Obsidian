"""Voice/audio parser using Gemini file upload + generate_content."""

from __future__ import annotations

import mimetypes
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, unquote, urlparse

from google import genai
from google.genai import types

from src.infra.ai_fallback import is_remote_ai_available, mark_remote_ai_failure, reset_remote_ai
from src.infra.logging import get_logger
from src.infra.resilience import RetryPolicy, with_retry
from src.parsers.models import ParseResult
from src.parsers.url_safety import safe_http_get
from src.pipeline.normalize import normalize_text

_AUDIO_EXT_TO_MIME = {
    ".3gp": "video/3gpp",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".m4v": "video/x-m4v",
    ".mov": "video/quicktime",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".mpeg": "video/mpeg",
    ".mpg": "video/mpeg",
    ".oga": "audio/ogg",
    ".ogg": "audio/ogg",
    ".wav": "audio/wav",
    ".weba": "audio/webm",
    ".webm": "audio/webm",
}

_TRANSCRIBE_PROMPT = (
    "Transcribe this audio in plain text. "
    "Keep original language. "
    "If speech is missing or unclear, briefly explain."
)
LOGGER = get_logger(__name__)
_AI_SCOPE = "voice_transcription"


def parse_voice(source: str, timeout_seconds: int = 40) -> ParseResult:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return ParseResult(
            parser="voice",
            source_url=source,
            status="fallback",
            title="Voice transcription unavailable",
            text="GEMINI_API_KEY is not configured.",
            links=[source],
            error="GEMINI_API_KEY is missing",
        )
    if not is_remote_ai_available(_AI_SCOPE):
        return ParseResult(
            parser="voice",
            source_url=source,
            status="fallback",
            title="Voice transcription unavailable",
            text="Voice transcription is temporarily running in fallback mode.",
            links=[source],
            error="remote ai quota cooldown is active",
        )

    client = genai.Client(api_key=api_key)
    try:
        audio_bytes, mime_type = _load_audio_bytes(source, timeout_seconds=timeout_seconds)

        policy = RetryPolicy(max_attempts=4, base_delay_seconds=2.0, max_delay_seconds=15.0)

        model_name = os.getenv("GEMINI_GENERATION_MODEL", "gemini-2.0-flash-lite").strip()

        def _call_generate() -> Any:
            return client.models.generate_content(
                model=model_name,
                contents=[
                    _TRANSCRIBE_PROMPT,
                    types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                ],
            )

        response = with_retry(policy, _call_generate, exc_types=(Exception,))
        reset_remote_ai(_AI_SCOPE)

        transcript = normalize_text(str(response.text or ""))[:12000]
        status = "ok" if transcript else "fallback"
        text = transcript or "Audio processed, but transcript is empty."

        return ParseResult(
            parser="voice",
            source_url=source,
            status=status,
            title="Voice transcription",
            text=text,
            links=[source],
            error=None if transcript else "Empty transcript from Gemini",
        )
    except Exception as exc:  # noqa: BLE001
        mark_remote_ai_failure(_AI_SCOPE, exc)
        if is_remote_ai_available(_AI_SCOPE):
            status = "error"
            text = ""
            error = str(exc)[:500]
        else:
            status = "fallback"
            text = "Voice transcription is temporarily unavailable due to remote AI limits."
            error = "remote ai quota cooldown is active"
        return ParseResult(
            parser="voice",
            source_url=source,
            status=status,
            title="Voice transcription failed",
            text=text,
            links=[source],
            error=error,
        )


def _load_audio_bytes(source: str, *, timeout_seconds: int) -> tuple[bytes, str]:
    parsed = urlparse(source)
    if parsed.scheme == "telegram-file":
        download_url = _telegram_download_url(source)
        response = safe_http_get(
            download_url,
            timeout_seconds=timeout_seconds,
            max_body_bytes=30 * 1024 * 1024,
        )
        response.raise_for_status()
        try:
            return bytes(response.content), _guess_mime_type_from_source(
                source,
                response.headers.get("Content-Type", ""),
            )
        finally:
            response.close()
    if parsed.scheme in {"http", "https"}:
        response = safe_http_get(
            source,
            timeout_seconds=timeout_seconds,
            max_body_bytes=30 * 1024 * 1024,
        )
        response.raise_for_status()
        try:
            return bytes(response.content), _guess_mime_type_from_source(
                source,
                response.headers.get("Content-Type", ""),
            )
        finally:
            response.close()

    path = Path(source)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Audio file not found: {source}")
    return path.read_bytes(), _guess_mime_type(str(path))


def _telegram_download_url(source: str) -> str:
    token = os.getenv("TELEGRAM_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN is required to fetch Telegram media.")
    parsed = urlparse(source)
    file_path = unquote(parsed.path.lstrip("/"))
    if not file_path:
        raise RuntimeError("Telegram media path is missing.")
    return f"https://api.telegram.org/file/bot{token}/{file_path}"


def _resolve_local_audio_path(source: str, *, timeout_seconds: int) -> str:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        return _download_to_temp(source, timeout_seconds=timeout_seconds)
    path = Path(source)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Audio file not found: {source}")
    return str(path)


def _download_to_temp(url: str, *, timeout_seconds: int) -> str:
    response = safe_http_get(
        url,
        timeout_seconds=timeout_seconds,
        max_body_bytes=30 * 1024 * 1024,
    )
    response.raise_for_status()
    try:
        suffix = _suffix_from_source(url)
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(response.content)
            return tmp.name
    finally:
        response.close()


def _suffix_from_source(source: str) -> str:
    suffix = Path(urlparse(source).path).suffix.lower()
    return suffix if suffix else ".audio"


def _guess_mime_type(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in _AUDIO_EXT_TO_MIME:
        return _AUDIO_EXT_TO_MIME[suffix]
    guessed, _ = mimetypes.guess_type(path)
    if guessed and (guessed.startswith("audio/") or guessed.startswith("video/")):
        return guessed
    return "audio/mpeg"


def _guess_mime_type_from_source(source: str, content_type: str) -> str:
    header_value = content_type.split(";")[0].strip().lower()
    if header_value and (header_value.startswith("audio/") or header_value.startswith("video/")):
        return header_value
    parsed = urlparse(source)
    for key, value in parse_qsl(parsed.fragment, keep_blank_values=True):
        if key.strip().lower() != "tgmime":
            continue
        mime_hint = value.strip().lower()
        if mime_hint.startswith("audio/") or mime_hint.startswith("video/"):
            return mime_hint
    return _guess_mime_type(parsed.path)


def _is_temp_path(path: str) -> bool:
    if not path:
        return False
    return str(path).startswith(tempfile.gettempdir())
