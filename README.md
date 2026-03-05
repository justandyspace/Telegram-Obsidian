# telegram-obsidian-local

Production-first Telegram bot для сохранения контента в Obsidian с очередью задач, tenant-изоляцией и RAG-поиском/саммари.

## Почему этот проект

`telegram-obsidian-local` принимает сообщения и ссылки из Telegram, безопасно обрабатывает контент и сохраняет заметки в Obsidian-совместимую структуру. Проект рассчитан на стабильную работу в self-hosted окружении: с health-check'ами, ретраями, восстановлением зависших задач и операционными runbook'ами.

## Ключевые возможности

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

- `src/main.py` — entrypoint ролей `bot` и `worker`.
- `src/bot` — роутинг Telegram и команды.
- `src/pipeline` — нормализация, действия, очередь.
- `src/parsers` — парсинг URL и guarded fetch.
- `src/obsidian` — маршрутизация и запись заметок.
- `src/rag` — индексация, retrieval и ответы.
- `src/infra` — конфиг, логирование, health, storage.
- `tests` — автотесты.
- `deploy` — deployment artifacts (включая systemd unit-файлы).

## Быстрый старт (локально)

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Запустите bot и worker в отдельных терминалах:

```bash
python -m src.main --role bot
python -m src.main --role worker
```

Для Windows можно использовать:

```powershell
.\run_local.ps1
```

Или одной командой поднять сразу `bot` и `worker`:

```powershell
.\scripts\start_all.ps1
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

Опционально для RAG-качества:

- `GEMINI_API_KEY`
- `GEMINI_EMBED_MODEL`
- `GEMINI_GENERATION_MODEL`

Для webhook режима:

- `WEBHOOK_BASE_URL`
- `WEBHOOK_SECRET_TOKEN` (длинный случайный секрет)

## Команды Telegram

- `/start` — справка и список возможностей.
- `/status` — состояние очереди, ошибки, статистика RAG и storage.
- `/find <query>` — semantic/keyword поиск по заметкам.
- `/summary <question>` — grounded summary по индексу.
- `/retry <job_id_or_prefix>` — ручной ретрай задачи.
- `/delete <note_id|job_id_prefix|file_name>` — удалить заметку (файл + индекс + DB-запись).

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
  --obsidian-dir "C:\Users\Desktop\Documents\Obsidian Vault\.obsidian"
```

## Troubleshooting: заметка не появилась в Obsidian

1. Убедитесь, что запущены оба процесса: `bot` и `worker`.
2. Проверьте `/status`:
   - `Queue` не должна застревать в `pending/retry/failed`.
   - `vault_path` должен указывать на ваш реальный Obsidian vault.
   - `recent_note_paths` должен показывать пути недавно сохранённых заметок.
3. Если `TENANT_MODE=multi`, заметки пишутся в подпапку `VAULT_PATH/<tenant_id>` (например, `tg_123456789`).

## Лицензия

В репозитории пока не добавлен отдельный `LICENSE` файл.
