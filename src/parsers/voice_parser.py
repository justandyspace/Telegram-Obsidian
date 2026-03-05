"""Voice/audio parser using Gemini file upload + generate_content."""

from __future__ import annotations

import mimetypes
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from google import genai
from google.genai import types

from src.parsers.models import ParseResult
from src.parsers.url_safety import safe_http_get
from src.pipeline.normalize import normalize_text

_AUDIO_EXT_TO_MIME = {
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
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

    local_path = ""
    uploaded_name = ""
    uploaded_uri = ""
    client = genai.Client(api_key=api_key)
    try:
        local_path = _resolve_local_audio_path(source, timeout_seconds=timeout_seconds)
        mime_type = _guess_mime_type(local_path)
        uploaded = client.files.upload(
            file=local_path,
            config=types.UploadFileConfig(mime_type=mime_type),
        )
        uploaded_name = uploaded.name or ""
        uploaded_uri = uploaded.uri or ""

        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[uploaded, _TRANSCRIBE_PROMPT],
        )
        transcript = normalize_text(str(response.text or ""))[:12000]
        status = "ok" if transcript else "fallback"
        text = transcript or "Audio processed, but transcript is empty."
        links = [source]
        if uploaded_uri:
            links.append(uploaded_uri)

        return ParseResult(
            parser="voice",
            source_url=source,
            status=status,
            title="Voice transcription",
            text=text,
            links=links,
            error=None if transcript else "Empty transcript from Gemini",
        )
    except Exception as exc:  # noqa: BLE001
        return ParseResult(
            parser="voice",
            source_url=source,
            status="error",
            title="Voice transcription failed",
            text="",
            links=[source],
            error=str(exc)[:500],
        )
    finally:
        if uploaded_name:
            try:
                client.files.delete(name=uploaded_name)
            except Exception:  # noqa: BLE001
                pass
        if _is_temp_path(local_path):
            try:
                Path(local_path).unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass


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
    if guessed and guessed.startswith("audio/"):
        return guessed
    return "audio/mpeg"


def _is_temp_path(path: str) -> bool:
    if not path:
        return False
    return str(path).startswith(tempfile.gettempdir())
