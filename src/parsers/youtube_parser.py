"""YouTube parser with transcript path fallback."""

from __future__ import annotations

from urllib.parse import parse_qs, quote_plus, urlparse

from youtube_transcript_api import YouTubeTranscriptApi

from src.parsers.models import ParseResult
from src.parsers.url_safety import safe_http_get
from src.pipeline.normalize import normalize_text

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)


def parse_youtube(url: str, timeout_seconds: int = 12) -> ParseResult:
    video_id = _extract_video_id(url)
    if not video_id:
        return ParseResult(
            parser="youtube",
            source_url=url,
            status="error",
            title="Invalid YouTube URL",
            text="",
            links=[url],
            error="Could not extract YouTube video id.",
        )

    watch_url = f"https://www.youtube.com/watch?v={video_id}"
    caption_path = f"https://www.youtube.com/api/timedtext?lang=en&v={video_id}"

    title = _fetch_title(watch_url, timeout_seconds) or f"YouTube {video_id}"

    transcript_text = ""
    transcript_error = None
    try:
        transcript_items = YouTubeTranscriptApi.get_transcript(
            video_id,
            languages=["en", "uk", "ru"],
        )
        transcript_text = normalize_text(
            " ".join(item.get("text", "") for item in transcript_items)
        )[:12000]
    except Exception as exc:  # noqa: BLE001
        transcript_error = str(exc)

    status = "ok" if transcript_text else "fallback"
    text = transcript_text or "Transcript unavailable. Use caption path for manual retrieval."
    return ParseResult(
        parser="youtube",
        source_url=url,
        status=status,
        title=title[:200],
        text=text,
        links=[url, watch_url, caption_path],
        error=transcript_error[:500] if transcript_error else None,
    )


def _extract_video_id(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.endswith("youtu.be"):
        return parsed.path.lstrip("/").split("/")[0]
    if "youtube.com" in host:
        query_video = parse_qs(parsed.query).get("v", [])
        if query_video:
            return query_video[0]
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] in {"shorts", "embed"}:
            return parts[1]
    return ""


def _fetch_title(watch_url: str, timeout_seconds: int) -> str:
    oembed_url = (
        "https://www.youtube.com/oembed?url="
        + quote_plus(watch_url)
        + "&format=json"
    )
    response = None
    try:
        response = safe_http_get(
            oembed_url,
            timeout_seconds=timeout_seconds,
            headers={"User-Agent": USER_AGENT},
            max_body_bytes=256 * 1024,
        )
        if response.ok:
            payload = response.json()
            return normalize_text(str(payload.get("title", "")))
    except Exception:  # noqa: BLE001
        return ""
    finally:
        if response is not None:
            response.close()
    return ""
