"""AI enrichment stage for worker payloads."""

from __future__ import annotations

import json
from typing import Any

from google import genai
from google.genai import types

from src.infra.ai_fallback import is_remote_ai_available, mark_remote_ai_failure, reset_remote_ai
from src.infra.logging import get_logger
from src.infra.resilience import RetryPolicy, with_retry

LOGGER = get_logger(__name__)
_AI_SCOPE = "payload_enrichment"

_BASE_PROMPT = (
    "Проанализируй текст и верни JSON с полями: "
    '{"tags": ["tag1", "tag2"], "summary": "краткая сводка до 280 символов"'
)
_PROMPT_SUFFIX = (
    "}. "
    "Теги: 2-8 штук, без #, в lower_snake_case. "
    "Без дополнительных полей."
)
_TRANSLATE_PROMPT = (
    ', "translation": "полный перевод текста на русский язык (или на английский, если текст уже на русском)"'
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
    if not is_remote_ai_available(_AI_SCOPE):
        merged["auto_tags"] = existing_tags
        if existing_summary:
            merged["ai_summary"] = existing_summary
        return merged

    actions = merged.get("actions", [])
    needs_translation = "translate" in actions
    
    prompt = _BASE_PROMPT
    if needs_translation:
        prompt += _TRANSLATE_PROMPT
    prompt += _PROMPT_SUFFIX

    try:
        gemini_client = client or genai.Client(api_key=api_key)
        
        def _call_gemini() -> Any:
            return gemini_client.models.generate_content(
                model=model_name,
                contents=f"{prompt}\n\nТекст:\n{base_text}",
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )
            
        policy = RetryPolicy(max_attempts=4, base_delay_seconds=2.0, max_delay_seconds=15.0)
        response = with_retry(policy, _call_gemini, exc_types=(Exception,))
        reset_remote_ai(_AI_SCOPE)
        
        ai_tags, ai_summary, translation = _parse_ai_response(response.text)
        merged["auto_tags"] = _merge_tags(existing_tags, ai_tags)
        if ai_summary:
            merged["ai_summary"] = ai_summary
            merged["enriched_text"] = _append_summary(base_text, ai_summary)
        elif existing_summary:
            merged["ai_summary"] = existing_summary
            
        if translation:
            merged["translation"] = translation
    except Exception as exc:  # noqa: BLE001
        mark_remote_ai_failure(_AI_SCOPE, exc)
        LOGGER.warning("AI enrichment skipped due to error: %s", exc)
        merged["auto_tags"] = existing_tags
        if existing_summary:
            merged["ai_summary"] = existing_summary

    return merged


def _parse_ai_response(response_text: str | None) -> tuple[list[str], str, str]:
    if not response_text:
        return [], "", ""
    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError:
        return [], "", ""
    tags = _normalize_tags(parsed.get("tags") or [])
    summary = str(parsed.get("summary") or "").strip()
    translation = str(parsed.get("translation") or "").strip()
    return tags, summary, translation


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
