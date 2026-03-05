"""AI enrichment stage for worker payloads."""

from __future__ import annotations

import json
from typing import Any

from google import genai
from google.genai import types

from src.infra.logging import get_logger

LOGGER = get_logger(__name__)

_PROMPT = (
    "Проанализируй текст и верни JSON с полями: "
    '{"tags": ["tag1", "tag2"], "summary": "краткая сводка до 280 символов"}. '
    "Теги: 2-8 штук, без #, в lower_snake_case. "
    "Без дополнительных полей."
)


def enrich_payload_with_ai(
    payload: dict,
    *,
    api_key: str,
    model_name: str,
    client: Any | None = None,
) -> dict:
    """Adds AI tags/summary to payload with graceful fallback."""
    merged = dict(payload)
    base_text = str(merged.get("enriched_text") or merged.get("content") or "").strip()
    merged["enriched_text"] = base_text

    existing_tags = _normalize_tags(merged.get("auto_tags") or [])
    existing_summary = str(merged.get("ai_summary") or "").strip()

    if not api_key:
        merged["auto_tags"] = existing_tags
        if existing_summary:
            merged["ai_summary"] = existing_summary
        return merged

    try:
        gemini_client = client or genai.Client(api_key=api_key)
        response = gemini_client.models.generate_content(
            model=model_name,
            contents=f"{_PROMPT}\n\nТекст:\n{base_text}",
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
        ai_tags, ai_summary = _parse_ai_response(response.text)
        merged["auto_tags"] = _merge_tags(existing_tags, ai_tags)
        if ai_summary:
            merged["ai_summary"] = ai_summary
            merged["enriched_text"] = _append_summary(base_text, ai_summary)
        elif existing_summary:
            merged["ai_summary"] = existing_summary
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("AI enrichment skipped due to error: %s", exc)
        merged["auto_tags"] = existing_tags
        if existing_summary:
            merged["ai_summary"] = existing_summary

    return merged


def _parse_ai_response(response_text: str | None) -> tuple[list[str], str]:
    if not response_text:
        return [], ""
    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError:
        return [], ""
    tags = _normalize_tags(parsed.get("tags") or [])
    summary = str(parsed.get("summary") or "").strip()
    return tags, summary


def _normalize_tags(tags: Any) -> list[str]:
    if not isinstance(tags, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        value = str(tag).strip().lstrip("#").replace(" ", "_").lower()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _merge_tags(existing: list[str], generated: list[str]) -> list[str]:
    seen = set(existing)
    merged = list(existing)
    for tag in generated:
        if tag not in seen:
            seen.add(tag)
            merged.append(tag)
    return merged


def _append_summary(base_text: str, ai_summary: str) -> str:
    marker = "AI summary:"
    if not ai_summary:
        return base_text
    if ai_summary in base_text:
        return base_text
    if not base_text:
        return f"{marker} {ai_summary}"
    return f"{base_text}\n\n{marker} {ai_summary}"
