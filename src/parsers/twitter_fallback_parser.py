"""X/Twitter fallback parser using fxtwitter/vxtwitter metadata."""

from __future__ import annotations

from urllib.parse import urlparse

from bs4 import BeautifulSoup

from src.parsers.models import ParseResult
from src.parsers.url_safety import safe_http_get
from src.pipeline.normalize import normalize_text

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)


def parse_twitter_fallback(url: str, timeout_seconds: int = 10) -> ParseResult:
    fx_url, vx_url = _convert_urls(url)
    links = [url, fx_url, vx_url]
    response = None

    try:
        response = safe_http_get(
            fx_url,
            timeout_seconds=timeout_seconds,
            headers={"User-Agent": USER_AGENT},
            max_body_bytes=1 * 1024 * 1024,
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        title = _read_meta(soup, "og:title") or "X/Twitter post"
        description = _read_meta(soup, "og:description")
        text = normalize_text(description or title)
        status = "ok" if description else "fallback"
        return ParseResult(
            parser="twitter_fallback",
            source_url=url,
            status=status,
            title=title[:200],
            text=text[:4000],
            links=links,
            error=None,
        )
    except Exception as exc:  # noqa: BLE001
        return ParseResult(
            parser="twitter_fallback",
            source_url=url,
            status="fallback",
            title="X/Twitter post (fallback)",
            text="Raw post URL stored. Metadata fetch from fxtwitter/vxtwitter failed.",
            links=links,
            error=str(exc)[:500],
        )
    finally:
        if response is not None:
            response.close()


def _convert_urls(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    path = parsed.path
    if parsed.query:
        path = f"{path}?{parsed.query}"
    fx_url = f"https://fxtwitter.com{path}"
    vx_url = f"https://vxtwitter.com{path}"
    return fx_url, vx_url


def _read_meta(soup: BeautifulSoup, prop: str) -> str:
    tag = soup.select_one(f"meta[property='{prop}']")
    if tag and tag.get("content"):
        return normalize_text(str(tag["content"]))
    return ""
