# Telegram -> Obsidian Bot (Phase 1 Foundation)

This repository now contains the Phase 1 critical foundation from `BOT_ARCHITECTURE_ROADMAP.md`.

## Included in this phase
- Docker Compose baseline: `bot`, `worker`, `couchdb`
- Strict Telegram authorization gate by one allowed `user_id`
- Long polling runtime with crash-restart backoff
- Ingestion contract: content + hashtags, default action is `#save`
- Idempotent queue + dedup + retry (SQLite-backed)
- Obsidian managed-block writer (`BOT_META`, `BOT_SUMMARY`, `BOT_TASKS`, `BOT_LINKS`)
- Deterministic note filename format: `YYYYMMDD-HHMM - Title (ID).md`
- Git-ready scaffolding (`.env.example`, `.gitignore`, modular `src/` tree)

## Quick start (local)
1. Create `.env` from `.env.example`.
2. Set `TELEGRAM_TOKEN` and `TELEGRAM_ALLOWED_USER_ID`.
3. Run:
   - `docker compose up --build`
4. Send a Telegram message from the authorized account.
5. Check generated note under `local_obsidian_inbox/`.

## Security baseline
- Secrets are env-only and excluded from git.
- Unauthorized Telegram users are rejected.
- Worker writes only managed bot blocks in notes and keeps user content outside blocks untouched.

## Storage boundaries
- Vault notes: `local_obsidian_inbox/` (mapped to `/data/vault`)
- Server-only runtime state: `.data/state`, `.data/cache`, `.data/index`

## Notes on scope
- This phase intentionally excludes transcription, webhook deployment, multi-tenant mode, and full RAG retrieval.
