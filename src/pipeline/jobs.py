"""Queue job creation service."""

from __future__ import annotations

from dataclasses import dataclass

from src.infra.storage import StateStore
from src.pipeline.actions import KNOWN_ACTIONS, parse_actions
from src.pipeline.dedup import build_content_fingerprint, build_idempotency_key
from src.pipeline.ingest import IngestRequest
from src.pipeline.normalize import (
    ascii_safe_title,
    derive_title,
    extract_hashtags,
    normalize_text,
    strip_hashtags,
)


@dataclass
class SubmissionResult:
    is_new: bool
    job_id: str
    status: str
    content_fingerprint: str
    actions: set[str]


class JobService:
    def __init__(self, store: StateStore, max_retries: int) -> None:
        self._store = store
        self._max_retries = max_retries

    def submit(self, request: IngestRequest) -> SubmissionResult:
        hashtags = extract_hashtags(request.raw_text)
        actions = parse_actions(hashtags)

        semantic_hashtags = {tag for tag in hashtags if tag not in KNOWN_ACTIONS}
        content = normalize_text(strip_hashtags(request.raw_text))
        title = ascii_safe_title(derive_title(content))

        content_fingerprint = build_content_fingerprint(
            user_id=request.user_id,
            normalized_content=content,
            semantic_hashtags=semantic_hashtags,
        )
        idempotency_key = build_idempotency_key(
            content_fingerprint=content_fingerprint,
            actions=actions,
        )

        payload = {
            "content": content,
            "title": title,
            "hashtags": sorted(hashtags),
            "semantic_hashtags": sorted(semantic_hashtags),
            "actions": sorted(actions),
            "content_fingerprint": content_fingerprint,
            "source": {
                "chat_id": request.chat_id,
                "message_id": request.message_id,
                "message_datetime": request.message_datetime.isoformat(),
                "user_id": request.user_id,
            },
        }

        is_new, job_id, status = self._store.enqueue_job(
            idempotency_key=idempotency_key,
            content_fingerprint=content_fingerprint,
            user_id=request.user_id,
            chat_id=request.chat_id,
            message_id=request.message_id,
            payload=payload,
            max_attempts=self._max_retries,
        )

        return SubmissionResult(
            is_new=is_new,
            job_id=job_id,
            status=status,
            content_fingerprint=content_fingerprint,
            actions=actions,
        )
