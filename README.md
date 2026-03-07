# VaultPulse OSS

[![Release](https://img.shields.io/github/v/release/justandyspace/VaultPulse-OSS?label=release)](https://github.com/justandyspace/VaultPulse-OSS/releases)
[![License](https://img.shields.io/github/license/justandyspace/VaultPulse-OSS)](https://github.com/justandyspace/VaultPulse-OSS/blob/main/LICENSE.md)
[![CI](https://img.shields.io/github/actions/workflow/status/justandyspace/VaultPulse-OSS/ci.yml?branch=main&label=CI)](https://github.com/justandyspace/VaultPulse-OSS/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Docker](https://img.shields.io/badge/docker-ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)

Turn Telegram into a structured capture layer for Obsidian.

VaultPulse ingests text, links, voice messages, and media from Telegram, converts them into searchable Markdown notes, and stores them directly in your Obsidian vault.

## Why VaultPulse

Telegram is convenient for capturing ideas, but it quickly becomes an unstructured archive of links, files, half-finished thoughts, and voice notes. VaultPulse turns that stream into something usable: clean notes in Obsidian that you can actually browse, search, and summarize later.

It is built for self-hosted use. Your data stays local, Docker support is included, and the ingestion pipeline is designed to keep running reliably instead of falling apart on retries, stuck jobs, or malformed inputs.

## What It Does

- Captures text, links, voice messages, and media from Telegram.
- Converts incoming content into structured Markdown notes inside Obsidian.
- Indexes saved notes for semantic search and grounded summaries.
- Runs locally or through Docker Compose.
- Keeps the pipeline operational with retries, stuck-job recovery, and health endpoints.

## How It Works

| Step | What happens |
| --- | --- |
| 1. Capture | Send a message, link, voice note, or file to the Telegram bot. |
| 2. Enrich | VaultPulse extracts text, metadata, and relevant context from the input. |
| 3. Store | The result is saved as a clean Markdown note in your Obsidian vault. |
| 4. Retrieve | Use `/find` and `/summary` to search and synthesize what you saved. |

## Key Features

- Строгая авторизация по allowlist (`TELEGRAM_ALLOWED_USER_ID(S)`).
- Поддержка режимов Telegram: `polling`, `webhook`, `auto`.
- Tenant-изоляция хранилищ (`VAULT_PATH`, `INDEX_DIR`, SQLite state).
- Идемпотентная очередь задач и ретраи с exponential backoff.
- Автовосстановление stuck jobs.
- Безопасный URL ingest с SSRF-защитой.
- RAG: semantic find + grounded summary (`/find`, `/summary`).
- Встроенные health endpoints для bot/worker.

## Технологии

- Python 3.12+
- aiogram 3
- aiohttp
- BeautifulSoup / pypdf / youtube-transcript-api
- Gemini API (опционально, для embedding/generation)
- SQLite
- Docker Compose

## Структура проекта

- `src/main.py` — entrypoint ролей `bot`, `worker`, `watcher`.
- `src/bot` — роутинг Telegram и команды.
- `src/pipeline` — нормализация, действия, очередь.
- `src/parsers` — парсинг URL и guarded fetch.
- `src/obsidian` — маршрутизация и запись заметок.
- `src/rag` — индексация, retrieval и ответы.
- `src/infra` — конфиг, логирование, health, storage.
- `tests` — автотесты.
- `deploy` — deployment artifacts (включая systemd unit-файлы).

## Быстрый старт

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Windows:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Linux / macOS:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Запуск ролей в отдельных терминалах:

```bash
python -m src.main --role bot
python -m src.main --role worker
python -m src.main --role watcher
```

## Быстрый старт (Docker Compose)

```bash
docker compose up -d --build bot worker
docker compose ps
docker compose logs -f --tail=200 bot worker
```

Health endpoints:

- Bot: `127.0.0.1:8080/health`
- Worker: `127.0.0.1:8081/health`

## Обязательные переменные окружения

Минимальный набор в `.env`:

- `TELEGRAM_TOKEN`
- `TELEGRAM_ALLOWED_USER_ID` или `TELEGRAM_ALLOWED_USER_IDS`
- `TENANT_MODE` (`single` или `multi`)
- `VAULT_PATH`, `STATE_DIR`, `CACHE_DIR`, `INDEX_DIR`
- `APP_ROLE` (`bot`, `worker`, `watcher`, `standalone`)

Опционально для RAG-качества:

- `GEMINI_API_KEY`
- `GEMINI_EMBED_MODEL`
- `GEMINI_GENERATION_MODEL`
- `GDRIVE_ENABLED`, `GDRIVE_CLIENT_ID`, `GDRIVE_CLIENT_SECRET`, `GDRIVE_REFRESH_TOKEN`, `GDRIVE_ROOT_FOLDER_ID`

Для webhook режима:

- `WEBHOOK_BASE_URL`
- `WEBHOOK_SECRET_TOKEN` (длинный случайный секрет)

Для Mini App deep-link'ов из бота:

- `MINI_APP_BASE_URL`

Для watcher fallback-поллинга:

- `WATCHER_POLL_SECONDS` (интервал polling, если watchdog недоступен)

## Команды Telegram

- `/start` — справка и список возможностей.
- `/status` — состояние очереди, ошибки, статистика RAG и storage.
- `/find <query>` — semantic/keyword поиск по заметкам.
- `/summary <question>` — grounded summary по индексу.
- `/retry <job_id_or_prefix>` — ручной ретрай задачи.
- `/delete <note_id|job_id_prefix|file_name>` — удалить заметку (файл + индекс + DB-запись).

Если задан `MINI_APP_BASE_URL`, бот будет добавлять WebApp CTA-кнопки в `/start`, `/status`, `/find` и `/summary`.

Сообщения можно отправлять с тегами действий:

- `#save`
- `#summary`
- `#task`
- `#resummarize`
- `#translate`

## Качество и проверки

```bash
ruff check src tests
mypy src
bandit -q -c pyproject.toml -r src
pip-audit -r requirements.txt
pytest -q
```

CI: `.github/workflows/ci.yml`

## Безопасность и надежность

- Блокировка неавторизованных пользователей Telegram.
- SSRF guard: только `http/https`, запрет private/internal ranges, валидация редиректов.
- Идемпотентность задач по ключу + tenant scope.
- Периодический recovery зависших задач.
- Проверка целостности SQLite и миграции схемы.

## Эксплуатация

- [RUNBOOK.md](RUNBOOK.md)
- [INCIDENT_PLAYBOOK.md](INCIDENT_PLAYBOOK.md)
- [DEPLOYMENT_CHECKLIST.md](DEPLOYMENT_CHECKLIST.md)
- [RELEASE_NOTES.md](RELEASE_NOTES.md)

### Weekly health-check (рекомендуется раз в неделю)

```powershell
python scripts/weekly_healthcheck.py `
  --state-db .data/state/bot_state.sqlite3 `
  --vault-dir local_obsidian_inbox `
  --obsidian-dir "C:\path\to\your\Obsidian Vault\.obsidian"
```

## Troubleshooting: заметка не появилась в Obsidian

1. Убедитесь, что запущены оба процесса: `bot` и `worker`.
2. Проверьте `/status`:
   - `Queue` не должна застревать в `pending/retry/failed`.
   - `vault_path` должен указывать на ваш реальный Obsidian vault.
   - `recent_note_paths` должен показывать пути недавно сохранённых заметок.
3. Если `TENANT_MODE=multi`, заметки пишутся в подпапку `VAULT_PATH/<tenant_id>` (например, `tg_123456789`).

## Google Drive

Если `GDRIVE_ENABLED=true`, worker включает три фоновых сценария:

1. Telegram media выгружается в Google Drive до записи заметки, а в `BOT_LINKS` добавляется прямой Drive URL.
2. Все markdown-заметки зеркалятся в папку `vault_mirror/` каждые 30 минут.
3. `bot_state.sqlite3` ежедневно снапшотится в `db_snapshots/`.

## Лицензия

См. [LICENSE.md](LICENSE.md).
