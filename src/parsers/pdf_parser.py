"""PDF URL parser."""

from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

from src.parsers.models import ParseResult
from src.parsers.url_safety import safe_http_get
from src.pipeline.normalize import normalize_text

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)


def parse_pdf(url: str, timeout_seconds: int = 20) -> ParseResult:
    response = None
    try:
        response = safe_http_get(
            url,
            timeout_seconds=timeout_seconds,
            headers={"User-Agent": USER_AGENT},
            stream=True,
            max_body_bytes=15 * 1024 * 1024,
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return ParseResult(
            parser="pdf",
            source_url=url,
            status="error",
            title="PDF fetch failed",
            text="",
            links=[url],
            error=str(exc)[:500],
        )

    try:
        reader = PdfReader(BytesIO(response.content))
        pages = []
        for page in reader.pages[:10]:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(normalize_text(text))
        extracted = "\n\n".join(pages).strip()[:12000]
        meta_title = ""
        if reader.metadata and reader.metadata.title:
            meta_title = normalize_text(str(reader.metadata.title))
        title = meta_title or _guess_title(url)
        status = "ok" if extracted else "fallback"
        if not extracted:
            extracted = "PDF downloaded but text extraction returned empty content."
        return ParseResult(
            parser="pdf",
            source_url=url,
            status=status,
            title=title[:200],
            text=extracted,
            links=[url, response.url] if response.url != url else [url],
            error=None,
        )
    except Exception as exc:  # noqa: BLE001
        return ParseResult(
            parser="pdf",
            source_url=url,
            status="error",
            title=_guess_title(url),
            text="",
            links=[url],
            error=f"PDF parse failed: {exc}"[:500],
        )
    finally:
        if response is not None:
            response.close()


def _guess_title(url: str) -> str:
    tail = url.rstrip("/").split("/")[-1]
    if tail.lower().endswith(".pdf"):
        tail = tail[:-4]
    return tail or "PDF Document"
