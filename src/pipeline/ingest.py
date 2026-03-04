"""Ingestion request model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class IngestRequest:
    user_id: int
    chat_id: int
    message_id: int
    message_datetime: datetime
    raw_text: str
