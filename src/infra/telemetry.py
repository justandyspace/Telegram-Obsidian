"""Minimal structured product telemetry."""

from __future__ import annotations

import json

from src.infra.logging import get_logger

LOGGER = get_logger("product.telemetry")


def track_event(event_name: str, **fields: object) -> None:
    payload = {key: value for key, value in fields.items() if value not in (None, "", [], {}, ())}
    LOGGER.info("event=%s payload=%s", event_name, json.dumps(payload, ensure_ascii=True, sort_keys=True))
