"""URL routing and parser orchestration."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from src.parsers.article_parser import parse_article
from src.parsers.models import ParseResult
from src.parsers.pdf_parser import parse_pdf
from src.parsers.twitter_fallback_parser import parse_twitter_fallback
from src.parsers.youtube_parser import parse_youtube

URL_RE = re.compile(r"https?://[^\s<>()\[\]{}\"']+")


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

    if path.endswith(".pdf"):
        return "pdf"
    if _host_matches(host, "youtube.com") or _host_matches(host, "youtu.be"):
        return "youtube"
    if _host_matches(host, "x.com") or _host_matches(host, "twitter.com"):
        return "twitter_fallback"
    return "article"


def parse_url(url: str) -> ParseResult:
    kind = classify_url(url)
    if kind == "pdf":
        return parse_pdf(url)
    if kind == "youtube":
        return parse_youtube(url)
    if kind == "twitter_fallback":
        return parse_twitter_fallback(url)
    return parse_article(url)


def enrich_payload(payload: dict, max_urls: int = 4) -> dict:
    content = str(payload.get("content", ""))
    urls = extract_urls(content)[:max_urls]

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
