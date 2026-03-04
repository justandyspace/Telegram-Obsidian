"""Idempotency and dedup key helpers."""

from __future__ import annotations

import hashlib


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_content_fingerprint(
    *,
    user_id: int,
    normalized_content: str,
    semantic_hashtags: set[str],
) -> str:
    hashtag_part = "|".join(sorted(semantic_hashtags))
    basis = f"u:{user_id}|c:{normalized_content}|h:{hashtag_part}"
    return _sha256(basis)


def build_idempotency_key(*, content_fingerprint: str, actions: set[str]) -> str:
    action_part = "|".join(sorted(actions))
    return _sha256(f"f:{content_fingerprint}|a:{action_part}|v:1")
