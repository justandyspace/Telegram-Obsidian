# Telegram -> Obsidian (Production Baseline)

Production-ready Telegram ingest bot with strict tenant isolation, resilient worker processing, SSRF-protected URL parsing, and RAG search/summary.

## Architecture

Layers:
- `src/bot`: Telegram auth, routing, commands.
- `src/pipeline`: normalize, dedup, action parsing, queue submission.
- `src/parsers`: URL extraction and guarded fetch/parsing.
- `src/infra`: config, health, logging, resilience, SQLite state store.
- `src/obsidian`: deterministic file routing and managed block writing.
- `src/rag`: chunking, embeddings, index store, retrieval/grounded answers.
- `src/main.py` / `src/worker.py`: role entrypoints.

Isolation model (`TENANT_MODE=multi`):
- Vault: `VAULT_PATH/<tenant_id>/...`
- Index: `INDEX_DIR/<tenant_id>/...`
- Queue + notes: tenant-scoped keys/queries in SQLite
- Bot commands (`/status`, `/find`, `/summary`, `/retry`) filtered by tenant

## Security controls

- Strict allowlist auth (`TELEGRAM_ALLOWED_USER_ID(S)`).
- Webhook hardening:
  - `WEBHOOK_SECRET_TOKEN` required for webhook-enabled runtime.
  - minimum secret length enforced.
- SSRF protection:
  - only `http/https`
  - no URL credentials
  - blocks localhost/internal/private/link-local/loopback IPs
  - validates redirect targets
  - bounded body size
  - retry/backoff + circuit-breaker for unstable upstreams
- Secrets excluded by default in `.gitignore` and `.dockerignore`.

## Reliability controls

- Idempotent enqueue by `(tenant_id, idempotency_key)`.
- Worker retries with exponential backoff.
- Automatic stuck job recovery (`processing` -> `retry`) on interval.
- Startup SQLite integrity check.
- Legacy table migration into current schema.
- Schema versioning via `schema_migrations`.

## Environment

Copy `.env.example` to `.env` and set:
- `TELEGRAM_TOKEN`
- `TELEGRAM_ALLOWED_USER_ID` or `TELEGRAM_ALLOWED_USER_IDS`
- `GEMINI_API_KEY` (optional; hash embeddings fallback exists)
- `WEBHOOK_*` + strong `WEBHOOK_SECRET_TOKEN` if webhook mode is enabled

Important worker knobs:
- `WORKER_POLL_SECONDS` (default `2`)
- `WORKER_RECOVERY_INTERVAL_SECONDS` (default `30`)
- `WORKER_STUCK_TIMEOUT_SECONDS` (default `600`)

## Local run

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m src.main --role bot
python -m src.main --role worker
```

Windows helper:
- `run_local.ps1`

## Docker Compose (recommended)

```bash
docker compose up -d --build bot worker
docker compose ps
docker compose logs -f --tail=200 bot worker
```

Health checks:
- Bot: `127.0.0.1:8080`
- Worker: `127.0.0.1:8081`

## Quality gates

```bash
ruff check src tests
mypy src
bandit -q -c pyproject.toml -r src
pip-audit -r requirements.txt
pytest -q
```

CI is configured in `.github/workflows/ci.yml`.

## Operations

- Runtime runbook: `RUNBOOK.md`
- Incident response: `INCIDENT_PLAYBOOK.md`
- Deploy checklist: `DEPLOYMENT_CHECKLIST.md`
