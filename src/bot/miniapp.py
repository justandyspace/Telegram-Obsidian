"""Helpers for Mini App deep-links and Telegram buttons."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo


def build_mini_app_url(
    base_url: str,
    *,
    screen: str,
    query: str = "",
    note_id: str = "",
    job_id: str = "",
) -> str:
    base = (base_url or "").strip()
    if not base:
        return ""
    if not (base.startswith("https://") or base.startswith("http://")):
        return ""

    parts = urlsplit(base)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params["screen"] = screen
    if query:
        params["q"] = query
    if note_id:
        params["note_id"] = note_id
    if job_id:
        params["job_id"] = job_id

    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(params),
            parts.fragment,
        )
    )


def build_mini_app_markup(
    base_url: str,
    *,
    label: str,
    screen: str,
    query: str = "",
    note_id: str = "",
    job_id: str = "",
) -> InlineKeyboardMarkup | None:
    url = build_mini_app_url(
        base_url,
        screen=screen,
        query=query,
        note_id=note_id,
        job_id=job_id,
    )
    if not url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label,
                    web_app=WebAppInfo(url=url),
                )
            ]
        ]
    )
