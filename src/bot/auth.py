"""Authorization checks and tenant resolution."""

from __future__ import annotations

from src.infra.tenancy import TenantContext, resolve_tenant_id


def is_authorized_user(*, incoming_user_id: int | None, allowed_user_ids: set[int]) -> bool:
    if incoming_user_id is None:
        return False
    return incoming_user_id in allowed_user_ids


def build_tenant_context(incoming_user_id: int) -> TenantContext:
    return TenantContext(
        tenant_id=resolve_tenant_id(incoming_user_id),
        user_id=incoming_user_id,
    )
