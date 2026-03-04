"""Article URL parser with graceful fallback."""

from __future__ import annotations

from bs4 import BeautifulSoup

from src.parsers.models import ParseResult
from src.parsers.url_safety import safe_http_get
from src.pipeline.normalize import normalize_text

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)


def parse_article(url: str, timeout_seconds: int = 12) -> ParseResult:
    response = None
    try:
        response = safe_http_get(
            url,
            timeout_seconds=timeout_seconds,
            headers={"User-Agent": USER_AGENT},
            max_body_bytes=2 * 1024 * 1024,
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return ParseResult(
            parser="article",
            source_url=url,
            status="error",
            title="Article fetch failed",
            text="",
            links=[url],
            error=str(exc)[:500],
        )

    try:
        soup = BeautifulSoup(response.text, "html.parser")
        title = _extract_title(soup) or "Untitled article"

        candidates = [
            *[p.get_text(" ", strip=True) for p in soup.select("article p")],
            *[p.get_text(" ", strip=True) for p in soup.select("main p")],
            *[p.get_text(" ", strip=True) for p in soup.select("p")],
        ]
        body = normalize_text(" ".join(text for text in candidates if len(text) > 30))
        status = "ok"
        if not body:
            body = normalize_text(soup.get_text(" ", strip=True))
            status = "fallback"

        body = body[:8000]
        links = [url]
        if response.url and response.url != url:
            links.append(response.url)

        return ParseResult(
            parser="article",
            source_url=url,
            status=status,
            title=title[:200],
            text=body,
            links=links,
            error=None,
        )
    finally:
        if response is not None:
            response.close()


def _extract_title(soup: BeautifulSoup) -> str:
    og_title = soup.select_one("meta[property='og:title']")
    if og_title and og_title.get("content"):
        return normalize_text(og_title["content"])

    if soup.title and soup.title.text:
        return normalize_text(soup.title.text)

    h1 = soup.select_one("h1")
    if h1 and h1.text:
        return normalize_text(h1.text)
    return ""
