"""URL routing and parser orchestration."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

from src.parsers.article_parser import parse_article
from src.parsers.models import ParseResult
from src.parsers.pdf_parser import parse_pdf
from src.parsers.twitter_fallback_parser import parse_twitter_fallback
from src.parsers.voice_parser import parse_voice
from src.parsers.youtube_parser import parse_youtube

URL_RE = re.compile(r"https?://[^\s<>()\[\]{}\"']+")
_VOICE_MEDIA_EXTENSIONS = {
    ".3gp",
    ".aac",
    ".flac",
    ".m4a",
    ".m4v",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".oga",
    ".ogg",
    ".wav",
    ".weba",
    ".webm",
}


def extract_urls(content: str) -> list[str]:
    found = [match.group(0).rstrip(".,;:!?") for match in URL_RE.finditer(content)]
    unique: list[str] = []
    seen: set[str] = set()
    for url in found:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def classify_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()

    if _has_voice_mime_fragment(parsed.fragment):
        return "voice"
    if _is_audio_path(path):
        return "voice"
    if path.endswith(".pdf"):
        return "pdf"
    if _host_matches(host, "youtube.com") or _host_matches(host, "youtu.be"):
        return "youtube"
    if _host_matches(host, "x.com") or _host_matches(host, "twitter.com"):
        return "twitter_fallback"
    return "article"


def classify_source(source: str) -> str:
    parsed = urlparse(source)
    if parsed.scheme == "telegram-file":
        return "voice"
    if parsed.scheme in {"http", "https"}:
        return classify_url(source)
    if _is_audio_path(source):
        return "voice"
    return "article"


def parse_url(url: str) -> ParseResult:
    kind = classify_source(url)
    if kind == "voice":
        return parse_voice(url)
    if kind == "pdf":
        return parse_pdf(url)
    if kind == "youtube":
        return parse_youtube(url)
    if kind == "twitter_fallback":
        return parse_twitter_fallback(url)
    return parse_article(url)


def enrich_payload(payload: dict, max_urls: int = 4) -> dict:
    content = str(payload.get("content", ""))
    urls = extract_urls(content)
    media_source = str(payload.get("media_source") or "").strip()
    if media_source and media_source not in urls:
        urls.append(media_source)
    urls = urls[:max_urls]

    parsed_items = []
    summary_parts = [content]
    for url in urls:
        result = parse_url(url)
        parsed_items.append(result.to_payload())
        if result.title or result.text:
            snippet = f"{result.title}\n{result.text}".strip()
            summary_parts.append(snippet[:2500])

    merged = dict(payload)
    merged["parsed_items"] = parsed_items
    merged["enriched_text"] = "\n\n".join(part for part in summary_parts if part).strip()
    return merged


def _host_matches(host: str, domain: str) -> bool:
    host = host.split("@")[-1].split(":")[0].strip().lower()
    domain = domain.strip().lower()
    return host == domain or host.endswith("." + domain)


def _is_audio_path(path: str) -> bool:
    suffix = Path(urlparse(path).path).suffix.lower()
    return suffix in _VOICE_MEDIA_EXTENSIONS


def _has_voice_mime_fragment(fragment: str) -> bool:
    if not fragment:
        return False
    for key, value in parse_qsl(fragment, keep_blank_values=True):
        if key.strip().lower() != "tgmime":
            continue
        mime_hint = value.strip().lower()
        if mime_hint.startswith("audio/") or mime_hint.startswith("video/"):
            return True
    return False
