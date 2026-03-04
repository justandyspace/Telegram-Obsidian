"""Strict single-user authorization checks."""

from __future__ import annotations


def is_authorized_user(*, incoming_user_id: int | None, allowed_user_id: int) -> bool:
    if incoming_user_id is None:
        return False
    return incoming_user_id == allowed_user_id
