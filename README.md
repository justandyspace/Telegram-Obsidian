<div align="center">

# Telegram-Obsidian

### Turn Telegram into a structured capture layer for Obsidian

[![Python](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)

Telegram-Obsidian ingests text, links, voice messages, and media from Telegram, converts them into searchable Markdown notes, and stores them directly in your Obsidian vault.

</div>

## Why Telegram-Obsidian

Telegram is convenient for capturing ideas, but it quickly becomes an unstructured archive of links, files, half-finished thoughts, and voice notes. Telegram-Obsidian turns that stream into something usable: clean notes in Obsidian that you can actually browse, search, and summarize later.

It is built for self-hosted use. Your data stays local, Docker support is included, and the ingestion pipeline is designed to keep running reliably instead of falling apart on retries, stuck jobs, or malformed inputs.

## What It Does

| Capability | Outcome |
| --- | --- |
| Telegram capture | Save text, links, voice messages, and media directly from chat |
| Note generation | Convert incoming content into structured Markdown notes |
| Search and summary | Index saved notes for semantic retrieval and grounded summaries |
| Local-first runtime | Run locally or through Docker Compose |
| Operational safety | Keep the pipeline healthy with retries, recovery, and health endpoints |

## How It Works

| Step | What happens |
| --- | --- |
| 1. Capture | Send a message, link, voice note, or file to the Telegram bot. |
| 2. Enrich | VaultPulse extracts text, metadata, and relevant context from the input. |
| 3. Store | The result is saved as a clean Markdown note in your Obsidian vault. |
| 4. Retrieve | Use `/find` and `/summary` to search and synthesize what you saved. |

## Key Features

| Area | Details |
| --- | --- |
| Access control | Strict allowlist-based authorization with `TELEGRAM_ALLOWED_USER_ID(S)` |
| Telegram runtime | Support for `polling`, `webhook`, and `auto` modes |
| Storage isolation | Tenant-scoped `VAULT_PATH`, `INDEX_DIR`, and SQLite state |
| Queue reliability | Idempotent jobs, retries, exponential backoff, and stuck-job recovery |
| Safe ingestion | URL handling with SSRF protection |
| Retrieval | Semantic search and grounded summaries via `/find` and `/summary` |
| Health | Built-in bot and worker health endpoints |

## Technology Stack

| Layer | Tools |
| --- | --- |
| Runtime | Python 3.12+, aiogram 3, aiohttp |
| Parsing | BeautifulSoup, pypdf, youtube-transcript-api |
| Intelligence | Gemini API (optional, for embeddings and generation) |
| Storage | SQLite |
| Deployment | Docker Compose |

## Project Structure

- `src/main.py` — entrypoint for the `bot`, `worker`, and `watcher` roles.
- `src/bot` — Telegram routing and commands.
- `src/pipeline` — normalization, actions, and queue handling.
- `src/parsers` — URL parsing and guarded fetch logic.
- `src/obsidian` — note routing and writing.
- `src/rag` — indexing, retrieval, and answers.
- `src/infra` — config, logging, health, and storage.
- `tests` — automated tests.
- `deploy` — deployment artifacts, including systemd unit files.

## Quick Start

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

**Windows:**

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

**Linux / macOS:**

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Run the roles in separate terminals:

```bash
python -m src.main --role bot
python -m src.main --role worker
python -m src.main --role watcher
```

## Quick Start (Docker Compose)

```bash
docker compose up -d --build bot worker
docker compose ps
docker compose logs -f --tail=200 bot worker
```

Health endpoints:

- Bot: `127.0.0.1:8080/health`
- Worker: `127.0.0.1:8081/health`

## Required Environment Variables

Minimum `.env` configuration:

- `TELEGRAM_TOKEN`
- `TELEGRAM_ALLOWED_USER_ID` or `TELEGRAM_ALLOWED_USER_IDS`
- `TENANT_MODE` (`single` or `multi`)
- `VAULT_PATH`, `STATE_DIR`, `CACHE_DIR`, `INDEX_DIR`
- `APP_ROLE` (`bot`, `worker`, `watcher`, `standalone`)

Optional for better RAG quality:

- `GEMINI_API_KEY`
- `GEMINI_EMBED_MODEL`
- `GEMINI_GENERATION_MODEL`
- `GDRIVE_ENABLED`, `GDRIVE_CLIENT_ID`, `GDRIVE_CLIENT_SECRET`, `GDRIVE_REFRESH_TOKEN`, `GDRIVE_ROOT_FOLDER_ID`

For webhook mode:

- `WEBHOOK_BASE_URL`
- `WEBHOOK_SECRET_TOKEN` (a long random secret)

For Mini App deep links from the bot:

- `MINI_APP_BASE_URL`

For watcher fallback polling:

- `WATCHER_POLL_SECONDS` (polling interval if watchdog is unavailable)

## Telegram Commands

- `/start` — help and feature overview.
- `/status` — queue state, errors, and RAG/storage stats.
- `/find <query>` — semantic/keyword note search.
- `/summary <question>` — grounded summary over the index.
- `/retry <job_id_or_prefix>` — manually retry a job.
- `/delete <note_id|job_id_prefix|file_name>` — delete a note (file + index + DB record).

If `MINI_APP_BASE_URL` is set, the bot adds WebApp CTA buttons to `/start`, `/status`, `/find`, and `/summary`.

Messages can include action tags: `#save`, `#summary`, `#task`, `#resummarize`, `#translate`.

## Quality and Verification

```bash
ruff check src tests
mypy src
bandit -q -c pyproject.toml -r src
pip-audit -r requirements.txt
pytest -q
```

## Security and Reliability

- Blocking for unauthorized Telegram users.
- SSRF guard: `http/https` only, private/internal range blocking, redirect validation.
- Job idempotency by key plus tenant scope.
- Periodic recovery for stuck jobs.
- SQLite integrity checks and schema migrations.

## Operations

- [RUNBOOK.md](RUNBOOK.md)
- [INCIDENT_PLAYBOOK.md](INCIDENT_PLAYBOOK.md)
- [DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md)
- [RELEASE_NOTES.md](RELEASE_NOTES.md)

### Weekly Health Check (Recommended Once Per Week)

```powershell
python scripts/weekly_healthcheck.py `
  --state-db .data/state/bot_state.sqlite3 `
  --vault-dir local_obsidian_inbox `
  --obsidian-dir "C:\path\to\your\Obsidian Vault\.obsidian"
```

## Troubleshooting: A Note Did Not Appear in Obsidian

1. Make sure both processes are running: `bot` and `worker`.
2. Check `/status`:
   - `Queue` should not remain stuck in `pending/retry/failed`.
   - `vault_path` should point to your real Obsidian vault.
   - `recent_note_paths` should show paths for recently saved notes.
3. If `TENANT_MODE=multi`, notes are written into the `VAULT_PATH/<tenant_id>` subfolder, for example `tg_123456789`.

## Google Drive

If `GDRIVE_ENABLED=true`, the worker enables three background flows:

1. Telegram media is uploaded to Google Drive before note writing, and a direct Drive URL is added to `BOT_LINKS`.
2. All Markdown notes are mirrored into `vault_mirror/` every 30 minutes.
3. `bot_state.sqlite3` is snapshotted daily into `db_snapshots/`.

## License

See [LICENSE.md](LICENSE.md).
