# Release Notes

## v0.2.0-rc1 (2026-03-05)

### Summary
- Production hardening completed for Telegram -> Obsidian pipeline.
- Security, reliability, and operational runbook baseline prepared for release.

### Security
- Enforced webhook secret policy for webhook-enabled runtime.
- Strengthened SSRF protections in URL fetch/parsing layer.
- Added resilient fetch behavior (retry/backoff/circuit-breaker).
- Upgraded vulnerable dependencies (`requests`, `pypdf`).
- Container hardening: non-root runtime, dropped caps, no-new-privileges, read-only FS.

### Reliability
- Added DB schema versioning with migration chain (`schema_migrations`).
- Added stuck-job recovery for long-running `processing` jobs.
- Added startup DB integrity checks.
- Added tenant mismatch guard in worker pipeline.

### Quality and CI
- Added quality/security gates: `ruff`, `mypy`, `bandit`, `pip-audit`, `pytest`.
- Added CI workflow with fail-fast checks.
- Expanded tests for SSRF, tenancy, recovery, migration, and resilience scenarios.

### Operations
- Added deployment and incident documentation:
  - `RUNBOOK.md`
  - `INCIDENT_PLAYBOOK.md`
  - `DEPLOYMENT_CHECKLIST.md`
- Added backup/restore and DB maintenance utilities in `scripts/`.
- Added systemd unit templates in `deploy/systemd/`.

### Cleanup
- Removed legacy scripts:
  - `scripts/bot_integration_legacy.py`
  - `scripts/telegram_bot_legacy.py`
- Removed transient caches and test artifacts from workspace tracking.

### Validation
- `pytest -q`: passed
- `ruff check src tests`: passed
- `mypy src`: passed
- `bandit -q -c pyproject.toml -r src`: passed
- `pip-audit -r requirements.txt`: passed

