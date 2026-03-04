"""Tenant helpers for multi-tenant mode."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TenantContext:
    tenant_id: str
    user_id: int


def resolve_tenant_id(user_id: int) -> str:
    return f"tg_{user_id}"


def tenant_vault_path(base_vault_path: Path, tenant_id: str, *, multi_tenant: bool) -> Path:
    if not multi_tenant:
        return base_vault_path
    return base_vault_path / tenant_id


def tenant_index_dir(base_index_dir: Path, tenant_id: str, *, multi_tenant: bool) -> Path:
    if not multi_tenant:
        return base_index_dir
    return base_index_dir / tenant_id

